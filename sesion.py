"""Sesiones de e.firma: las credenciales viven SOLO en memoria.

REGLA DE SEGURIDAD (no negociable):
- El .cer, el .key y la contraseña de la e.firma NUNCA se escriben en disco,
  NUNCA se guardan en la base de datos y NUNCA se suben a ningún servidor.
- Se guardan en un dict en memoria del proceso, asociado a un token aleatorio.
- La sesión expira a los 30 minutos de inactividad o al cerrar sesión.
- Al expirar, las referencias se eliminan y Python libera la memoria.

Si el proceso se reinicia, hay que volver a cargar la e.firma. Es intencional.
"""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field

# 30 minutos de expiración por inactividad
TTL_SEGUNDOS = 30 * 60


@dataclass
class SesionEFirma:
    cer_bytes: bytes
    key_bytes: bytes
    password: str
    rfc: str
    ultimo_uso: float = field(default_factory=time.time)

    def tocar(self) -> None:
        self.ultimo_uso = time.time()

    def expirada(self) -> bool:
        return (time.time() - self.ultimo_uso) > TTL_SEGUNDOS


_sesiones: dict[str, SesionEFirma] = {}


def _limpiar_expiradas() -> None:
    ahora = time.time()
    for token in [t for t, s in _sesiones.items()
                  if ahora - s.ultimo_uso > TTL_SEGUNDOS]:
        del _sesiones[token]


def crear_sesion(cer_bytes: bytes, key_bytes: bytes, password: str, rfc: str) -> str:
    """Guarda la e.firma en memoria y devuelve un token de sesión."""
    _limpiar_expiradas()
    token = secrets.token_urlsafe(32)
    _sesiones[token] = SesionEFirma(
        cer_bytes=cer_bytes, key_bytes=key_bytes, password=password,
        rfc=rfc.upper().strip(),
    )
    return token


def obtener_sesion(token: str) -> SesionEFirma | None:
    """Devuelve la sesión si existe y no expiró (None en caso contrario)."""
    _limpiar_expiradas()
    sesion = _sesiones.get(token)
    if sesion is None or sesion.expirada():
        _sesiones.pop(token, None)
        return None
    sesion.tocar()
    return sesion


def cerrar_sesion(token: str) -> None:
    """Elimina la sesión y con ella toda referencia a la e.firma."""
    _sesiones.pop(token, None)
