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
**Archivo principal:** `bot_envios.py` (~2074 lineas)

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

### Flujo de envio (simplificado 17 abril 2026)
```
1. Encargado produccion: /enviar o boton "📦 Enviar"
2. Ingresa su nombre
3. Selecciona local destino (CDP/LH2/LH3/LH4/LH5)
4. Escribe productos en TEXTO LIBRE: "medialunas 50, budines 20"
   Bot parsea con fuzzy matching contra catalogo
5. Selecciona transporte (Ezequiel/Uber)
6. Revisa resumen editable (puede agregar/quitar/cambiar)
7. Confirma → se registra en Google Sheet + notificacion a Martin/Iaras
```

**CAMBIO CLAVE (17 abril 2026):** Se eliminaron los menus de categoria →
producto → cantidad. Ahora es texto libre directo. Martin: "muy complejo".

### Flujo de recepcion
```
1. Encargado local: /recibir o boton "📥 Recibir"
2. Ve lista de envios pendientes para su local
3. Selecciona envio
4. Confirma recepcion con nombre del receptor
5. Si hay diferencia (faltante), lo reporta
6. Notificacion a Martin/Iaras
7. Stock del local se actualiza automaticamente con los items recibidos
```

---

## Como funciona — STOCK (reescrito 17 abril 2026)

### Flujo de carga de stock (TEMPLATE)
```
1. Encargado: boton "📝 Cargar stock"
2. Selecciona local (CDP/LH2/LH3/LH4/LH5)
3. Selecciona zona (Cocina/Mostrador/Barra)
4. Bot envia TEMPLATE con todos los productos de esa zona:
   "🧊 COCINA — LH3 - Maure 1516
    Completá las cantidades y mandá:

    Medialunas: _
    Budín banana: _
    Alfajor de chocolate: _
    ..."
5. Empleado copia, completa cantidades, envia de vuelta
6. Bot parsea con _parsear_template(), ignora ": 0" y ": _"
7. Guarda via stock_apply_movement(TIPO_CARGA_STOCK)
8. Responde solo "✅ Anotado" (NO muestra resumen)
```

**Estado default por zona:** Cocina=CONGELADO, Mostrador=HORNEADO, Barra=HORNEADO
(dict `ZONA_DEFAULT_STATE` en el codigo).

### Flujo de fermentacion (TEMPLATE)
```
1. Encargado: boton "🔥 Fermentación"
2. Selecciona local
3. Bot lee stock CONGELADO actual del local
4. Envia template con stock disponible:
   "🔥 FERMENTACIÓN — LH3 - Maure 1516
    Cuánto sacás a fermentar de cada uno:

    Medialunas (hay 120): _
    Budín banana (hay 30): _
    ..."
5. Empleado completa cantidades
6. Bot parsea, decrementa CONGELADO por cada producto
7. Responde solo "✅ Anotado"
```

### Ordenes del dia (ex-sugerencias)
```
1. Encargado: boton "📋 Órdenes del día"
2. Selecciona local
3. Bot muestra en tono IMPERATIVO:
   a. Pedido a CDP: items bajo stock minimo
   b. Fermentacion: basada en stock congelado + dia de semana
```

### Comandos ELIMINADOS (17 abril 2026)
- `/stock` (Ver stock) — ELIMINADO. Empleados no deben ver stock.
- `/reporte` (Reporte global) — ELIMINADO. Va al dashboard.
- `/sugerencia` — RENOMBRADO a `/ordenes` (Ordenes del dia).
- Funciones eliminadas: `cmd_stock`, `cmd_reporte`, `_format_stock_for_local`,
  `_format_reporte_global`, todos los handlers de cargar step-by-step
  (cargar_eligiendo_tipo, cargar_tipo_*, cargar_cat_*, cargar_prod_*, etc.)

---

## Google Sheets (TODO EN UNO SOLO)

Martin decidio usar el mismo Sheet que envios para todo (logistica, stock,
produccion). Sheet ID via env var `ENVIOS_SHEETS_ID`.

### Pestanas

| Pestana | Tipo | Descripcion |
|---------|------|-------------|
| `Productos Envio` | Catalogo | Categoria, Producto, Unidad, Zona (~90 items, 4 columnas) |
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

