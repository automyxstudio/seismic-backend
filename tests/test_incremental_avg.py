"""
Tests unitarios para la fórmula de promedio incremental usada en MetricsService.

La fórmula: avg_new = avg_old + (new_value - avg_old) / n

Cubren:
  - Primer evento (n=1, avg_old=0): el promedio debe ser la magnitud misma.
  - Segundo evento: verificar que el resultado coincide con la media aritmética.
  - Muchos eventos: el promedio incremental debe converger al promedio real.
  - Estabilidad numérica: valores extremos no producen overflow.
"""

import pytest


def incremental_avg(avg_old: float, new_value: float, n: int) -> float:
    """
    Fórmula incremental de promedio.
    Replica exactamente lo que hace MetricsService._recalculate_avg().

    Args:
        avg_old: promedio antes de este evento.
        new_value: magnitud del nuevo evento.
        n: conteo DESPUÉS de incluir el nuevo evento.
    """
    return avg_old + (new_value - avg_old) / n


class TestIncrementalAvg:

    def test_primer_evento_igual_a_magnitud(self):
        """Con n=1 y avg_old=0, el resultado debe ser la magnitud del primer evento."""
        result = incremental_avg(avg_old=0.0, new_value=4.5, n=1)
        assert result == pytest.approx(4.5)

    def test_segundo_evento_media_aritmetica(self):
        """Dos eventos: el promedio incremental debe ser idéntico a (a+b)/2."""
        # Primer evento: 4.0, segundo: 6.0 → esperado: 5.0
        avg1 = incremental_avg(avg_old=0.0, new_value=4.0, n=1)
        avg2 = incremental_avg(avg_old=avg1, new_value=6.0, n=2)
        assert avg2 == pytest.approx(5.0)

    def test_tres_eventos_coincide_con_media_aritmetica(self):
        """Tres eventos: el resultado incremental debe coincidir con sum/n."""
        magnitudes = [3.0, 5.0, 7.0]
        avg = 0.0
        for i, mag in enumerate(magnitudes, start=1):
            avg = incremental_avg(avg_old=avg, new_value=mag, n=i)

        expected = sum(magnitudes) / len(magnitudes)  # 5.0
        assert avg == pytest.approx(expected)

    def test_cien_eventos_precision(self):
        """100 eventos aleatorios: promedio incremental vs aritmético deben coincidir."""
        import random
        random.seed(42)
        magnitudes = [round(random.uniform(1.0, 9.0), 2) for _ in range(100)]

        avg = 0.0
        for i, mag in enumerate(magnitudes, start=1):
            avg = incremental_avg(avg_old=avg, new_value=mag, n=i)

        expected = sum(magnitudes) / len(magnitudes)
        assert avg == pytest.approx(expected, rel=1e-6)

    def test_todos_iguales(self):
        """Si todos los eventos tienen la misma magnitud, el promedio es esa magnitud."""
        avg = 0.0
        for i in range(1, 11):
            avg = incremental_avg(avg_old=avg, new_value=5.0, n=i)
        assert avg == pytest.approx(5.0)

    def test_magnitud_muy_grande(self):
        """Magnitud grande (9.5, el máximo histórico) no produce overflow."""
        avg = incremental_avg(avg_old=0.0, new_value=9.5, n=1)
        assert avg == pytest.approx(9.5)
        assert not (avg != avg)  # NaN check

    def test_magnitudes_muy_distintas(self):
        """Magnitudes en extremos opuestos — el promedio incremental es estable."""
        avg = 0.0
        magnitudes = [0.1, 9.5, 0.1, 9.5]
        for i, mag in enumerate(magnitudes, start=1):
            avg = incremental_avg(avg_old=avg, new_value=mag, n=i)

        expected = sum(magnitudes) / len(magnitudes)
        assert avg == pytest.approx(expected, rel=1e-6)
