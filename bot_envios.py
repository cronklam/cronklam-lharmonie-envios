#!/usr/bin/env python3
"""
Bot de Telegram — Envios + Stock Lharmonie
===========================================
Registra envios de mercaderia entre locales y gestiona stock
(congelado/horneado) por local con alertas y sugerencias.
Catalogo de productos editable desde Google Sheets.
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
# Old list kept as alias for backward compat in envio matching
LOCALES_STOCK = [
    "CDP - Nicaragua (Produccion)",
    "LH2 - Nicaragua 6068",
    "LH3 - Maure 1516",
    "LH4 - Zabala 1925",
    "LH5 - Libertador 3118",
]
LOCALES_ENVIO = LOCALES_STOCK  # envios now use same list
LOCALES = LOCALES_ENVIO        # backward compat alias

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
        log.error("❌ GOOGLE_CREDENTIALS no configurado")
        return None, None
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(json.loads(creds_json), scopes=scopes)
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(SHEETS_ID)
        _sheets_cache.update({"gc": gc, "sh": sh, "ts": now})
        return gc, sh
    except Exception as e:
        log.error(f"❌ Error conectando a Sheets: {e}")
        return None, None


def get_stock_sheet():
    """Returns the same gspread Spreadsheet as envios — todo en un solo Sheet."""
    gc, sh = get_sheets_client()
    return sh


# ── PRODUCTOS ─────────────────────────────────────────────────────────────────
def cargar_productos() -> tuple:
    """
    Lee la pestana 'Productos Envio' del Sheet.
    Retorna (dict categorias, dict unidades):
      - categorias: {categoria: [producto1, producto2, ...]}
      - unidades:   {producto: "u"|"kg"|"lt"|"g"|...}
    """
    try:
        gc, sh = get_sheets_client()
        if not sh:
            return {}, {}
        try:
            ws = sh.worksheet("Productos Envío")
        except:
            ws = sh.add_worksheet("Productos Envío", rows=200, cols=3)
            ws.append_row(["Categoría", "Producto", "Unidad"])
            _crear_productos_iniciales(ws)
        vals = ws.get_all_values()
        header_idx = 0
        for i, row in enumerate(vals):
            if "Categoría" in row or "Categoria" in row:
                header_idx = i
                break
        productos = {}
        unidades = {}
        for row in vals[header_idx + 1:]:
            if not any(row):
                continue
            cat = row[0].strip() if len(row) > 0 else ""
            prod = row[1].strip() if len(row) > 1 else ""
            unidad = row[2].strip() if len(row) > 2 else "u"
            if cat and prod:
                if cat not in productos:
                    productos[cat] = []
                productos[cat].append(prod)
                unidades[prod] = unidad or "u"
        log.info(f"✅ Productos cargados: {sum(len(v) for v in productos.values())} en {len(productos)} categorias")
        return productos, unidades
    except Exception as e:
        log.error(f"❌ Error cargando productos: {e}")
        return {}, {}


def _crear_productos_iniciales(ws):
    """Crea el catalogo inicial de productos."""
    productos = [
        # Pasteleria
        ("Pastelería", "Alfajor de chocolate", "u"),
        ("Pastelería", "Alfajor de nuez", "u"),
        ("Pastelería", "Alfajor de pistacho", "u"),
        ("Pastelería", "Barritas proteína", "u"),
        ("Pastelería", "Brownie", "u"),
        ("Pastelería", "Budín", "u"),
        ("Pastelería", "Cookie chocolate", "u"),
        ("Pastelería", "Cookie de maní", "u"),
        ("Pastelería", "Cookie melu", "u"),
        ("Pastelería", "Cookie nuez", "u"),
        ("Pastelería", "Cookie red velvet", "u"),
        ("Pastelería", "Cuadrado de coco", "u"),
        ("Pastelería", "Muffin", "u"),
        ("Pastelería", "Porción de dátiles", "u"),
        ("Pastelería", "Porción de torta", "u"),
        ("Pastelería", "Tarteleta", "u"),
        # Elaborados
        ("Elaborados", "Bavka choco", "u"),
        ("Elaborados", "Bavka pistacho", "u"),
        ("Elaborados", "Brioche pastelera", "u"),
        ("Elaborados", "Chipa", "u"),
        ("Elaborados", "Chipa prensado", "u"),
        ("Elaborados", "Croissant", "u"),
        ("Elaborados", "Medialunas", "u"),
        ("Elaborados", "Pain au choco", "u"),
        ("Elaborados", "Palitos de queso", "u"),
        ("Elaborados", "Palmeras", "u"),
        ("Elaborados", "Pan brioche", "u"),
        ("Elaborados", "Pan brioche cuadrado", "u"),
        ("Elaborados", "Pan masa madre con semillas", "u"),
        ("Elaborados", "Pan suisse", "u"),
        ("Elaborados", "Roll canela", "u"),
        ("Elaborados", "Roll frambuesa", "u"),
        ("Elaborados", "Tarta del día", "u"),
        # Varios
        ("Varios", "Aceite de girasol", "u"),
        ("Varios", "Aceite de oliva cocina", "u"),
        ("Varios", "Aderezo caesar", "u"),
        ("Varios", "Almendras", "kg"),
        ("Varios", "Almendras fileteadas", "kg"),
        ("Varios", "Arroz yamani cocido", "kg"),
        ("Varios", "Arroz yamani crudo", "kg"),
        ("Varios", "Arvejas", "u"),
        ("Varios", "Azúcar común", "kg"),
        ("Varios", "Azúcar impalpable", "kg"),
        ("Varios", "Chocolate en barra", "u"),
        ("Varios", "Chocolate en trozos", "kg"),
        ("Varios", "Crema bariloche", "u"),
        ("Varios", "Crema pastelera de chocolate", "kg"),
        ("Varios", "Crema pastelera de panadería", "kg"),
        ("Varios", "Dulce de leche", "kg"),
        ("Varios", "Frangipane", "kg"),
        ("Varios", "Frosting de queso", "g"),
        ("Varios", "Granola", "kg"),
        ("Varios", "Hongos cocidos", "u"),
        ("Varios", "Lomitos de atún", "u"),
        ("Varios", "Maple de huevos", "u"),
        ("Varios", "Manteca común", "u"),
        ("Varios", "Manteca saborizada", "u"),
        ("Varios", "Mermelada de cocina", "u"),
        ("Varios", "Mermelada de frambuesa", "u"),
        ("Varios", "Miel", "u"),
        ("Varios", "Pasta de atún", "g"),
        ("Varios", "Pasta de pistacho", "g"),
        ("Varios", "Pesto", "g"),
        ("Varios", "Picles de pepino", "u"),
        ("Varios", "Pistacho procesado", "g"),
        ("Varios", "Porción de trucha grill", "u"),
        ("Varios", "Queso crema", "u"),
        ("Varios", "Queso sardo", "u"),
        ("Varios", "Queso tybo", "u"),
        ("Varios", "Quinoa cocida", "kg"),
        ("Varios", "Quinoa crocante", "kg"),
        ("Varios", "Salsa holandesa", "u"),
        ("Varios", "Vinagre", "u"),
        ("Varios", "Wraps de espinaca", "u"),
        ("Varios", "Maní", "kg"),
        ("Varios", "Sal", "kg"),
    ]
    rows = [[cat, prod, unidad] for cat, prod, unidad in productos]
    ws.append_rows(rows)
    log.info(f"✅ Catalogo inicial creado: {len(rows)} productos")


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
    Levanta excepcion si falla.
    NUNCA modifica headers existentes — solo lee lo que hay.
    """
    try:
        ws = sh.worksheet("Envíos")
        return ws, False
    except Exception as e:
        err_str = str(e).lower()
        if "not found" in err_str or "no worksheet" in err_str:
            ws = sh.add_worksheet("Envíos", rows=2000, cols=len(EXPECTED_HEADERS))
            ws.append_row(EXPECTED_HEADERS)
            log.info("✅ Pestana 'Envios' creada")
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
            return (False, "No se pudo conectar a Google Sheets. Verifica las credenciales.")

        ws, created = _get_or_create_envios_ws(sh)

        # Leer headers actuales y construir fila por nombre
        headers = ws.row_values(1)
        log.info(f"Headers actuales: {headers}")

        # FIX: Usar " | " como separador en vez de "\n" para que el sheet no
        # expanda filas y get_all_values() devuelva 1 fila por envio
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
        log.info(f"✅ Envio guardado: {datos.get('origen')} -> {datos.get('destino')}")
        return (True, None)
    except Exception as e:
        log.error(f"❌ Error guardando envio: {e}")
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
            return ([], None)  # No hay pestana = no hay envios, no es error

        all_values = ws.get_all_values()
        log.info(f"📊 Envios sheet: {len(all_values)} filas totales")

        if len(all_values) <= 1:
            return ([], None)  # Solo headers, sin datos

        h_idx = 0
        for i, row in enumerate(all_values):
            if "Fecha" in row and "Origen" in row:
                h_idx = i
                break
        headers = all_values[h_idx]
        log.info(f"Headers encontrados en fila {h_idx}: {headers}")

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

            # FIX: Matching mas robusto para Estado
            es_enviado = "enviado" in estado.lower() and "recibido" not in estado.lower() and "diferencia" not in estado.lower() and "congelado" not in estado.lower()

            # FIX: Matching de destino mas flexible
            destino_match = False
            if destino and local_destino:
                if local_destino.lower() in destino.lower() or destino.lower() in local_destino.lower():
                    destino_match = True
                elif local_corto(local_destino).lower() in destino.lower():
                    destino_match = True

            log.info(f"  Fila {i}: estado='{estado}' es_enviado={es_enviado}, destino='{destino}' match={destino_match}")

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

        log.info(f"📥 Pendientes para '{local_destino}': {len(pendientes)}")
        return (pendientes, None)
    except Exception as e:
        log.error(f"❌ Error obteniendo envios pendientes: {e}")
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
    except Exception as e:
        log.error(f"Error calculando tiempo envio: {e}")
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

        log.info(f"✅ Envio fila {fila} marcado como {estado} — Tiempo: {tiempo}")
    except Exception as e:
        log.error(f"❌ Error marcando recibido: {e}")


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
            log.info(f"✅ Pestana '{tab_name}' creada en Stock Sheet")
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
    """Parse a value to float safely."""
    if not val:
        return default
    try:
        return float(str(val).replace(",", ".").strip())
    except (ValueError, TypeError):
        return default


