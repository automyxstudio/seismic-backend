"""
Configuración de logging estructurado con structlog.

Se llama una sola vez en el startup de la aplicación (main.py).
Todos los módulos obtienen su logger con: log = structlog.get_logger()

En desarrollo: logs con colores y formato legible para humanos.
En producción: logs en JSON puro, parseables por herramientas como
Grafana Loki, AWS CloudWatch o ELK Stack.

Los campos fijos en cada log son: timestamp, level, logger_name.
Los campos de contexto del negocio (event_id, service, etc.) se agregan
con log.bind() o structlog.contextvars.bind_contextvars().
"""

import logging
import structlog


def setup_logging(env: str = "development") -> None:
    """
    Inicializa structlog con el formato apropiado para el entorno.

    Args:
        env: 'development' para logs con colores, 'production' para JSON.
    """
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if env == "production":
        processors = shared_processors + [structlog.processors.JSONRenderer()]
    else:
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=True)
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        level=logging.INFO,
    )
