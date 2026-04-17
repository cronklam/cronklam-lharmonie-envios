# CLAUDE.md — Lharmonie Bot Envios + Stock

> **OBLIGATORIO:** Leer este archivo COMPLETO antes de tocar cualquier
> archivo del repo. Sin excepciones.

---

## Que es este proyecto

Bot de Telegram para CARGA DE DATOS de logistica y stock de Lharmonie.
Los empleados registran envios, recepciones, stock por zona y
fermentacion. El bot NO muestra reportes ni stock — es solo INPUT.
Los reportes van a un dashboard (por construir).

**Repo:** `cronklam/cronklam-lharmonie-envios` (privado)
**Stack:** Python 3 + python-telegram-bot 21.6 + gspread + google-auth + requests
**Deploy:** Railway (servicio `cronklam-lharmonie-en...` dentro del
proyecto `satisfied-wholeness`, junto al bot principal)
**Archivo principal:** `bot_envios.py` (~1453 lineas)

**Dueno:** Martin Masri (martin.a.masri@gmail.com).
**Nombre:** siempre "Lharmonie" (sin apostrofe). Nunca "L'Harmonie".

---

## Estructura del repo

```
cronklam/cronklam-lharmonie-envios/
├── bot_envios.py       ← Bot completo (envios + stock, todo en un archivo)
├── requirements.txt    ← python-telegram-bot, gspread, google-auth, requests
├── Procfile            ← worker: python bot_envios.py
└── CLAUDE.md           ← ESTE ARCHIVO
```

---

## Locales (ESTADO REAL abril 2026)

| Local | Direccion | Estado | Rol |
|-------|-----------|--------|-----|
| LH1 | Segui | CERRADO (en remodelacion) | Futuro: reapertura |
| LH2 | Nicaragua 6068 | Activo | LOCAL + CENTRO DE PRODUCCION (CDP) |
| LH3 | Maure 1516 | Activo | Local retail |
| LH4 | Zabala 1925 | Activo | Local retail |
| LH5 | Libertador 3118 | Activo | Local retail |
| LH6 | Nunez (TBD) | Proxima apertura | 6to local |

**IMPORTANTE:**
- **CDP = Nicaragua (LH2)**, NO Segui. Martin: "El centro de produccion es Nicaragua."
- **LH1 (Segui) esta CERRADO** — no incluir en opciones activas
- **CDP opera como unidad separada** de Nicaragua local, aunque estan en el mismo lugar fisico
- **6to local en Nunez** viene en camino — anticipar en diseno

---

## SISTEMA DE STOCK (nuevo abril 2026)

### Modelo de 2 estados (NO 4)

Martin rechazo explicitamente el modelo de 4 estados.
**Solo 2 estados: CONGELADO (en freezer) y HORNEADO (ya horneado/listo).**
Quote: "No serian 4 estados, son 2. Freezado o ya horneado."

### Movimientos que se trackean

Aunque solo hay 2 estados, se registran TODOS los movimientos:
- **ENVIO_RECIBIDO** — de CDP a local
- **FERMENTACION** — de freezer, en proceso
- **HORNEADO** — pasa a HORNEADO
- **VENTA** — sale de HORNEADO (dato de Bistrosoft POS)
- **TRANSFER** — entre locales
- **MERMA** — descarte

### Zonas de carga por local (3 zonas)

- **Cocina**: los chicos de cocina cargan stock de cocina (freezer/congelados)
- **Mostrador**: encargado de mostrador carga lo de mostrador (horneado exhibido)
- **Barra**: deberia cargar el de barra

Hoy solo cargan cocina y mostrador via Google Forms. Barra es nuevo.

### Auditoria AUTOMATICA (no manual)

Martin NO quiere que los encargados hagan auditoria manual.
La auditoria se calcula sola cuando hay datos del POS (Bistrosoft):
`Stock apertura + Envios + Horneado - Ventas(Bistrosoft) - Transfers - Merma = Stock cierre teorico`
Se compara contra stock real cargado → diferencia = discrepancia automatica.

### Sugerencia de fermentacion

DEBE contemplar:
1. Stock CONGELADO disponible para sacar a fermentar
2. Stock HORNEADO que ya hay de ese dia
3. Demanda esperada de manana (dia de semana, clima, fechas especiales, tendencia)
→ Resultado: cuanto sacar a fermentar

