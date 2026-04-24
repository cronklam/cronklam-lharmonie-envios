# CLAUDE.md — Lharmonie Bot Envios + Stock

> **OBLIGATORIO:** Leer este archivo COMPLETO antes de tocar cualquier
> archivo del repo. Sin excepciones.
> Historial detallado en `CLAUDE_ARCHIVE.md`.

---

## Que es este proyecto

Bot de Telegram para CARGA DE DATOS de logistica y stock de Lharmonie.
Los empleados registran envios, recepciones, stock por zona y
fermentacion. El bot NO muestra reportes ni stock — es solo INPUT.

**Repo:** `cronklam/cronklam-lharmonie-envios` (privado)
**Stack:** Python 3 + python-telegram-bot 21.6 + gspread + google-auth + requests
**Deploy:** Railway `satisfied-wholeness`, auto-deploy desde `main`
**Archivo principal:** `bot_envios.py` (~2074 lineas)
**Dueno:** Martin Masri. **Nombre:** siempre "Lharmonie" (sin apostrofe).

---

## Locales

| Local | Direccion | Estado | Rol |
|-------|-----------|--------|-----|
| LH1 | Segui | CERRADO | Futuro reapertura |
| LH2 | Nicaragua 6068 | Activo | LOCAL + CDP (Centro de Produccion) |
| LH3 | Maure 1516 | Activo | Retail |
| LH4 | Zabala 1925 | Activo | Retail |
| LH5 | Libertador 3118 | Activo | Retail |
| LH6 | Nunez (TBD) | Proxima apertura | 6to local |

**CDP = Nicaragua (LH2)**, NO Segui. Opera como unidad separada.

---

## Stock: modelo de estados

- **Productos terminados:** 2 estados: CONGELADO y HORNEADO. NUNCA agregar mas.
- **Materia prima (solo CDP):** 1 estado: STOCK (zona Deposito, exclusiva CDP).
- **Movimientos:** ENVIO_RECIBIDO, FERMENTACION, HORNEADO, VENTA, TRANSFER,
  MERMA, CARGA_STOCK.
- **Zonas:** Cocina (congelado), Mostrador (horneado), Barra (horneado),
  Deposito (stock, solo CDP). `_zones_for_local()` filtra por local.
- **Auditoria AUTOMATICA** (no manual): stock apertura + envios + horneado
  - ventas(Bistrosoft) - transfers - merma = stock cierre teorico.
- **Stock Minimo:** Bistrosoft Sheet tab "Stock Minimo"
  (`1s6kPguwD25k3xpmbUoHq1KNFd_SEva3z7pvTGhA4bsE`).

---

## Flujos principales