def _safe_int(val, default=0):
    """Parse a value to int safely."""
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
        log.error(f"❌ Error leyendo Productos stock: {e}")
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
        log.error(f"❌ Error leyendo Stock Actual: {e}")
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

        # Find existing row
        target_row = None
        for i, row in enumerate(vals[1:], start=2):
            if len(row) > 0 and row[0].strip().lower() == producto.lower():
                target_row = i
                break

        # Build row values
        row_data = [""] * len(headers)
        row_data[0] = producto
        if "Categoria" in headers:
            row_data[headers.index("Categoria")] = categoria

        # If row exists, read current values first
        if target_row:
            existing = vals[target_row - 1]  # vals is 0-indexed, rows are 1-indexed
            for j in range(len(existing)):
                if j < len(row_data):
                    row_data[j] = existing[j]

        # Apply updates
        for key, val in updates.items():
            # key is like "LH2_congelado" -> header "LH2 Congelado"
            parts = key.split("_")
            if len(parts) == 2:
                header_name = f"{parts[0]} {parts[1].capitalize()}"
                if header_name in headers:
                    row_data[headers.index(header_name)] = str(val)

        # Update timestamp
        if "Ultima Actualizacion" in headers:
            row_data[headers.index("Ultima Actualizacion")] = ahora

        if target_row:
            # Update existing row — use range update for efficiency
            cell_range = f"A{target_row}:{chr(64 + len(headers))}{target_row}"
            ws.update(cell_range, [row_data])
        else:
            ws.append_row(row_data, value_input_option="RAW")

        log.info(f"✅ Stock actualizado: {producto} — {updates}")
    except Exception as e:
        log.error(f"❌ Error actualizando stock: {e}")
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
        log.info(f"✅ Movimiento registrado: {tipo} {cantidad}x {producto} en {local}")
    except Exception as e:
        log.error(f"❌ Error registrando movimiento: {e}")
        raise


def _local_key_from_name(local_name: str) -> str:
    """Extract LH2/LH3/LH4/LH5 from a local name string."""
    local_upper = local_name.upper()
    for lk in LOCAL_KEYS:
        if lk in local_upper:
            return lk
    # Fallback: try to match by address
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
        productos, _ = cargar_productos()
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

    # Read current stock
    current = stock_read_actual(sh)
    prod_stock = current.get(producto, {})
    cong = prod_stock.get(f"{lk}_congelado", 0)
    horn = prod_stock.get(f"{lk}_horneado", 0)

    estado_origen = ""
    estado_destino = ""
    updates = {}

    if tipo == TIPO_ENVIO_RECIBIDO:
        # Received shipment -> adds to congelado
        updates[f"{lk}_congelado"] = cong + cantidad
        estado_destino = "congelado"

    elif tipo == TIPO_FERMENTO:
        # Took out to ferment -> removes from congelado
        new_cong = max(0, cong - cantidad)
        updates[f"{lk}_congelado"] = new_cong
        estado_origen = "congelado"

    elif tipo == TIPO_HORNEO:
        # Baked -> adds to horneado
        updates[f"{lk}_horneado"] = horn + cantidad
        estado_destino = "horneado"

    elif tipo == TIPO_MERMA:
        # Waste/discard -> removes from horneado
        new_horn = max(0, horn - cantidad)
        updates[f"{lk}_horneado"] = new_horn
        estado_origen = "horneado"

    elif tipo == TIPO_AJUSTE:
        # Manual adjustment -> set exact values
        # For ajuste, `cantidad` is the new value.
        # The observaciones field tells which state (congelado/horneado)
        if "horneado" in observaciones.lower():
            updates[f"{lk}_horneado"] = cantidad
            estado_destino = "horneado"
        else:
            updates[f"{lk}_congelado"] = cantidad
            estado_destino = "congelado"

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
    Called from the recibir flow.
    """
    lk = _local_key_from_name(local_destino)
    if not lk:
        log.warning(f"⚠️ No se pudo mapear local para stock: {local_destino}")
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
                log.warning(f"⚠️ Error actualizando stock para {prod}: {msg}")
            _time.sleep(1)  # Rate limit
        except Exception as e:
            log.error(f"❌ Error en stock_apply_envio_recibido para {prod}: {e}")


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
        log.error(f"❌ Error checking stock alerts: {e}")
        return []


async def _send_stock_alerts(context, alerts: list):
    """Send stock alert notifications to NOTIFY_IDS."""
    if not alerts:
        return
    # Group by local
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


def _parsear_carga_manual(texto: str) -> list:
    """
    Parsea texto libre de carga manual.
    Acepta formatos como:
      10 medialunas, 5 brownies
      medialunas 10
      10 x medialunas
      medialunas: 10
      - 10 medialunas
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
        lines.append(f"  {j + 1}\\. *{esc(p)}*: {cant} {u}")
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
        f"_Toca para editar cualquier dato._"
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
        try:
            ws = sh.worksheet("Productos Envío")
        except:
            return
        ws.append_row([categoria, nombre, unidad])
        log.info(f"✅ Nuevo producto agregado al catalogo: {nombre} ({categoria})")
    except Exception as e:
        log.error(f"❌ Error agregando producto: {e}")


# ── STOCK VIEW HELPERS ────────────────────────────────────────────────────────

