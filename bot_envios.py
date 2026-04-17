#!/usr/bin/env python3
"""
Bot de Telegram — Envíos + Stock Lharmonie (v2 simplificado)
=============================================================
Herramienta de CARGA DE DATOS para empleados.
4 acciones: Enviar, Recibir, Cargar stock, Fermentación.
Carga manual por texto libre con fuzzy matching.
"""
import os
import re
import json
import logging
import time as _time
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher

# Timezone Argentina (UTC-3)
TZ_AR = timezone(timedelta(hours=-3))

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes,
)

# ── CONFIG ────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ.get(
    "ENVIOS_TELEGRAM_TOKEN",
    "8631530577:AAGM0J5qq2VqcZ7FaSeXP_UAtinPcAYW9jc",
)
SHEETS_ID = os.environ.get("ENVIOS_SHEETS_ID", "")
GOOGLE_CREDS = os.environ.get("GOOGLE_CREDENTIALS", "")

# ── LOCALES ───────────────────────────────────────────────────────────────────
LOCALES = [
    "CDP - Nicaragua (Produccion)",
    "LH2 - Nicaragua 6068",
    "LH3 - Maure 1516",
    "LH4 - Zabala 1925",
    "LH5 - Libertador 3118",
]
LOCALES_RETAIL = [l for l in LOCALES if "CDP" not in l]
LOCAL_KEYS = ["LH2", "LH3", "LH4", "LH5"]
ZONAS = ["Cocina", "Mostrador", "Barra"]
TRANSPORTES = ["🚗 Ezequiel (Mister)", "🚕 Uber"]

# IDs para notificaciones (Martin + Iaras)
NOTIFY_IDS = [6457094702, 5358183977, 7354049230]

logging.basicConfig(
    format="%(asctime)s — %(levelname)s — %(message)s", level=logging.INFO
)
log = logging.getLogger(__name__)

# ── ESTADO DE USUARIOS ───────────────────────────────────────────────────────
estado_usuario = {}  # chat_id -> {paso, datos...}

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
        creds = Credentials.from_service_account_info(
            json.loads(creds_json), scopes=scopes
        )
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(SHEETS_ID)
        _sheets_cache.update({"gc": gc, "sh": sh, "ts": now})
        return gc, sh
    except Exception as e:
        log.error(f"Error conectando a Sheets: {e}")
        return None, None


def get_stock_sheet():
    """Returns the same gspread Spreadsheet — todo en un solo Sheet."""
    _, sh = get_sheets_client()
    return sh


# ── PRODUCTOS ─────────────────────────────────────────────────────────────────
def cargar_productos() -> tuple:
    """
    Lee la pestana 'Productos Envio' del Sheet.
    Retorna (dict categorias, dict unidades):
      - categorias: {categoria: [producto1, ...]}
      - unidades:   {producto: "u"|"kg"|...}
    """
    try:
        _, sh = get_sheets_client()
        if not sh:
            return {}, {}
        try:
            ws = sh.worksheet("Productos Envío")
        except Exception:
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
        for row in vals[header_idx + 1 :]:
            if not any(row):
                continue
            cat = row[0].strip() if len(row) > 0 else ""
            prod = row[1].strip() if len(row) > 1 else ""
            unidad = row[2].strip() if len(row) > 2 else "u"
            if cat and prod:
                productos.setdefault(cat, []).append(prod)
                unidades[prod] = unidad or "u"
        log.info(
            f"Productos cargados: {sum(len(v) for v in productos.values())} "
            f"en {len(productos)} categorias"
        )
        return productos, unidades
    except Exception as e:
        log.error(f"Error cargando productos: {e}")
        return {}, {}


def _crear_productos_iniciales(ws):
    """Crea el catalogo inicial de productos."""
    productos = [
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
    log.info(f"Catalogo inicial creado: {len(rows)} productos")


# ── ENVIOS SHEET ──────────────────────────────────────────────────────────────
EXPECTED_HEADERS = [
    "Fecha", "Hora", "Origen", "Destino", "Responsable envío",
    "Transporte", "Productos", "Cantidades", "Unidades",
    "Bultos", "Estado", "Responsable recepción", "Fecha recepción",
    "Recibido OK", "Diferencias", "Tiempo envio", "Observaciones",
]


def _get_or_create_envios_ws(sh):
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
        raise


def guardar_envio(datos: dict) -> tuple:
    """Guarda un envio en la pestana 'Envios'. Retorna (ok, error_msg)."""
    try:
        _, sh = get_sheets_client()
        if not sh:
            return (False, "No se pudo conectar a Google Sheets.")
        ws, _ = _get_or_create_envios_ws(sh)
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
            "Cantidades": SEP.join(str(c) for c in datos.get("cantidades_lista", [])),
            "Unidades": SEP.join(datos.get("unidades_lista", [])),
            "Bultos": datos.get("bultos_total", ""),
            "Estado": "Enviado",
            "Observaciones": datos.get("observaciones", ""),
        }
        row = [valores.get(h, "") for h in headers]
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
    if "\n" in value:
        return [v.strip() for v in value.split("\n") if v.strip()]
    return [value.strip()] if value.strip() else []