### Propositos del stock (5)

1. **Auditorias**: conciliar ventas Bistrosoft vs diferencias de stock
2. **Generacion automatica de pedidos**: stock minimo - stock actual = pedido a CDP
3. **Verificar que CDP tiene para mandar**: antes de pedir, chequear disponibilidad
4. **Sugerencias inteligentes**: clima, dia, tendencia → cuanto fermentar
5. **Transfers entre locales**: reducir merma (productos duran max 2 dias)

### Stock Minimo

Se saca de Bistrosoft Sheet, tab "Stock Minimo" (promedio de qty por dia de semana x 2).
Sheet ID: `1s6kPguwD25k3xpmbUoHq1KNFd_SEva3z7pvTGhA4bsE`

---

## Como funciona — ENVIOS

### Flujo de envio
```
1. Encargado produccion: /enviar o boton "Nuevo envio"
2. Selecciona local destino (CDP/LH2/LH3/LH4/LH5)
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
1. Encargado local: /recibir o boton "Recibir envio"
2. Ve lista de envios pendientes para su local
3. Selecciona envio
4. Confirma recepcion con nombre del receptor
5. Si hay diferencia (faltante), lo reporta
6. Notificacion a Martin/Iaras
7. Stock del local se actualiza automaticamente con los items recibidos
```

---

## Como funciona — STOCK

### Comandos principales

| Comando | Que hace |
|---------|----------|
| `/stock` o "Ver stock" | Muestra stock actual del local seleccionado |
| `/cargar` o "Cargar stock" | Inicia carga de stock por zona |
| `/sugerencia` o "Sugerencias" | Muestra sugerencias de pedido y fermentacion |
| `/reporte` o "Reporte" | Reporte global de todos los locales |

### Flujo de carga de stock
```
1. Encargado: /cargar
2. Selecciona local
3. Selecciona zona (Cocina/Mostrador/Barra)
4. Selecciona producto
5. Indica cantidad y estado (CONGELADO o HORNEADO)
6. Puede agregar mas productos o finalizar
7. Se actualiza el Sheet y se loguea el movimiento
```

### Flujo de sugerencias
```
1. /sugerencia
2. Selecciona local
3. Bot muestra:
   a. Sugerencia de pedido: items bajo stock minimo
   b. Sugerencia de fermentacion: basada en stock actual + demanda esperada
```

---

## Google Sheets (TODO EN UNO SOLO)

Martin decidio usar el mismo Sheet que envios para todo (logistica, stock,
produccion). Sheet ID via env var `ENVIOS_SHEETS_ID`.

### Pestanas

| Pestana | Tipo | Descripcion |
|---------|------|-------------|
| `Productos Envio` | Catalogo | Categoria, Producto, Unidad (~60 items) |
| `Envios` | Registro | Fecha, origen, destino, productos, transporte, estado |
| `Stock_{LOCAL}` | Stock actual | Producto, Congelado, Horneado, Zona, Ultima actualizacion |
| `Movimientos` | Log | Timestamp, local, producto, tipo, cantidad, estado, usuario |

**Pestanas creadas automaticamente:** Si no existen, el bot las crea al
primer uso (`_ensure_stock_tabs()`). El catalogo de productos se sincroniza
desde la pestana "Productos Envio".

### Credenciales

- **Service account:** `bot-sheets@lharmonie-bot.iam.gserviceaccount.com`
- **ATENCION:** NO confundir con `pnl-drive-sync@...` que es del pipeline P&L.
  Los bots usan `bot-sheets@`, el pipeline usa `pnl-drive-sync@`.

---

## Variables de entorno

| Variable | Descripcion |
|----------|-------------|
| `ENVIOS_TELEGRAM_TOKEN` | Token del bot de envios |
| `ENVIOS_SHEETS_ID` | ID del Google Sheet (envios + stock) |
| `GOOGLE_CREDENTIALS` | JSON de service account (compartida con bot principal) |

**ATENCION:** El token de Telegram esta hardcodeado como fallback en el
codigo (`8631530577:AAGM...`). Esto es un riesgo de seguridad — deberia
estar SOLO en variables de entorno.

---

## Notificaciones