def _format_stock_for_local(lk: str, stock: dict, mins: dict) -> str:
    """Format stock summary for a single local. Returns markdown string."""
    # Group products by category
    productos, _ = cargar_productos()

    # Build category -> products mapping
    cat_prods = {}
    for cat, prods in productos.items():
        for p in prods:
            if p in stock:
                cat_prods.setdefault(cat, []).append(p)

    # Also add products in stock not in catalog
    cataloged = set()
    for prods in productos.values():
        cataloged.update(prods)
    for p in stock:
        if p not in cataloged:
            cat_prods.setdefault("Sin Categoria", []).append(p)

    if not cat_prods:
        return f"📍 *{lk}*\n_Sin stock registrado_"

    lines = [f"📍 *{lk}*\n"]
    total_alerts = 0

    for cat in sorted(cat_prods.keys()):
        cat_lines = []
        for prod in sorted(cat_prods[cat]):
            s = stock.get(prod, {})
            cong = s.get(f"{lk}_congelado", 0)
            horn = s.get(f"{lk}_horneado", 0)
            total = cong + horn
            if total == 0 and cong == 0 and horn == 0:
                continue  # Skip products with zero stock

            minimum = mins.get(prod, {}).get(lk, 0)
            alert = ""
            if minimum > 0 and total < minimum:
                alert = " ⚠️"
                total_alerts += 1

            cat_lines.append(f"  {esc(prod)}: 🧊{cong} 🔥{horn}{alert}")

        if cat_lines:
            lines.append(f"🏷️ *{esc(cat)}*")
            lines.extend(cat_lines)
            lines.append("")

    if total_alerts > 0:
        lines.insert(1, f"🔴 {total_alerts} producto(s) bajo minimo\n")

    return "\n".join(lines)


def _format_sugerencia_pedido(lk: str, stock: dict, mins: dict) -> str:
    """Format order suggestion for CDP."""
    lines = []
    for prod, min_by_local in sorted(mins.items()):
        minimum = min_by_local.get(lk, 0)
        if minimum <= 0:
            continue
        s = stock.get(prod, {})
        total = s.get(f"{lk}_congelado", 0) + s.get(f"{lk}_horneado", 0)
        deficit = minimum - total
        if deficit > 0:
            lines.append(f"  📦 {esc(prod)}: pedir *{deficit}* (tiene {total}, min {minimum})")

    if not lines:
        return f"📍 *{lk}* — ✅ Stock OK, no necesita pedido"

    header = f"📍 *{lk}* — Pedido sugerido a CDP:\n"
    return header + "\n".join(lines)


def _format_sugerencia_fermentacion(lk: str, stock: dict, mins: dict) -> str:
    """Format fermentation suggestion."""
    lines = []
    for prod, min_by_local in sorted(mins.items()):
        minimum = min_by_local.get(lk, 0)
        if minimum <= 0:
            continue
        s = stock.get(prod, {})
        horn = s.get(f"{lk}_horneado", 0)
        cong = s.get(f"{lk}_congelado", 0)
        # If horneado < half of minimum, suggest fermenting
        threshold = minimum // 2
        if horn < threshold and cong > 0:
            to_ferment = min(minimum - horn, cong)  # Don't suggest more than available
            if to_ferment > 0:
                lines.append(f"  🧊→🔥 {esc(prod)}: fermentar *{to_ferment}* (horneado: {horn}, congelado: {cong})")

    if not lines:
        return f"📍 *{lk}* — ✅ Horneado OK, no necesita fermentacion"

    header = f"📍 *{lk}* — Sugerencia de fermentacion:\n"
    return header + "\n".join(lines)


def _format_reporte_global(stock: dict, mins: dict) -> str:
    """Format global stock report for managers."""
    lines = ["📊 *REPORTE DE STOCK*\n"]
    lines.append(f"📅 {datetime.now(TZ_AR).strftime('%d/%m/%Y %H:%M')}\n")

    total_alerts = 0
    total_excess = 0

    for lk in LOCAL_KEYS:
        lk_alerts = []
        lk_excess = []
        lk_total_items = 0

        for prod, min_by_local in sorted(mins.items()):
            minimum = min_by_local.get(lk, 0)
            if minimum <= 0:
                continue
            s = stock.get(prod, {})
            cong = s.get(f"{lk}_congelado", 0)
            horn = s.get(f"{lk}_horneado", 0)
            total = cong + horn
            if total > 0:
                lk_total_items += 1
            if total < minimum:
                lk_alerts.append(f"    🔴 {esc(prod)}: {total}/{minimum}")
                total_alerts += 1
            elif total > minimum * 2:
                lk_excess.append(f"    🟡 {esc(prod)}: {total} (min {minimum})")
                total_excess += 1

        lines.append(f"📍 *{lk}* ({lk_total_items} items con stock)")
        if lk_alerts:
            lines.append(f"  ⚠️ Bajo minimo ({len(lk_alerts)}):")
            lines.extend(lk_alerts[:10])  # Limit to avoid message too long
            if len(lk_alerts) > 10:
                lines.append(f"    _...y {len(lk_alerts) - 10} mas_")
        if lk_excess:
            lines.append(f"  📦 Exceso >2x ({len(lk_excess)}):")
            lines.extend(lk_excess[:5])
            if len(lk_excess) > 5:
                lines.append(f"    _...y {len(lk_excess) - 5} mas_")
        if not lk_alerts and not lk_excess:
            lines.append("  ✅ Todo OK")
        lines.append("")

    # Summary
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"🔴 Total bajo minimo: *{total_alerts}*")
    lines.append(f"🟡 Total exceso: *{total_excess}*")

    # Today's movements count
    try:
        sh = get_stock_sheet()
        if sh:
            ws = _get_or_create_stock_ws(sh, "Movimientos", MOVIMIENTOS_HEADERS, rows=5000)
            vals = ws.get_all_values()
            hoy = datetime.now(TZ_AR).strftime("%d/%m/%Y")
            today_count = sum(1 for row in vals[1:] if row and row[0].startswith(hoy))
            lines.append(f"📝 Movimientos hoy: *{today_count}*")
    except:
        pass

    return "\n".join(lines)


# ── HANDLERS ──────────────────────────────────────────────────────────────────