def obtener_envios_pendientes(local_destino: str) -> tuple:
    """Trae envios pendientes de recepcion para un local."""
    try:
        _, sh = get_sheets_client()
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
            except Exception:
                return ""

        pendientes = []
        for i, row in enumerate(all_values[h_idx + 1 :], start=h_idx + 2):
            if not any(row):
                continue
            estado = gcol(row, "Estado")
            destino = gcol(row, "Destino")
            es_enviado = (
                "enviado" in estado.lower()
                and "recibido" not in estado.lower()
                and "diferencia" not in estado.lower()
                and "congelado" not in estado.lower()
            )
            destino_match = False
            if destino and local_destino:
                if (
                    local_destino.lower() in destino.lower()
                    or destino.lower() in local_destino.lower()
                    or local_corto(local_destino).lower() in destino.lower()
                ):
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
    try:
        ahora = datetime.now(TZ_AR)
        dt_envio = datetime.strptime(
            f"{fecha_envio} {hora_envio}", "%d/%m/%Y %H:%M"
        ).replace(tzinfo=TZ_AR)
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
        return f"{dias}d {horas % 24}h"
    except Exception:
        return "—"


def marcar_recibido(fila: int, responsable: str, recibido_ok: bool, diferencias: str = ""):
    try:
        _, sh = get_sheets_client()
        if not sh:
            return
        ws = sh.worksheet("Envíos")
        headers = ws.row_values(1)

        def col_idx(name):
            try:
                return headers.index(name) + 1
            except Exception:
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
        tiempo = (
            _calcular_tiempo_envio(fecha_envio, hora_envio)
            if fecha_envio and hora_envio
            else "—"
        )
        updates = [
            ("Estado", estado),
            ("Responsable recepción", responsable),
            ("Fecha recepción", ahora.strftime("%d/%m/%Y %H:%M")),
            ("Recibido OK", "Sí" if recibido_ok else "No"),
            ("Tiempo envio", tiempo),
        ]
        if diferencias:
            updates.append(("Diferencias", diferencias))
        for name, val in updates:
            ci = col_idx(name)
            if ci:
                ws.update_cell(fila, ci, val)
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
    "Ultima Actualizacion",
]

MOVIMIENTOS_HEADERS = [
    "Timestamp", "Local", "Zona", "Producto", "Tipo",
    "Cantidad", "Estado Origen", "Estado Destino",
    "Responsable", "Chat ID", "Observaciones",
]

PRODUCTOS_STOCK_HEADERS = [
    "Categoria", "Producto", "Unidad",
    "Stock Minimo LH2", "Stock Minimo LH3",
    "Stock Minimo LH4", "Stock Minimo LH5",
]

AUDITORIA_HEADERS = [
    "Fecha", "Local", "Producto",
    "Stock Apertura", "Envios Recibidos", "Horneado",
    "Ventas Bistrosoft", "Transfers", "Merma",
    "Stock Cierre Teorico", "Stock Cierre Real",
    "Diferencia", "%Diferencia",
]

TIPO_ENVIO_RECIBIDO = "envio_recibido"
TIPO_FERMENTO = "fermento"
TIPO_HORNEO = "horneo"
TIPO_MERMA = "merma"
TIPO_AJUSTE = "ajuste"


def _get_or_create_stock_ws(sh, tab_name, headers, rows=2000):
    try:
        return sh.worksheet(tab_name)
    except Exception as e:
        err_str = str(e).lower()
        if "not found" in err_str or "no worksheet" in err_str:
            ws = sh.add_worksheet(tab_name, rows=rows, cols=len(headers))
            ws.append_row(headers)
            _time.sleep(1)
            log.info(f"Pestana '{tab_name}' creada")
            return ws
        raise


def _ensure_stock_tabs(sh):
    _get_or_create_stock_ws(sh, "Productos", PRODUCTOS_STOCK_HEADERS, rows=300)
    _time.sleep(1)
    _get_or_create_stock_ws(sh, "Stock Actual", STOCK_ACTUAL_HEADERS, rows=300)
    _time.sleep(1)
    _get_or_create_stock_ws(sh, "Movimientos", MOVIMIENTOS_HEADERS, rows=5000)
    _time.sleep(1)
    _get_or_create_stock_ws(sh, "Auditoria", AUDITORIA_HEADERS, rows=2000)


def _safe_int(val, default=0):
    if not val:
        return default
    try:
        return int(round(float(str(val).replace(",", ".").strip())))
    except (ValueError, TypeError):
        return default


def _local_key_from_name(local_name: str) -> str:
    up = local_name.upper()
    for lk in LOCAL_KEYS:
        if lk in up:
            return lk
    if "NICARAGUA" in up and "CDP" not in up:
        return "LH2"
    if "MAURE" in up:
        return "LH3"
    if "ZABALA" in up:
        return "LH4"
    if "LIBERTADOR" in up:
        return "LH5"
    return ""


