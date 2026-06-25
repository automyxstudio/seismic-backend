"""
Tests unitarios para classify_magnitude() y el enum MagnitudeRange.

Cubren:
  - Clasificación correcta en cada rango.
  - Valores exactos en los bordes (límites de cada rango).
  - Magnitud negativa (sismos muy profundos pueden tener valores < 0).
  - Serialización del enum a string (importante para MongoDB y JSON).
"""

import pytest
from src.config.constants import classify_magnitude, MagnitudeRange


class TestClassifyMagnitude:
    """Tabla de verdad para la clasificación de magnitudes."""

    # --- Casos nominales (centro de cada rango) ---

    def test_micro_range(self):
        """Magnitud 1.0 → micro (< 2.0)."""
        assert classify_magnitude(1.0) == MagnitudeRange.MICRO

    def test_menor_range(self):
        """Magnitud 3.0 → menor (2.0–3.9)."""
        assert classify_magnitude(3.0) == MagnitudeRange.MENOR

    def test_ligero_range(self):
        """Magnitud 4.5 → ligero (4.0–4.9)."""
        assert classify_magnitude(4.5) == MagnitudeRange.LIGERO

    def test_moderado_range(self):
        """Magnitud 5.5 → moderado (5.0–5.9)."""
        assert classify_magnitude(5.5) == MagnitudeRange.MODERADO

    def test_fuerte_range(self):
        """Magnitud 6.5 → fuerte (6.0–6.9)."""
        assert classify_magnitude(6.5) == MagnitudeRange.FUERTE

    def test_mayor_range(self):
        """Magnitud 7.5 → mayor (>= 7.0)."""
        assert classify_magnitude(7.5) == MagnitudeRange.MAYOR

    # --- Valores exactos en los bordes (boundary testing) ---

    def test_boundary_micro_menor(self):
        """2.0 exacto → menor (el límite inferior de menor es 2.0 inclusive)."""
        assert classify_magnitude(2.0) == MagnitudeRange.MENOR

    def test_boundary_just_below_menor(self):
        """1.99 → micro (justo debajo del límite inferior de menor)."""
        assert classify_magnitude(1.99) == MagnitudeRange.MICRO

    def test_boundary_menor_ligero(self):
        """4.0 exacto → ligero."""
        assert classify_magnitude(4.0) == MagnitudeRange.LIGERO

    def test_boundary_ligero_moderado(self):
        """5.0 exacto → moderado."""
        assert classify_magnitude(5.0) == MagnitudeRange.MODERADO

    def test_boundary_moderado_fuerte(self):
        """6.0 exacto → fuerte."""
        assert classify_magnitude(6.0) == MagnitudeRange.FUERTE

    def test_boundary_fuerte_mayor(self):
        """7.0 exacto → mayor."""
        assert classify_magnitude(7.0) == MagnitudeRange.MAYOR

    def test_boundary_just_below_mayor(self):
        """6.99 → fuerte (justo debajo del límite de mayor)."""
        assert classify_magnitude(6.99) == MagnitudeRange.FUERTE

    # --- Casos extremos ---

    def test_zero_magnitude(self):
        """Magnitud 0.0 → micro (válido, sismos casi imperceptibles)."""
        assert classify_magnitude(0.0) == MagnitudeRange.MICRO

    def test_negative_magnitude(self):
        """Magnitud negativa → micro (sismos muy pequeños pueden ser < 0)."""
        assert classify_magnitude(-1.5) == MagnitudeRange.MICRO

    def test_very_large_magnitude(self):
        """Magnitud 9.5 (mayor conocido: Valdivia 1960) → mayor."""
        assert classify_magnitude(9.5) == MagnitudeRange.MAYOR

    # --- Serialización del enum ---

    def test_enum_serializes_to_string(self):
        """El enum hereda de str — se serializa directamente sin conversión."""
        assert MagnitudeRange.MICRO == "micro"
        assert MagnitudeRange.MAYOR == "mayor"

    def test_classify_returns_string_compatible(self):
        """El resultado de classify_magnitude puede compararse directamente con string."""
        result = classify_magnitude(5.5)
        assert result == "moderado"