IDs de Telegram que reciben notificaciones:
- `6457094702` — Martin
- `5358183977` — Iara Zayat
- `7354049230` — Iara Rodriguez

---

## Arquitectura del codigo

### Estado del usuario

El bot usa un dict `estado_usuario` (NO ConversationHandler de python-telegram-bot).
Cada usuario tiene su propio estado con contexto del flujo actual.

### Funciones principales (~49 funciones)

**Envios:** handle_button, flujo_enviar_*, flujo_recibir_*, confirmar_envio,
confirmar_recepcion, cmd_enviar, cmd_recibir

**Stock:** get_stock_sheet, _get_or_create_stock_ws, _ensure_stock_tabs,
stock_get_all_products, stock_get_minimums, stock_read_actual,
stock_update_product, stock_log_movement, stock_apply_movement,
stock_apply_envio_recibido, stock_check_alerts, _send_stock_alerts,
_format_stock_for_local, _format_sugerencia_pedido,
_format_sugerencia_fermentacion, _format_reporte_global,
cmd_stock, cmd_cargar, cmd_sugerencia, cmd_reporte

**Menu:** cmd_start (menu principal con 6 botones)

### Menu principal (4 botones, simplificado 17 abril 2026)

```
📦 Enviar         📥 Recibir
📝 Cargar stock   🔥 Fermentación
```

**REGLA UX (Martin, 17 abril 2026):** El bot es SOLO para cargar datos.
Los empleados NO deben ver stock ni reportes. Eso va a un dashboard.
"No necesito que vean ahi el stock que cargaron, justamente el chiste es
que no lo vean."

---

## Config clave en el codigo

```python
LOCALES_STOCK = [
    "CDP - Nicaragua (Produccion)",
    "LH2 - Nicaragua 6068",
    "LH3 - Maure 1516",
    "LH4 - Zabala 1925",
    "LH5 - Libertador 3118",
]
LOCALES_RETAIL = [loc for loc in LOCALES_STOCK if "CDP" not in loc]
LOCAL_KEYS = ["LH2", "LH3", "LH4", "LH5"]
ZONAS = ["Cocina", "Mostrador", "Barra"]
```

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
5. **Solo 2 estados de stock.** CONGELADO y HORNEADO. NUNCA agregar mas.
6. **Auditoria automatica, no manual.** Martin lo pidio explicitamente.
7. **Mismo Sheet para todo.** Envios, stock, movimientos — todo en el
   mismo Google Sheet. NO crear sheets separados.
8. **CDP es Nicaragua, NO Segui.** LH1 esta cerrado.

---

## Relacion con otros repos y areas

- **Api-bistrosoft (Area 1: Ventas):** Bistrosoft provee datos de ventas
  por local. El stock los usa para auditorias automaticas (ventas Bistrosoft
  = lo que salio de HORNEADO). Sheet: `1s6kPguwD25k3xpmbUoHq1KNFd_SEva3z7pvTGhA4bsE`
- **lharmonie-pnl-upload (Area 2: Finanzas):** Los envios tienen costo
  logistico que deberia reflejarse en el P&L.
- **Area 4 (Produccion):** Los envios son el output de produccion.
  Produccion → envio → recepcion → diferencia = merma.
- **Area 5 (Logistica/Stock):** ESTE BOT es el sistema central.
  Maneja remitos, stock, sugerencias, auditorias.
- **lharmonie-bot (bot principal):** Comparten el mismo proyecto Railway.
  Comparten `GOOGLE_CREDENTIALS`.

---

## Deploy en Railway

- **Proyecto:** `satisfied-wholeness`
- **Servicio:** `cronklam-lharmonie-en...` (nombre truncado en Railway UI)
- **Procfile:** `worker: python bot_envios.py`
- **Auto-deploy:** Si, desde branch `main` de GitHub
- Cada push a main redeploya automaticamente

---

## Bugs conocidos / pendientes

- [ ] **Token hardcodeado** en el codigo — mover a env var only
- [ ] **STOCK_SHEETS_ID eliminado** — ahora usa ENVIOS_SHEETS_ID para todo.
      Verificar que Railway tenga ENVIOS_SHEETS_ID seteado correctamente.
- [ ] **Pestanas de stock se crean al primer uso** — verificar que la service
      account tenga permisos de edicion en el Sheet