def _get_product_category(producto: str) -> str:
    try:
        productos, _ = cargar_productos()
        for cat, prods in productos.items():
            if producto in prods:
                return cat
        return "Varios"
    except Exception:
        return "Varios"


def stock_read_actual(sh) -> dict:
    """Reads Stock Actual tab. Returns {producto: {LH2_congelado: N, ...}}"""
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
            prod = row[0].strip() if row else ""
            if not prod:
                continue
            d = {}
            for lk in LOCAL_KEYS:
                for estado in ("Congelado", "Horneado"):
                    col = f"{lk} {estado}"
                    idx = headers.index(col) if col in headers else -1
                    d[f"{lk}_{estado.lower()}"] = _safe_int(
                        row[idx] if 0 <= idx < len(row) else "0"
                    )
            stock[prod] = d
        return stock
    except Exception as e:
        log.error(f"Error leyendo Stock Actual: {e}")
        return {}


def stock_update_product(sh, producto: str, categoria: str, updates: dict):
    """Updates a single product row in Stock Actual."""
    try:
        ws = _get_or_create_stock_ws(sh, "Stock Actual", STOCK_ACTUAL_HEADERS, rows=300)
        vals = ws.get_all_values()
        headers = vals[0] if vals else STOCK_ACTUAL_HEADERS
        ahora = datetime.now(TZ_AR).strftime("%d/%m/%Y %H:%M")
        target_row = None
        for i, row in enumerate(vals[1:], start=2):
            if row and row[0].strip().lower() == producto.lower():
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


def stock_log_movement(sh, local, zona, producto, tipo, cantidad,
                       estado_origen, estado_destino, responsable,
                       chat_id, observaciones=""):
    """Logs a movement to the Movimientos tab."""
    try:
        ws = _get_or_create_stock_ws(sh, "Movimientos", MOVIMIENTOS_HEADERS, rows=5000)
        ahora = datetime.now(TZ_AR).strftime("%d/%m/%Y %H:%M:%S")
        row = [
            ahora, local, zona, producto, tipo,
            str(cantidad), estado_origen, estado_destino,
            responsable, str(chat_id), observaciones,
        ]
        ws.append_row(row, value_input_option="RAW")
        log.info(f"Movimiento: {tipo} {cantidad}x {producto} en {local}")
    except Exception as e:
        log.error(f"Error registrando movimiento: {e}")
        raise


def stock_apply_movement(sh, local_name, producto, tipo, cantidad,
                         zona="", responsable="", chat_id=0, observaciones=""):
    """Apply a stock movement: update Stock Actual and log to Movimientos."""
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
        updates[f"{lk}_congelado"] = max(0, cong - cantidad)
        estado_origen = "congelado"
    elif tipo == TIPO_HORNEO:
        updates[f"{lk}_horneado"] = horn + cantidad
        estado_destino = "horneado"
    elif tipo == TIPO_MERMA:
        updates[f"{lk}_horneado"] = max(0, horn - cantidad)
        estado_origen = "horneado"
    elif tipo == TIPO_AJUSTE:
        if "horneado" in observaciones.lower():
            updates[f"{lk}_horneado"] = cantidad
            estado_destino = "horneado"
        else:
            updates[f"{lk}_congelado"] = cantidad
            estado_destino = "congelado"
    else:
        return False, f"Tipo desconocido: {tipo}"

    try:
        categoria = _get_product_category(producto)
        stock_update_product(sh, producto, categoria, updates)
        _time.sleep(1)
        stock_log_movement(
            sh, local_name, zona, producto, tipo,
            cantidad, estado_origen, estado_destino,
            responsable, chat_id, observaciones,
        )
        return True, "OK"
    except Exception as e:
        return False, str(e)


def stock_apply_envio_recibido(sh, local_destino, productos_lista,
                               cantidades_lista, responsable, chat_id):
    """When an envio is received, add all products to congelado stock."""
    lk = _local_key_from_name(local_destino)
    if not lk:
        return
    for i, prod in enumerate(productos_lista):
        cant = _safe_int(cantidades_lista[i] if i < len(cantidades_lista) else "0")
        if cant <= 0:
            continue
        try:
            ok, msg = stock_apply_movement(
                sh, local_destino, prod, TIPO_ENVIO_RECIBIDO,
                cant, zona="", responsable=responsable,
                chat_id=chat_id, observaciones="Desde envio recibido",
            )
            if not ok:
                log.warning(f"Error stock {prod}: {msg}")
            _time.sleep(1)
        except Exception as e:
            log.error(f"Error stock_apply_envio_recibido {prod}: {e}")


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


