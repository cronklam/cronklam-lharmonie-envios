#!/usr/bin/env python3
"""
Bot de Telegram — Envios + Stock Lharmonie
===========================================
Registra envios de mercaderia entre locales y gestiona stock
(congelado/horneado) por local. Template-based para carga rapida.
Catalogo de productos editable desde Google Sheets.

Bot = INPUT only. No muestra stock ni reportes a empleados.
"""
import os
import io
import re
import json
import logging
import asyncio
import time as _time
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher

# Timezone Argentina (UTC-3)
TZ_AR = timezone(timedelta(hours=-3))

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)

# ── CONFIG ────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ.get("ENVIOS_TELEGRAM_TOKEN", "8631530577:AAGM0J5qq2VqcZ7FaSeXP_UAtinPcAYW9jc")
SHEETS_ID      = os.environ.get("ENVIOS_SHEETS_ID", "")
GOOGLE_CREDS   = os.environ.get("GOOGLE_CREDENTIALS", "")

# ── LOCALES ──────────────────────────────────────────────────────────────────
LOCALES_STOCK = [
    "CDP - Nicaragua (Produccion)",
    "LH2 - Nicaragua 6068",
    "LH3 - Maure 1516",
    "LH4 - Zabala 1925",
    "LH5 - Libertador 3118",
]
LOCALES_ENVIO = LOCALES_STOCK
LOCALES = LOCALES_ENVIO

# Retail locals only (no CDP) — used for stock tracking
LOCALES_RETAIL = [
    "LH2 - Nicaragua 6068",
    "LH3 - Maure 1516",
    "LH4 - Zabala 1925",
    "LH5 - Libertador 3118",
]

# Short keys for stock columns
LOCAL_KEYS = ["LH2", "LH3", "LH4", "LH5"]

ZONAS = ["Cocina", "Mostrador", "Barra"]
ZONAS_DISPLAY = ["🍳 Cocina", "🧁 Mostrador", "☕ Barra"]

# Default stock state per zone
ZONA_DEFAULT_STATE = {
    "Cocina": "congelado",
    "Mostrador": "horneado",
    "Barra": "horneado",
}

TRANSPORTES = ["🚗 Ezequiel (Mister)", "🚕 Uber"]

# IDs para notificaciones (Martin + Iaras)
NOTIFY_IDS = [
    6457094702,   # Martin
    5358183977,   # Iara Zayat
    7354049230,   # Iara Rodriguez
]

