# 🧾 Mis Facturas SAT

![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.142-009688?logo=fastapi)
![Tests](https://img.shields.io/badge/tests-14%2F14-brightgreen)
![License](https://img.shields.io/badge/licencia-MIT-green)
![Local](https://img.shields.io/badge/100%25-local-orange)

App de escritorio local (corre en tu PC, sin nube) para consultar y descargar **todos tus CFDI del SAT**: facturas **emitidas** y **recibidas** —incluidas las **nóminas** (TipoDeComprobante `N`)— con visor, filtros, descarga de XML/PDF y conexión directa al web service de descarga masiva del SAT.

Todo queda en tu computadora: base de datos SQLite, los XML descargados y la app. No hay servicios externos, no hay cuentas, no hay telemetría.

## ✨ Características

- ✓ Descarga masiva del SAT por periodo: emitidas, recibidas o ambas
- ✓ Búsqueda de un comprobante por **folio fiscal (UUID)**
- ✓ Dos tipos de descarga: **CFDI** (XML completos) o **Metadata** (listado ligero, incluye cancelados)
- ✓ Filtro opcional por RFC de contraparte (emisor en recibidas, receptor en emitidas)
- ✓ Atajos de rango: últimos 7/30 días, este mes, este año
- ✓ **Auto-refresh**: las solicitudes en proceso se revisan solas cada 3 segundos
- ✓ La tabla de solicitudes **muestra el motivo del SAT** (código + mensaje) cuando algo falla
- ✓ Visor con filtros (tipo, fechas, RFC, texto libre, montos), paginación y chips por flujo
- ✓ Detalle de factura en panel lateral: conceptos, impuestos, sección dedicada de nómina (percepciones, deducciones, neto)
- ✓ Descarga individual de **XML** y **PDF** (representación impresa con QR oficial de verificación)
- ✓ Exportación masiva en **ZIP** con los filtros aplicados
- ✓ Importación manual de XML (útil sin e.firma o para XML descargados del portal)
- ✓ **Seguridad**: tu e.firma vive solo en memoria RAM, expira a los 30 min y nunca toca el disco

## 📸 Capturas

> Pega aquí tus capturas cuando la tengas corriendo.

| Visor de facturas | Descarga SAT | Detalle de nómina |
|---|---|---|
| `docs/img/visor.png` | `docs/img/descarga.png` | `docs/img/nomina.png` |

## 🚀 Instalación (desde GitHub)

```bash
# 1. Clona el repo
git clone https://github.com/adrianlunamx/DESCARGADOR-SE-FACTURAS-SAT-.git
cd DESCARGADOR-SE-FACTURAS-SAT-

# 2. Crea el entorno virtual
python -m venv .venv

# 3. Actívalo
source .venv/bin/activate        # Linux/Mac
.venv\Scripts\Activate.ps1       # Windows PowerShell

# 4. Instala dependencias
pip install -r requirements.txt

# 5. Corre la app
uvicorn main:app --port 8000
```

Abre en tu navegador: **http://127.0.0.1:8000**

> La app solo escucha en tu máquina (`127.0.0.1`). No la expongas a internet: tu e.firma vive en la memoria del proceso.

<details>
<summary><b>Instalación alternativa: ZIP</b></summary>

Si prefieres no usar git, descarga el ZIP del repo (Code → Download ZIP), descomprímelo y sigue desde el paso 2.
</details>

### Requisitos

- Python 3.12 (probado en 3.12; 3.11+ debería funcionar)
- Tus archivos de e.firma del SAT: `.cer`, `.key` y contraseña (solo para la descarga masiva; el visor funciona sin ellos importando XML a mano)

## 📖 Uso paso a paso

### Opción A — Descarga masiva del SAT (recomendada)

1. Pestaña **Descarga SAT** → paso 1: carga tu `.cer`, `.key`, contraseña y RFC (se valida el formato antes de enviar nada).
2. Paso 2: elige tipo (*emitidas*, *recibidas* o *ambas*), tipo de descarga (**CFDI** o **Metadata**), el rango de fechas (usa los atajos si quieres) y, opcionalmente, un RFC de contraparte para acotar.
3. Pulsa **Solicitar al SAT**. El SAT tarda de **minutos a horas** en preparar los paquetes; puedes cerrar la app, la solicitud queda registrada.
4. Pestaña **Solicitudes**: las que estén en proceso **se revisan solas cada 3 segundos** (también hay botón manual). Cuando el SAT marque una como *terminada*, la app descarga los paquetes e importa los XML sola. Si el SAT la rechaza, verás el **motivo exacto** en la tabla.
5. Pestaña **Facturas**: filtra, abre el detalle, descarga XML/PDF o el ZIP.

### Opción B — Buscar por folio fiscal (UUID)

En **Descarga SAT** → paso 3, pega el UUID del comprobante y pulsa **Buscar**. El SAT lo prepara como una solicitud más y aparece en **Solicitudes**.

### Opción C — Importar XML a mano

Pestaña **Importar XML**: sube los XML que hayas bajado del portal del SAT (*Factura electrónica → Cancela y recupera tus facturas*). Útil para probar sin e.firma.

## 🗂️ Estructura del proyecto

```
.
├── main.py            # Backend FastAPI: endpoints, validaciones, orquestación SAT
├── sat_client.py      # Cliente del web service de descarga masiva (vía satcfdi)
├── validaciones.py    # Validación de RFC, UUID y rangos de fechas (con tests)
├── parser.py          # Parseo de XML CFDI 3.3/4.0 + complemento de nómina 1.2
├── db.py              # SQLite local (facturas, impuestos, conceptos, solicitudes)
├── sesion.py          # e.firma SOLO en memoria (expira a los 30 min)
├── pdf_gen.py         # Representación impresa en PDF con QR oficial del SAT
├── static/index.html  # UI completa en un solo archivo (sin build, sin CDNs)
├── tests/             # pytest: parser + validaciones (14 pruebas)
├── requirements.txt   # dependencias con versiones fijadas
└── data/              # BD y XML (se crea solo; no se versiona)
    ├── facturas.db
    ├── xml/           # XML descargados/importados
    └── metadata/      # archivos crudos de metadata del SAT
```

## 🛰️ Quirks del SAT (documentados con la práctica)

La descarga masiva del SAT tiene sus mañas. Estas están verificadas contra el servicio real:

| Código | Significado | Qué hacer |
|---|---|---|
| 300 | Usuario no válido | Revisa RFC y e.firma |
| 301 | XML mal formado (p. ej. RFC inválido) | La app valida el RFC antes de enviar; si lo ves, revisa el dato |
| 302/303 | Sello mal formado / no corresponde | Tu .cer y .key no hacen pareja: usa los vigentes |
| 304/305 | Certificado revocado, caduco o inválido | Renueva tu e.firma en el SAT |
| 5000 | Solicitud recibida | Todo bien; espera el proceso |
| 5002/5005 | Solicitud duplicada | Ya hay una igual en proceso; espera |
| 5003 | Demasiados comprobantes | Divide el rango en periodos más cortos |
| **5004** | **Sin información en el periodo** | **No es un error**: no hay CFDIs en ese rango (el SAT lo marca como "rechazada") |
| 5011 | Límite diario de folios | Intenta mañana |
| 5012 | Comprobante cancelado | No se puede descargar ese XML por folio |

**Quirk importante (SAT v1.5):** el atributo `EstadoComprobante` es obligatorio aunque la documentación diga que es opcional. Si se omite, el SAT rechaza con 301 *"No se permite la descarga de xml que se encuentren cancelados"*. La app siempre envía `EstadoComprobante=Vigente`: solo trae comprobantes vigentes. Los cancelados no vienen en la descarga CFDI (para verlos usa **Metadata**).

**Tiempos reales:** el SAT tarda de minutos a horas en preparar los paquetes (típico: 20–35 min). Los paquetes vencen a las 72 horas.

## 🔒 Seguridad

- Tu `.cer`, `.key` y contraseña **viven solo en la memoria RAM** del proceso, asociados a un token aleatorio. Nunca se escriben en disco, nunca van a la base de datos, nunca salen de tu máquina.
- La sesión expira a los **30 minutos sin uso** o al cerrar sesión / detener la app.
- La app escucha solo en `127.0.0.1`. No la publiques ni la pongas detrás de un túnel.
- El PDF es solo la representación impresa: **el documento con validez fiscal es el XML**.

## ❓ Troubleshooting / FAQ

**"Se recibió un RfcEmisor/RfcReceptor inválido (código 301)"**
El RFC tenía formato incorrecto. La app ahora lo valida antes de enviar (12–13 caracteres, ej. `AAA010101AAA`).

**"No se permite la descarga de xml que se encuentren cancelados (código 301)"**
Era el quirk de `EstadoComprobante` (ver tabla de arriba). Ya está corregido en el código: siempre se envía `Vigente`.

**Mi solicitud de emitidas sale "rechazada"**
Casi seguro es código **5004**: no tienes comprobantes emitidos en ese periodo. No es un error de la app. Revisa el motivo en la columna correspondiente.

**La solicitud lleva horas "en proceso"**
Normal. El SAT puede tardar horas. Déjala y revisa más tarde; el auto-refresh la detectará cuando termine.

**"No hay sesión de e.firma activa (o expiró)"**
Pasaron 30 min sin uso o reiniciaste la app. Vuelve a cargar tu e.firma en la pestaña Descarga SAT.

**En Windows, `python` abre la tienda o no se reconoce**
Usa el Python instalado (3.12): sal del intérprete con `Ctrl+Z` + Enter y usa `python` (no `python3`). Si PowerShell bloquea el script de activación: `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`.

**¿Probar sin e.firma?**
En `tests/fixtures/` hay una factura y un recibo de nómina ficticios: impórtalos desde la pestaña Importar XML y explora el visor.

## 🗺️ Roadmap

- [ ] Parseo estructurado del archivo de metadata (hoy se guarda crudo para descarga)
- [ ] Conciliación de facturas contra movimientos bancarios
- [ ] Verificación de estatus vigente/cancelado por UUID contra el SAT
- [ ] Exportación a Excel/CSV del listado filtrado
- [ ] Soporte de CFDI de retenciones

## 📄 Licencia

MIT — ver [LICENSE](LICENSE). Úsala, modifícala y compártela libremente.