def _normalizar(texto: str) -> str:
    t = texto.lower().strip()
    for k, v in {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ü": "u", "ñ": "n"}.items():
        t = t.replace(k, v)
    return t


def _buscar_producto_similar(nombre: str, productos_dict: dict,
                              unidades_dict: dict = None,
                              umbral: float = 0.6) -> tuple:
    """Fuzzy match producto. Retorna (nombre, categoria, unidad) o (None, None, None)."""
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
        return mejor_prod, mejor_cat, (unidades_dict or {}).get(mejor_prod, "u")
    return None, None, None


def _parsear_lista_productos(texto: str) -> list:
    """
    Parsea texto libre tipo "medialunas 50, budines 20" o multilínea.
    Retorna lista de (cantidad_str, nombre_item).
    """
    items = []
    partes = re.split(r'[,;\n]+', texto)
    for parte in partes:
        parte = parte.strip().lstrip('-\u2022\u00b7').strip()
        if not parte:
            continue
        # "50 medialunas" o "50 x medialunas"
        m = re.match(r'^(\d+[\.,]?\d*)\s*[xX]?\s+(.+)$', parte)
        if m:
            items.append((m.group(1).strip(), m.group(2).strip()))
            continue
        # "medialunas 50" o "medialunas: 50"
        m = re.match(r'^(.+?)\s*[:xX]?\s*(\d+[\.,]?\d*)$', parte)
        if m and m.group(2):
            items.append((m.group(2).strip(), m.group(1).strip()))
            continue
        # Solo nombre, cantidad = 1
        items.append(("1", parte))
    return items


def _procesar_lista_texto(texto: str) -> tuple:
    """
    Parsea texto libre y fuzzy-matchea contra catalogo.
    Retorna (productos_lista, cantidades_lista, unidades_lista, resumen_texto).
    """
    items = _parsear_lista_productos(texto)
    if not items:
        return [], [], [], ""

    productos_dict, unidades_dict = cargar_productos()
    productos_lista = []
    cantidades_lista = []
    unidades_lista = []
    lines = []

    for cantidad_str, nombre in items:
        prod_match, cat_match, unit_match = _buscar_producto_similar(
            nombre, productos_dict, unidades_dict
        )
        if prod_match:
            productos_lista.append(prod_match)
            cantidades_lista.append(cantidad_str)
            unidades_lista.append(unit_match or "u")
            lines.append(f"  {prod_match} — {cantidad_str} {unit_match or 'u'}")
        else:
            nombre_cap = nombre.strip().capitalize()
            # Agregar al catalogo automaticamente
            try:
                agregar_producto_nuevo(nombre_cap)
            except Exception:
                pass
            productos_lista.append(nombre_cap)
            cantidades_lista.append(cantidad_str)
            unidades_lista.append("u")
            lines.append(f"  {nombre_cap} — {cantidad_str} u (nuevo)")

    resumen = "\n".join(lines)
    return productos_lista, cantidades_lista, unidades_lista, resumen


def agregar_producto_nuevo(nombre: str, categoria: str = "Varios", unidad: str = "u"):
    try:
        _, sh = get_sheets_client()
        if not sh:
            return
        try:
            ws = sh.worksheet("Productos Envío")
        except Exception:
            return
        ws.append_row([categoria, nombre, unidad])
        log.info(f"Nuevo producto: {nombre}")
    except Exception as e:
        log.error(f"Error agregando producto: {e}")


# ── TECLADOS ──────────────────────────────────────────────────────────────────
def _main_menu_kb():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📦 Enviar", callback_data="menu_enviar"),
            InlineKeyboardButton("📥 Recibir", callback_data="menu_recibir"),
        ],
        [
            InlineKeyboardButton("📝 Cargar stock", callback_data="menu_cargar"),
            InlineKeyboardButton("🔥 Fermentación", callback_data="menu_fermentar"),
        ],
    ])


def _locales_kb(prefix: str, include_cdp: bool = True):
    """Keyboard con locales. prefix se usa en callback_data."""
    lista = LOCALES if include_cdp else LOCALES_RETAIL
    keyboard = []
    for i, l in enumerate(lista):
        keyboard.append([InlineKeyboardButton(
            local_corto(l), callback_data=f"{prefix}_{i}"
        )])
    keyboard.append([InlineKeyboardButton("Cancelar", callback_data="cancelar")])
    return InlineKeyboardMarkup(keyboard)


# ── HANDLERS ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    estado_usuario.pop(update.effective_chat.id, None)
    await update.message.reply_text(
        "🥐 *Lharmonie*\n\n¿Qué hacemos?",
        reply_markup=_main_menu_kb(),
        parse_mode="Markdown",
    )


async def cmd_enviar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    estado_usuario[chat_id] = {"paso": "enviar_destino"}
    await update.message.reply_text(
        "📦 *Nuevo envío*\n\n¿A dónde va?",
        reply_markup=_locales_kb("enviar_dest"),
        parse_mode="Markdown",
    )


async def cmd_recibir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    estado_usuario[chat_id] = {"paso": "recibir_local"}
    await update.message.reply_text(
        "📥 *Recibir envío*\n\n¿En qué local estás?",
        reply_markup=_locales_kb("recibir_local"),
        parse_mode="Markdown",
    )


async def cmd_cargar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    estado_usuario[chat_id] = {"paso": "cargar_local"}
    await update.message.reply_text(
        "📝 *Cargar stock*\n\n¿Qué local?",
        reply_markup=_locales_kb("cargar_local", include_cdp=False),
        parse_mode="Markdown",
    )