### Funciones principales (post-rewrite 17 abril 2026)

**Envios:** handle_button, flujo_enviar_* (nombre→destino→texto libre→transporte→
resumen→confirmar), flujo_recibir_*, confirmar_envio, confirmar_recepcion

**Stock (template):** get_stock_sheet, _get_or_create_stock_ws, _ensure_stock_tabs,
stock_get_all_products, stock_get_minimums, stock_read_actual,
stock_update_product, stock_log_movement, stock_apply_movement,
stock_apply_envio_recibido, stock_check_alerts, _send_stock_alerts,
_get_products_for_zone, _parsear_template, _format_orden_pedido,
_format_orden_fermentacion

**Constantes nuevas:** ZONA_DEFAULT_STATE (zona→estado default),
TIPO_CARGA_STOCK ("carga_stock" — nuevo tipo de movimiento)

**Menu:** cmd_start + _main_menu_keyboard (menu principal con 5 botones)

### Menu principal (5 botones, 17 abril 2026)

```
📦 Enviar         📥 Recibir
📝 Cargar stock   🔥 Fermentación
📋 Órdenes del día
```

**REGLA UX (Martin, 17 abril 2026):** El bot es SOLO para cargar datos.
Los empleados NO deben ver stock ni reportes. Eso va a un dashboard.
"No necesito que vean ahi el stock que cargaron, justamente el chiste es
que no lo vean."

**REGLA: DIRECTIVAS, NO SUGERENCIAS.** Las ordenes del dia (pedido a CDP,
fermentacion) se presentan como HECHOS, no como opcionales. Martin:
"lo que tienen que sacar a fermentar o los envios no pueden ser sugerencias,
tienen que ser un hecho."

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
- [ ] **Ordenes del dia simplificadas** — usa dia de semana + stock actual.
      Falta integrar clima (requests ya en requirements) y fechas especiales.
      NOTA: renombrado de "Sugerencias" a "Ordenes" porque Martin dijo que
      fermentacion/envios "no pueden ser sugerencias, tienen que ser un hecho"
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
15. **DIRECTIVAS, no sugerencias (17 abril 2026).** Martin: "lo que tienen
    que sacar a fermentar o los envios no pueden ser sugerencias, tienen que
    ser un hecho." La feature "Sugerencias" fue renombrada a "Ordenes del dia".
    El tono es imperativo: "Saca 50 medialunas", no "Sugerimos sacar 50".
    NUNCA volver a usar lenguaje opcional para cantidades de fermentacion/envios.
16. **Zone-aware product catalog (17 abril 2026).** La pestana "Productos Envio"
    ahora tiene 4 columnas: Categoria, Producto, Unidad, Zona. Cada producto
    se asigna a Cocina, Mostrador, Barra (o combinaciones). Al cargar stock,
    el bot muestra checklist solo de productos de esa zona. ~90 productos
    totales distribuidos en 3 zonas.
17. **Bistrosoft Transacciones tab rota (17 abril 2026).** Martin noto que
    la tab solo tiene datos de Marzo. Deberia tener rolling 15 dias siempre
    (para Stock Minimo). Fix pendiente en repo Api-bistrosoft DESPUES del bot.
    **UPDATE:** Fix deployado — STEP 5 en monthly_close.yml restaura rolling.
    Pero la API de Bistrosoft no devolvía datos de Abril al 17 abril (Pesaj).
    Cuando la API tenga datos, el daily sync los agrega automáticamente.
18. **TEMPLATE > MENUS para carga de stock (17 abril 2026).** La version con
    menus step-by-step (elegir producto → cantidad → estado → siguiente) tenia
    8 pasos por producto y daba "error producto" constantemente (cada paso
    requeria Sheets API calls que podian fallar). Martin pidio: "SI CUANDO
    QUIEREN CARGAR EL STOCK LE DAMOS A LA GENTE UN MENSAJE PREDETERMINADO
    PARA QUE COPIEN, COMPLETEN CON INFO Y ENVIEN?" Se implemento exactamente
    asi: bot envia template con todos los productos de la zona, empleado copia,
    completa numeros, envia. Bot parsea con `_parsear_template()`. Reduce de
    8 pasos por producto a 3 pasos TOTAL (local → zona → template response).
    NUNCA volver a hacer menus step-by-step para carga de stock.
