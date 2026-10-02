"""Pruebas de las validaciones de entrada (sin red ni SAT).

Ejecutar desde la carpeta app/:  pytest tests/ -v
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from validaciones import validar_rfc, validar_uuid, validar_rango_fechas  # noqa: E402
import pytest  # noqa: E402


def test_rfc_valido_fisica():
    ok, msg = validar_rfc("HELJ0102235X0")
    assert ok and msg == ""


def test_rfc_valido_moral():
    ok, _ = validar_rfc("AAA010101AAA")
    assert ok


def test_rfc_minusculas_y_espacios():
    ok, _ = validar_rfc("  helj0102235x0 ")
    assert ok


def test_rfc_invalido():
    for malo in ["", "TEAMO250", "ABC123", "HELJ0102235X", "HELJ0102235X012",
                 "1234567890123", "HELJ-010223-5X0"]:
        ok, msg = validar_rfc(malo)
        assert not ok, f"'{malo}' debería ser inválido"
        assert msg, "debe explicar el problema"


def test_uuid_valido():
    ok, _ = validar_uuid("123e4567-e89b-12d3-a456-426614174000")
    assert ok


def test_uuid_invalido():
    for malo in ["", "no-es-uuid", "123e4567e89b12d3a456426614174000",
                 "123e4567-e89b-12d3-a456-42661417400Z", "  "]:
        ok, msg = validar_uuid(malo)
        assert not ok, f"'{malo}' debería ser inválido"
        assert msg


def test_rango_fechas_ok():
    fi, ff = validar_rango_fechas("2026-01-01", "2026-01-31")
    assert fi == date(2026, 1, 1)
    assert ff == date(2026, 1, 31)


def test_rango_fechas_invertido():
    with pytest.raises(ValueError, match="posterior"):
        validar_rango_fechas("2026-02-01", "2026-01-01")


def test_rango_fechas_futura():
    manana = (date.today() + timedelta(days=1)).isoformat()
    with pytest.raises(ValueError, match="futura"):
        validar_rango_fechas("2026-01-01", manana)


def test_rango_fechas_formato_malo():
    with pytest.raises(ValueError, match="aaaa-mm-dd"):
        validar_rango_fechas("01/01/2026", "31/01/2026")
    with pytest.raises(ValueError, match="indicar"):
        validar_rango_fechas("", "2026-01-01")