- [ ] **Sugerencia de fermentacion simplificada** — usa dia de semana + stock
      actual. Falta integrar clima (requests ya en requirements) y fechas
      especiales
- [ ] **Integracion Bistrosoft pendiente** — cmd_stock lee stock minimo de
      Bistrosoft Sheet pero la auditoria automatica (ventas vs stock) aun no
      esta implementada como cron/scheduled task
- [ ] **Sin tests** — el bot no tiene tests unitarios
- [ ] **Procfile indica Heroku** (`worker: python bot_envios.py`) pero
      esta deployado en Railway — funciona igual pero verificar

---

## Lecciones aprendidas

1. **El bot ya hace remitos basicos + stock.** El flujo
   envio→recepcion→diferencia→stock existe. Falta conectar Bistrosoft
   para auditorias automaticas.
2. **El catalogo es editable desde Sheets.** Martin/Iara pueden agregar
   productos sin tocar codigo. Buen patron para reusar.
3. **Dos bots en el mismo proyecto Railway.** El bot de envios y el bot
   principal comparten Railway. Si uno crashea, el otro sigue. Pero
   comparten env vars — cuidado al editar.
4. **Martin quiere 2 estados, no 4.** Se propuso modelo de 4 estados
   (CONGELADO → FERMENTANDO → HORNEADO → MOSTRADOR) y Martin lo rechazo.
   Solo CONGELADO y HORNEADO. No volver a proponer.
5. **Todo en un solo Sheet.** Martin pidio que envios y stock compartan
   el mismo Google Sheet. No crear sheets separados.
6. **CDP opera separado de Nicaragua retail.** Aunque estan en el mismo
   lugar fisico, el CDP es una unidad logica separada para produccion/envios.
7. **Productos duran max 2 dias.** Esto es critico para las sugerencias
   de transfer entre locales — si un local tiene excedente y otro deficit,
   hay que mover antes de que se pierda.
8. **Stock minimo viene de Bistrosoft.** La tab "Stock Minimo" de la Sheet
   Bistrosoft tiene promedio de qty por dia de semana x 2. Es la fuente
   de verdad para las sugerencias de pedido.
9. **Lharmonie NO abre sabados (Shabbat).** Datos faltantes en sabados
   son correctos, no son bugs.
10. **Vision futura: app propia.** Martin dijo "En algun momento quiero
    dejar todo en una sola app seria y prolija". Pero por ahora: bot
    Telegram + Google Sheets. La arquitectura esta pensada para que la
    logica se pueda migrar a un backend de app en el futuro.
11. **TEXTO LIBRE > MENUS (17 abril 2026).** La version con menus de
    categoria/producto/cantidad era "muy complejo". Martin pidio que
    acepte texto directo: "medialunas 50, budines 20". El bot parsea
    con fuzzy matching. NUNCA volver a hacer flujos multi-step para
    cargar productos. Texto libre + fuzzy match + confirmar = listo.
12. **Espanol ARGENTINO, no formal.** "Dale", "manda", "listo", "anotado".
    Tuteo ("vos mandas", "elegi"). No "Confirmar envio", no "Desea usted".
    Los usuarios son encargados laburando rapido, no ejecutivos.
13. **Bot = INPUT, dashboard = OUTPUT.** El bot NO muestra stock, reportes,
    sugerencias. Solo CARGA datos. Para ver cuanto producir, cuanto enviar,
    stock por local, etc → dashboard (por construir). Martin: "para saber
    cuanto tiene que producir y cuanto enviar vamos a armar un dashboard".
14. **No mostrar resumen al empleado.** Despues de cargar stock o fermentacion,
    no mostrar lo que cargaron. "El chiste es que no lo vean." Solo confirmar
    "Anotado" y listo. La transparencia es para Martin en el dashboard.

---

## ACTUALIZAR EN

- **Project instructions (parte 9):** Proceso 5.1 (Remitos) puede pasar
  de "Basico" a "Funcional con stock". Proceso 5.2 (Stock por local) pasa
  de "No existe" a "MVP funcional".
- **lharmonie-bot CLAUDE.md:** Anotar que el bot de envios ahora maneja
  stock tambien, para que no se duplique funcionalidad.
