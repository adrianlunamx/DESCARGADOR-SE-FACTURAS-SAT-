# 🧾 Mis Facturas SAT

App local (corre en tu PC) para ver y descargar **todos tus CFDI del SAT**:
facturas **emitidas** y **recibidas** —incluidas las **nóminas**
(TipoDeComprobante `N`, que entran en la misma descarga masiva).

Todo queda en tu computadora: base de datos SQLite, los XML descargados y la
app. No hay servicios externos ni cuentas en la nube.

## Requisitos

- Python 3.11 o superior
- `pip`
- Tus archivos de e.firma del SAT: `.cer`, `.key` y tu contraseña
  (solo para la descarga masiva; para probar el visor puedes importar XMLs a mano)

## Instalación

```bash
cd app
python3 -m venv .venv
source .venv/bin/activate   # en Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Cómo correrla

```bash
cd app
source .venv/bin/activate
uvicorn main:app --reload --port 8000
```

Abre en tu navegador: **http://127.0.0.1:8000**

> La app solo escucha en tu máquina (`127.0.0.1`). No la expongas a internet:
> tu e.firma vive en la memoria del proceso.

## Cómo obtener tus archivos de e.firma

1. Son los que generaste en el SAT o con tu contador: un `.cer` (certificado),
   un `.key` (llave privada) y la contraseña que les pusiste.
2. Si los perdiste, hay que revocar y generar una e.firma nueva en el SAT
   (cita o SAT ID); nadie puede "recuperar" la contraseña de una e.firma.
3. Guárdalos en una carpeta segura de tu PC. La app **nunca los copia a otro
   lado**: los lees desde el formulario y quedan solo en memoria.

## Flujo de uso

### Opción A — Descarga masiva del SAT (recomendada)

1. Pestaña **Descarga SAT** → paso 1: carga tu `.cer`, `.key`, contraseña y RFC.
2. Paso 2: elige tipo (*emitidas*, *recibidas* o *ambas*) y el rango de fechas,
   y pulsa **Solicitar al SAT**.
3. El SAT tarda de **minutos a horas** en preparar los paquetes. Puedes cerrar
   la app; la solicitud queda registrada.
4. Pestaña **Solicitudes** → **Revisar en el SAT** (vuelve a cargar tu e.firma
   si la sesión expiró). Cuando el SAT marque la solicitud como *terminada*,
   la app descarga los paquetes e importa los XML sola.
5. Pestaña **Facturas**: filtra, revisa el detalle, descarga XML/PDF o el ZIP.

### Opción B — Importar XMLs a mano (sin e.firma)

1. En el portal del SAT: *Factura electrónica → Cancela y recupera tus facturas*,
   consulta y descarga tus XML.
2. Pestaña **Importar XML** → indica si son emitidas o recibidas, selecciona
   los archivos e **Importar**. Listo: el visor, los filtros y los PDF
   funcionan igual.

### Filtros disponibles

- Chips rápidos: **Todas · Emitidas · Recibidas · 🧾 Nómina**
- Tipo de comprobante (Ingreso, Egreso, Nómina, Pago, Traslado), rango de
  fechas, RFC (emisor o receptor), búsqueda libre, monto mínimo/máximo.
- En las facturas de nómina la tabla muestra el **neto pagado** y el detalle
  abre la sección de nómina: fecha de pago, días pagados, percepciones,
  deducciones y neto.

## Seguridad de tu e.firma (regla no negociable)

- El `.cer`, el `.key` y la contraseña **nunca se escriben en disco**, nunca se
  guardan en la base de datos y nunca se suben a ningún servidor.
- Viven solo en la **memoria** del proceso de la app, asociados a un token de
  sesión aleatorio.
- La sesión **expira a los 30 minutos sin uso** o al pulsar *Cerrar sesión*.
- Si reinicias la app, hay que volver a cargar la e.firma. Es intencional.

## Estructura del proyecto

```
app/
├── main.py          # Backend FastAPI + endpoints
├── sat_client.py    # Adaptador al web service del SAT (librería satcfdi)
├── parser.py        # Parseo de XML CFDI 3.3/4.0 (+ complemento de nómina 1.2)
├── db.py            # SQLite local (facturas, impuestos, conceptos, solicitudes)
├── sesion.py        # Sesiones de e.firma: solo memoria, con expiración
├── pdf_gen.py       # Representación impresa en PDF con QR de verificación
├── static/
│   └── index.html   # UI web (un solo archivo, sin build step)
├── tests/
│   ├── test_parser.py
│   └── fixtures/    # XML de ejemplo con datos ficticios
├── data/            # facturas.db y xml/ (se crea solo; no subir a git)
└── requirements.txt
```

## Pruebas

```bash
cd app
source .venv/bin/activate
pytest tests/ -v
```

Las pruebas usan XML de ejemplo con datos 100% ficticios (RFC genérico
`XAXX010101000`): una factura de ingreso y un recibo de nómina.

## Limitaciones conocidas del MVP

- La **integración con el SAT está implementada según la documentación y el
  código de la librería `satcfdi`, pero pendiente de verificación con una
  e.firma real** (no había credenciales disponibles al construirla). El visor,
  los filtros, la importación manual, el PDF y el ZIP sí están probados.
- El **estatus de vigencia/cancelación** de cada CFDI se muestra como
  `sin_verificar`: el SAT lo informa en la descarga masiva como metadato, pero
  el MVP aún no lo cruza. Si necesitas saber si una factura fue cancelada,
  verifícala en el portal del SAT con el QR/UUID.
- Los CFDI de **retenciones** usan endpoints distintos del SAT y no están
  incluidos (solo facturas estándar y nómina).
- Límite del SAT: ~200 mil CFDI por solicitud; si pides un rango enorme y el
  SAT responde código `5003`, divide el periodo en meses.
- Los paquetes del SAT **vencen a las 72 horas**: revisa tus solicitudes a tiempo.

## Roadmap

- [ ] Verificación con e.firma real (probar solicitud → polling → descarga).
- [ ] Cruce del estatus vigente/cancelado desde la metadata del SAT.
- [ ] **Conciliación con el libro de gastos**: emparejar facturas recibidas con
      los movimientos del Google Sheet "Control de gastos e ingresos".
- [ ] Generación de **DIOT** a partir de las facturas recibidas.
- [ ] Detección de duplicados entre descargas y reportes mensuales.
- [ ] Soporte de CFDI de retenciones e información de pagos.
