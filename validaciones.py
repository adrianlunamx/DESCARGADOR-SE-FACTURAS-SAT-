"""Validaciones de entrada para la app (sin dependencias del SAT).

Todo lo que el usuario escribe en los formularios se valida aquí antes de
llegar al SAT, para dar errores claros en español en vez de códigos crípticos.
"""
from __future__ import annotations

import re
from datetime import date

# RFC mexicano: 3-4 letras (incluye Ñ y &) + 6 dígitos de fecha + 3 alfanuméricos
# Persona física: 13 caracteres (4 letras). Persona moral: 12 (3 letras).
RFC_RE = re.compile(r"^[A-ZÑ&]{3,4}[0-9]{6}[A-Z0-9]{3}$")

# UUID v4 genérico (el folio fiscal del CFDI)
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def validar_rfc(rfc: str | None) -> tuple[bool, str]:
    """Valida el formato de un RFC mexicano. Devuelve (válido, mensaje)."""
    if not rfc or not rfc.strip():
        return False, "El RFC es obligatorio."
    r = rfc.strip().upper()
    if not RFC_RE.match(r):
        return (
            False,
            f"'{rfc.strip()}' no parece un RFC válido: debe tener 12 o 13 "
            "caracteres (ej. AAA010101AAA). Revísalo y vuelve a intentarlo.",
        )
    return True, ""


def validar_uuid(folio: str | None) -> tuple[bool, str]:
    """Valida el formato de un folio fiscal (UUID). Devuelve (válido, mensaje)."""
    if not folio or not folio.strip():
        return False, "El folio fiscal (UUID) es obligatorio."
    if not UUID_RE.match(folio.strip()):
        return (
            False,
            "Ese folio no tiene formato de UUID válido "
            "(ej. 123e4567-e89b-12d3-a456-426614174000).",
        )
    return True, ""


def validar_rango_fechas(inicio: str | None, fin: str | None) -> tuple[date, date]:
    """Valida un rango de fechas ISO (aaaa-mm-dd).

    Devuelve (fecha_inicio, fecha_fin) o lanza ValueError con mensaje en español.
    """
    if not inicio or not fin:
        raise ValueError("Debes indicar fecha de inicio y fecha de fin.")
    try:
        fi = date.fromisoformat(inicio.strip())
        ff = date.fromisoformat(fin.strip())
    except ValueError:
        raise ValueError(
            "Las fechas deben tener formato aaaa-mm-dd (ej. 2026-01-01)."
        ) from None
    if fi > ff:
        raise ValueError(
            "La fecha de inicio no puede ser posterior a la fecha de fin."
        )
    hoy = date.today()
    if ff > hoy:
        raise ValueError(
            "La fecha de fin no puede ser futura: el SAT no tiene comprobantes "
            f"de después de hoy ({hoy.isoformat()})."
        )
    return fi, ff