**Envio:** /enviar -> nombre -> destino -> texto libre ("medialunas 50,
budines 20") -> transporte -> resumen editable -> confirma -> Sheet + notif.

**Recepcion:** /recibir -> envios pendientes -> seleccionar -> confirmar
con receptor -> diferencia reportada -> stock actualizado.

**Carga stock (template):** Cargar stock -> local -> zona -> bot envia
template con productos de esa zona -> empleado completa cantidades ->
bot parsea con `_parsear_template()` -> "Anotado".

**Fermentacion (template):** Fermentacion -> local -> template con stock
congelado actual -> empleado completa -> decrementa congelado -> "Anotado".

**Ordenes del dia:** local -> pedido a CDP (items bajo minimo) +
fermentacion (stock congelado + dia de semana). Tono IMPERATIVO.

**Menu:** 5 botones (Enviar, Recibir, Cargar stock, Fermentacion, Ordenes).

---

## Google Sheets

Un solo Sheet para todo (env var `ENVIOS_SHEETS_ID`).
Service account: `bot-sheets@lharmonie-bot.iam.gserviceaccount.com`
(NO confundir con `pnl-drive-sync@` del pipeline P&L).

| Pestana | Descripcion |
|---------|-------------|
| `Productos Envio` | Catalogo: Categoria, Producto, Unidad, Zona (~148 items) |
| `Envios` | Registro envios con estado (Pendiente/Recibido) |
| `Stock_{LOCAL}` | Stock actual: Producto, Congelado, Horneado, Zona |
| `Movimientos` | Log append-only de todos los movimientos |

Pestanas creadas automaticamente si no existen (`_ensure_stock_tabs()`).

---

## Variables de entorno (Railway)

| Variable | Descripcion |
|----------|-------------|
| `ENVIOS_TELEGRAM_TOKEN` | Token del bot |
| `ENVIOS_SHEETS_ID` | ID del Google Sheet |
| `GOOGLE_CREDENTIALS` | JSON de service account |

Notificaciones: Martin (6457094702), Iara Z (5358183977), Iara R (7354049230).

---

## Config clave

```python
LOCALES_STOCK = ["CDP - Nicaragua (Produccion)", "LH2 - Nicaragua 6068",
    "LH3 - Maure 1516", "LH4 - Zabala 1925", "LH5 - Libertador 3118"]
LOCAL_KEYS = ["CDP", "LH2", "LH3", "LH4", "LH5"]
ZONAS = ["Cocina", "Mostrador", "Barra", "Deposito"]
ZONA_DEFAULT_STATE = {"Cocina": "congelado", "Mostrador": "horneado",
    "Barra": "horneado", "Deposito": "stock"}
```

---

## Reglas inquebrantables

1. **Catalogo desde Sheets**, no desde codigo. Tab "Productos Envio".
2. **Bot NO modifica precios/costos.** Solo registra cantidades.
3. **Fuzzy matching** con SequenceMatcher para productos manuales.
4. **Timezone Argentina** (UTC-3) en todas las fechas.
5. **2 estados prod. terminados** (CONGELADO/HORNEADO). Materia prima: STOCK.
6. **Auditoria automatica**, nunca manual.
7. **Mismo Sheet para todo.** NO crear sheets separados.
8. **CDP = Nicaragua (LH2).** LH1 cerrado.
9. **Texto libre > menus.** NUNCA flujos multi-step para cargar productos.
10. **Templates > menus** para carga de stock. NUNCA step-by-step.
11. **Bot = INPUT, dashboard = OUTPUT.** No mostrar stock ni reportes.
12. **"Anotado" sin resumen.** No mostrar al empleado lo que cargo.
13. **Directivas, no sugerencias.** Ordenes = hechos, no opcionales.
14. **Espanol argentino informal.** Tuteo, "dale", "listo".
15. **Google Forms = referencia absoluta** para nombres de productos.

---

## Producto update flow

1. Verificar los 3 Google Forms (Cocina/Mostrador/Barra)
2. Actualizar `_HARDCODED_PRODUCTS` en `bot_envios.py`
3. Bumpar `CATALOG_VERSION`
4. Push -> Railway auto-deploy -> bot re-sync al arrancar
5. **Sincronizar con** `products.ts` en lharmonie-staff

---

## Pendientes

- [ ] Token de Telegram hardcodeado — mover a env var only
- [ ] Ordenes del dia: falta integrar clima y fechas especiales
- [ ] Auditoria automatica Bistrosoft (ventas vs stock) no implementada
- [ ] Sin tests unitarios

---

## Lecciones clave

- **Cowork mount != git repo.** `bot-envios/` != `cronklam-lharmonie-envios/`.
  Copiar archivos al repo correcto antes de commitear.
- **Tab names con acentos** causan bugs. Buscar AMBAS variantes, crear SIN acento.
- **cargar_productos()** tiene 3 capas: cache 10min, manejo tabs duplicados,
  fallback hardcoded. Bot NUNCA muestra "0 productos".
- **_parsear_template()** es robusto: ignora ": 0", ": _", emojis, lineas
  vacias. Soporta decimales para kg. Fuzzy matching contra catalogo.
- **MarkdownV2** causaba errores silenciosos. Usar Markdown v1 o sin parse_mode.
- **Productos duran max 2 dias.** Critico para transfers entre locales.
- **Lharmonie NO abre sabados** (Shabbat).
- **2 bots en Railway.** Comparten env vars — cuidado al editar.
- **Materia prima CDP:** zona Deposito, ~63 productos, estado "stock".
  Sufijo "MP" donde colision de nombres con prod. terminados.

---

## Relacion con otros repos

- **Api-bistrosoft:** Ventas + Stock Minimo (Sheet `1s6kPg...`)
- **lharmonie-pnl-upload:** Pipeline P&L (costo logistico)
- **lharmonie-bot:** Bot facturas, mismo proyecto Railway
- **lharmonie-staff:** App web, mismos productos en `products.ts`