19. **_parsear_template() es robusto.** Parsea formato "Producto: N" por linea.
    Ignora lineas con ": 0", ": _", headers con emojis, lineas vacias.
    Stripea contexto de fermentacion "(hay N)" antes de parsear. Fuzzy matching
    contra catalogo para tolerar typos. Si no matchea ningun producto, avisa
    al usuario y pide que reintente.
20. **Cowork mount ≠ git repo path.** El folder montado como `bot-envios` en
    Cowork (`/mnt/bot-envios/`) NO es el mismo que el git repo que GitHub
    Desktop trackea (`/mnt/cronklam-lharmonie-envios/`). Cambios hechos con
    Write/Edit en `bot-envios` NO aparecen en GitHub Desktop. Hay que copiar
    el archivo al repo correcto antes de commitear. Verificar SIEMPRE con
    `ls` que los cambios esten en el mount que tiene `.git/`.
21. **Nuevo tipo de movimiento: TIPO_CARGA_STOCK.** Antes solo habia
    ENVIO_RECIBIDO, FERMENTACION, HORNEADO, VENTA, TRANSFER, MERMA. Se agrego
    "carga_stock" para distinguir cargas manuales de stock (template) de otros
    movimientos. `stock_apply_movement()` lo maneja: si estado es "congelado"
    → actualiza columna Congelado, si "horneado" → columna Horneado. La zona
    se registra en el movimiento tambien.
22. **MarkdownV2 escaping bug.** El bot usaba `parse_mode="MarkdownV2"` en
    algunos mensajes pero el texto tenia caracteres sin escapear (puntos,
    guiones). Esto causaba errores silenciosos de Telegram ("Bad Request:
    can't parse entities"). Fix: se paso a `parse_mode="Markdown"` (v1) o
    sin parse_mode donde no hace falta formatting.
23. **Google Forms son REFERENCIA ABSOLUTA para productos (17 abril 2026).**
    Martin pidio: "tenemos que usar como absoluta referencia toda la info que
    pregunta en el google form, que es lo que estan usando actualmente".
    Hay 3 forms: COCINA (stock cocina por local), MOSTRADOR (stock mostrador
    por local), y BARRA (café y barra — Sheet #5). Los nombres de producto
    en `_crear_productos_iniciales()` DEBEN coincidir EXACTO con los forms.
    Si se cambia un producto en el form, hay que cambiarlo en el codigo y
    viceversa. NUNCA inventar nombres de producto — copiarlos del form.
24. **CATALOG_VERSION fuerza re-sync de productos.** El Sheet "Productos Envio"
    se crea una sola vez. Si se cambia el catalogo en el codigo, la version
    vieja persiste en Sheets y el bot sigue usando los productos viejos.
    Fix: `CATALOG_VERSION` en el codigo (ej: "2026-04-17-v2"). Al arrancar,
    `cargar_productos()` compara contra la version guardada en celda F1 del
    Sheet. Si difiere, borra la pestana y la recrea con los productos nuevos.
    **Para actualizar productos:** cambiar `_crear_productos_iniciales()` Y
    bumpar `CATALOG_VERSION`. En el proximo arranque se re-sincroniza solo.
25. **Cantidades decimales para kg.** `_parsear_template()` ahora soporta
    float para items en kg (ej: "Pasta de pistacho: 0.5"). Enteros se
    mantienen como int, decimales como float redondeado a 3 decimales.
    Todo el pipeline (stock_apply_movement, stock_update_product,
    stock_log_movement) maneja floats correctamente.

---

## ACTUALIZAR EN

- **Project instructions (parte 9):** Proceso 5.1 (Remitos) puede pasar
  de "Basico" a "Funcional con stock". Proceso 5.2 (Stock por local) pasa
  de "No existe" a "MVP funcional".
- **lharmonie-bot CLAUDE.md:** Anotar que el bot de envios ahora maneja
  stock tambien, para que no se duplique funcionalidad.