async def cmd_fermentar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    estado_usuario[chat_id] = {"paso": "fermentar_local"}
    await update.message.reply_text(
        "🔥 *Fermentación*\n\n¿Qué local?",
        reply_markup=_locales_kb("fermentar_local", include_cdp=False),
        parse_mode="Markdown",
    )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    data = query.data

    # ── MENU PRINCIPAL ────────────────────────────────────────────────
    if data == "menu_enviar":
        estado_usuario[chat_id] = {"paso": "enviar_destino"}
        await query.edit_message_text(
            "📦 *Nuevo envío*\n\n¿A dónde va?",
            reply_markup=_locales_kb("enviar_dest"),
            parse_mode="Markdown",
        )
        return

    if data == "menu_recibir":
        estado_usuario[chat_id] = {"paso": "recibir_local"}
        await query.edit_message_text(
            "📥 *Recibir envío*\n\n¿En qué local estás?",
            reply_markup=_locales_kb("recibir_local"),
            parse_mode="Markdown",
        )
        return

    if data == "menu_cargar":
        estado_usuario[chat_id] = {"paso": "cargar_local"}
        await query.edit_message_text(
            "📝 *Cargar stock*\n\n¿Qué local?",
            reply_markup=_locales_kb("cargar_local", include_cdp=False),
            parse_mode="Markdown",
        )
        return

    if data == "menu_fermentar":
        estado_usuario[chat_id] = {"paso": "fermentar_local"}
        await query.edit_message_text(
            "🔥 *Fermentación*\n\n¿Qué local?",
            reply_markup=_locales_kb("fermentar_local", include_cdp=False),
            parse_mode="Markdown",
        )
        return

    if data == "menu_principal":
        estado_usuario.pop(chat_id, None)
        await query.edit_message_text(
            "🥐 *Lharmonie*\n\n¿Qué hacemos?",
            reply_markup=_main_menu_kb(),
            parse_mode="Markdown",
        )
        return

    if data == "cancelar":
        estado_usuario.pop(chat_id, None)
        await query.edit_message_text(
            "Cancelado. Mandá /start para volver al menú."
        )
        return

    # ── FLUJO ENVIAR ──────────────────────────────────────────────────
    if data.startswith("enviar_dest_"):
        idx = int(data.split("_")[2])
        info = estado_usuario.get(chat_id, {})
        info["destino"] = LOCALES[idx]
        info["paso"] = "enviar_lista"
        estado_usuario[chat_id] = info
        await query.edit_message_text(
            f"📦 Envío a *{local_corto(LOCALES[idx])}*\n\n"
            f"Dale, mandá la lista\\. Ej:\n"
            f"`medialunas 50, budines 20, cookies 15`",
            parse_mode="MarkdownV2",
        )
        return

    if data == "enviar_confirmar":
        info = estado_usuario.get(chat_id, {})
        # Pedir transporte
        info["paso"] = "enviar_transporte"
        estado_usuario[chat_id] = info
        keyboard = [[InlineKeyboardButton(t, callback_data=f"enviar_transp_{i}")]
                     for i, t in enumerate(TRANSPORTES)]
        keyboard.append([InlineKeyboardButton("Cancelar", callback_data="cancelar")])
        await query.edit_message_text(
            "🚗 ¿Cómo se envía?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data == "enviar_corregir":
        info = estado_usuario.get(chat_id, {})
        info["paso"] = "enviar_lista"
        info.pop("productos_lista", None)
        info.pop("cantidades_lista", None)
        info.pop("unidades_lista", None)
        estado_usuario[chat_id] = info
        await query.edit_message_text(
            f"📦 Envío a *{local_corto(info.get('destino', '?'))}*\n\n"
            f"Dale, mandá la lista de nuevo:",
            parse_mode="Markdown",
        )
        return

    if data.startswith("enviar_transp_"):
        idx = int(data.split("_")[2])
        info = estado_usuario.get(chat_id, {})
        info["transporte"] = TRANSPORTES[idx]

        # Guardar envio
        ahora = datetime.now(TZ_AR)
        info["fecha"] = ahora.strftime("%d/%m/%Y")
        info["hora"] = ahora.strftime("%H:%M")
        info["origen"] = "CDP - Nicaragua (Produccion)"
        info["responsable"] = info.get("responsable_nombre", "")

        await query.edit_message_text("Guardando...")

        ok, error_msg = guardar_envio(info)
        if not ok:
            await query.edit_message_text(
                f"Error guardando: {esc(error_msg or 'desconocido')}\n"
                f"Intentá de nuevo con /start",
                parse_mode="Markdown",
            )
            estado_usuario.pop(chat_id, None)
            return

        # Notificar
        n_prods = len(info.get("productos_lista", []))
        lines = []
        for j, p in enumerate(info.get("productos_lista", [])):
            c = info["cantidades_lista"][j] if j < len(info.get("cantidades_lista", [])) else "?"
            lines.append(f"  {p}: {c}")
        resumen = "\n".join(lines)

        msg_notif = (
            f"📦 *Nuevo envío*\n\n"
            f"📍 CDP → *{local_corto(info['destino'])}*\n"
            f"🚗 {info['transporte']}\n"
            f"🕐 {info['hora']}\n\n"
            f"📋 *Productos:*\n{resumen}"
        )
        for cid in NOTIFY_IDS:
            try:
                await context.bot.send_message(
                    chat_id=cid, text=msg_notif, parse_mode="Markdown"
                )
            except Exception:
                pass

        await query.edit_message_text(
            f"Listo, enviado a *{local_corto(info['destino'])}* 👍\n"
            f"{n_prods} productos registrados.",
            parse_mode="Markdown",
        )
        estado_usuario.pop(chat_id, None)
        return

    # ── FLUJO RECIBIR ─────────────────────────────────────────────────
    if data.startswith("recibir_local_"):
        idx = int(data.split("_")[2])
        local = LOCALES[idx]
        await query.edit_message_text("Buscando envíos pendientes...")

        pendientes, error_msg = obtener_envios_pendientes(local)
        if error_msg:
            await query.edit_message_text(f"Error: {esc(error_msg)}", parse_mode="Markdown")
            estado_usuario.pop(chat_id, None)
            return
        if not pendientes:
            await query.edit_message_text(
                f"No hay envíos pendientes para *{local_corto(local)}* 👍",
                parse_mode="Markdown",
            )
            estado_usuario.pop(chat_id, None)
            return

        info = estado_usuario.get(chat_id, {})
        info["local_recibir"] = local
        info["pendientes"] = pendientes
        estado_usuario[chat_id] = info

        keyboard = []
        for i, env in enumerate(pendientes):
            n_prods = len(_split_multi(env["productos"])) if env["productos"] else 0
            label = f"{env['fecha']} {env['hora']} — {local_corto(env['origen'])} ({n_prods} prod)"
            keyboard.append([InlineKeyboardButton(label, callback_data=f"recibir_env_{i}")])
        keyboard.append([InlineKeyboardButton("Cancelar", callback_data="cancelar")])
        await query.edit_message_text(
            f"📥 Envíos pendientes para *{local_corto(local)}*:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )
        return

    if data.startswith("recibir_env_"):
        idx = int(data.split("_")[2])
        info = estado_usuario.get(chat_id, {})
        pendientes = info.get("pendientes", [])
        if idx >= len(pendientes):
            return
        env = pendientes[idx]
        info["envio_a_recibir"] = env
        info["paso"] = "recibir_nombre"
        estado_usuario[chat_id] = info

        prods = _split_multi(env["productos"])
        cants = _split_multi(env["cantidades"])
        lines = []
        for j, p in enumerate(prods):
            c = cants[j] if j < len(cants) else "?"
            lines.append(f"  {p}: {c}")
        resumen = "\n".join(lines)

        await query.edit_message_text(
            f"📥 *Envío de {local_corto(env['origen'])}*\n"
            f"{env['fecha']} {env['hora']}\n\n"
            f"📋 *Productos:*\n{resumen}\n\n"
            f"👤 Escribí tu nombre:",
            parse_mode="Markdown",
        )
        return

    if data == "recibir_todo_ok":
        info = estado_usuario.get(chat_id, {})
        env = info.get("envio_a_recibir", {})
        resp = info.get("nombre_recibir", "")
        tiempo = _calcular_tiempo_envio(env.get("fecha", ""), env.get("hora", ""))
        marcar_recibido(env["fila"], resp, recibido_ok=True)

        # Update stock
        local_dest = info.get("local_recibir", env.get("destino", ""))
        prods = _split_multi(env.get("productos", ""))
        cants = _split_multi(env.get("cantidades", ""))
        try:
            sh_stock = get_stock_sheet()
            if sh_stock and prods:
                _ensure_stock_tabs(sh_stock)
                stock_apply_envio_recibido(sh_stock, local_dest, prods, cants, resp, chat_id)
        except Exception as se:
            log.error(f"Error stock al recibir: {se}")

        msg_notif = (
            f"✅ *Envío recibido*\n\n"
            f"📍 {local_corto(env.get('origen', '?'))} → {local_corto(env.get('destino', '?'))}\n"
            f"👤 {esc(resp)}\n"
            f"⏱ {tiempo}\n"
            f"Todo OK"
        )
        for cid in NOTIFY_IDS:
            try:
                await context.bot.send_message(chat_id=cid, text=msg_notif, parse_mode="Markdown")
            except Exception:
                pass
        await query.edit_message_text(f"Recibido, todo OK 👍\nTiempo: {tiempo}")
        estado_usuario.pop(chat_id, None)
        return

    if data == "recibir_falta":
        info = estado_usuario.get(chat_id, {})
        info["paso"] = "recibir_diferencias"
        estado_usuario[chat_id] = info
        await query.edit_message_text("Decime qué falta:")
        return

    # ── FLUJO CARGAR STOCK ────────────────────────────────────────────
    if data.startswith("cargar_local_"):
        idx = int(data.split("_")[2])
        local = LOCALES_RETAIL[idx]
        info = estado_usuario.get(chat_id, {})
        info["cargar_local"] = local
        info["paso"] = "cargar_zona"
        estado_usuario[chat_id] = info
        keyboard = [[InlineKeyboardButton(z, callback_data=f"cargar_zona_{i}")]
                     for i, z in enumerate(ZONAS)]
        keyboard.append([InlineKeyboardButton("Cancelar", callback_data="cancelar")])
        await query.edit_message_text(
            f"📝 *{local_corto(local)}*\n\n¿Qué zona?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )
        return

    if data.startswith("cargar_zona_"):
        idx = int(data.split("_")[2])
        info = estado_usuario.get(chat_id, {})
        info["cargar_zona"] = ZONAS[idx]
        info["paso"] = "cargar_lista"
        estado_usuario[chat_id] = info
        await query.edit_message_text(
            f"📝 *{local_corto(info['cargar_local'])}* — {ZONAS[idx]}\n\n"
            f"Mandá lo que tenés\\. Ej:\n"
            f"`medialunas 30, budines 10`",
            parse_mode="MarkdownV2",
        )
        return

    # ── FLUJO FERMENTACIÓN ────────────────────────────────────────────
    if data.startswith("fermentar_local_"):
        idx = int(data.split("_")[2])
        local = LOCALES_RETAIL[idx]
        info = estado_usuario.get(chat_id, {})
        info["fermentar_local"] = local
        info["paso"] = "fermentar_lista"
        estado_usuario[chat_id] = info
        await query.edit_message_text(
            f"🔥 *{local_corto(local)}*\n\n"
            f"¿Qué sacaste a fermentar? Ej:\n"
            f"`medialunas 100, croissants 50`",
            parse_mode="MarkdownV2",
        )
        return

    # ── FALLBACK: estado perdido ──────────────────────────────────────
    await query.edit_message_text(
        "Se perdió la sesión. Mandá /start para empezar de nuevo.",
    )
    estado_usuario.pop(chat_id, None)


async def handle_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    texto = update.message.text.strip()

    if chat_id not in estado_usuario:
        await update.message.reply_text(
            "🥐 *Lharmonie*\n\n¿Qué hacemos?",
            reply_markup=_main_menu_kb(),
            parse_mode="Markdown",
        )
        return

    info = estado_usuario[chat_id]
    paso = info.get("paso", "")

    # ── ENVIAR: lista de productos ────────────────────────────────────
    if paso == "enviar_lista":
        prods, cants, units, resumen = _procesar_lista_texto(texto)
        if not prods:
            await update.message.reply_text(
                "No entendí ningún producto. Mandá algo como:\n"
                "`medialunas 50, budines 20`",
                parse_mode="Markdown",
            )
            return
        info["productos_lista"] = prods
        info["cantidades_lista"] = cants
        info["unidades_lista"] = units
        info["paso"] = "enviar_confirmar"
        estado_usuario[chat_id] = info

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Listo", callback_data="enviar_confirmar"),
                InlineKeyboardButton("✏️ Corregir", callback_data="enviar_corregir"),
            ],
        ])
        await update.message.reply_text(
            f"📦 *{local_corto(info['destino'])}*\n\n"
            f"{resumen}\n\n"
            f"¿Está bien?",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
        return

    # ── RECIBIR: nombre ───────────────────────────────────────────────
    if paso == "recibir_nombre":
        info["nombre_recibir"] = texto
        info["paso"] = "recibir_ok_o_falta"
        estado_usuario[chat_id] = info
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Todo OK", callback_data="recibir_todo_ok"),
                InlineKeyboardButton("⚠️ Falta algo", callback_data="recibir_falta"),
            ],
        ])
        await update.message.reply_text(
            f"👤 {esc(texto)}\n\n¿Llegó todo bien?",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
        return

    # ── RECIBIR: diferencias ──────────────────────────────────────────
    if paso == "recibir_diferencias":
        env = info.get("envio_a_recibir", {})
        resp = info.get("nombre_recibir", "")
        tiempo = _calcular_tiempo_envio(env.get("fecha", ""), env.get("hora", ""))
        marcar_recibido(env["fila"], resp, recibido_ok=False, diferencias=texto)

        # Update stock anyway
        local_dest = info.get("local_recibir", env.get("destino", ""))
        prods = _split_multi(env.get("productos", ""))
        cants = _split_multi(env.get("cantidades", ""))
        try:
            sh_stock = get_stock_sheet()
            if sh_stock and prods:
                _ensure_stock_tabs(sh_stock)
                stock_apply_envio_recibido(sh_stock, local_dest, prods, cants, resp, chat_id)
        except Exception as se:
            log.error(f"Error stock recibir con diff: {se}")

        msg_notif = (
            f"⚠️ *Envío con diferencias*\n\n"
            f"📍 {local_corto(env.get('origen', '?'))} → {local_corto(env.get('destino', '?'))}\n"
            f"👤 {esc(resp)}\n"
            f"📝 {esc(texto)}"
        )
        for cid in NOTIFY_IDS:
            try:
                await context.bot.send_message(chat_id=cid, text=msg_notif, parse_mode="Markdown")
            except Exception:
                pass
        await update.message.reply_text("Anotado, el equipo fue notificado 👍")
        estado_usuario.pop(chat_id, None)
        return

    # ── CARGAR STOCK: lista ───────────────────────────────────────────
    if paso == "cargar_lista":
        prods, cants, units, resumen = _procesar_lista_texto(texto)
        if not prods:
            await update.message.reply_text(
                "No entendí. Mandá algo como:\n`medialunas 30, budines 10`",
                parse_mode="Markdown",
            )
            return

        local = info.get("cargar_local", "")
        zona = info.get("cargar_zona", "")
        await update.message.reply_text("Guardando...")

        try:
            sh = get_stock_sheet()
            if not sh:
                await update.message.reply_text("Error conectando a Sheets.")
                estado_usuario.pop(chat_id, None)
                return
            _ensure_stock_tabs(sh)

            errores = 0
            for j, prod in enumerate(prods):
                cant = _safe_int(cants[j] if j < len(cants) else "0")
                if cant <= 0:
                    continue
                # Cargar stock = ajuste: setea el valor exacto como congelado
                ok, msg = stock_apply_movement(
                    sh, local, prod, TIPO_AJUSTE, cant,
                    zona=zona, responsable="",
                    chat_id=chat_id, observaciones=f"carga stock {zona.lower()}",
                )
                if not ok:
                    errores += 1
                    log.warning(f"Error cargando {prod}: {msg}")
                _time.sleep(1)

            if errores:
                await update.message.reply_text(
                    f"Listo, pero hubo {errores} error(es). "
                    f"Revisá el Sheet."
                )
            else:
                await update.message.reply_text("Listo, cargado 👍")
        except Exception as e:
            log.error(f"Error cargar stock: {e}")
            await update.message.reply_text(f"Error: {esc(str(e))}", parse_mode="Markdown")

        estado_usuario.pop(chat_id, None)
        return

    # ── FERMENTACIÓN: lista ───────────────────────────────────────────
    if paso == "fermentar_lista":
        prods, cants, units, resumen = _procesar_lista_texto(texto)
        if not prods:
            await update.message.reply_text(
                "No entendí. Mandá algo como:\n`medialunas 100, croissants 50`",
                parse_mode="Markdown",
            )
            return

        local = info.get("fermentar_local", "")
        await update.message.reply_text("Guardando...")

        try:
            sh = get_stock_sheet()
            if not sh:
                await update.message.reply_text("Error conectando a Sheets.")
                estado_usuario.pop(chat_id, None)
                return
            _ensure_stock_tabs(sh)

            errores = 0
            for j, prod in enumerate(prods):
                cant = _safe_int(cants[j] if j < len(cants) else "0")
                if cant <= 0:
                    continue
                ok, msg = stock_apply_movement(
                    sh, local, prod, TIPO_FERMENTO, cant,
                    zona="Cocina", responsable="",
                    chat_id=chat_id, observaciones="fermentación",
                )
                if not ok:
                    errores += 1
                    log.warning(f"Error fermentación {prod}: {msg}")
                _time.sleep(1)

            if errores:
                await update.message.reply_text(
                    f"Anotado, pero hubo {errores} error(es). "
                    f"Revisá el Sheet."
                )
            else:
                await update.message.reply_text("Anotado 👍")
        except Exception as e:
            log.error(f"Error fermentación: {e}")
            await update.message.reply_text(f"Error: {esc(str(e))}", parse_mode="Markdown")

        estado_usuario.pop(chat_id, None)
        return

    # ── FALLBACK ──────────────────────────────────────────────────────
    await update.message.reply_text(
        "No entendí. Mandá /start para volver al menú."
    )
    estado_usuario.pop(chat_id, None)


# ── ERROR HANDLER ─────────────────────────────────────────────────────────────
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log.error(f"Error no atrapado: {context.error}", exc_info=context.error)
    try:
        if update and update.effective_chat:
            chat_id = update.effective_chat.id
            estado_usuario.pop(chat_id, None)
            msg = "Hubo un error. Mandá /start para empezar de nuevo."
            if update.callback_query:
                await update.callback_query.message.reply_text(msg)
            elif update.message:
                await update.message.reply_text(msg)
    except Exception as e:
        log.error(f"Error en error_handler: {e}")


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    if not TELEGRAM_TOKEN:
        print("Falta ENVIOS_TELEGRAM_TOKEN")
        return
    print("Iniciando Bot Envíos Lharmonie...")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("enviar", cmd_enviar))
    app.add_handler(CommandHandler("recibir", cmd_recibir))
    app.add_handler(CommandHandler("cargar", cmd_cargar))
    app.add_handler(CommandHandler("fermentar", cmd_fermentar))

    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_texto))

    app.add_error_handler(error_handler)
    print("Bot Envíos corriendo.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