logging.basicConfig(format="%(asctime)s — %(levelname)s — %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

# ── ESTADO DE USUARIOS ────────────────────────────────────────────────────────
estado_usuario = {}  # chat_id -> {paso, datos del envio/stock en curso...}

# ── GOOGLE SHEETS ─────────────────────────────────────────────────────────────
_sheets_cache = {"gc": None, "sh": None, "ts": 0}
SHEETS_CACHE_TTL = 300


def get_sheets_client():
    import gspread
    from google.oauth2.service_account import Credentials
    now = datetime.now(TZ_AR).timestamp()
    if _sheets_cache["gc"] and (now - _sheets_cache["ts"]) < SHEETS_CACHE_TTL:
        return _sheets_cache["gc"], _sheets_cache["sh"]
    creds_json = GOOGLE_CREDS
    if not creds_json:
        log.error("GOOGLE_CREDENTIALS no configurado")
        return None, None
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(json.loads(creds_json), scopes=scopes)
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(SHEETS_ID)
        _sheets_cache.update({"gc": gc, "sh": sh, "ts": now})
        return gc, sh
    except Exception as e:
        log.error(f"Error conectando a Sheets: {e}")
        return None, None


def get_stock_sheet():
    """Returns the same gspread Spreadsheet as envios — todo en un solo Sheet."""
    gc, sh = get_sheets_client()
    return sh


# ── PRODUCTOS ─────────────────────────────────────────────────────────────────
CATALOG_VERSION = "2026-04-17-v3"  # Bump this to force re-sync of product catalog

# In-memory product cache to avoid hitting Sheets API every interaction
_product_cache = {"productos": {}, "unidades": {}, "zonas": {}, "ts": 0}
_PRODUCT_CACHE_TTL = 600  # 10 minutes

# Hardcoded product list — FALLBACK when Sheets is unreachable.
# Source: Google Forms (Cocina + Mostrador + Barra). 17 abril 2026.
_HARDCODED_PRODUCTS = [
    # ── MOSTRADOR (del form "LH {LOCAL} - MOSTRADOR") ──
    ("Pastelería", "Alfajor de nuez", "u", "Mostrador"),
    ("Pastelería", "Alfajor de chocolate", "u", "Mostrador"),
    ("Pastelería", "Alfajor de pistacho", "u", "Mostrador"),
    ("Pastelería", "Cookie nuez", "u", "Mostrador"),
    ("Pastelería", "Cookie melu", "u", "Mostrador"),
    ("Pastelería", "Cookie red velvet", "u", "Mostrador"),
    ("Pastelería", "Cookie chocolate simple", "u", "Mostrador"),
    ("Pastelería", "Cookie de mani", "u", "Mostrador"),
    ("Pastelería", "Brownie", "u", "Mostrador"),
    ("Pastelería", "Cuadrado de coco", "u", "Mostrador"),
    ("Pastelería", "Muffin", "u", "Mostrador"),
    ("Pastelería", "Barritas proteína", "u", "Mostrador"),
    ("Pastelería", "Porción de dátiles", "u", "Mostrador"),
    ("Pastelería", "Brioche de pastelera", "u", "Mostrador"),
    ("Pastelería", "Tarteleta", "u", "Mostrador"),
    # ── COCINA (del form "LH {LOCAL} - STOCK COCINA") ──
    ("Elaborados", "Tarta del día", "u", "Cocina"),
    ("Elaborados", "Pan masa madre con semillas", "u", "Cocina"),
    ("Elaborados", "Pan brioche", "u", "Cocina"),
    ("Elaborados", "Pan brioche cuadrado", "u", "Cocina"),
    ("Elaborados", "Pain au choco", "u", "Cocina"),
    ("Elaborados", "Bavka pistacho", "u", "Cocina"),
    ("Elaborados", "Bavka de chocolate", "u", "Cocina"),
    ("Elaborados", "Pan suisse", "u", "Cocina"),
    ("Elaborados", "Roll de maní", "u", "Cocina"),
    ("Elaborados", "Roll canela", "u", "Cocina"),
    ("Elaborados", "Medialunas", "u", "Cocina"),
    ("Elaborados", "Croissant", "u", "Cocina"),
    ("Elaborados", "Chipa", "u", "Cocina"),
    ("Elaborados", "Chipa prensado", "u", "Cocina"),
    ("Elaborados", "Palmeras", "u", "Cocina"),
    ("Elaborados", "Palitos de queso", "u", "Cocina"),
    ("Varios", "Pasta de pistacho", "kg", "Cocina"),
    ("Varios", "Pistacho procesado", "kg", "Cocina"),
    ("Varios", "Frangipane", "kg", "Cocina"),
    ("Varios", "Dulce de leche", "kg", "Cocina"),
    ("Varios", "Mermelada", "kg", "Cocina"),
    ("Varios", "Mermelada de frambuesa", "kg", "Cocina"),
    ("Varios", "Bariloche", "kg", "Cocina"),
    ("Varios", "Maní salado", "kg", "Cocina"),
    ("Varios", "Frosting de queso", "kg", "Cocina"),
    ("Varios", "Queso crema", "kg", "Cocina"),
    ("Varios", "Azucar", "kg", "Cocina"),
    ("Varios", "Azucar impalpable", "kg", "Cocina"),
    ("Varios", "Granola", "kg", "Cocina, Barra"),
    ("Varios", "Pasta de atún", "kg", "Cocina"),
    ("Varios", "Pesto", "kg", "Cocina"),
    ("Varios", "Salsa holandesa", "kg", "Cocina"),
    ("Varios", "Manteca común", "kg", "Cocina"),
    ("Varios", "Manteca saborizada", "kg", "Cocina"),
    ("Varios", "Aderezo cesar", "kg", "Cocina"),
    ("Varios", "Hongos cocidos", "kg", "Cocina"),
    ("Varios", "Wraps", "u", "Cocina"),
    ("Varios", "Papas gauchitas", "paq", "Cocina"),
    ("Varios", "Almendras", "kg", "Cocina"),
    ("Varios", "Almendras fileteadas", "kg", "Cocina"),
    ("Varios", "Picle de pepino redondo", "kg", "Cocina"),
    ("Varios", "Quinoa crocante", "kg", "Cocina"),
    ("Varios", "Quinoa cocida", "kg", "Cocina"),
    ("Varios", "Arroz yamani cocido", "kg", "Cocina"),
    ("Varios", "Arroz yamani crudo", "kg", "Cocina"),
    ("Varios", "Atún", "kg", "Cocina"),
    ("Varios", "Queso sardo", "kg", "Cocina"),
    ("Varios", "Queso tybo", "kg", "Cocina"),
    ("Varios", "Porción de trucha", "kg", "Cocina"),
    ("Varios", "Miel", "kg", "Cocina, Barra"),
    ("Varios", "Aceite de oliva Zuelo", "lt", "Cocina"),
    ("Varios", "Vinagre blanco", "lt", "Cocina"),
    ("Varios", "Siracha", "kg", "Cocina"),
    ("Varios", "Sal", "kg", "Cocina"),
    # ── BARRA (del form "Stock Café y barra") ──
    ("Barra", "Café de tolva", "kg", "Barra"),
    ("Barra", "Paquete 1/4 Café Jairo", "u", "Barra"),
    ("Barra", "Paquete 1/4 Café Luis", "u", "Barra"),
    ("Barra", "Paquete 1/4 Café Samba Brasil", "u", "Barra"),
    ("Barra", "Paquete 1/4 Café Trailblazer Brasil", "u", "Barra"),
    ("Barra", "Paquete 1/4 Café Cumbia", "u", "Barra"),
    ("Barra", "Receta leche casera", "u", "Barra"),
    ("Barra", "Matcha", "u", "Barra"),
    ("Barra", "Hibiscus", "u", "Barra"),
    ("Barra", "Curcuma", "u", "Barra"),
    ("Barra", "Frutilla congelada", "u", "Barra"),
    ("Barra", "Arandanos congelados", "u", "Barra"),
    ("Barra", "Té Grey", "u", "Barra"),
    ("Barra", "Té Royal frut", "u", "Barra"),
    ("Barra", "Té breakfast", "u", "Barra"),
    ("Barra", "Té Berrys", "u", "Barra"),
]


def _parse_product_list(product_tuples: list) -> tuple:
    """Parse a list of (cat, prod, unidad, zona) tuples into dicts."""
    productos = {}
    unidades = {}
    zonas = {}
    for cat, prod, unidad, zona_raw in product_tuples:
        if cat not in productos:
            productos[cat] = []
        productos[cat].append(prod)
        unidades[prod] = unidad or "u"
        if zona_raw:
            zonas[prod] = [z.strip() for z in zona_raw.split(",") if z.strip()]
        else:
            zonas[prod] = ["Cocina", "Mostrador", "Barra"]
    return productos, unidades, zonas


def cargar_productos() -> tuple:
    """
    Lee la pestana 'Productos Envio' del Sheet.
    Retorna (dict categorias, dict unidades, dict zonas).
    Uses in-memory cache (10min). Falls back to hardcoded products
    if Sheets is unreachable.
    """
    # Check cache first
    now = _time.time()
    if _product_cache["productos"] and (now - _product_cache["ts"]) < _PRODUCT_CACHE_TTL:
        return _product_cache["productos"], _product_cache["unidades"], _product_cache["zonas"]

    try:
        gc, sh = get_sheets_client()
        if not sh:
            raise RuntimeError("No sheets client")

        # Find ALL matching worksheets (handle duplicates from failed deletes)
        ws_accented = None
        ws_plain = None
        for w in sh.worksheets():
            title = w.title
            if title == "Productos Envío":
                ws_accented = w
            elif title == "Productos Envio":
                ws_plain = w

        # Prefer the plain (non-accented) tab — it's the one our code creates
        ws = ws_plain or ws_accented
        need_create = False

        if ws:
            try:
                version_cell = ws.acell("F1").value or ""
            except Exception:
                version_cell = ""
            if version_cell != CATALOG_VERSION:
                log.info(f"Catalogo desactualizado ({version_cell!r} vs {CATALOG_VERSION}). Recreando...")
                # Delete ALL product tabs (both accented and plain)
                for old_ws in [ws_accented, ws_plain]:
                    if old_ws:
                        try:
                            sh.del_worksheet(old_ws)
                            log.info(f"Borrada pestana '{old_ws.title}'")
                            _time.sleep(1)
                        except Exception as del_err:
                            log.warning(f"No se pudo borrar '{old_ws.title}': {del_err}")
                need_create = True
        else:
            need_create = True

        if need_create:
            # Double-check no tab exists before creating (avoid duplicates)
            existing_titles = [w.title for w in sh.worksheets()]
            for old_name in ["Productos Envío", "Productos Envio"]:
                if old_name in existing_titles:
                    try:
                        old_w = sh.worksheet(old_name)
                        sh.del_worksheet(old_w)
                        log.info(f"Limpieza: borrada '{old_name}' residual")
                        _time.sleep(1)
                    except Exception:
                        pass
            ws = sh.add_worksheet("Productos Envio", rows=200, cols=6)
            ws.append_row(["Categoria", "Producto", "Unidad", "Zona", "", CATALOG_VERSION])
            _crear_productos_iniciales(ws)
            _time.sleep(2)

        vals = ws.get_all_values()
        header_idx = 0
        for i, row in enumerate(vals):
            if "Categoría" in row or "Categoria" in row:
                header_idx = i
                break
        productos = {}
        unidades = {}
        zonas = {}
        for row in vals[header_idx + 1:]:
            if not any(row):
                continue
            cat = row[0].strip() if len(row) > 0 else ""
            prod = row[1].strip() if len(row) > 1 else ""
            unidad = row[2].strip() if len(row) > 2 else "u"
            zona_raw = row[3].strip() if len(row) > 3 else ""
            if cat and prod:
                if cat not in productos:
                    productos[cat] = []
                productos[cat].append(prod)
                unidades[prod] = unidad or "u"
                if zona_raw:
                    zonas[prod] = [z.strip() for z in zona_raw.split(",") if z.strip()]
                else:
                    zonas[prod] = ["Cocina", "Mostrador", "Barra"]
        total = sum(len(v) for v in productos.values())
        zonas_with_cocina = sum(1 for z_list in zonas.values() if "Cocina" in z_list)
        zonas_empty = sum(1 for z_list in zonas.values() if not z_list)
        log.info(f"Productos cargados desde Sheet: {total} en {len(productos)} categorias. "
                 f"Zonas: {len(zonas)} total, {zonas_with_cocina} con Cocina, {zonas_empty} vacias")

        # Validate: if Sheet returned 0 products, something is wrong — use fallback
        if total == 0:
            log.warning("Sheet devolvio 0 productos — usando fallback hardcoded")
            productos, unidades, zonas = _parse_product_list(_HARDCODED_PRODUCTS)

        # Update cache
        _product_cache.update({"productos": productos, "unidades": unidades, "zonas": zonas, "ts": _time.time()})
        return productos, unidades, zonas

    except Exception as e:
        log.error(f"Error cargando productos desde Sheet: {e}")
        # Fallback: use hardcoded products so the bot keeps working
        log.info("Usando catalogo hardcoded como fallback")
        productos, unidades, zonas = _parse_product_list(_HARDCODED_PRODUCTS)
        _product_cache.update({"productos": productos, "unidades": unidades, "zonas": zonas, "ts": _time.time()})
        return productos, unidades, zonas


def _crear_productos_iniciales(ws):
    """Crea el catalogo inicial de productos.
    FUENTE: Google Forms de stock (Cocina + Mostrador + Barra).
    Los nombres DEBEN coincidir con los forms. Si se cambian,
    actualizar tambien los forms y viceversa.
    Ultima sync: 17 abril 2026.
    """
    rows = [[cat, prod, unidad, zona] for cat, prod, unidad, zona in _HARDCODED_PRODUCTS]
    ws.append_rows(rows)
    log.info(f"Catalogo inicial creado: {len(rows)} productos")


def _get_products_for_zone(zona: str) -> list:
    """Returns sorted list of product names that belong to a given zone.
    Has its own hardcoded fallback — NEVER returns empty."""
    productos, unidades, zonas = cargar_productos()
    zona_lower = zona.lower()
    result = []
    for cat, prods in productos.items():
        for prod in prods:
            prod_zones = zonas.get(prod, [])
            # Case-insensitive zone matching
            if any(z.lower() == zona_lower for z in prod_zones):
                result.append(prod)
    if result:
        log.info(f"_get_products_for_zone({zona!r}): {len(result)} productos encontrados")
        return sorted(result)

    # If cargar_productos() returned data but no zone matches, try hardcoded directly
    log.warning(f"_get_products_for_zone({zona!r}): 0 productos de cargar_productos() "
                f"({sum(len(v) for v in productos.values())} prods total, "
                f"{len(zonas)} con zona). Usando hardcoded directo.")
    hc_prods, _, hc_zonas = _parse_product_list(_HARDCODED_PRODUCTS)
    for cat, prods in hc_prods.items():
        for prod in prods:
            prod_zones = hc_zonas.get(prod, [])
            if any(z.lower() == zona_lower for z in prod_zones):
                result.append(prod)
    if result:
        log.info(f"_get_products_for_zone({zona!r}): {len(result)} productos via hardcoded fallback")
    else:
        log.error(f"_get_products_for_zone({zona!r}): 0 incluso con hardcoded! Imposible.")
    return sorted(result)


# ── ENVIOS SHEET ──────────────────────────────────────────────────────────────
EXPECTED_HEADERS = [
    "Fecha", "Hora", "Origen", "Destino", "Responsable envío",
    "Transporte", "Productos", "Cantidades", "Unidades",
    "Bultos", "Estado", "Responsable recepción", "Fecha recepción",
    "Recibido OK", "Diferencias", "Tiempo envio", "Observaciones"
]


def _get_or_create_envios_ws(sh):
    """
    Obtiene o crea la pestana 'Envios'. Retorna (worksheet, created_bool).
    """
    try:
        ws = sh.worksheet("Envíos")
        return ws, False
    except Exception as e:
        err_str = str(e).lower()
        if "not found" in err_str or "no worksheet" in err_str:
            ws = sh.add_worksheet("Envíos", rows=2000, cols=len(EXPECTED_HEADERS))
            ws.append_row(EXPECTED_HEADERS)
            log.info("Pestana 'Envios' creada")
            return ws, True
        else:
            raise


def guardar_envio(datos: dict) -> tuple:
    """
    Guarda un envio en la pestana 'Envios' del Sheet.
    Retorna (True, None) si OK, o (False, "mensaje de error") si fallo.
    """
    try:
        gc, sh = get_sheets_client()
        if not sh:
            return (False, "No se pudo conectar a Google Sheets.")

        ws, created = _get_or_create_envios_ws(sh)
        headers = ws.row_values(1)

        SEP = " | "
        valores = {
            "Fecha": datos.get("fecha", ""),
            "Hora": datos.get("hora", ""),
            "Origen": datos.get("origen", ""),
            "Destino": datos.get("destino", ""),
            "Responsable envío": datos.get("responsable", ""),
            "Transporte": datos.get("transporte", ""),
            "Productos": SEP.join(datos.get("productos_lista", [])),
            "Cantidades": SEP.join(datos.get("cantidades_lista", [])),
            "Unidades": SEP.join(datos.get("unidades_lista", [])),
            "Bultos": datos.get("bultos_total", ""),
            "Estado": "Enviado",
            "Observaciones": datos.get("observaciones", ""),
        }
        row = []
        for h in headers:
            row.append(valores.get(h, ""))

        ws.append_row(row, value_input_option="RAW")
        log.info(f"Envio guardado: {datos.get('origen')} -> {datos.get('destino')}")
        return (True, None)
    except Exception as e:
        log.error(f"Error guardando envio: {e}")
        return (False, f"Error al guardar: {e}")


def _split_multi(value: str) -> list:
    """Splitea un campo que puede usar ' | ' o '\\n' como separador."""
    if " | " in value:
        return [v.strip() for v in value.split(" | ") if v.strip()]
    elif "\n" in value:
        return [v.strip() for v in value.split("\n") if v.strip()]
    else:
        return [value.strip()] if value.strip() else []


def obtener_envios_pendientes(local_destino: str) -> tuple:
    """
    Trae envios pendientes de recepcion para un local.
    Retorna (lista_pendientes, error_msg_o_None).
    """
    try:
        gc, sh = get_sheets_client()
        if not sh:
            return ([], "No se pudo conectar a Google Sheets.")

        try:
            ws = sh.worksheet("Envíos")
        except Exception:
            return ([], None)

        all_values = ws.get_all_values()
        if len(all_values) <= 1:
            return ([], None)

        h_idx = 0
        for i, row in enumerate(all_values):
            if "Fecha" in row and "Origen" in row:
                h_idx = i
                break
        headers = all_values[h_idx]

        def gcol(row, cn):
            try:
                idx = headers.index(cn)
                return row[idx].strip() if idx < len(row) else ""
            except:
                return ""

        pendientes = []
        for i, row in enumerate(all_values[h_idx + 1:], start=h_idx + 2):
            if not any(row):
                continue
            estado = gcol(row, "Estado")
            destino = gcol(row, "Destino")

            es_enviado = "enviado" in estado.lower() and "recibido" not in estado.lower() and "diferencia" not in estado.lower() and "congelado" not in estado.lower()

            destino_match = False
            if destino and local_destino:
                if local_destino.lower() in destino.lower() or destino.lower() in local_destino.lower():
                    destino_match = True
                elif local_corto(local_destino).lower() in destino.lower():
                    destino_match = True

            if es_enviado and destino_match:
                pendientes.append({
                    "fila": i,
                    "fecha": gcol(row, "Fecha"),
                    "hora": gcol(row, "Hora"),
                    "origen": gcol(row, "Origen"),
                    "destino": destino,
                    "responsable": gcol(row, "Responsable envío"),
                    "transporte": gcol(row, "Transporte"),
                    "productos": gcol(row, "Productos"),
                    "cantidades": gcol(row, "Cantidades"),
                    "bultos": gcol(row, "Bultos"),
                })

        return (pendientes, None)
    except Exception as e:
        log.error(f"Error obteniendo envios pendientes: {e}")
        return ([], f"Error al buscar envios: {e}")


def _calcular_tiempo_envio(fecha_envio: str, hora_envio: str) -> str:
    """Calcula el tiempo transcurrido desde el envio hasta ahora."""
    try:
        ahora = datetime.now(TZ_AR)
        dt_envio = datetime.strptime(f"{fecha_envio} {hora_envio}", "%d/%m/%Y %H:%M")
        dt_envio = dt_envio.replace(tzinfo=TZ_AR)
        diff = ahora - dt_envio
        total_min = int(diff.total_seconds() / 60)
        if total_min < 0:
            return "—"
        if total_min < 60:
            return f"{total_min} min"
        horas = total_min // 60
        minutos = total_min % 60
        if horas < 24:
            return f"{horas}h {minutos}min"
        dias = horas // 24
        horas_rest = horas % 24
        return f"{dias}d {horas_rest}h"
    except Exception:
        return "—"


def marcar_recibido(fila: int, responsable: str, recibido_ok: bool, diferencias: str = ""):
    """Marca un envio como recibido en el Sheet y calcula tiempo de envio."""
    try:
        gc, sh = get_sheets_client()
        if not sh:
            return
        ws = sh.worksheet("Envíos")
        headers = ws.row_values(1)

        def col_idx(name):
            try:
                return headers.index(name) + 1
            except:
                return None

        ahora = datetime.now(TZ_AR)
        estado = "Recibido" if recibido_ok else "Con diferencias"

        row_data = ws.row_values(fila)
        fecha_envio = ""
        hora_envio = ""
        try:
            fecha_envio = row_data[headers.index("Fecha")] if "Fecha" in headers else ""
            hora_envio = row_data[headers.index("Hora")] if "Hora" in headers else ""
        except (IndexError, ValueError):
            pass
        tiempo = _calcular_tiempo_envio(fecha_envio, hora_envio) if fecha_envio and hora_envio else "—"

        col_estado = col_idx("Estado")
        col_resp = col_idx("Responsable recepción")
        col_fecha = col_idx("Fecha recepción")
        col_ok = col_idx("Recibido OK")
        col_dif = col_idx("Diferencias")
        col_tiempo = col_idx("Tiempo envio")

        if col_estado:
            ws.update_cell(fila, col_estado, estado)
        if col_resp:
            ws.update_cell(fila, col_resp, responsable)
        if col_fecha:
            ws.update_cell(fila, col_fecha, ahora.strftime("%d/%m/%Y %H:%M"))
        if col_ok:
            ws.update_cell(fila, col_ok, "Sí" if recibido_ok else "No")
        if col_dif and diferencias:
            ws.update_cell(fila, col_dif, diferencias)
        if col_tiempo:
            ws.update_cell(fila, col_tiempo, tiempo)

        log.info(f"Envio fila {fila} marcado como {estado} — Tiempo: {tiempo}")
    except Exception as e:
        log.error(f"Error marcando recibido: {e}")


# ── STOCK SHEET FUNCTIONS ─────────────────────────────────────────────────────

STOCK_ACTUAL_HEADERS = [
    "Producto", "Categoria",
    "LH2 Congelado", "LH2 Horneado",
    "LH3 Congelado", "LH3 Horneado",
    "LH4 Congelado", "LH4 Horneado",
    "LH5 Congelado", "LH5 Horneado",
    "Ultima Actualizacion"
]

MOVIMIENTOS_HEADERS = [
    "Timestamp", "Local", "Zona", "Producto", "Tipo",
    "Cantidad", "Estado Origen", "Estado Destino",
    "Responsable", "Chat ID", "Observaciones"
]

PRODUCTOS_STOCK_HEADERS = [
    "Categoria", "Producto", "Unidad",
    "Stock Minimo LH2", "Stock Minimo LH3",
    "Stock Minimo LH4", "Stock Minimo LH5"
]

AUDITORIA_HEADERS = [
    "Fecha", "Local", "Producto",
    "Stock Apertura", "Envios Recibidos", "Horneado",
    "Ventas Bistrosoft", "Transfers", "Merma",
    "Stock Cierre Teorico", "Stock Cierre Real",
    "Diferencia", "%Diferencia"
]

# Movement types
TIPO_ENVIO_RECIBIDO = "envio_recibido"
TIPO_FERMENTO = "fermento"
TIPO_HORNEO = "horneo"
TIPO_MERMA = "merma"
TIPO_TRANSFER_OUT = "transfer_out"
TIPO_TRANSFER_IN = "transfer_in"
TIPO_AJUSTE = "ajuste"
TIPO_CARGA_STOCK = "carga_stock"


def _get_or_create_stock_ws(sh, tab_name, headers, rows=2000):
    """Get or create a worksheet in the stock sheet."""
    try:
        ws = sh.worksheet(tab_name)
        return ws
    except Exception as e:
        err_str = str(e).lower()
        if "not found" in err_str or "no worksheet" in err_str:
            ws = sh.add_worksheet(tab_name, rows=rows, cols=len(headers))
            ws.append_row(headers)
            _time.sleep(1)
            log.info(f"Pestana '{tab_name}' creada en Stock Sheet")
            return ws
        else:
            raise


def _ensure_stock_tabs(sh):
    """Ensure all 4 stock tabs exist."""
    _get_or_create_stock_ws(sh, "Productos", PRODUCTOS_STOCK_HEADERS, rows=300)
    _time.sleep(1)
    _get_or_create_stock_ws(sh, "Stock Actual", STOCK_ACTUAL_HEADERS, rows=300)
    _time.sleep(1)
    _get_or_create_stock_ws(sh, "Movimientos", MOVIMIENTOS_HEADERS, rows=5000)
    _time.sleep(1)
    _get_or_create_stock_ws(sh, "Auditoria", AUDITORIA_HEADERS, rows=2000)


def _safe_float(val, default=0.0):
    if not val:
        return default
    try:
        return float(str(val).replace(",", ".").strip())
    except (ValueError, TypeError):
        return default


def _safe_int(val, default=0):
    f = _safe_float(val, float(default))
    return int(round(f))


def stock_get_all_products(sh) -> list:
    """Returns list of dicts with product info from Productos tab."""
    try:
        ws = _get_or_create_stock_ws(sh, "Productos", PRODUCTOS_STOCK_HEADERS, rows=300)
        vals = ws.get_all_values()
        if len(vals) <= 1:
            return []
        headers = vals[0]
        products = []
        for row in vals[1:]:
            if not any(row):
                continue
            d = {}
            for j, h in enumerate(headers):
                d[h] = row[j].strip() if j < len(row) else ""
            if d.get("Producto"):
                products.append(d)
        return products
    except Exception as e:
        log.error(f"Error leyendo Productos stock: {e}")
        return []


def stock_get_minimums(sh) -> dict:
    """Returns {producto: {LH2: min, LH3: min, ...}} from Productos tab."""
    products = stock_get_all_products(sh)
    mins = {}
    for p in products:
        nombre = p.get("Producto", "")
        if not nombre:
            continue
        mins[nombre] = {}
        for lk in LOCAL_KEYS:
            mins[nombre][lk] = _safe_int(p.get(f"Stock Minimo {lk}", "0"))
    return mins


def stock_read_actual(sh) -> dict:
    """
    Reads Stock Actual tab.
    Returns {producto: {LH2_congelado: N, LH2_horneado: N, ...}}
    """
    try:
        ws = _get_or_create_stock_ws(sh, "Stock Actual", STOCK_ACTUAL_HEADERS, rows=300)
        vals = ws.get_all_values()
        if len(vals) <= 1:
            return {}
        headers = vals[0]
        stock = {}
        for row in vals[1:]:
            if not any(row):
                continue
            prod = row[0].strip() if len(row) > 0 else ""
            if not prod:
                continue
            d = {}
            for lk in LOCAL_KEYS:
                col_c = f"{lk} Congelado"
                col_h = f"{lk} Horneado"
                idx_c = headers.index(col_c) if col_c in headers else -1
                idx_h = headers.index(col_h) if col_h in headers else -1
                d[f"{lk}_congelado"] = _safe_int(row[idx_c] if idx_c >= 0 and idx_c < len(row) else "0")
                d[f"{lk}_horneado"] = _safe_int(row[idx_h] if idx_h >= 0 and idx_h < len(row) else "0")
            stock[prod] = d
        return stock
    except Exception as e:
        log.error(f"Error leyendo Stock Actual: {e}")
        return {}


def stock_update_product(sh, producto: str, categoria: str, updates: dict):
    """
    Updates a single product row in Stock Actual.
    updates = {LH2_congelado: N, LH2_horneado: N, ...}
    Creates the row if it doesn't exist.
    """
    try:
        ws = _get_or_create_stock_ws(sh, "Stock Actual", STOCK_ACTUAL_HEADERS, rows=300)
        vals = ws.get_all_values()
        headers = vals[0] if vals else STOCK_ACTUAL_HEADERS
        ahora = datetime.now(TZ_AR).strftime("%d/%m/%Y %H:%M")

        target_row = None
        for i, row in enumerate(vals[1:], start=2):
            if len(row) > 0 and row[0].strip().lower() == producto.lower():
                target_row = i
                break

        row_data = [""] * len(headers)
        row_data[0] = producto
        if "Categoria" in headers:
            row_data[headers.index("Categoria")] = categoria

        if target_row:
            existing = vals[target_row - 1]
            for j in range(len(existing)):
                if j < len(row_data):
                    row_data[j] = existing[j]

        for key, val in updates.items():
            parts = key.split("_")
            if len(parts) == 2:
                header_name = f"{parts[0]} {parts[1].capitalize()}"
                if header_name in headers:
                    row_data[headers.index(header_name)] = str(val)

        if "Ultima Actualizacion" in headers:
            row_data[headers.index("Ultima Actualizacion")] = ahora

        if target_row:
            cell_range = f"A{target_row}:{chr(64 + len(headers))}{target_row}"
            ws.update(cell_range, [row_data])
        else:
            ws.append_row(row_data, value_input_option="RAW")

        log.info(f"Stock actualizado: {producto} — {updates}")
    except Exception as e:
        log.error(f"Error actualizando stock: {e}")
        raise


def stock_log_movement(sh, local: str, zona: str, producto: str, tipo: str,
                       cantidad: int, estado_origen: str, estado_destino: str,
                       responsable: str, chat_id: int, observaciones: str = ""):
    """Logs a movement to the Movimientos tab."""
    try:
        ws = _get_or_create_stock_ws(sh, "Movimientos", MOVIMIENTOS_HEADERS, rows=5000)
        ahora = datetime.now(TZ_AR).strftime("%d/%m/%Y %H:%M:%S")
        row = [
            ahora, local, zona, producto, tipo,
            str(cantidad), estado_origen, estado_destino,
            responsable, str(chat_id), observaciones
        ]
        ws.append_row(row, value_input_option="RAW")
        log.info(f"Movimiento registrado: {tipo} {cantidad}x {producto} en {local}")
    except Exception as e:
        log.error(f"Error registrando movimiento: {e}")
        raise


def _local_key_from_name(local_name: str) -> str:
    """Extract LH2/LH3/LH4/LH5 from a local name string."""
    local_upper = local_name.upper()
    for lk in LOCAL_KEYS:
        if lk in local_upper:
            return lk
    if "NICARAGUA" in local_upper and "CDP" not in local_upper:
        return "LH2"
    if "MAURE" in local_upper:
        return "LH3"
    if "ZABALA" in local_upper:
        return "LH4"
    if "LIBERTADOR" in local_upper:
        return "LH5"
    return ""


def _get_product_category(producto: str, sh_envios=None) -> str:
    """Get category for a product from the envios product catalog."""
    try:
        productos, _, _ = cargar_productos()
        for cat, prods in productos.items():
            if producto in prods:
                return cat
        return "Varios"
    except:
        return "Varios"


def stock_apply_movement(sh, local_name: str, producto: str, tipo: str,
                         cantidad: int, zona: str = "", responsable: str = "",
                         chat_id: int = 0, observaciones: str = ""):
    """
    Apply a stock movement: update Stock Actual and log to Movimientos.
    Returns (success: bool, message: str)
    """
    lk = _local_key_from_name(local_name)
    if not lk:
        return False, f"No se pudo identificar el local: {local_name}"

    current = stock_read_actual(sh)
    prod_stock = current.get(producto, {})
    cong = prod_stock.get(f"{lk}_congelado", 0)
    horn = prod_stock.get(f"{lk}_horneado", 0)

    estado_origen = ""
    estado_destino = ""
    updates = {}

    if tipo == TIPO_ENVIO_RECIBIDO:
        updates[f"{lk}_congelado"] = cong + cantidad
        estado_destino = "congelado"

    elif tipo == TIPO_FERMENTO:
        new_cong = max(0, cong - cantidad)
        updates[f"{lk}_congelado"] = new_cong
        estado_origen = "congelado"

    elif tipo == TIPO_HORNEO:
        updates[f"{lk}_horneado"] = horn + cantidad
        estado_destino = "horneado"

    elif tipo == TIPO_MERMA:
        new_horn = max(0, horn - cantidad)
        updates[f"{lk}_horneado"] = new_horn
        estado_origen = "horneado"

    elif tipo == TIPO_AJUSTE:
        if "horneado" in observaciones.lower():
            updates[f"{lk}_horneado"] = cantidad
            estado_destino = "horneado"
        else:
            updates[f"{lk}_congelado"] = cantidad
            estado_destino = "congelado"

    elif tipo == TIPO_CARGA_STOCK:
        # Direct set — used by template stock loading
        estado = observaciones  # "congelado" or "horneado"
        updates[f"{lk}_{estado}"] = cantidad
        estado_destino = estado

    else:
        return False, f"Tipo de movimiento desconocido: {tipo}"

    try:
        categoria = _get_product_category(producto)
        stock_update_product(sh, producto, categoria, updates)
        _time.sleep(1)
        stock_log_movement(sh, local_name, zona, producto, tipo,
                           cantidad, estado_origen, estado_destino,
                           responsable, chat_id, observaciones)
        return True, "OK"
    except Exception as e:
        return False, str(e)


def stock_apply_envio_recibido(sh, local_destino: str, productos_lista: list,
                               cantidades_lista: list, responsable: str,
                               chat_id: int):
    """
    When an envio is received, add all products to congelado stock.
    """
    lk = _local_key_from_name(local_destino)
    if not lk:
        log.warning(f"No se pudo mapear local para stock: {local_destino}")
        return

    for i, prod in enumerate(productos_lista):
        cant_str = cantidades_lista[i] if i < len(cantidades_lista) else "0"
        cant = _safe_int(cant_str)
        if cant <= 0:
            continue
        try:
            ok, msg = stock_apply_movement(
                sh, local_destino, prod, TIPO_ENVIO_RECIBIDO,
                cant, zona="", responsable=responsable,
                chat_id=chat_id, observaciones="Desde envio recibido"
            )
            if not ok:
                log.warning(f"Error actualizando stock para {prod}: {msg}")
            _time.sleep(1)
        except Exception as e:
            log.error(f"Error en stock_apply_envio_recibido para {prod}: {e}")


def stock_check_alerts(sh) -> list:
    """
    Check all products against minimums.
    Returns list of (local_key, producto, current_total, minimum) where below min.
    """
    try:
        current = stock_read_actual(sh)
        mins = stock_get_minimums(sh)
        alerts = []
        for prod, min_by_local in mins.items():
            prod_stock = current.get(prod, {})
            for lk in LOCAL_KEYS:
                minimum = min_by_local.get(lk, 0)
                if minimum <= 0:
                    continue
                cong = prod_stock.get(f"{lk}_congelado", 0)
                horn = prod_stock.get(f"{lk}_horneado", 0)
                total = cong + horn
                if total < minimum:
                    alerts.append((lk, prod, total, minimum))
        return alerts
    except Exception as e:
        log.error(f"Error checking stock alerts: {e}")
        return []


async def _send_stock_alerts(context, alerts: list):
    """Send stock alert notifications to NOTIFY_IDS."""
    if not alerts:
        return
    by_local = {}
    for lk, prod, current, minimum in alerts:
        by_local.setdefault(lk, []).append((prod, current, minimum))

    lines = ["⚠️ *ALERTA STOCK BAJO*\n"]
    for lk in sorted(by_local.keys()):
        lines.append(f"\n📍 *{lk}*:")
        for prod, current, minimum in by_local[lk]:
            deficit = minimum - current
            lines.append(f"  🔴 {esc(prod)}: {current}/{minimum} (faltan {deficit})")

    msg = "\n".join(lines)
    for cid in NOTIFY_IDS:
        try:
            await context.bot.send_message(chat_id=cid, text=msg, parse_mode="Markdown")
        except:
            pass


# ── HELPERS ───────────────────────────────────────────────────────────────────
def esc(t) -> str:
    """Escape Markdown v1 special characters."""
    if t is None:
        return "-"
    s = str(t)
    for c in ["*", "_", "`", "["]:
        s = s.replace(c, "\\" + c)
    return s


def local_corto(local: str) -> str:
    return local.split(" - ")[-1].strip() if " - " in local else local


def _fmt_prod_line(info, j):
    """Formatea una linea de producto con cantidad y unidad."""
    p = info["productos_lista"][j]
    c = info["cantidades_lista"][j]
    u = info["unidades_lista"][j] if j < len(info.get("unidades_lista", [])) else "u"
    return f"{p}: {c} {u}"


def _normalizar(texto: str) -> str:
    """Normaliza texto para comparacion: minusculas, sin acentos basicos."""
    t = texto.lower().strip()
    reemplazos = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ü": "u", "ñ": "n"}
    for k, v in reemplazos.items():
        t = t.replace(k, v)
    return t


def _buscar_producto_similar(nombre: str, productos_dict: dict, unidades_dict: dict = None, umbral: float = 0.6) -> tuple:
    """
    Busca el producto mas similar en el catalogo.
    Retorna (nombre_encontrado, categoria, unidad) o (None, None, None).
    """
    nombre_norm = _normalizar(nombre)
    mejor_score = 0
    mejor_prod = None
    mejor_cat = None
    for cat, prods in productos_dict.items():
        for prod in prods:
            prod_norm = _normalizar(prod)
            if nombre_norm == prod_norm:
                return prod, cat, (unidades_dict or {}).get(prod, "u")
            if nombre_norm in prod_norm or prod_norm in nombre_norm:
                score = 0.85
            else:
                score = SequenceMatcher(None, nombre_norm, prod_norm).ratio()
            if score > mejor_score:
                mejor_score = score
                mejor_prod = prod
                mejor_cat = cat
    if mejor_score >= umbral:
        unidad = (unidades_dict or {}).get(mejor_prod, "u")
        return mejor_prod, mejor_cat, unidad
    return None, None, None


def _parsear_template(texto: str) -> list:
    """
    Parsea un template de stock completado por el empleado.
    Cada linea con formato "Producto: N" -> (producto, cantidad).
    Ignora lineas con : 0, : _, : o sin numero.
    Retorna lista de (nombre_producto, cantidad_float).
    Cantidad es float para soportar kg decimales (ej: 0.5 kg).
    """
    items = []
    for line in texto.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Skip header/emoji lines
        if line.startswith("🧊") or line.startswith("🔥") or line.startswith("🧁") or line.startswith("☕"):
            continue
        # Try "Producto: N" format (integer or decimal)
        m = re.match(r'^(.+?):\s*(\d+[\.,]?\d*)\s*$', line)
        if m:
            nombre = m.group(1).strip()
            # Strip "(hay N)" context from fermentation templates
            nombre = re.sub(r'\s*\(hay\s+\d+[\.,]?\d*\)\s*$', '', nombre)
            try:
                val = float(m.group(2).replace(",", "."))
            except ValueError:
                continue
            if val > 0:
                # Keep as int if whole number, float if decimal (for kg)
                cantidad = int(val) if val == int(val) else round(val, 3)
                items.append((nombre, cantidad))
            continue
        # Also try "Producto: _" or "Producto:" — skip those
    return items


def _parsear_carga_manual(texto: str) -> list:
    """
    Parsea texto libre de carga manual para envios.
    Acepta formatos como:
      10 medialunas, 5 brownies
      medialunas 10
      10 x medialunas
      medialunas: 10
    Retorna lista de (cantidad, nombre_item)
    """
    items = []
    partes = re.split(r'[,;\n]+', texto)
    for parte in partes:
        parte = parte.strip().lstrip('-\u2022\u00b7').strip()
        if not parte:
            continue
        m = re.match(r'^(\d+[\.,]?\d*)\s*[xX]?\s+(.+)$', parte)
        if m:
            items.append((m.group(1).strip(), m.group(2).strip()))
            continue
        m = re.match(r'^(.+?)\s*[:xX]?\s*(\d+[\.,]?\d*)$', parte)
        if m and m.group(2):
            items.append((m.group(2).strip(), m.group(1).strip()))
            continue
        items.append(("1", parte))
    return items


async def _mostrar_resumen_editable(query_or_msg, info, is_message=False):
    """Muestra el resumen editable con botones para editar/eliminar cada producto y datos del envio."""
    lines = []
    keyboard = []
    for j, p in enumerate(info["productos_lista"]):
        cant = info["cantidades_lista"][j]
        u = info["unidades_lista"][j] if j < len(info.get("unidades_lista", [])) else "u"
        lines.append(f"  {j + 1}. *{esc(p)}*: {cant} {u}")
        keyboard.append([
            InlineKeyboardButton(f"✏️ {p[:18]}: {cant} {u}", callback_data=f"edit_prod_{j}"),
            InlineKeyboardButton("🗑️", callback_data=f"del_prod_{j}"),
        ])
    resumen = "\n".join(lines)
    keyboard.append([
        InlineKeyboardButton(f"📍 Destino: {local_corto(info['destino'])}", callback_data="edit_destino"),
        InlineKeyboardButton(f"👤 {info.get('responsable','?')[:12]}", callback_data="edit_responsable"),
    ])
    keyboard.append([InlineKeyboardButton("➕ Agregar mas", callback_data="resumen_agregar_mas")])
    keyboard.append([InlineKeyboardButton(f"✅ Confirmar ({len(info['productos_lista'])})", callback_data="resumen_ok")])
    keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
    text = (
        f"📋 *Revisa antes de continuar:*\n\n"
        f"📍 *{local_corto(info['origen'])}* → *{local_corto(info['destino'])}*\n"
        f"👤 {esc(info.get('responsable', ''))}\n\n"
        f"{resumen}\n\n"
        f"Toca para editar cualquier dato."
    )
    if is_message:
        await query_or_msg.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await query_or_msg.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")


def agregar_producto_nuevo(nombre: str, categoria: str = "Varios", unidad: str = "u"):
    """Agrega un producto nuevo a la pestana 'Productos Envio' del Sheet."""
    try:
        gc, sh = get_sheets_client()
        if not sh:
            return
        ws = None
        for tab_name in ["Productos Envio", "Productos Envío"]:
            try:
                ws = sh.worksheet(tab_name)
                break
            except Exception:
                continue
        if not ws:
            return
        ws.append_row([categoria, nombre, unidad, ""])
        # Invalidate product cache so new product shows up
        _product_cache["ts"] = 0
        log.info(f"Nuevo producto agregado al catalogo: {nombre} ({categoria})")
    except Exception as e:
        log.error(f"Error agregando producto: {e}")


# ── ORDENES DEL DIA HELPERS ──────────────────────────────────────────────────

def _format_orden_pedido(lk: str, stock: dict, mins: dict) -> str:
    """Format order directive for CDP — imperative tone."""
    lines = []
    for prod, min_by_local in sorted(mins.items()):
        minimum = min_by_local.get(lk, 0)
        if minimum <= 0:
            continue
        s = stock.get(prod, {})
        total = s.get(f"{lk}_congelado", 0) + s.get(f"{lk}_horneado", 0)
        deficit = minimum - total
        if deficit > 0:
            lines.append(f"  📦 {esc(prod)}: *{deficit}* (tiene {total}, min {minimum})")

    if not lines:
        return f"📍 *{lk}* — Stock OK, no necesita pedido"

    header = f"📍 *{lk}* — Pedir a CDP:\n"
    return header + "\n".join(lines)


def _format_orden_fermentacion(lk: str, stock: dict, mins: dict) -> str:
    """Format fermentation directive — imperative tone."""
    lines = []
    for prod, min_by_local in sorted(mins.items()):
        minimum = min_by_local.get(lk, 0)
        if minimum <= 0:
            continue
        s = stock.get(prod, {})
        horn = s.get(f"{lk}_horneado", 0)
        cong = s.get(f"{lk}_congelado", 0)
        threshold = minimum // 2
        if horn < threshold and cong > 0:
            to_ferment = min(minimum - horn, cong)
            if to_ferment > 0:
                lines.append(f"  🧊→🔥 {esc(prod)}: sacar *{to_ferment}* (horneado: {horn}, congelado: {cong})")

    if not lines:
        return f"📍 *{lk}* — Horneado OK"

    header = f"📍 *{lk}* — Sacar a fermentar:\n"
    return header + "\n".join(lines)


# ── HANDLERS ──────────────────────────────────────────────────────────────────

def _main_menu_keyboard():
    """Returns the main menu inline keyboard — 5 buttons as per CLAUDE.md."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📦 Enviar", callback_data="menu_envio"),
            InlineKeyboardButton("📥 Recibir", callback_data="menu_recibir"),
        ],
        [
            InlineKeyboardButton("📝 Cargar stock", callback_data="menu_cargar"),
            InlineKeyboardButton("🔥 Fermentación", callback_data="menu_fermentar"),
        ],
        [InlineKeyboardButton("📋 Órdenes del día", callback_data="menu_ordenes")],
    ])


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    estado_usuario.pop(update.effective_chat.id, None)
    await update.message.reply_text(
        "🥐 *Lharmonie — Envios y Stock*\n\n"
        "Dale, elegí que hacer:",
        reply_markup=_main_menu_keyboard(),
        parse_mode="Markdown"
    )


async def cmd_cargar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shortcut command /cargar"""
    estado_usuario[update.effective_chat.id] = {"paso": "cargar_eligiendo_local"}
    keyboard = [[InlineKeyboardButton(local_corto(l), callback_data=f"cargar_local_{i}")] for i, l in enumerate(LOCALES_RETAIL)]
    keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
    await update.message.reply_text(
        "📝 *Cargar stock*\n\nEn que local?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def cmd_fermentar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shortcut command /fermentar"""
    estado_usuario[update.effective_chat.id] = {"paso": "ferm_eligiendo_local"}
    keyboard = [[InlineKeyboardButton(local_corto(l), callback_data=f"ferm_local_{i}")] for i, l in enumerate(LOCALES_RETAIL)]
    keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
    await update.message.reply_text(
        "🔥 *Fermentación*\n\nEn que local?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def cmd_ordenes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shortcut command /ordenes"""
    estado_usuario[update.effective_chat.id] = {"paso": "ord_eligiendo_local"}
    keyboard = [[InlineKeyboardButton(local_corto(l), callback_data=f"ord_local_{i}")] for i, l in enumerate(LOCALES_RETAIL)]
    keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
    await update.message.reply_text(
        "📋 *Ordenes del día*\n\nPara que local?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    data = query.data

    # ── MENU PRINCIPAL ─────────────────────────────────────────────────
    if data == "menu_envio":
        estado_usuario[chat_id] = {
            "paso": "eligiendo_origen",
            "productos_lista": [], "cantidades_lista": [],
            "tipos_lista": [], "unidades_lista": []
        }
        keyboard = [[InlineKeyboardButton(local_corto(l), callback_data=f"origen_{i}")] for i, l in enumerate(LOCALES)]
        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
        await query.edit_message_text(
            "📍 *De donde sale el envio?*",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return

    if data == "menu_recibir":
        estado_usuario[chat_id] = {"paso": "eligiendo_local_recibir"}
        keyboard = [[InlineKeyboardButton(local_corto(l), callback_data=f"recibir_local_{i}")] for i, l in enumerate(LOCALES)]
        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
        await query.edit_message_text(
            "📍 *En que local estas?*",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return

    if data == "menu_cargar":
        estado_usuario[chat_id] = {"paso": "cargar_eligiendo_local"}
        keyboard = [[InlineKeyboardButton(local_corto(l), callback_data=f"cargar_local_{i}")] for i, l in enumerate(LOCALES_RETAIL)]
        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
        await query.edit_message_text(
            "📝 *Cargar stock*\n\nEn que local?",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return

    if data == "menu_fermentar":
        estado_usuario[chat_id] = {"paso": "ferm_eligiendo_local"}
        keyboard = [[InlineKeyboardButton(local_corto(l), callback_data=f"ferm_local_{i}")] for i, l in enumerate(LOCALES_RETAIL)]
        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
        await query.edit_message_text(
            "🔥 *Fermentación*\n\nEn que local?",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return

    if data == "menu_ordenes":
        estado_usuario[chat_id] = {"paso": "ord_eligiendo_local"}
        keyboard = [[InlineKeyboardButton(local_corto(l), callback_data=f"ord_local_{i}")] for i, l in enumerate(LOCALES_RETAIL)]
        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
        await query.edit_message_text(
            "📋 *Ordenes del día*\n\nPara que local?",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return

    if data == "menu_principal":
        estado_usuario.pop(chat_id, None)
        await query.edit_message_text(
            "🥐 *Lharmonie — Envios y Stock*\n\nDale, elegí que hacer:",
            reply_markup=_main_menu_keyboard(),
            parse_mode="Markdown"
        )
        return

    if data == "cancelar":
        estado_usuario.pop(chat_id, None)
        await query.edit_message_text(
            "Cancelado. Usa /start para volver al menu.",
            parse_mode="Markdown"
        )
        return

    # ── FLUJO CARGAR STOCK (TEMPLATE) ────────────────────────────────
    if data.startswith("cargar_local_"):
        idx = int(data.split("_")[2])
        local = LOCALES_RETAIL[idx]
        info = estado_usuario.get(chat_id, {})
        info["paso"] = "cargar_eligiendo_zona"
        info["cargar_local"] = local
        info["cargar_lk"] = _local_key_from_name(local)
        estado_usuario[chat_id] = info
        keyboard = [[InlineKeyboardButton(z, callback_data=f"cargar_zona_{i}")] for i, z in enumerate(ZONAS_DISPLAY)]
        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
        await query.edit_message_text(
            f"📍 *{local_corto(local)}*\n\nQue zona?",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return

    if data.startswith("cargar_zona_"):
        idx = int(data.split("_")[2])
        info = estado_usuario.get(chat_id, {})
        zona = ZONAS[idx]
        info["cargar_zona"] = zona
        info["paso"] = "cargar_esperando_template"
        estado_usuario[chat_id] = info

        try:
            # Build template for this zone
            products = _get_products_for_zone(zona)
            local = info.get("cargar_local", "")

            if not products:
                log.warning(f"No products found for zone {zona}")
                await query.edit_message_text(
                    f"No se encontraron productos para {zona}. Probá de nuevo con /start"
                )
                estado_usuario.pop(chat_id, None)
                return

            zona_emoji = {"Cocina": "🍳", "Mostrador": "🧁", "Barra": "☕"}.get(zona, "📝")
            state_label = {"Cocina": "🧊 CONGELADO", "Mostrador": "🔥 HORNEADO", "Barra": "☕ HORNEADO"}.get(zona, "STOCK")

            template_lines = [f"{zona_emoji} STOCK {zona.upper()} - {local_corto(local)} ({state_label})"]
            template_lines.append("")
            for prod in products:
                template_lines.append(f"{prod}: _")

            template = "\n".join(template_lines)

            # Send template as a separate message so user can copy it
            await query.edit_message_text(
                f"Copia este mensaje, completa las cantidades y mandalo:",
            )
            # Send template as plain text (no markdown) so it's easy to copy
            await query.message.reply_text(template)
        except Exception as e:
            log.error(f"Error generando template para {zona}: {e}", exc_info=True)
            await query.edit_message_text(
                f"Error cargando productos: {e}\n\nProbá de nuevo con /start"
            )
            estado_usuario.pop(chat_id, None)
        return

    # ── FLUJO FERMENTACION (TEMPLATE) ────────────────────────────────
    if data.startswith("ferm_local_"):
        idx = int(data.split("_")[2])
        local = LOCALES_RETAIL[idx]
        lk = _local_key_from_name(local)

        info = estado_usuario.get(chat_id, {})
        info["paso"] = "ferm_esperando_template"
        info["ferm_local"] = local
        info["ferm_lk"] = lk
        estado_usuario[chat_id] = info

        await query.edit_message_text("⏳ Cargando stock congelado...")

        try:
            sh = get_stock_sheet()
            if not sh:
                await query.edit_message_text("No se pudo conectar a Sheets.")
                estado_usuario.pop(chat_id, None)
                return

            _ensure_stock_tabs(sh)
            stock = stock_read_actual(sh)

            # Build template with products that have congelado > 0
            template_lines = [f"🧊→🔥 FERMENTACION - {local_corto(local)}"]
            template_lines.append("")
            has_products = False
            productos, _, _ = cargar_productos()
            all_prods = []
            for cat_prods in productos.values():
                all_prods.extend(cat_prods)
            all_prods = sorted(set(all_prods))

            for prod in all_prods:
                cong = stock.get(prod, {}).get(f"{lk}_congelado", 0)
                if cong > 0:
                    template_lines.append(f"{prod} (hay {cong}): _")
                    has_products = True

            if not has_products:
                await query.message.reply_text(
                    f"📍 *{local_corto(local)}*\n\n"
                    f"No hay stock congelado para fermentar.",
                    parse_mode="Markdown"
                )
                estado_usuario.pop(chat_id, None)
                return

            template = "\n".join(template_lines)
            await query.message.reply_text(
                "Copia, completá cuanto sacas a fermentar y mandalo 👇",
                parse_mode="Markdown"
            )
            await query.message.reply_text(template)

        except Exception as e:
            log.error(f"Error en fermentacion: {e}")
            await query.message.reply_text(f"Error: {esc(str(e))}", parse_mode="Markdown")
            estado_usuario.pop(chat_id, None)
        return

    # ── FLUJO ORDENES DEL DIA ────────────────────────────────────────
    if data.startswith("ord_local_"):
        idx = int(data.split("_")[2])
        local = LOCALES_RETAIL[idx]
        lk = _local_key_from_name(local)

        await query.edit_message_text("⏳ Calculando ordenes...")

        try:
            sh = get_stock_sheet()
            if not sh:
                await query.edit_message_text("No se pudo conectar a Sheets.")
                estado_usuario.pop(chat_id, None)
                return
            _ensure_stock_tabs(sh)
            stock = stock_read_actual(sh)
            mins = stock_get_minimums(sh)

            pedido = _format_orden_pedido(lk, stock, mins)
            fermentacion = _format_orden_fermentacion(lk, stock, mins)

            msg = (
                f"📋 *Ordenes del día — {local_corto(local)}*\n\n"
                f"━━━ PEDIR A CDP ━━━\n{pedido}\n\n"
                f"━━━ SACAR A FERMENTAR ━━━\n{fermentacion}"
            )

            keyboard = [
                [InlineKeyboardButton("🔄 Actualizar", callback_data=data)],
                [InlineKeyboardButton("⬅️ Menu", callback_data="menu_principal")],
            ]
            if len(msg) > 4000:
                await query.edit_message_text(msg[:4000], parse_mode="Markdown")
            else:
                await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        except Exception as e:
            log.error(f"Error en ordenes: {e}")
            await query.edit_message_text(f"Error: {esc(str(e))}", parse_mode="Markdown")
        estado_usuario.pop(chat_id, None)
        return

    # ── FLUJO ENVIO ────────────────────────────────────────────────────
    info = estado_usuario.get(chat_id)
    if info is None:
        await query.edit_message_text(
            "Se perdio la sesion (el bot se reinicio).\n\nDale, elegí que hacer:",
            reply_markup=_main_menu_keyboard(), parse_mode="Markdown"
        )
        return

    if data.startswith("origen_"):
        idx = int(data.split("_")[1])
        info["origen"] = LOCALES[idx]
        info["paso"] = "eligiendo_destino"
        keyboard = [[InlineKeyboardButton(local_corto(l), callback_data=f"destino_{i}")] for i, l in enumerate(LOCALES) if i != idx]
        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
        await query.edit_message_text(
            f"📍 Origen: *{local_corto(info['origen'])}*\n\nA donde va?",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return

    if data.startswith("destino_"):
        idx = int(data.split("_")[1])
        info["destino"] = LOCALES[idx]
        info["paso"] = "esperando_nombre"
        await query.edit_message_text(
            f"📦 *{local_corto(info['origen'])}* → *{local_corto(info['destino'])}*\n\n👤 Tu nombre:",
            parse_mode="Markdown"
        )
        return

    # Terminar productos -> resumen editable
    if data == "terminar_productos":
        if not info.get("productos_lista"):
            await query.answer("Agrega al menos un producto", show_alert=True)
            return
        info["paso"] = "resumen_editable"
        await _mostrar_resumen_editable(query, info)
        return

    # Editar un producto en el resumen
    if data.startswith("edit_prod_"):
        idx = int(data.split("_")[2])
        if idx < len(info.get("productos_lista", [])):
            info["editando_idx"] = idx
            prod = info["productos_lista"][idx]
            cant = info["cantidades_lista"][idx]
            u = info["unidades_lista"][idx] if idx < len(info.get("unidades_lista", [])) else "u"
            keyboard = [
                [InlineKeyboardButton(f"🔢 Cantidad ({cant})", callback_data=f"editcant_{idx}")],
                [InlineKeyboardButton(f"📏 Unidad ({u})", callback_data=f"editunit_{idx}")],
                [InlineKeyboardButton(f"📦 Producto ({prod[:25]})", callback_data=f"editname_{idx}")],
                [InlineKeyboardButton("⬅️ Volver al resumen", callback_data="volver_resumen")],
            ]
            await query.edit_message_text(
                f"✏️ *Editando:* {esc(prod)}: {cant} {u}\n\nQue corregis?",
                reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
            )
        return

    if data.startswith("editcant_"):
        idx = int(data.split("_")[1])
        info["editando_idx"] = idx
        info["paso"] = "editando_cantidad"
        prod = info["productos_lista"][idx]
        u = info["unidades_lista"][idx] if idx < len(info.get("unidades_lista", [])) else "u"
        await query.edit_message_text(
            f"🔢 *{esc(prod)}* — Actual: *{info['cantidades_lista'][idx]} {u}*\n\nNueva cantidad:",
            parse_mode="Markdown"
        )
        return

    if data.startswith("editunit_"):
        idx = int(data.split("_")[1])
        info["editando_idx"] = idx
        keyboard = [
            [
                InlineKeyboardButton("u (unidades)", callback_data=f"setunit_{idx}_u"),
                InlineKeyboardButton("kg", callback_data=f"setunit_{idx}_kg"),
            ],
            [
                InlineKeyboardButton("g (gramos)", callback_data=f"setunit_{idx}_g"),
                InlineKeyboardButton("lt (litros)", callback_data=f"setunit_{idx}_lt"),
            ],
            [InlineKeyboardButton("⬅️ Volver", callback_data="volver_resumen")],
        ]
        prod = info["productos_lista"][idx]
        u_actual = info["unidades_lista"][idx] if idx < len(info.get("unidades_lista", [])) else "u"
        await query.edit_message_text(
            f"📏 *{esc(prod)}* — Unidad actual: *{u_actual}*\n\nElegi:",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return

    if data.startswith("setunit_"):
        parts = data.split("_")
        idx = int(parts[1])
        new_unit = parts[2]
        if idx < len(info.get("unidades_lista", [])):
            info["unidades_lista"][idx] = new_unit
        await query.answer(f"Unidad cambiada a {new_unit}")
        info["paso"] = "resumen_editable"
        await _mostrar_resumen_editable(query, info)
        return

    if data.startswith("editname_"):
        idx = int(data.split("_")[1])
        info["editando_idx"] = idx
        info["paso"] = "editando_nombre_prod"
        prod = info["productos_lista"][idx]
        await query.edit_message_text(
            f"📦 Producto actual: *{esc(prod)}*\n\nNombre correcto:",
            parse_mode="Markdown"
        )
        return

    if data == "volver_resumen":
        info["paso"] = "resumen_editable"
        await _mostrar_resumen_editable(query, info)
        return

    if data == "edit_destino":
        info["paso"] = "editando_destino"
        origen_idx = None
        for i, l in enumerate(LOCALES):
            if l == info.get("origen"):
                origen_idx = i
                break
        keyboard = [[InlineKeyboardButton(local_corto(l), callback_data=f"newdest_{i}")] for i, l in enumerate(LOCALES) if i != origen_idx]
        keyboard.append([InlineKeyboardButton("⬅️ Volver", callback_data="volver_resumen")])
        await query.edit_message_text(
            f"📍 Destino actual: *{local_corto(info['destino'])}*\n\nCual es?",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return

    if data.startswith("newdest_"):
        idx = int(data.split("_")[1])
        info["destino"] = LOCALES[idx]
        await query.answer(f"Destino: {local_corto(LOCALES[idx])}")
        info["paso"] = "resumen_editable"
        await _mostrar_resumen_editable(query, info)
        return

    if data == "edit_responsable":
        info["paso"] = "editando_responsable"
        await query.edit_message_text(
            f"👤 Responsable actual: *{esc(info.get('responsable', ''))}*\n\nNombre correcto:",
            parse_mode="Markdown"
        )
        return

    if data.startswith("del_prod_"):
        idx = int(data.split("_")[2])
        if idx < len(info.get("productos_lista", [])):
            eliminado = info["productos_lista"].pop(idx)
            info["cantidades_lista"].pop(idx)
            info["tipos_lista"].pop(idx)
            if idx < len(info.get("unidades_lista", [])):
                info["unidades_lista"].pop(idx)
            await query.answer(f"🗑️ {eliminado} eliminado")
            if not info["productos_lista"]:
                # All deleted, go back to text libre
                info["paso"] = "esperando_carga_manual"
                await query.edit_message_text(
                    "Se eliminaron todos los productos.\n\n"
                    "Manda los productos con cantidades.\n"
                    "Ej: 10 medialunas, 5 brownies, 3 pain au choco",
                    parse_mode="Markdown"
                )
                return
            await _mostrar_resumen_editable(query, info)
        return

    if data == "resumen_ok":
        info["paso"] = "esperando_bultos_total"
        lines = [f"  · {_fmt_prod_line(info, j)}" for j in range(len(info["productos_lista"]))]
        resumen = "\n".join(lines)
        await query.edit_message_text(
            f"📦 *{local_corto(info['origen'])}* → *{local_corto(info['destino'])}*\n\n"
            f"📋 *Productos:*\n{resumen}\n\n"
            f"📦 Cuantos bultos son?",
            parse_mode="Markdown"
        )
        return

    if data == "resumen_agregar_mas":
        info["paso"] = "esperando_carga_manual"
        await query.edit_message_text(
            f"📦 *{local_corto(info['origen'])}* → *{local_corto(info['destino'])}*\n\n"
            f"📋 Ya tenes {len(info['productos_lista'])} productos.\n\n"
            f"Manda mas con cantidades (ej: 10 medialunas, 5 brownies):",
            parse_mode="Markdown"
        )
        return

    if data.startswith("transporte_"):
        idx = int(data.split("_")[1])
        info["transporte"] = TRANSPORTES[idx]
        info["paso"] = "confirmando_envio"
        lines = [f"  · {_fmt_prod_line(info, j)}" for j in range(len(info["productos_lista"]))]
        resumen = "\n".join(lines)
        keyboard = [
            [InlineKeyboardButton("✅ Confirmar envio", callback_data="confirmar_envio")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")],
        ]
        await query.edit_message_text(
            f"📦 *Confirmar envio*\n\n"
            f"📍 *{local_corto(info['origen'])}* → *{local_corto(info['destino'])}*\n"
            f"👤 {esc(info.get('responsable', ''))}\n"
            f"🚗 {info['transporte']}\n"
            f"📦 Bultos: {info.get('bultos_total', '?')}\n\n"
            f"📋 *Productos:*\n{resumen}",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return

    if data == "confirmar_envio":
        ahora = datetime.now(TZ_AR)
        info["fecha"] = ahora.strftime("%d/%m/%Y")
        info["hora"] = ahora.strftime("%H:%M")

        ok, error_msg = guardar_envio(info)

        if not ok:
            await query.edit_message_text(
                f"No se pudo guardar el envio: {esc(error_msg or 'Error desconocido')}\n\nIntenta de nuevo con /start",
                parse_mode="Markdown"
            )
            estado_usuario.pop(chat_id, None)
            return

        # Notificar
        lines = [f"  · {_fmt_prod_line(info, j)}" for j in range(len(info["productos_lista"]))]
        resumen = "\n".join(lines)
        msg_notif = (
            f"📦 *Nuevo envio*\n\n"
            f"📍 *{local_corto(info['origen'])}* → *{local_corto(info['destino'])}*\n"
            f"👤 {esc(info.get('responsable', ''))}\n"
            f"🚗 {info['transporte']}\n"
            f"📦 Bultos: {info.get('bultos_total', '?')}\n"
            f"🕐 {info['hora']}\n\n"
            f"📋 *Productos:*\n{resumen}"
        )
        for cid in NOTIFY_IDS:
            try:
                await context.bot.send_message(chat_id=cid, text=msg_notif, parse_mode="Markdown")
            except:
                pass
        await query.edit_message_text(
            f"✅ *Anotado*\n\n"
            f"📍 {local_corto(info['origen'])} → {local_corto(info['destino'])}\n"
            f"📋 {len(info['productos_lista'])} productos",
            parse_mode="Markdown"
        )
        estado_usuario.pop(chat_id, None)
        return

    # ── FLUJO RECIBIR ──────────────────────────────────────────────────
    if data.startswith("recibir_local_"):
        idx = int(data.split("_")[2])
        local = LOCALES[idx]

        pendientes, error_msg = obtener_envios_pendientes(local)

        if error_msg:
            await query.edit_message_text(
                f"Error buscando envios: {esc(error_msg)}",
                parse_mode="Markdown"
            )
            estado_usuario.pop(chat_id, None)
            return

        if not pendientes:
            await query.edit_message_text(
                f"No hay envios pendientes para *{local_corto(local)}*.",
                parse_mode="Markdown"
            )
            estado_usuario.pop(chat_id, None)
            return
        info["local_recibir"] = local
        info["pendientes"] = pendientes
        keyboard = []
        for i, env in enumerate(pendientes):
            n_prods = len(_split_multi(env["productos"])) if env["productos"] else 0
            keyboard.append([InlineKeyboardButton(
                f"{env['fecha']} {env['hora']} — {local_corto(env['origen'])} ({n_prods} prod)",
                callback_data=f"recibir_env_{i}"
            )])
        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
        await query.edit_message_text(
            f"📥 *Envios pendientes para {local_corto(local)}:*",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return

    if data.startswith("recibir_env_"):
        idx = int(data.split("_")[2])
        pendientes = info.get("pendientes", [])
        if idx >= len(pendientes):
            return
        env = pendientes[idx]
        info["envio_a_recibir"] = env
        info["paso"] = "esperando_nombre_recibir"
        prods = _split_multi(env["productos"])
        cants = _split_multi(env["cantidades"])
        lines = []
        for j, p in enumerate(prods):
            c = cants[j] if j < len(cants) else "?"
            lines.append(f"  · {p}: {c}")
        resumen = "\n".join(lines)
        await query.edit_message_text(
            f"📥 *Envio de {local_corto(env['origen'])}*\n"
            f"📅 {env['fecha']} {env['hora']}\n"
            f"👤 Envio: {esc(env['responsable'])}\n"
            f"📦 Bultos: {env.get('bultos', '')}\n\n"
            f"📋 *Productos:*\n{resumen}\n\n"
            f"👤 Tu nombre para confirmar:",
            parse_mode="Markdown"
        )
        return

    if data == "recibir_todo_ok":
        env = info.get("envio_a_recibir", {})
        resp = info.get("nombre_recibir", "")
        tiempo = _calcular_tiempo_envio(env.get("fecha", ""), env.get("hora", ""))
        marcar_recibido(env["fila"], resp, recibido_ok=True)

        local_dest = info.get("local_recibir", env.get("destino", ""))
        prods = _split_multi(env.get("productos", ""))
        cants = _split_multi(env.get("cantidades", ""))
        try:
            sh_stock = get_stock_sheet()
            if sh_stock and prods:
                _ensure_stock_tabs(sh_stock)
                stock_apply_envio_recibido(sh_stock, local_dest, prods, cants, resp, chat_id)
        except Exception as se:
            log.error(f"Error actualizando stock al recibir envio: {se}")

        msg_notif = (
            f"✅ *Envio recibido*\n\n"
            f"📍 {local_corto(env['origen'])} → {local_corto(env['destino'])}\n"
            f"👤 Recibio: {esc(resp)}\n"
            f"⏱️ Tiempo: {tiempo}\n"
            f"📋 Todo OK"
        )
        for cid in NOTIFY_IDS:
            try:
                await context.bot.send_message(chat_id=cid, text=msg_notif, parse_mode="Markdown")
            except:
                pass
        await query.edit_message_text(f"✅ *Anotado*", parse_mode="Markdown")
        estado_usuario.pop(chat_id, None)
        return

    if data == "recibir_con_diferencias":
        info["paso"] = "esperando_diferencias"
        await query.edit_message_text(
            "Escribi que diferencias encontraste:\n\n"
            "Ej: Faltaron 3 medialunas, llegaron 2 brownies de mas",
            parse_mode="Markdown"
        )
        return


async def handle_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    texto = update.message.text.strip()

    if chat_id not in estado_usuario:
        await update.message.reply_text(
            "🥐 *Lharmonie — Envios y Stock*\n\nDale, elegí que hacer:",
            reply_markup=_main_menu_keyboard(),
            parse_mode="Markdown"
        )
        return

    info = estado_usuario[chat_id]
    paso = info.get("paso", "")

    # ── STOCK: Template response ──
    if paso == "cargar_esperando_template":
        items = _parsear_template(texto)
        if not items:
            await update.message.reply_text(
                "No encontre productos con cantidades. Asegurate de completar con numeros.\n\n"
                "Formato: Medialunas: 50",
                parse_mode="Markdown"
            )
            return

        local = info.get("cargar_local", "")
        zona = info.get("cargar_zona", "")
        lk = info.get("cargar_lk", "")
        default_state = ZONA_DEFAULT_STATE.get(zona, "congelado")

        await update.message.reply_text("⏳ Guardando...")

        try:
            sh = get_stock_sheet()
            if not sh:
                await update.message.reply_text("No se pudo conectar a Sheets.")
                estado_usuario.pop(chat_id, None)
                return
            _ensure_stock_tabs(sh)

            productos_dict, unidades_dict, _ = cargar_productos()
            saved_count = 0
            errors = []

            for nombre, cantidad in items:
                # Fuzzy match against catalog
                prod_match, cat_match, _ = _buscar_producto_similar(nombre, productos_dict, unidades_dict)
                prod_name = prod_match if prod_match else nombre
                cat_name = cat_match if cat_match else "Varios"

                try:
                    ok, msg = stock_apply_movement(
                        sh, local, prod_name, TIPO_CARGA_STOCK,
                        cantidad, zona=zona, responsable="",
                        chat_id=chat_id, observaciones=default_state
                    )
                    if ok:
                        saved_count += 1
                    else:
                        errors.append(f"{prod_name}: {msg}")
                    _time.sleep(1)  # Rate limit
                except Exception as e:
                    errors.append(f"{prod_name}: {e}")

            if errors:
                log.warning(f"Errores en carga stock: {errors}")

            await update.message.reply_text("✅ Anotado")
            # Back to menu
            await update.message.reply_text(
                "Dale, elegí que hacer:",
                reply_markup=_main_menu_keyboard(),
                parse_mode="Markdown"
            )

        except Exception as e:
            log.error(f"Error en carga stock template: {e}")
            await update.message.reply_text(f"Error: {esc(str(e))}", parse_mode="Markdown")

        estado_usuario.pop(chat_id, None)
        return

    # ── FERMENTACION: Template response ──
    if paso == "ferm_esperando_template":
        items = _parsear_template(texto)
        if not items:
            await update.message.reply_text(
                "No encontre productos con cantidades. Completá con numeros.\n\n"
                "Formato: Medialunas (hay 50): 20",
                parse_mode="Markdown"
            )
            return

        local = info.get("ferm_local", "")
        lk = info.get("ferm_lk", "")

        await update.message.reply_text("⏳ Guardando...")

        try:
            sh = get_stock_sheet()
            if not sh:
                await update.message.reply_text("No se pudo conectar a Sheets.")
                estado_usuario.pop(chat_id, None)
                return
            _ensure_stock_tabs(sh)

            productos_dict, unidades_dict, _ = cargar_productos()
            saved_count = 0

            for nombre, cantidad in items:
                prod_match, _, _ = _buscar_producto_similar(nombre, productos_dict, unidades_dict)
                prod_name = prod_match if prod_match else nombre

                try:
                    ok, msg = stock_apply_movement(
                        sh, local, prod_name, TIPO_FERMENTO,
                        cantidad, zona="Cocina", responsable="",
                        chat_id=chat_id, observaciones="fermentacion"
                    )
                    if ok:
                        saved_count += 1
                    _time.sleep(1)
                except Exception as e:
                    log.error(f"Error fermentacion {prod_name}: {e}")

            await update.message.reply_text("✅ Anotado")
            await update.message.reply_text(
                "Dale, elegí que hacer:",
                reply_markup=_main_menu_keyboard(),
                parse_mode="Markdown"
            )

        except Exception as e:
            log.error(f"Error en fermentacion template: {e}")
            await update.message.reply_text(f"Error: {esc(str(e))}", parse_mode="Markdown")

        estado_usuario.pop(chat_id, None)
        return

    # ── ENVIO: Nombre del que envia ──
    if paso == "esperando_nombre":
        info["responsable"] = texto
        info["paso"] = "esperando_carga_manual"
        await update.message.reply_text(
            f"👤 {esc(texto)}\n\n"
            f"Manda los productos con cantidades.\n"
            f"Ej: 10 medialunas, 5 brownies, 3 pain au choco",
            parse_mode="Markdown"
        )
        return

    # ── ENVIO: Carga manual de productos (texto libre) ──
    if paso == "esperando_carga_manual":
        items = _parsear_carga_manual(texto)
        if not items:
            await update.message.reply_text(
                "No pude interpretar ningun producto. Intenta de nuevo.\n\n"
                "Ej: 10 medialunas, 5 brownies",
                parse_mode="Markdown"
            )
            return
        productos, unidades, _ = cargar_productos()
        for cantidad, nombre in items:
            prod_match, cat_match, unit_match = _buscar_producto_similar(nombre, productos, unidades)
            if prod_match:
                info["productos_lista"].append(prod_match)
                info["cantidades_lista"].append(cantidad)
                info["unidades_lista"].append(unit_match or "u")
                tipo = cat_match if cat_match else "Producto Terminado"
                info["tipos_lista"].append(tipo)
            else:
                nombre_cap = nombre.strip().capitalize()
                agregar_producto_nuevo(nombre_cap)
                info["productos_lista"].append(nombre_cap)
                info["cantidades_lista"].append(cantidad)
                info["unidades_lista"].append("u")
                info["tipos_lista"].append("Producto Terminado")

        info["paso"] = "resumen_editable"
        await _mostrar_resumen_editable(update.message, info, is_message=True)
        return

    # ── ENVIO: Editando cantidad desde resumen editable ──
    if paso == "editando_cantidad":
        idx = info.get("editando_idx", 0)
        if idx < len(info["cantidades_lista"]):
            prod = info["productos_lista"][idx]
            u = info["unidades_lista"][idx] if idx < len(info.get("unidades_lista", [])) else "u"
            info["cantidades_lista"][idx] = texto
            info["paso"] = "resumen_editable"
            await _mostrar_resumen_editable(update.message, info, is_message=True)
        return

    # ── ENVIO: Editando nombre del producto ──
    if paso == "editando_nombre_prod":
        idx = info.get("editando_idx", 0)
        if idx < len(info["productos_lista"]):
            info["productos_lista"][idx] = texto.strip()
            info["paso"] = "resumen_editable"
            await _mostrar_resumen_editable(update.message, info, is_message=True)
        return

    # ── ENVIO: Editando responsable ──
    if paso == "editando_responsable":
        info["responsable"] = texto.strip()
        info["paso"] = "resumen_editable"
        await _mostrar_resumen_editable(update.message, info, is_message=True)
        return

    # ── ENVIO: Bultos totales ──
    if paso == "esperando_bultos_total":
        info["bultos_total"] = texto
        info["paso"] = "eligiendo_transporte"
        keyboard = [[InlineKeyboardButton(t, callback_data=f"transporte_{i}")] for i, t in enumerate(TRANSPORTES)]
        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
        await update.message.reply_text(
            f"📦 Bultos: *{texto}*\n\n🚗 Como se envia?",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return

    # ── RECIBIR: Nombre del que recibe ──
    if paso == "esperando_nombre_recibir":
        info["nombre_recibir"] = texto
        keyboard = [
            [InlineKeyboardButton("✅ Todo OK", callback_data="recibir_todo_ok")],
            [InlineKeyboardButton("⚠️ Hay diferencias", callback_data="recibir_con_diferencias")],
        ]
        await update.message.reply_text(
            f"👤 {esc(texto)}\n\nLlego todo bien?",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return

    # ── RECIBIR: Diferencias ──
    if paso == "esperando_diferencias":
        env = info.get("envio_a_recibir", {})
        resp = info.get("nombre_recibir", "")
        tiempo = _calcular_tiempo_envio(env.get("fecha", ""), env.get("hora", ""))
        marcar_recibido(env["fila"], resp, recibido_ok=False, diferencias=texto)

        local_dest = info.get("local_recibir", env.get("destino", ""))
        prods = _split_multi(env.get("productos", ""))
        cants = _split_multi(env.get("cantidades", ""))
        try:
            sh_stock = get_stock_sheet()
            if sh_stock and prods:
                _ensure_stock_tabs(sh_stock)
                stock_apply_envio_recibido(sh_stock, local_dest, prods, cants, resp, chat_id)
        except Exception as se:
            log.error(f"Error actualizando stock al recibir envio con diff: {se}")

        msg_notif = (
            f"⚠️ *Envio recibido con diferencias*\n\n"
            f"📍 {local_corto(env['origen'])} → {local_corto(env['destino'])}\n"
            f"👤 Recibio: {esc(resp)}\n"
            f"⏱️ Tiempo: {tiempo}\n"
            f"📝 Diferencias: {esc(texto)}"
        )
        for cid in NOTIFY_IDS:
            try:
                await context.bot.send_message(chat_id=cid, text=msg_notif, parse_mode="Markdown")
            except:
                pass
        await update.message.reply_text("✅ Anotado. El equipo fue notificado.", parse_mode="Markdown")
        estado_usuario.pop(chat_id, None)
        return


# ── MAIN ──────────────────────────────────────────────────────────────────────
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler global de errores."""
    log.error(f"Error no atrapado: {context.error}", exc_info=context.error)
    try:
        if update and update.effective_chat:
            chat_id = update.effective_chat.id
            estado_usuario.pop(chat_id, None)
            if update.callback_query:
                await update.callback_query.message.reply_text(
                    "Ocurrio un error. Empeza de nuevo:",
                    reply_markup=_main_menu_keyboard()
                )
            elif update.message:
                await update.message.reply_text(
                    "Ocurrio un error. Empeza de nuevo:",
                    reply_markup=_main_menu_keyboard()
                )
    except Exception as e:
        log.error(f"Error en el error handler: {e}")


def main():
    if not TELEGRAM_TOKEN:
        print("Falta ENVIOS_TELEGRAM_TOKEN")
        return
    print("Iniciando Bot Envios + Stock Lharmonie...")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Command handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("cargar", cmd_cargar))
    app.add_handler(CommandHandler("fermentar", cmd_fermentar))
    app.add_handler(CommandHandler("ordenes", cmd_ordenes))

    # Callback and text handlers
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_texto))

    app.add_error_handler(error_handler)
    print("Bot Envios + Stock corriendo.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