def _main_menu_keyboard():
    """Returns the main menu inline keyboard."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 Nuevo envio", callback_data="menu_envio")],
        [InlineKeyboardButton("📥 Recibir envio", callback_data="menu_recibir")],
        [InlineKeyboardButton("📊 Ver stock", callback_data="menu_stock")],
        [InlineKeyboardButton("📝 Cargar stock", callback_data="menu_cargar")],
        [InlineKeyboardButton("💡 Sugerencias", callback_data="menu_sugerencia")],
        [InlineKeyboardButton("📋 Reporte", callback_data="menu_reporte")],
    ])


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🥐 *Lharmonie — Envios y Stock*\n\n"
        "Gestiona envios y stock entre locales.\n\n"
        "¿Que queres hacer?",
        reply_markup=_main_menu_keyboard(),
        parse_mode="Markdown"
    )


async def cmd_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shortcut command /stock"""
    estado_usuario[update.effective_chat.id] = {"paso": "stock_eligiendo_local"}
    keyboard = [[InlineKeyboardButton(local_corto(l), callback_data=f"stock_local_{i}")] for i, l in enumerate(LOCALES_RETAIL)]
    keyboard.append([InlineKeyboardButton("📊 Todos", callback_data="stock_local_all")])
    keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
    await update.message.reply_text(
        "📊 *Ver stock*\n\n¿De que local?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def cmd_cargar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shortcut command /cargar"""
    estado_usuario[update.effective_chat.id] = {"paso": "cargar_eligiendo_local"}
    keyboard = [[InlineKeyboardButton(local_corto(l), callback_data=f"cargar_local_{i}")] for i, l in enumerate(LOCALES_RETAIL)]
    keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
    await update.message.reply_text(
        "📝 *Cargar movimiento de stock*\n\n¿En que local?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def cmd_sugerencia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shortcut command /sugerencia"""
    estado_usuario[update.effective_chat.id] = {"paso": "sug_eligiendo_local"}
    keyboard = [[InlineKeyboardButton(local_corto(l), callback_data=f"sug_local_{i}")] for i, l in enumerate(LOCALES_RETAIL)]
    keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
    await update.message.reply_text(
        "💡 *Sugerencias*\n\n¿Para que local?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def cmd_reporte(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shortcut command /reporte"""
    chat_id = update.effective_chat.id
    await update.message.reply_text("📋 Generando reporte...")
    try:
        sh = get_stock_sheet()
        if not sh:
            await update.message.reply_text("❌ No se pudo conectar a Google Sheets. Verifica ENVIOS_SHEETS_ID.")
            return
        _ensure_stock_tabs(sh)
        stock = stock_read_actual(sh)
        mins = stock_get_minimums(sh)
        msg = _format_reporte_global(stock, mins)
        # Split if too long
        if len(msg) > 4000:
            parts = msg.split("\n\n")
            current = ""
            for part in parts:
                if len(current) + len(part) > 3800:
                    await update.message.reply_text(current, parse_mode="Markdown")
                    current = part
                else:
                    current += "\n\n" + part if current else part
            if current:
                await update.message.reply_text(current, parse_mode="Markdown")
        else:
            await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        log.error(f"❌ Error en reporte: {e}")
        await update.message.reply_text(f"❌ Error generando reporte: {esc(str(e))}", parse_mode="Markdown")


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    data = query.data

    # ── MENU PRINCIPAL ─────────────────────────────────────────────────
    if data == "menu_envio":
        estado_usuario[chat_id] = {"paso": "eligiendo_origen", "productos_lista": [], "cantidades_lista": [], "tipos_lista": [], "unidades_lista": []}
        keyboard = [[InlineKeyboardButton(local_corto(l), callback_data=f"origen_{i}")] for i, l in enumerate(LOCALES)]
        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
        await query.edit_message_text("📍 *¿De donde sale el envio?*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return

    if data == "menu_recibir":
        estado_usuario[chat_id] = {"paso": "eligiendo_local_recibir"}
        keyboard = [[InlineKeyboardButton(local_corto(l), callback_data=f"recibir_local_{i}")] for i, l in enumerate(LOCALES)]
        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
        await query.edit_message_text("📍 *¿En que local estas?*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return

    if data == "menu_stock":
        estado_usuario[chat_id] = {"paso": "stock_eligiendo_local"}
        keyboard = [[InlineKeyboardButton(local_corto(l), callback_data=f"stock_local_{i}")] for i, l in enumerate(LOCALES_RETAIL)]
        keyboard.append([InlineKeyboardButton("📊 Todos", callback_data="stock_local_all")])
        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
        await query.edit_message_text("📊 *Ver stock*\n\n¿De que local?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return

    if data == "menu_cargar":
        estado_usuario[chat_id] = {"paso": "cargar_eligiendo_local"}
        keyboard = [[InlineKeyboardButton(local_corto(l), callback_data=f"cargar_local_{i}")] for i, l in enumerate(LOCALES_RETAIL)]
        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
        await query.edit_message_text("📝 *Cargar movimiento de stock*\n\n¿En que local?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return

    if data == "menu_sugerencia":
        estado_usuario[chat_id] = {"paso": "sug_eligiendo_local"}
        keyboard = [[InlineKeyboardButton(local_corto(l), callback_data=f"sug_local_{i}")] for i, l in enumerate(LOCALES_RETAIL)]
        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
        await query.edit_message_text("💡 *Sugerencias*\n\n¿Para que local?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return

    if data == "menu_reporte":
        await query.edit_message_text("📋 Generando reporte...")
        try:
            sh = get_stock_sheet()
            if not sh:
                await query.edit_message_text("❌ No se pudo conectar a la Stock Sheet.")
                estado_usuario.pop(chat_id, None)
                return
            _ensure_stock_tabs(sh)
            stock = stock_read_actual(sh)
            mins = stock_get_minimums(sh)
            msg = _format_reporte_global(stock, mins)
            if len(msg) > 4000:
                await query.edit_message_text(msg[:4000] + "\n\n_...truncado_", parse_mode="Markdown")
            else:
                await query.edit_message_text(msg, parse_mode="Markdown")
        except Exception as e:
            log.error(f"❌ Error en reporte: {e}")
            await query.edit_message_text(f"❌ Error: {esc(str(e))}", parse_mode="Markdown")
        estado_usuario.pop(chat_id, None)
        return

    if data == "menu_principal":
        estado_usuario.pop(chat_id, None)
        await query.edit_message_text(
            "🥐 *Lharmonie — Envios y Stock*\n\n¿Que queres hacer?",
            reply_markup=_main_menu_keyboard(),
            parse_mode="Markdown"
        )
        return

    if data == "cancelar":
        estado_usuario.pop(chat_id, None)
        await query.edit_message_text("Cancelado\\. Usa /start para volver al menu.", parse_mode="Markdown")
        return

    # ── FLUJO STOCK: VER ──────────────────────────────────────────────
    if data.startswith("stock_local_"):
        try:
            sh = get_stock_sheet()
            if not sh:
                await query.edit_message_text("❌ No se pudo conectar a la Stock Sheet.")
                estado_usuario.pop(chat_id, None)
                return
            _ensure_stock_tabs(sh)
            stock = stock_read_actual(sh)
            mins = stock_get_minimums(sh)

            if data == "stock_local_all":
                parts = []
                for lk in LOCAL_KEYS:
                    parts.append(_format_stock_for_local(lk, stock, mins))
                msg = "\n\n".join(parts)
            else:
                idx = int(data.split("_")[2])
                local = LOCALES_RETAIL[idx]
                lk = _local_key_from_name(local)
                msg = _format_stock_for_local(lk, stock, mins)

            keyboard = [[InlineKeyboardButton("🔄 Actualizar", callback_data=data)],
                         [InlineKeyboardButton("⬅️ Menu", callback_data="menu_principal")]]
            if len(msg) > 4000:
                await query.edit_message_text(msg[:4000] + "\n\n_...truncado_", parse_mode="Markdown")
            else:
                await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        except Exception as e:
            log.error(f"❌ Error viendo stock: {e}")
            await query.edit_message_text(f"❌ Error: {esc(str(e))}", parse_mode="Markdown")
        estado_usuario.pop(chat_id, None)
        return

    # ── FLUJO STOCK: CARGAR ───────────────────────────────────────────
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
            f"📍 *{local_corto(local)}*\n\n¿En que zona estas?",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return

    if data.startswith("cargar_zona_"):
        idx = int(data.split("_")[2])
        info = estado_usuario.get(chat_id, {})
        info["cargar_zona"] = ZONAS[idx]
        info["paso"] = "cargar_eligiendo_tipo"
        estado_usuario[chat_id] = info
        keyboard = [
            [InlineKeyboardButton("🧊 Saco a fermentar", callback_data="cargar_tipo_fermento")],
            [InlineKeyboardButton("🔥 Horneo", callback_data="cargar_tipo_horneo")],
            [InlineKeyboardButton("📦 Recibio envio", callback_data="cargar_tipo_envio")],
            [InlineKeyboardButton("🗑️ Merma/descarte", callback_data="cargar_tipo_merma")],
            [InlineKeyboardButton("📝 Ajuste manual", callback_data="cargar_tipo_ajuste")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")],
        ]
        await query.edit_message_text(
            f"📍 *{local_corto(info['cargar_local'])}* — {ZONAS_DISPLAY[idx]}\n\n"
            f"¿Que tipo de movimiento?",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return

    if data.startswith("cargar_tipo_"):
        tipo_raw = data.replace("cargar_tipo_", "")
        tipo_map = {
            "fermento": TIPO_FERMENTO,
            "horneo": TIPO_HORNEO,
            "envio": TIPO_ENVIO_RECIBIDO,
            "merma": TIPO_MERMA,
            "ajuste": TIPO_AJUSTE,
        }
        tipo = tipo_map.get(tipo_raw, tipo_raw)
        info = estado_usuario.get(chat_id, {})
        info["cargar_tipo"] = tipo
        info["paso"] = "cargar_eligiendo_cat"
        estado_usuario[chat_id] = info

        # Show categories for product selection
        productos, _ = cargar_productos()
        categorias = list(productos.keys())
        keyboard = [[InlineKeyboardButton(f"🏷️ {cat}", callback_data=f"cargar_cat_{cat}")] for cat in categorias]
        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])

        tipo_labels = {
            TIPO_FERMENTO: "🧊 Saco a fermentar",
            TIPO_HORNEO: "🔥 Horneo",
            TIPO_ENVIO_RECIBIDO: "📦 Recibio envio",
            TIPO_MERMA: "🗑️ Merma/descarte",
            TIPO_AJUSTE: "📝 Ajuste manual",
        }
        await query.edit_message_text(
            f"📍 *{local_corto(info['cargar_local'])}*\n"
            f"Tipo: {tipo_labels.get(tipo, tipo)}\n\n"
            f"Elegi la categoria del producto:",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return

    if data.startswith("cargar_cat_"):
        cat = data[len("cargar_cat_"):]
        info = estado_usuario.get(chat_id, {})
        info["cargar_categoria"] = cat
        info["paso"] = "cargar_eligiendo_prod"
        productos, unidades = cargar_productos()
        prods = productos.get(cat, [])
        keyboard = []
        for i in range(0, len(prods), 2):
            row = [InlineKeyboardButton(prods[i], callback_data=f"cargar_prod_{i}")]
            if i + 1 < len(prods):
                row.append(InlineKeyboardButton(prods[i + 1], callback_data=f"cargar_prod_{i + 1}"))
            keyboard.append(row)
        keyboard.append([InlineKeyboardButton("⬅️ Volver a categorias", callback_data="cargar_volver_cats")])
        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
        info["_cargar_prods_cache"] = prods
        estado_usuario[chat_id] = info
        await query.edit_message_text(
            f"🏷️ *{cat}*\n\nElegi el producto:",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return

    if data == "cargar_volver_cats":
        info = estado_usuario.get(chat_id, {})
        info["paso"] = "cargar_eligiendo_cat"
        productos, _ = cargar_productos()
        categorias = list(productos.keys())
        keyboard = [[InlineKeyboardButton(f"🏷️ {cat}", callback_data=f"cargar_cat_{cat}")] for cat in categorias]
        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
        await query.edit_message_text(
            "Elegi la categoria del producto:",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return

    if data.startswith("cargar_prod_"):
        idx = int(data.split("_")[2])
        info = estado_usuario.get(chat_id, {})
        prods = info.get("_cargar_prods_cache", [])
        if idx < len(prods):
            info["cargar_producto"] = prods[idx]

            if info.get("cargar_tipo") == TIPO_AJUSTE:
                # For ajuste, ask which state to adjust
                info["paso"] = "cargar_ajuste_estado"
                keyboard = [
                    [InlineKeyboardButton("🧊 Congelado", callback_data="cargar_ajuste_congelado")],
                    [InlineKeyboardButton("🔥 Horneado", callback_data="cargar_ajuste_horneado")],
                    [InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")],
                ]
                await query.edit_message_text(
                    f"📝 *Ajuste manual: {esc(prods[idx])}*\n\n"
                    f"¿Que estado vas a ajustar?",
                    reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
                )
            else:
                info["paso"] = "cargar_esperando_cantidad"
                await query.edit_message_text(
                    f"📦 *{esc(prods[idx])}*\n\n"
                    f"Escribi la cantidad:",
                    parse_mode="Markdown"
                )
        estado_usuario[chat_id] = info
        return

    if data.startswith("cargar_ajuste_"):
        estado_val = data.replace("cargar_ajuste_", "")
        info = estado_usuario.get(chat_id, {})
        info["cargar_ajuste_tipo"] = estado_val  # "congelado" or "horneado"
        info["paso"] = "cargar_esperando_cantidad"
        estado_usuario[chat_id] = info

        # Show current value
        try:
            sh = get_stock_sheet()
            if sh:
                stock = stock_read_actual(sh)
                lk = info.get("cargar_lk", "")
                prod = info.get("cargar_producto", "")
                current = stock.get(prod, {}).get(f"{lk}_{estado_val}", 0)
                await query.edit_message_text(
                    f"📝 *Ajuste {estado_val}: {esc(prod)}*\n"
                    f"Valor actual: *{current}*\n\n"
                    f"Escribi el nuevo valor exacto:",
                    parse_mode="Markdown"
                )
            else:
                await query.edit_message_text(
                    f"📝 *Ajuste {estado_val}: {esc(info.get('cargar_producto', ''))}*\n\n"
                    f"Escribi el nuevo valor exacto:",
                    parse_mode="Markdown"
                )
        except:
            await query.edit_message_text(
                f"📝 *Ajuste {estado_val}*\n\nEscribi el nuevo valor exacto:",
                parse_mode="Markdown"
            )
        return

    if data == "cargar_confirmar":
        info = estado_usuario.get(chat_id, {})
        local = info.get("cargar_local", "")
        zona = info.get("cargar_zona", "")
        producto = info.get("cargar_producto", "")
        tipo = info.get("cargar_tipo", "")
        cantidad = info.get("cargar_cantidad", 0)
        responsable = info.get("cargar_responsable", "")

        await query.edit_message_text("⏳ Guardando...")

        try:
            sh = get_stock_sheet()
            if not sh:
                await query.edit_message_text("❌ No se pudo conectar a la Stock Sheet.")
                estado_usuario.pop(chat_id, None)
                return
            _ensure_stock_tabs(sh)

            obs = ""
            if tipo == TIPO_AJUSTE:
                obs = f"ajuste {info.get('cargar_ajuste_tipo', 'congelado')}"

            ok, msg = stock_apply_movement(
                sh, local, producto, tipo, cantidad,
                zona=zona, responsable=responsable,
                chat_id=chat_id, observaciones=obs
            )

            if ok:
                tipo_labels = {
                    TIPO_FERMENTO: "🧊 Saco a fermentar",
                    TIPO_HORNEO: "🔥 Horneo",
                    TIPO_ENVIO_RECIBIDO: "📦 Envio recibido",
                    TIPO_MERMA: "🗑️ Merma",
                    TIPO_AJUSTE: "📝 Ajuste",
                }
                emoji = "✅"
                text = (
                    f"{emoji} *Movimiento registrado*\n\n"
                    f"📍 {local_corto(local)} — {zona}\n"
                    f"📦 {esc(producto)}: {cantidad}\n"
                    f"📝 {tipo_labels.get(tipo, tipo)}\n"
                    f"👤 {esc(responsable)}"
                )
                keyboard = [
                    [InlineKeyboardButton("📝 Otro movimiento", callback_data="menu_cargar")],
                    [InlineKeyboardButton("⬅️ Menu", callback_data="menu_principal")],
                ]
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

                # Check for stock alerts after movement
                try:
                    alerts = stock_check_alerts(sh)
                    lk = _local_key_from_name(local)
                    local_alerts = [(a_lk, p, c, m) for a_lk, p, c, m in alerts if a_lk == lk]
                    if local_alerts:
                        await _send_stock_alerts(context, local_alerts)
                except Exception as ae:
                    log.error(f"⚠️ Error checking alerts: {ae}")
            else:
                await query.edit_message_text(f"❌ Error: {esc(msg)}", parse_mode="Markdown")

        except Exception as e:
            log.error(f"❌ Error en cargar stock: {e}")
            await query.edit_message_text(f"❌ Error: {esc(str(e))}", parse_mode="Markdown")

        estado_usuario.pop(chat_id, None)
        return

    if data == "cargar_cancelar":
        estado_usuario.pop(chat_id, None)
        await query.edit_message_text("Cancelado\\.", parse_mode="Markdown")
        return

    # ── FLUJO SUGERENCIAS ─────────────────────────────────────────────
    if data.startswith("sug_local_"):
        idx = int(data.split("_")[2])
        local = LOCALES_RETAIL[idx]
        lk = _local_key_from_name(local)

        await query.edit_message_text("⏳ Calculando sugerencias...")

        try:
            sh = get_stock_sheet()
            if not sh:
                await query.edit_message_text("❌ No se pudo conectar a la Stock Sheet.")
                estado_usuario.pop(chat_id, None)
                return
            _ensure_stock_tabs(sh)
            stock = stock_read_actual(sh)
            mins = stock_get_minimums(sh)

            pedido = _format_sugerencia_pedido(lk, stock, mins)
            fermentacion = _format_sugerencia_fermentacion(lk, stock, mins)

            msg = (
                f"💡 *Sugerencias para {local_corto(local)}*\n\n"
                f"━━━ PEDIDO A CDP ━━━\n{pedido}\n\n"
                f"━━━ FERMENTACION ━━━\n{fermentacion}"
            )

            keyboard = [
                [InlineKeyboardButton("🔄 Actualizar", callback_data=data)],
                [InlineKeyboardButton("⬅️ Menu", callback_data="menu_principal")],
            ]
            if len(msg) > 4000:
                await query.edit_message_text(msg[:4000] + "\n\n_...truncado_", parse_mode="Markdown")
            else:
                await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        except Exception as e:
            log.error(f"❌ Error en sugerencias: {e}")
            await query.edit_message_text(f"❌ Error: {esc(str(e))}", parse_mode="Markdown")
        estado_usuario.pop(chat_id, None)
        return

    # ── FLUJO ENVIO ────────────────────────────────────────────────────
    info = estado_usuario.get(chat_id)
    if info is None:
        # Bot restarted, lost state
        await query.edit_message_text(
            "⚠️ Se perdio la sesion (el bot se reinicio).\n\n¿Que queres hacer?",
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
            f"📍 Origen: *{local_corto(info['origen'])}*\n\n¿A donde va el envio?",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return

    if data.startswith("destino_"):
        idx = int(data.split("_")[1])
        info["destino"] = LOCALES[idx]
        info["paso"] = "esperando_nombre"
        await query.edit_message_text(
            f"📦 *{local_corto(info['origen'])}* → *{local_corto(info['destino'])}*\n\n👤 Escribi tu nombre:",
            parse_mode="Markdown"
        )
        return

    # Elegir categoria
    if data.startswith("cat_"):
        cat = data[4:]
        info["categoria_actual"] = cat
        productos, unidades = cargar_productos()
        info["_unidades_cache"] = unidades
        prods = productos.get(cat, [])
        keyboard = []
        for i in range(0, len(prods), 2):
            row = [InlineKeyboardButton(prods[i], callback_data=f"prod_{i}")]
            if i + 1 < len(prods):
                row.append(InlineKeyboardButton(prods[i + 1], callback_data=f"prod_{i + 1}"))
            keyboard.append(row)
        keyboard.append([InlineKeyboardButton("⬅️ Volver a categorias", callback_data="volver_categorias")])
        keyboard.append([InlineKeyboardButton("✅ Terminar y enviar", callback_data="terminar_productos")])
        resumen = ""
        if info["productos_lista"]:
            lines = [f"  · {_fmt_prod_line(info, j)}" for j in range(len(info["productos_lista"]))]
            resumen = "\n\n📋 *Agregados:*\n" + "\n".join(lines)
        await query.edit_message_text(
            f"📦 *{local_corto(info['origen'])}* → *{local_corto(info['destino'])}*\n"
            f"🏷️ Categoria: *{cat}*\n\n"
            f"Elegi un producto:{resumen}",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return

    if data == "volver_categorias":
        productos, _ = cargar_productos()
        categorias = list(productos.keys())
        keyboard = [[InlineKeyboardButton(f"🏷️ {cat}", callback_data=f"cat_{cat}")] for cat in categorias]
        keyboard.append([InlineKeyboardButton("✏️ Carga manual", callback_data="carga_manual")])
        if info.get("productos_lista"):
            keyboard.append([InlineKeyboardButton(f"✅ Terminar y enviar ({len(info['productos_lista'])} productos)", callback_data="terminar_productos")])
        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
        resumen = ""
        if info["productos_lista"]:
            lines = [f"  · {_fmt_prod_line(info, j)}" for j in range(len(info["productos_lista"]))]
            resumen = "\n\n📋 *Agregados:*\n" + "\n".join(lines)
        await query.edit_message_text(
            f"📦 *{local_corto(info['origen'])}* → *{local_corto(info['destino'])}*\n\n"
            f"Elegi una categoria:{resumen}",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return

    if data == "carga_manual":
        info["paso"] = "esperando_carga_manual"
        await query.edit_message_text(
            "✏️ *Carga manual*\n\n"
            "Escribi los productos con cantidades, separados por coma o en lineas distintas.\n\n"
            "*Ejemplos:*\n"
            "  `10 medialunas, 5 brownies, 3 pan brioche`\n"
            "  `medialunas 10, croissants 5`\n"
            "  `10 x alfajores, 20 x cookies`\n\n"
            "Si el producto no existe en el catalogo, se agrega automaticamente.",
            parse_mode="Markdown"
        )
        return

    if data.startswith("prod_"):
        idx = int(data.split("_")[1])
        productos, unidades = cargar_productos()
        cat = info.get("categoria_actual", "")
        prods = productos.get(cat, [])
        if idx < len(prods):
            info["producto_actual"] = prods[idx]
            info["unidad_actual"] = unidades.get(prods[idx], "u")
            info["paso"] = "esperando_cantidad"
            u = info["unidad_actual"]
            hint = {"u": "unidades", "kg": "kg", "g": "gramos", "lt": "litros"}.get(u, u)
            await query.edit_message_text(
                f"📦 *{info['producto_actual']}*  ({hint})\n\n"
                f"Escribi la cantidad:",
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
                f"✏️ *Editando:* {esc(prod)}: {cant} {u}\n\n"
                f"¿Que queres corregir?",
                reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
            )
        return

    # Sub-edicion: cantidad
    if data.startswith("editcant_"):
        idx = int(data.split("_")[1])
        info["editando_idx"] = idx
        info["paso"] = "editando_cantidad"
        prod = info["productos_lista"][idx]
        u = info["unidades_lista"][idx] if idx < len(info.get("unidades_lista", [])) else "u"
        await query.edit_message_text(
            f"🔢 *{esc(prod)}* — Actual: *{info['cantidades_lista'][idx]} {u}*\n\n"
            f"Escribi la nueva cantidad:",
            parse_mode="Markdown"
        )
        return

    # Sub-edicion: unidad
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
            f"📏 *{esc(prod)}* — Unidad actual: *{u_actual}*\n\nElegi la unidad correcta:",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return

    # Setear unidad
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

    # Sub-edicion: nombre del producto
    if data.startswith("editname_"):
        idx = int(data.split("_")[1])
        info["editando_idx"] = idx
        info["paso"] = "editando_nombre_prod"
        prod = info["productos_lista"][idx]
        await query.edit_message_text(
            f"📦 Producto actual: *{esc(prod)}*\n\n"
            f"Escribi el nombre correcto:",
            parse_mode="Markdown"
        )
        return

    # Volver al resumen desde sub-edicion
    if data == "volver_resumen":
        info["paso"] = "resumen_editable"
        await _mostrar_resumen_editable(query, info)
        return

    # Editar destino
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
            f"📍 Destino actual: *{local_corto(info['destino'])}*\n\n¿Cual es el destino correcto?",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return

    # Setear nuevo destino
    if data.startswith("newdest_"):
        idx = int(data.split("_")[1])
        info["destino"] = LOCALES[idx]
        await query.answer(f"Destino: {local_corto(LOCALES[idx])}")
        info["paso"] = "resumen_editable"
        await _mostrar_resumen_editable(query, info)
        return

    # Editar responsable
    if data == "edit_responsable":
        info["paso"] = "editando_responsable"
        await query.edit_message_text(
            f"👤 Responsable actual: *{esc(info.get('responsable', ''))}*\n\n"
            f"Escribi el nombre correcto:",
            parse_mode="Markdown"
        )
        return

    # Eliminar un producto del resumen
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
                info["paso"] = "eligiendo_categoria"
                productos, _ = cargar_productos()
                categorias = list(productos.keys())
                keyboard = [[InlineKeyboardButton(f"🏷️ {cat}", callback_data=f"cat_{cat}")] for cat in categorias]
                keyboard.append([InlineKeyboardButton("✏️ Carga manual", callback_data="carga_manual")])
                keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
                await query.edit_message_text(
                    "Se eliminaron todos los productos.\n\nElegi una categoria para agregar:",
                    reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
                )
                return
            await _mostrar_resumen_editable(query, info)
        return

    # Confirmar resumen -> preguntar bultos
    if data == "resumen_ok":
        info["paso"] = "esperando_bultos_total"
        lines = [f"  · {_fmt_prod_line(info, j)}" for j in range(len(info["productos_lista"]))]
        resumen = "\n".join(lines)
        await query.edit_message_text(
            f"📦 *{local_corto(info['origen'])}* → *{local_corto(info['destino'])}*\n\n"
            f"📋 *Productos:*\n{resumen}\n\n"
            f"📦 ¿Cuantos bultos son en total?",
            parse_mode="Markdown"
        )
        return

    # Agregar mas productos desde el resumen
    if data == "resumen_agregar_mas":
        info["paso"] = "eligiendo_categoria"
        productos, _ = cargar_productos()
        categorias = list(productos.keys())
        keyboard = [[InlineKeyboardButton(f"🏷️ {cat}", callback_data=f"cat_{cat}")] for cat in categorias]
        keyboard.append([InlineKeyboardButton("✏️ Carga manual", callback_data="carga_manual")])
        keyboard.append([InlineKeyboardButton(f"✅ Terminar y enviar ({len(info['productos_lista'])} productos)", callback_data="terminar_productos")])
        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
        lines = [f"  · {_fmt_prod_line(info, j)}" for j in range(len(info["productos_lista"]))]
        resumen = "\n".join(lines)
        await query.edit_message_text(
            f"📦 *{local_corto(info['origen'])}* → *{local_corto(info['destino'])}*\n\n"
            f"📋 *Productos actuales:*\n{resumen}\n\n"
            f"Elegi una categoria para agregar mas:",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
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
                f"❌ *No se pudo guardar el envio*\n\n{esc(error_msg or 'Error desconocido')}\n\n"
                f"Intenta de nuevo con /start",
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
            f"✅ *Envio registrado y guardado*\n\n"
            f"📍 {local_corto(info['origen'])} → {local_corto(info['destino'])}\n"
            f"📋 {len(info['productos_lista'])} productos\n"
            f"🚗 {info['transporte']}",
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
                f"❌ *Error buscando envios*\n\n{esc(error_msg)}",
                parse_mode="Markdown"
            )
            estado_usuario.pop(chat_id, None)
            return

        if not pendientes:
            await query.edit_message_text(
                f"✅ No hay envios pendientes para *{local_corto(local)}*\\.",
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
        bultos_str = env.get("bultos", "")
        lines = []
        for j, p in enumerate(prods):
            c = cants[j] if j < len(cants) else "?"
            lines.append(f"  · {p}: {c}")
        resumen = "\n".join(lines)
        await query.edit_message_text(
            f"📥 *Envio de {local_corto(env['origen'])}*\n"
            f"📅 {env['fecha']} {env['hora']}\n"
            f"👤 Envio: {esc(env['responsable'])}\n"
            f"🚗 {env['transporte']}\n"
            f"📦 Bultos: {bultos_str}\n\n"
            f"📋 *Productos:*\n{resumen}\n\n"
            f"👤 Escribi tu nombre para confirmar recepcion:",
            parse_mode="Markdown"
        )
        return

    if data == "recibir_todo_ok":
        env = info.get("envio_a_recibir", {})
        resp = info.get("nombre_recibir", "")
        tiempo = _calcular_tiempo_envio(env.get("fecha", ""), env.get("hora", ""))
        marcar_recibido(env["fila"], resp, recibido_ok=True)

        # ── STOCK INTEGRATION: Update stock on envio received ──
        local_dest = info.get("local_recibir", env.get("destino", ""))
        prods = _split_multi(env.get("productos", ""))
        cants = _split_multi(env.get("cantidades", ""))
        try:
            sh_stock = get_stock_sheet()
            if sh_stock and prods:
                _ensure_stock_tabs(sh_stock)
                stock_apply_envio_recibido(sh_stock, local_dest, prods, cants, resp, chat_id)
                log.info(f"✅ Stock actualizado por envio recibido en {local_dest}")
        except Exception as se:
            log.error(f"⚠️ Error actualizando stock al recibir envio: {se}")
        # ── END STOCK INTEGRATION ──

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
        await query.edit_message_text(f"✅ *Envio recibido correctamente.*\n⏱️ Tiempo: {tiempo}", parse_mode="Markdown")
        estado_usuario.pop(chat_id, None)
        return

    if data == "recibir_con_diferencias":
        info["paso"] = "esperando_diferencias"
        await query.edit_message_text(
            "⚠️ Escribi que diferencias encontraste:\n\n"
            "Ejemplo: _Faltaron 3 medialunas, llegaron 2 brownies de mas_",
            parse_mode="Markdown"
        )
        return


async def handle_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    texto = update.message.text.strip()

    if chat_id not in estado_usuario:
        # No state, show menu
        await update.message.reply_text(
            "🥐 *Lharmonie — Envios y Stock*\n\n¿Que queres hacer?",
            reply_markup=_main_menu_keyboard(),
            parse_mode="Markdown"
        )
        return

    info = estado_usuario[chat_id]
    paso = info.get("paso", "")

    # ── STOCK: Cargar — esperando nombre responsable ──
    if paso == "cargar_esperando_nombre":
        info["cargar_responsable"] = texto
        info["paso"] = "cargar_eligiendo_zona"
        keyboard = [[InlineKeyboardButton(z, callback_data=f"cargar_zona_{i}")] for i, z in enumerate(ZONAS_DISPLAY)]
        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
        await update.message.reply_text(
            f"👤 {esc(texto)}\n\n¿En que zona estas?",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return

    # ── STOCK: Cargar — esperando cantidad ──
    if paso == "cargar_esperando_cantidad":
        try:
            cantidad = int(texto.replace(",", "").replace(".", "").strip())
        except ValueError:
            await update.message.reply_text("❌ Escribi un numero valido. Ejemplo: `10`", parse_mode="Markdown")
            return
        if cantidad < 0:
            await update.message.reply_text("❌ La cantidad debe ser positiva.")
            return

        info["cargar_cantidad"] = cantidad

        # Ask for responsable name
        info["paso"] = "cargar_esperando_responsable"
        await update.message.reply_text("👤 Escribi tu nombre:")
        return

    # ── STOCK: Cargar — esperando responsable ──
    if paso == "cargar_esperando_responsable":
        info["cargar_responsable"] = texto
        # Show confirmation
        local = info.get("cargar_local", "")
        zona = info.get("cargar_zona", "")
        producto = info.get("cargar_producto", "")
        tipo = info.get("cargar_tipo", "")
        cantidad = info.get("cargar_cantidad", 0)

        tipo_labels = {
            TIPO_FERMENTO: "🧊 Saco a fermentar",
            TIPO_HORNEO: "🔥 Horneo",
            TIPO_ENVIO_RECIBIDO: "📦 Envio recibido",
            TIPO_MERMA: "🗑️ Merma",
            TIPO_AJUSTE: "📝 Ajuste",
        }
        tipo_label = tipo_labels.get(tipo, tipo)

        keyboard = [
            [InlineKeyboardButton("✅ Confirmar", callback_data="cargar_confirmar")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")],
        ]

        extra = ""
        if tipo == TIPO_AJUSTE:
            ajuste_tipo = info.get("cargar_ajuste_tipo", "congelado")
            extra = f"\n📊 Estado: {ajuste_tipo}"

        await update.message.reply_text(
            f"📝 *Confirmar movimiento:*\n\n"
            f"📍 {local_corto(local)} — {zona}\n"
            f"📦 {esc(producto)}: *{cantidad}*\n"
            f"📝 {tipo_label}{extra}\n"
            f"👤 {esc(texto)}\n\n"
            f"¿Todo OK?",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return

    # ── ENVIO: Nombre del que envia ──
    if paso == "esperando_nombre":
        info["responsable"] = texto
        info["paso"] = "eligiendo_categoria"
        productos, _ = cargar_productos()
        categorias = list(productos.keys())
        keyboard = [[InlineKeyboardButton(f"🏷️ {cat}", callback_data=f"cat_{cat}")] for cat in categorias]
        keyboard.append([InlineKeyboardButton("✏️ Carga manual", callback_data="carga_manual")])
        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
        await update.message.reply_text(
            f"👤 {esc(texto)}\n\nElegi una categoria de productos:",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return

    # ── ENVIO: Carga manual de productos ──
    if paso == "esperando_carga_manual":
        items = _parsear_carga_manual(texto)
        if not items:
            await update.message.reply_text(
                "❌ No pude interpretar ningun producto. Intenta de nuevo.\n\n"
                "Ejemplo: `10 medialunas, 5 brownies`",
                parse_mode="Markdown"
            )
            return
        productos, unidades = cargar_productos()
        resumen_lines = []
        nuevos = []
        matcheados = []
        for cantidad, nombre in items:
            prod_match, cat_match, unit_match = _buscar_producto_similar(nombre, productos, unidades)
            if prod_match:
                info["productos_lista"].append(prod_match)
                info["cantidades_lista"].append(cantidad)
                info["unidades_lista"].append(unit_match or "u")
                tipo = cat_match if cat_match else "Producto Terminado"
                info["tipos_lista"].append(tipo)
                matcheados.append(f"  ✅ {prod_match}: {cantidad} {unit_match or 'u'}")
            else:
                nombre_cap = nombre.strip().capitalize()
                agregar_producto_nuevo(nombre_cap)
                info["productos_lista"].append(nombre_cap)
                info["cantidades_lista"].append(cantidad)
                info["unidades_lista"].append("u")
                info["tipos_lista"].append("Producto Terminado")
                nuevos.append(f"  🆕 {nombre_cap}: {cantidad} u")
        if matcheados:
            resumen_lines.append("*Productos encontrados:*\n" + "\n".join(matcheados))
        if nuevos:
            resumen_lines.append("*Productos nuevos (agregados al catalogo):*\n" + "\n".join(nuevos))
        info["paso"] = "eligiendo_categoria"
        categorias = list(productos.keys())
        keyboard = [[InlineKeyboardButton(f"🏷️ {cat}", callback_data=f"cat_{cat}")] for cat in categorias]
        keyboard.append([InlineKeyboardButton("✏️ Carga manual", callback_data="carga_manual")])
        keyboard.append([InlineKeyboardButton(f"✅ Terminar y enviar ({len(info['productos_lista'])} productos)", callback_data="terminar_productos")])
        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
        all_lines = [f"  · {_fmt_prod_line(info, j)}" for j in range(len(info["productos_lista"]))]
        resumen_total = "\n".join(all_lines)
        await update.message.reply_text(
            f"✏️ *Carga manual procesada*\n\n"
            + "\n\n".join(resumen_lines) +
            f"\n\n📋 *Todos los productos:*\n{resumen_total}\n\n"
            f"Segui agregando o termina:",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return

    # ── ENVIO: Editando cantidad desde resumen editable ──
    if paso == "editando_cantidad":
        idx = info.get("editando_idx", 0)
        if idx < len(info["cantidades_lista"]):
            prod = info["productos_lista"][idx]
            u = info["unidades_lista"][idx] if idx < len(info.get("unidades_lista", [])) else "u"
            info["cantidades_lista"][idx] = texto
            info["paso"] = "resumen_editable"
            await update.message.reply_text(f"✅ *{esc(prod)}* → {texto} {u}")
            await _mostrar_resumen_editable(update.message, info, is_message=True)
        return

    # ── ENVIO: Editando nombre del producto ──
    if paso == "editando_nombre_prod":
        idx = info.get("editando_idx", 0)
        if idx < len(info["productos_lista"]):
            old = info["productos_lista"][idx]
            info["productos_lista"][idx] = texto.strip()
            info["paso"] = "resumen_editable"
            await update.message.reply_text(f"✅ *{esc(old)}* → *{esc(texto.strip())}*", parse_mode="Markdown")
            await _mostrar_resumen_editable(update.message, info, is_message=True)
        return

    # ── ENVIO: Editando responsable ──
    if paso == "editando_responsable":
        info["responsable"] = texto.strip()
        info["paso"] = "resumen_editable"
        await update.message.reply_text(f"✅ Responsable: *{esc(texto.strip())}*", parse_mode="Markdown")
        await _mostrar_resumen_editable(update.message, info, is_message=True)
        return

    # ── ENVIO: Cantidad del producto ──
    if paso == "esperando_cantidad":
        prod = info.get("producto_actual", "")
        unidad = info.get("unidad_actual", "u")
        info["productos_lista"].append(prod)
        info["cantidades_lista"].append(texto)
        info["unidades_lista"].append(unidad)
        cat = info.get("categoria_actual", "Varios")
        tipo = cat if cat != "Varios" else "Producto Terminado"
        info["tipos_lista"].append(tipo)
        info["paso"] = "eligiendo_categoria"
        productos, _ = cargar_productos()
        categorias = list(productos.keys())
        keyboard = [[InlineKeyboardButton(f"🏷️ {cat}", callback_data=f"cat_{cat}")] for cat in categorias]
        keyboard.append([InlineKeyboardButton("✏️ Carga manual", callback_data="carga_manual")])
        keyboard.append([InlineKeyboardButton(f"✅ Terminar y enviar ({len(info['productos_lista'])} productos)", callback_data="terminar_productos")])
        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
        lines = [f"  · {_fmt_prod_line(info, j)}" for j in range(len(info["productos_lista"]))]
        resumen = "\n".join(lines)
        await update.message.reply_text(
            f"✅ Agregado: *{prod}* — {texto} {unidad}\n\n"
            f"📋 *Productos:*\n{resumen}\n\n"
            f"Elegi otra categoria o termina:",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return

    # ── ENVIO: Bultos totales ──
    if paso == "esperando_bultos_total":
        info["bultos_total"] = texto
        info["paso"] = "eligiendo_transporte"
        keyboard = [[InlineKeyboardButton(t, callback_data=f"transporte_{i}")] for i, t in enumerate(TRANSPORTES)]
        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
        await update.message.reply_text(
            f"📦 Bultos: *{texto}*\n\n🚗 ¿Como se envia?",
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
            f"👤 {esc(texto)}\n\n¿Llego todo bien?",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return

    # ── RECIBIR: Diferencias ──
    if paso == "esperando_diferencias":
        env = info.get("envio_a_recibir", {})
        resp = info.get("nombre_recibir", "")
        tiempo = _calcular_tiempo_envio(env.get("fecha", ""), env.get("hora", ""))
        marcar_recibido(env["fila"], resp, recibido_ok=False, diferencias=texto)

        # ── STOCK INTEGRATION: Update stock even with differences ──
        # We still add whatever was received. The difference is noted.
        local_dest = info.get("local_recibir", env.get("destino", ""))
        prods = _split_multi(env.get("productos", ""))
        cants = _split_multi(env.get("cantidades", ""))
        try:
            sh_stock = get_stock_sheet()
            if sh_stock and prods:
                _ensure_stock_tabs(sh_stock)
                stock_apply_envio_recibido(sh_stock, local_dest, prods, cants, resp, chat_id)
                log.info(f"✅ Stock actualizado por envio con diferencias en {local_dest}")
        except Exception as se:
            log.error(f"⚠️ Error actualizando stock al recibir envio con diff: {se}")
        # ── END STOCK INTEGRATION ──

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
        await update.message.reply_text(f"⚠️ *Envio registrado con diferencias.*\nEl equipo fue notificado.", parse_mode="Markdown")
        estado_usuario.pop(chat_id, None)
        return


# ── MAIN ──────────────────────────────────────────────────────────────────────
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler global de errores."""
    log.error(f"❌ Error no atrapado: {context.error}", exc_info=context.error)
    try:
        if update and update.effective_chat:
            chat_id = update.effective_chat.id
            estado_usuario.pop(chat_id, None)
            if update.callback_query:
                await update.callback_query.message.reply_text(
                    "⚠️ Ocurrio un error. Empeza de nuevo:",
                    reply_markup=_main_menu_keyboard()
                )
            elif update.message:
                await update.message.reply_text(
                    "⚠️ Ocurrio un error. Empeza de nuevo:",
                    reply_markup=_main_menu_keyboard()
                )
    except Exception as e:
        log.error(f"❌ Error en el error handler: {e}")


def main():
    if not TELEGRAM_TOKEN:
        print("❌ Falta ENVIOS_TELEGRAM_TOKEN")
        return
    print("🚚 Iniciando Bot Envios + Stock Lharmonie...")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Command handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("stock", cmd_stock))
    app.add_handler(CommandHandler("cargar", cmd_cargar))
    app.add_handler(CommandHandler("sugerencia", cmd_sugerencia))
    app.add_handler(CommandHandler("reporte", cmd_reporte))

    # Callback and text handlers
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_texto))

    app.add_error_handler(error_handler)
    print("✅ Bot Envios + Stock corriendo.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
