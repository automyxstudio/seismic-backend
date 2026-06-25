"""
DAG de Airflow: reporte horario consolidado de eventos sísmicos.

Schedule: cada hora (@hourly).

Flujo de 3 tasks encadenadas:
  read_events → generate_report → save_report

Cada task puede hacer retry de forma independiente. Si generate_report falla,
Airflow no vuelve a leer MongoDB — usa el resultado de read_events del XCom.

XCom (Cross-Communication): mecanismo de Airflow para pasar datos entre tasks
dentro del mismo DAG run. Los datos se serializan en JSON.

Idempotencia: si el DAG se re-ejecuta para la misma hora (por fallo + retry
o backfill), save_report usa upsert por report_date — no crea duplicados.
"""

import json
import logging
from datetime import datetime, timedelta, timezone

from airflow import DAG
from airflow.operators.python import PythonOperator

from src.services.reporting_service import ReportingService

log = logging.getLogger(__name__)

# Configuración del DAG
DEFAULT_ARGS = {
    "owner": "seismic-platform",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": False,
}


def read_events(logical_date: datetime, **context) -> str:
    """
    Task 1: lee los eventos sísmicos de la ventana horaria actual.

    Airflow inyecta `logical_date` (el timestamp del DAG run).
    Calculamos el inicio y fin de la hora correspondiente.

    Returns:
        JSON string con la lista de eventos (se pasa al siguiente task vía XCom).
    """
    # Calcular ventana horaria: desde el inicio de la hora hasta el final
    period_start = logical_date.replace(minute=0, second=0, microsecond=0)
    period_end = period_start + timedelta(hours=1)

    log.info(f"Leyendo eventos de {period_start} a {period_end}")

    service = ReportingService()
    try:
        events = service.read_events_for_hour(period_start, period_end)
        # Serializar para XCom — los ObjectId de Mongo son strings ya
        return json.dumps(events, default=str)
    finally:
        service.close()


def generate_report(logical_date: datetime, ti, **context) -> str:
    """
    Task 2: genera el reporte consolidado a partir de los eventos leídos.

    `ti` (task instance) permite acceder al XCom del task anterior.

    Returns:
        JSON string del reporte generado (se pasa al siguiente task vía XCom).
    """
    # Obtener eventos del XCom del task anterior
    events_json = ti.xcom_pull(task_ids="read_events")
    events = json.loads(events_json)

    period_start = logical_date.replace(minute=0, second=0, microsecond=0)
    period_end = period_start + timedelta(hours=1)

    service = ReportingService()
    try:
        report = service.generate_report(events, period_start, period_end)
        # Serializar para XCom — model_dump() retorna dict serializable
        return json.dumps(report.model_dump(), default=str)
    finally:
        service.close()


def save_report(ti, **context) -> None:
    """
    Task 3: persiste el reporte en MongoDB.

    Idempotente — upsert por report_date, sin duplicados ante retries.
    """
    report_json = ti.xcom_pull(task_ids="generate_report")
    report_dict = json.loads(report_json)

    from src.models.report import HourlyReportDocument
    report = HourlyReportDocument(**report_dict)

    service = ReportingService()
    try:
        doc_id = service.save_report(report)
        log.info(f"Reporte guardado: {doc_id}")
    finally:
        service.close()


# Definición del DAG
with DAG(
    dag_id="hourly_seismic_report",
    description="Genera un reporte consolidado de sismos cada hora",
    schedule="@hourly",
    start_date=datetime(2026, 6, 24, tzinfo=timezone.utc),
    catchup=False,       # no generar reportes retroactivos al arrancar
    default_args=DEFAULT_ARGS,
    tags=["seismic", "reports"],
) as dag:

    read_task = PythonOperator(
        task_id="read_events",
        python_callable=read_events,
    )

    generate_task = PythonOperator(
        task_id="generate_report",
        python_callable=generate_report,
    )

    save_task = PythonOperator(
        task_id="save_report",
        python_callable=save_report,
    )

    # Definir dependencias con el operador >> (bitshift)
    # read_events debe terminar exitosamente antes de generate_report
    # generate_report debe terminar exitosamente antes de save_report
    read_task >> generate_task >> save_task
