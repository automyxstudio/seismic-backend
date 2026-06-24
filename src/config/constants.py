"""
Constantes y enumeraciones globales del sistema.

Centralizar las constantes aquí evita magic strings dispersos por el código
y facilita cambios en un solo lugar.
"""

from enum import Enum


class MagnitudeRange(str, Enum):
    """
    Clasificación de sismos por magnitud, basada en la escala del USGS.

    Heredar de str permite que el enum se serialice directamente a string
    en JSON y MongoDB sin conversión adicional.
    """
    MICRO = "micro"        # < 2.0  — imperceptible para humanos
    MENOR = "menor"        # 2.0–3.9 — raramente perceptible
    LIGERO = "ligero"      # 4.0–4.9 — perceptible, daños menores
    MODERADO = "moderado"  # 5.0–5.9 — daños en estructuras débiles
    FUERTE = "fuerte"      # 6.0–6.9 — daños en zonas pobladas
    MAYOR = "mayor"        # >= 7.0  — daños graves en grandes áreas


def classify_magnitude(magnitude: float) -> MagnitudeRange:
    """
    Determina el rango de magnitud de un sismo.

    Esta función se llama en la ingesta para enriquecer cada evento
    con su categoría, permitiendo filtros e índices eficientes en MongoDB.

    Args:
        magnitude: Magnitud del sismo en la escala de Richter.

    Returns:
        MagnitudeRange correspondiente al valor dado.
    """
    if magnitude < 2.0:
        return MagnitudeRange.MICRO
    if magnitude < 4.0:
        return MagnitudeRange.MENOR
    if magnitude < 5.0:
        return MagnitudeRange.LIGERO
    if magnitude < 6.0:
        return MagnitudeRange.MODERADO
    if magnitude < 7.0:
        return MagnitudeRange.FUERTE
    return MagnitudeRange.MAYOR


# Canal Redis donde la ingesta publica nuevos eventos para los WebSockets
REDIS_CHANNEL_NEW_EVENT = "seismic:new_event"

# Clave Redis donde se cachean las métricas de la ventana actual
REDIS_KEY_METRICS_CURRENT = "seismic:metrics:current"
