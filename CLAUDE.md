# CLAUDE.md — Lharmonie Bot Envios

> **OBLIGATORIO:** Leer este archivo COMPLETO antes de tocar cualquier
> archivo del repo. Sin excepciones.

---

## Que es este proyecto

Bot de Telegram para gestionar envios de mercaderia entre el centro de
produccion y los locales de Lharmonie. Registra que se manda, a donde,
quien lo lleva, y permite al local receptor confirmar la recepcion.

**Repo:** `cronklam/cronklam-lharmonie-envios` (privado)
**Stack:** Python 3 + python-telegram-bot 21.6 + gspread + Google Sheets
**Deploy:** Railway (servicio `cronklam-lharmonie-en...` dentro del
proyecto `satisfied-wholeness`, junto al bot principal)
**Archivo principal:** `bot_envios.py` (~400 lineas)

**Dueno:** Martin Masri (martin.a.masri@gmail.com).
**Nombre:** siempre "Lharmonie" (sin apostrofe). Nunca "L'Harmonie".

---

## Estructura del repo

```
cronklam/cronklam-lharmonie-envios/
├── bot_envios.py       ← Bot completo (todo en un archivo)
├── requirements.txt    ← python-telegram-bot, gspread, google-auth
├── Procfile            ← worker: python bot_envios.py
└── CLAUDE.md           ← ESTE ARCHIVO
```

---

## Como funciona

### Flujo de envio
```
1. Encargado produccion: /enviar
2. Selecciona local destino (LH2/LH3/LH4/LH5)
3. Agrega productos:
   a. Selecciona categoria (Pasteleria, Elaborados, Varios)
   b. Selecciona producto del catalogo (o agrega manual con fuzzy matching)
   c. Indica cantidad y unidad
   d. Repite hasta completar
4. Selecciona transporte (Ezequiel/Uber)
5. Revisa resumen editable
6. Confirma → se registra en Google Sheet + notificacion a Martin/Iaras
```

### Flujo de recepcion
```
1. Encargado local: /recibir
2. Ve lista de envios pendientes para su local
3. Selecciona envio
4. Confirma recepcion con nombre del receptor
5. Si hay diferencia (faltante), lo reporta
6. Notificacion a Martin/Iaras
```

### Locales
| Codigo | Direccion |
|--------|-----------|
| LH2 | Nicaragua 6068 |
| LH3 | Maure 1516 |
| LH4 | Zabala 1925 |
| LH5 | Libertador 3118 |

### Transporte
- Ezequiel (Mister) — transporte propio
- Uber — cuando Ezequiel no esta disponible

---

## Google Sheets

### Conexion
- Sheet ID: via env var `ENVIOS_SHEETS_ID`
- Credenciales: misma service account que el resto (`GOOGLE_CREDENTIALS`)
- Cache TTL: 300 segundos (5 minutos)

### Pestana "Productos Envio"
Catalogo de productos editable. Columnas: Categoria | Producto | Unidad.
Si no existe, el bot la crea automaticamente con ~60 productos iniciales
en 3 categorias: Pasteleria, Elaborados, Varios.

### Pestana de envios
(Verificar nombre exacto) — registro de cada envio con fecha, origen,
destino, productos, cantidades, transporte, receptor, estado.

---

## Variables de entorno

| Variable | Descripcion |
|----------|-------------|
| `ENVIOS_TELEGRAM_TOKEN` | Token del bot de envios |
| `ENVIOS_SHEETS_ID` | ID del Google Sheet de envios |
| `GOOGLE_CREDENTIALS` | JSON de service account (compartida) |

**ATENCION:** El token de Telegram esta hardcodeado como fallback en el
codigo (`8631530577:AAGM...`). Esto es un riesgo de seguridad — deberia
estar SOLO en variables de entorno.

---

## Notificaciones

IDs de Telegram que reciben notificaciones de envios:
- `6457094702` — Martin
- `5358183977` — Iara Zayat
- `7354049230` — Iara Rodriguez

---

## Reglas que no se deben romper

1. **Los productos se editan desde Google Sheets, no desde codigo.**
   El catalogo es la pestana "Productos Envio" del Sheet.
2. **El bot NO modifica precios ni costos.** Solo registra cantidades
   y productos. Los costos se calculan en el pipeline P&L.
3. **Fuzzy matching para productos manuales.** Si el encargado tipea
   un producto que no esta en el catalogo, el bot busca el mas parecido
   con SequenceMatcher. Umbral configurable.
4. **Timezone Argentina.** Todas las fechas/horas usan UTC-3.

---

## Relacion con otros repos y areas

- **lharmonie-pnl-upload (Area 2: Finanzas):** Los envios tienen costo
  logistico que deberia reflejarse en el P&L. Hoy no estan conectados.
- **Area 4 (Produccion):** Los envios son el output de produccion.
  Conectar: produccion → envio → recepcion → diferencia = merma.
- **Area 8 (Logistica):** ESTE BOT es la base del sistema de logistica.
  Falta: remitos formales, control de stock por local, trazabilidad,
  marketplace interno de excedentes.
- **lharmonie-bot (bot principal):** Comparten el mismo proyecto Railway.
  Comparten `GOOGLE_CREDENTIALS`.

---

## Bugs conocidos / estado actual

- [ ] **Token hardcodeado** en el codigo — mover a env var only
- [ ] **Sin registro de recepciones** verificado — confirmar que la
      pestana de recepciones existe y funciona
- [ ] **Sin conexion con costos** — los envios no suman costo logistico
- [ ] **Sin control de stock** — solo registra movimiento, no actualiza
      stock del local destino
- [ ] **Procfile indica Heroku** (`worker: python bot_envios.py`) pero
      esta deployado en Railway — verificar compatibilidad

---

## Lecciones aprendidas

1. **El bot ya hace remitos basicos.** No hay que empezar de cero para
   el Area 8 (Logistica). El flujo envio→recepcion→diferencia ya existe.
   Falta: agregar costos por producto, stock por local, trazabilidad.
2. **El catalogo es editable desde Sheets.** Martin/Iara pueden agregar
   productos sin tocar codigo. Buen patron para reusar en otros bots.
3. **Dos bots en el mismo proyecto Railway.** El bot de envios y el bot
   principal comparten Railway. Si uno crashea, el otro sigue. Pero
   comparten env vars — cuidado al editar.
