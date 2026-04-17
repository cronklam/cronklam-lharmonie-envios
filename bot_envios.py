#!/usr/bin/env python3
"""
Bot de Telegram — Envios + Stock Lharmonie (v3)
=============================================================
Herramienta de CARGA DE DATOS para empleados.
5 acciones: Enviar, Recibir, Cargar stock, Fermentacion, Ordenes del dia.
Carga manual por texto libre con fuzzy matching.
Zone-aware product catalog con checklist por zona.
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

# -- CONFIG --------------------------------------------------------------------
TELEGRAM_TOKEN = os.environ.get(
    "ENVIOS_TELEGRAM_TOKEN",
    "8631530577:AAGM0J5qq2VqcZ7FaSeXP_UAtinPcAYW9jc",
)
SHEETS_ID = os.environ.get("ENVIOS_SHEETS_ID", "")
GOOGLE_CREDS = os.environ.get("GOOGLE_CREDENTIALS", "")

# Bistrosoft Sheet (stock minimo)
BISTROSOFT_SHEET_ID = "1s6kPguwD25k3xpmbUoHq1KNFd_SEva3z7pvTGhA4bsE"

# -- LOCALES -------------------------------------------------------------------
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
TRANSPORTES = ["\U0001f697 Ezequiel (Mister)", "\U0001f695 Uber"]

# IDs para notificaciones (Martin + Iaras)
NOTIFY_IDS = [6457094702, 5358183977, 7354049230]

logging.basicConfig(
    format="%(asctime)s \u2014 %(levelname)s \u2014 %(message)s", level=logging.INFO
)
log = logging.getLogger(__name__)

# -- ESTADO DE USUARIOS -------------------------------------------------------
estado_usuario = {}  # chat_id -> {paso, datos...}

# -- GOOGLE SHEETS -------------------------------------------------------------
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


def _get_gspread_client():
    """Returns just the gspread client (gc) for opening other sheets."""
    gc, _ = get_sheets_client()
    return gc


def get_stock_sheet():
    """Returns the same gspread Spreadsheet -- todo en un solo Sheet."""
    _, sh = get_sheets_client()
    return sh


# -- PRODUCTOS -----------------------------------------------------------------
def cargar_productos() -> tuple:
    """
    Lee la pestana 'Productos Envio' del Sheet.
    Retorna (dict categorias, dict unidades, dict zonas):
      - categorias: {categoria: [producto1, ...]}
      - unidades:   {producto: "u"|"kg"|...}
      - zonas:      {producto: ["Cocina", "Mostrador", ...]}
    """
    try:
        _, sh = get_sheets_client()
        if not sh:
            return {}, {}, {}
        try:
            ws = sh.worksheet("Productos Envio")
        except Exception:
            try:
                ws = sh.worksheet("Productos Env\u00edo")
            except Exception:
                ws = sh.add_worksheet("Productos Envio", rows=200, cols=4)
                ws.append_row(["Categor\u00eda", "Producto", "Unidad", "Zona"])
                _crear_productos_iniciales(ws)
        vals = ws.get_all_values()
        header_idx = 0
        for i, row in enumerate(vals):
            if "Categor\u00eda" in row or "Categoria" in row:
                header_idx = i
                break
        productos = {}
        unidades = {}
        zonas = {}
        # Detect if there's a 4th column (Zona)
        has_zona_col = len(vals[header_idx]) >= 4 if vals else False
        for row in vals[header_idx + 1:]:
            if not any(row):
                continue
            cat = row[0].strip() if len(row) > 0 else ""
            prod = row[1].strip() if len(row) > 1 else ""
            unidad = row[2].strip() if len(row) > 2 else "u"
            zona_str = row[3].strip() if len(row) > 3 and has_zona_col else ""
            if cat and prod:
                productos.setdefault(cat, []).append(prod)
                unidades[prod] = unidad or "u"
                if zona_str:
                    zonas[prod] = [z.strip() for z in zona_str.split(",") if z.strip()]
                else:
                    # Default zone assignment based on category
                    zonas[prod] = _default_zones_for_category(cat)
        log.info(
            f"Productos cargados: {sum(len(v) for v in productos.values())} "
            f"en {len(productos)} categorias"
        )
        return productos, unidades, zonas
    except Exception as e:
        log.error(f"Error cargando productos: {e}")
        return {}, {}, {}


def _default_zones_for_category(cat: str) -> list:
    """Default zone for a category when not specified in sheet."""
    cat_lower = cat.lower()
    if "pasteler" in cat_lower:
        return ["Mostrador"]
    if "elaborados" in cat_lower:
        return ["Cocina"]
    if "varios" in cat_lower:
        return ["Cocina"]
    if "barra" in cat_lower:
        return ["Barra"]
    return ["Cocina"]


def _crear_productos_iniciales(ws):
    """Crea el catalogo inicial de productos con zona."""
    productos = [
        # Pasteleria -> Mostrador
        ("Pasteler\u00eda", "Alfajor de chocolate", "u", "Mostrador"),
        ("Pasteler\u00eda", "Alfajor de nuez", "u", "Mostrador"),
        ("Pasteler\u00eda", "Alfajor de pistacho", "u", "Mostrador"),
        ("Pasteler\u00eda", "Barritas prote\u00edna", "u", "Mostrador"),
        ("Pasteler\u00eda", "Brownie", "u", "Mostrador"),
        ("Pasteler\u00eda", "Bud\u00edn", "u", "Mostrador"),
        ("Pasteler\u00eda", "Cookie chocolate", "u", "Mostrador"),
        ("Pasteler\u00eda", "Cookie de man\u00ed", "u", "Mostrador"),
        ("Pasteler\u00eda", "Cookie melu", "u", "Mostrador"),
        ("Pasteler\u00eda", "Cookie nuez", "u", "Mostrador"),
        ("Pasteler\u00eda", "Cookie red velvet", "u", "Mostrador"),
        ("Pasteler\u00eda", "Cuadrado de coco", "u", "Mostrador"),
        ("Pasteler\u00eda", "Muffin", "u", "Mostrador"),
        ("Pasteler\u00eda", "Porci\u00f3n de d\u00e1tiles", "u", "Mostrador"),
        ("Pasteler\u00eda", "Porci\u00f3n de torta", "u", "Mostrador"),
        ("Pasteler\u00eda", "Tarteleta", "u", "Mostrador"),
        ("Pasteler\u00eda", "Torta entera", "u", "Mostrador"),
        ("Pasteler\u00eda", "Torta rogel", "u", "Mostrador"),
        # Elaborados -> Cocina (congelados)
        ("Elaborados", "Bavka choco", "u", "Cocina"),
        ("Elaborados", "Bavka pistacho", "u", "Cocina"),
        ("Elaborados", "Brioche pastelera", "u", "Cocina,Mostrador"),
        ("Elaborados", "Chipa", "u", "Cocina"),
        ("Elaborados", "Chipa prensado", "u", "Cocina"),
        ("Elaborados", "Croissant", "u", "Cocina"),
        ("Elaborados", "Croissant de almendras", "u", "Cocina"),
        ("Elaborados", "Medialunas", "u", "Cocina"),
        ("Elaborados", "Muffin de banana", "u", "Mostrador"),
        ("Elaborados", "Pain au choco", "u", "Cocina"),
        ("Elaborados", "Pain au choco con almendras", "u", "Cocina"),
        ("Elaborados", "Palitos de queso", "u", "Cocina"),
        ("Elaborados", "Palmeras", "u", "Cocina"),
        ("Elaborados", "Pan brioche", "u", "Cocina"),
        ("Elaborados", "Pan brioche cuadrado", "u", "Cocina"),
        ("Elaborados", "Pan masa madre con semillas", "u", "Cocina"),
        ("Elaborados", "Pan suisse", "u", "Cocina"),
        ("Elaborados", "Roll canela", "u", "Cocina"),
        ("Elaborados", "Roll frambuesa", "u", "Cocina"),
        ("Elaborados", "Roll de man\u00ed", "u", "Cocina"),
        ("Elaborados", "Tarta del d\u00eda", "u", "Cocina"),
        # Varios -> Cocina (insumos)
        ("Varios", "Aceite de girasol", "u", "Cocina"),
        ("Varios", "Aceite de oliva cocina", "u", "Cocina"),
        ("Varios", "Aceite de oliva Zuelo", "lt", "Cocina"),
        ("Varios", "Aderezo caesar", "u", "Cocina"),
        ("Varios", "Almendras", "kg", "Cocina"),
        ("Varios", "Almendras fileteadas", "kg", "Cocina"),
        ("Varios", "Arroz yamani cocido", "kg", "Cocina"),
        ("Varios", "Arroz yamani crudo", "kg", "Cocina"),
        ("Varios", "Arvejas", "u", "Cocina"),
        ("Varios", "Az\u00facar com\u00fan", "kg", "Cocina"),
        ("Varios", "Az\u00facar impalpable", "kg", "Cocina"),
        ("Varios", "Chocolate en barra", "u", "Cocina"),
        ("Varios", "Chocolate en trozos", "kg", "Cocina"),
        ("Varios", "Crema bariloche", "u", "Cocina"),
        ("Varios", "Crema pastelera de chocolate", "kg", "Cocina"),
        ("Varios", "Crema pastelera de panader\u00eda", "kg", "Cocina"),
        ("Varios", "Dulce de leche", "kg", "Cocina"),
        ("Varios", "Frangipane", "kg", "Cocina"),
        ("Varios", "Frosting de queso", "g", "Cocina"),
        ("Varios", "Granola", "kg", "Cocina"),
        ("Varios", "Hongos cocidos", "u", "Cocina"),
        ("Varios", "Lomitos de at\u00fan", "u", "Cocina"),
        ("Varios", "Maple de huevos", "u", "Cocina"),
        ("Varios", "Manteca com\u00fan", "u", "Cocina"),
        ("Varios", "Manteca saborizada", "u", "Cocina"),
        ("Varios", "Mermelada de cocina", "u", "Cocina"),
        ("Varios", "Mermelada de frambuesa", "u", "Cocina"),
        ("Varios", "Miel", "u", "Cocina"),
        ("Varios", "Papas gauchitas", "u", "Cocina"),
        ("Varios", "Pasta de at\u00fan", "g", "Cocina"),
        ("Varios", "Pasta de pistacho", "g", "Cocina"),
        ("Varios", "Pesto", "g", "Cocina"),
        ("Varios", "Picles de pepino", "u", "Cocina"),
        ("Varios", "Pistacho procesado", "g", "Cocina"),
        ("Varios", "Porci\u00f3n de trucha grill", "u", "Cocina"),
        ("Varios", "Queso crema", "u", "Cocina"),
        ("Varios", "Queso sardo", "u", "Cocina"),
        ("Varios", "Queso tybo", "u", "Cocina"),
        ("Varios", "Quinoa cocida", "kg", "Cocina"),
        ("Varios", "Quinoa crocante", "kg", "Cocina"),
        ("Varios", "Salsa holandesa", "u", "Cocina"),
        ("Varios", "Siracha", "kg", "Cocina"),
        ("Varios", "Vinagre", "u", "Cocina"),
        ("Varios", "Vinagre blanco", "lt", "Cocina"),
        ("Varios", "Wraps de espinaca", "u", "Cocina"),
        ("Varios", "Man\u00ed", "kg", "Cocina"),
        ("Varios", "Sal", "kg", "Cocina"),
        # Barra -> Barra
        ("Barra", "Caf\u00e9 de tolva", "u", "Barra"),
        ("Barra", "Caf\u00e9 Jairo 1/4", "u", "Barra"),
        ("Barra", "Caf\u00e9 Luis 1/4", "u", "Barra"),
        ("Barra", "Caf\u00e9 Samba Brasil 1/4", "u", "Barra"),
        ("Barra", "Caf\u00e9 Trailblazer 1/4", "u", "Barra"),
        ("Barra", "Caf\u00e9 Cumbia 1/4", "u", "Barra"),
        ("Barra", "Receta leche casera", "u", "Barra"),
        ("Barra", "Matcha", "u", "Barra"),
        ("Barra", "Hibiscus", "u", "Barra"),
        ("Barra", "C\u00farcuma", "u", "Barra"),
        ("Barra", "Frutilla congelada", "kg", "Barra"),
        ("Barra", "Ar\u00e1ndanos congelados", "kg", "Barra"),
        ("Barra", "T\u00e9 Grey", "u", "Barra"),
        ("Barra", "T\u00e9 Royal Frut", "u", "Barra"),
        ("Barra", "T\u00e9 Breakfast", "u", "Barra"),
        ("Barra", "T\u00e9 Berrys", "u", "Barra"),
    ]
    rows = [[cat, prod, unidad, zona] for cat, prod, unidad, zona in productos]
    ws.append_rows(rows)
    log.info(f"Catalogo inicial creado: {len(rows)} productos")


# -- ENVIOS SHEET --------------------------------------------------------------
EXPECTED_HEADERS = [
    "Fecha", "Hora", "Origen", "Destino", "Responsable env\u00edo",
    "Transporte", "Productos", "Cantidades", "Unidades",
    "Bultos", "Estado", "Responsable recepci\u00f3n", "Fecha recepci\u00f3n",
    "Recibido OK", "Diferencias", "Tiempo envio", "Observaciones",
]


def _get_or_create_envios_ws(sh):
    try:
        ws = sh.worksheet("Env\u00edos")
        return ws, False
    except Exception as e:
        err_str = str(e).lower()
        if "not found" in err_str or "no worksheet" in err_str:
            ws = sh.add_worksheet("Env\u00edos", rows=2000, cols=len(EXPECTED_HEADERS))
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
            "Responsable env\u00edo": datos.get("responsable", ""),
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
            ws = sh.worksheet("Env\u00edos")
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
        for i, row in enumerate(all_values[h_idx + 1:], start=h_idx + 2):
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
                    "responsable": gcol(row, "Responsable env\u00edo"),
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
            return "\u2014"
        if total_min < 60:
            return f"{total_min} min"
        horas = total_min // 60
        minutos = total_min % 60
        if horas < 24:
            return f"{horas}h {minutos}min"
        dias = horas // 24
        return f"{dias}d {horas % 24}h"
    except Exception:
        return "\u2014"


def marcar_recibido(fila: int, responsable: str, recibido_ok: bool, diferencias: str = ""):
    try:
        _, sh = get_sheets_client()
        if not sh:
            return
        ws = sh.worksheet("Env\u00edos")
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
            else "\u2014"
        )
        updates = [
            ("Estado", estado),
            ("Responsable recepci\u00f3n", responsable),
            ("Fecha recepci\u00f3n", ahora.strftime("%d/%m/%Y %H:%M")),
            ("Recibido OK", "S\u00ed" if recibido_ok else "No"),
            ("Tiempo envio", tiempo),
        ]
        if diferencias:
            updates.append(("Diferencias", diferencias))
        for name, val in updates:
            ci = col_idx(name)
            if ci:
                ws.update_cell(fila, ci, val)
        log.info(f"Envio fila {fila} marcado como {estado} \u2014 Tiempo: {tiempo}")
    except Exception as e:
        log.error(f"Error marcando recibido: {e}")


# -- STOCK SHEET FUNCTIONS -----------------------------------------------------

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
        productos, _, _ = cargar_productos()
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
        log.info(f"Stock actualizado: {producto} \u2014 {updates}")
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
        if "horneado" in observaciones.lower() or "mostrador" in observaciones.lower():
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


# -- ORDENES DEL DIA: leer stock minimo de Bistrosoft -------------------------

def _read_stock_minimo_bistrosoft(local_key: str) -> dict:
    """
    Lee la tab 'Stock Minimo' del Bistrosoft Sheet.
    Retorna {producto_lower: cantidad_minima} para el local y dia de semana actual.
    """
    try:
        gc = _get_gspread_client()
        if not gc:
            return {}
        bistro_sh = gc.open_by_key(BISTROSOFT_SHEET_ID)
        try:
            ws = bistro_sh.worksheet("Stock M\u00ednimo")
        except Exception:
            try:
                ws = bistro_sh.worksheet("Stock Minimo")
            except Exception:
                log.warning("No se encontro tab Stock Minimo en Bistrosoft Sheet")
                return {}

        vals = ws.get_all_values()
        if not vals:
            return {}

        headers = vals[0]
        # Find the column for this local + today's day of week
        dias_es = {
            0: "Lunes", 1: "Martes", 2: "Mi\u00e9rcoles", 3: "Jueves",
            4: "Viernes", 5: "S\u00e1bado", 6: "Domingo",
        }
        ahora = datetime.now(TZ_AR)
        dia_semana = dias_es.get(ahora.weekday(), "Lunes")

        # Try to find column like "LH4 Lunes" or just the local key
        target_col = None
        target_col_general = None
        for ci, h in enumerate(headers):
            h_up = h.upper().strip()
            if local_key.upper() in h_up and _normalizar(dia_semana) in _normalizar(h):
                target_col = ci
                break
            if local_key.upper() in h_up and target_col_general is None:
                target_col_general = ci

        # Find producto column (first column usually)
        prod_col = 0
        for ci, h in enumerate(headers):
            h_low = h.lower().strip()
            if "producto" in h_low or "product" in h_low:
                prod_col = ci
                break

        if target_col is None:
            target_col = target_col_general
        if target_col is None:
            log.warning(f"No se encontro columna para {local_key} en Stock Minimo")
            return {}

        result = {}
        for row in vals[1:]:
            if not any(row):
                continue
            prod = row[prod_col].strip() if prod_col < len(row) else ""
            val = row[target_col] if target_col < len(row) else ""
            if prod:
                result[_normalizar(prod)] = _safe_int(val)
        return result
    except Exception as e:
        log.error(f"Error leyendo Stock Minimo de Bistrosoft: {e}")
        return {}


def _generar_ordenes(local_name: str) -> str:
    """
    Genera ordenes de pedido y fermentacion para un local.
    NO son sugerencias opcionales — son DIRECTIVAS basadas en datos.
    Retorna el texto formateado para Telegram.
    """
    lk = _local_key_from_name(local_name)
    if not lk:
        return "No se pudo identificar el local."

    local_short = local_corto(local_name)
    ahora = datetime.now(TZ_AR)
    dia = ahora.strftime("%d/%m")

    # Leer stock actual
    try:
        sh = get_stock_sheet()
        if not sh:
            return "Error conectando a Sheets."
        stock_actual = stock_read_actual(sh)
    except Exception as e:
        log.error(f"Error leyendo stock actual: {e}")
        return f"Error leyendo stock: {e}"

    # Leer stock minimo de Bistrosoft
    stock_min = _read_stock_minimo_bistrosoft(lk)
    if not stock_min:
        return (
            f"\U0001f4cb Ordenes {lk} {local_short} — {dia}\n\n"
            f"Sin datos de stock m\u00ednimo.\n"
            f"Corr\u00e9 el sync de Bistrosoft primero."
        )

    # Calcular ordenes
    pedido_lines = []
    fermento_lines = []

    # Build a mapping from normalized product name to actual name
    productos_dict, _, _ = cargar_productos()
    all_prods = {}
    for cat, prods in productos_dict.items():
        for p in prods:
            all_prods[_normalizar(p)] = p

    for prod_norm, minimo in sorted(stock_min.items(), key=lambda x: -x[1]):
        if minimo <= 0:
            continue
        prod_display = all_prods.get(prod_norm, prod_norm.capitalize())
        prod_data = stock_actual.get(prod_display, {})
        congelado = prod_data.get(f"{lk}_congelado", 0)
        horneado = prod_data.get(f"{lk}_horneado", 0)
        total = congelado + horneado

        # Pedido: si el total esta por debajo del minimo
        deficit = minimo - total
        if deficit > 0:
            pedido_lines.append(
                f"  \u2022 {prod_display}: *{deficit}* (ten\u00e9s {total}, necesit\u00e1s {minimo})"
            )

        # Fermentacion: si hay congelado y se necesita hornear
        if congelado > 0:
            demanda = max(0, minimo - horneado)
            if demanda > 0:
                sacar = min(congelado, demanda)
                fermento_lines.append(
                    f"  \u2022 {prod_display}: sac\u00e1 *{sacar}* (ten\u00e9s {congelado} congeladas)"
                )

    # Armar mensaje — tono directivo, no sugerencia
    parts = [f"\U0001f4cb *ORDENES {lk} {local_short}* — {dia}\n"]

    if pedido_lines:
        parts.append("\U0001f4e6 *PEDIR A CDP:*")
        parts.extend(pedido_lines[:20])
        if len(pedido_lines) > 20:
            parts.append(f"  ... y {len(pedido_lines) - 20} m\u00e1s")
    else:
        parts.append("\U0001f4e6 PEDIDO: stock completo, no hace falta pedir")

    parts.append("")

    if fermento_lines:
        parts.append("\U0001f525 *SACAR A FERMENTAR:*")
        parts.extend(fermento_lines[:15])
        if len(fermento_lines) > 15:
            parts.append(f"  ... y {len(fermento_lines) - 15} m\u00e1s")
    else:
        parts.append("\U0001f525 FERMENTACI\u00d3N: no hay congelados para sacar")

    return "\n".join(parts)


# -- CHECKLIST POR ZONA --------------------------------------------------------

def _build_zone_checklist(local_name: str, zona: str) -> str:
    """
    Builds the checklist message for a zone showing all products.
    """
    local_short = local_corto(local_name)
    lk = _local_key_from_name(local_name)

    productos_dict, unidades_dict, zonas_dict = cargar_productos()

    # Filter products that belong to this zona
    zone_products = {}  # {categoria: [producto, ...]}
    for cat, prods in productos_dict.items():
        for p in prods:
            prod_zonas = zonas_dict.get(p, _default_zones_for_category(cat))
            if zona in prod_zonas:
                zone_products.setdefault(cat, []).append(p)

    if not zone_products:
        return f"\U0001f4dd {lk} {local_short} \u2014 {zona}\n\nNo hay productos para esta zona."

    parts = [f"\U0001f4dd {lk} {local_short} \u2014 {zona}\n"]
    parts.append("Chequea\u0301 y manda\u0301 las cantidades:\n")

    for cat in sorted(zone_products.keys()):
        prods = zone_products[cat]
        # Use lowercase product names for the checklist (casual)
        prod_names = [p.lower() for p in prods]
        parts.append(f"{cat.upper()}:")
        parts.append(", ".join(prod_names))
        parts.append("")

    parts.append("Mand\u00e1 tipo: alfajor nuez 5, brownie 8, muffin 3")
    parts.append("Solo lo que ten\u00e9s, el resto queda en 0.")

    return "\n".join(parts)


# -- HELPERS -------------------------------------------------------------------
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
    for k, v in {"\u00e1": "a", "\u00e9": "e", "\u00ed": "i", "\u00f3": "o", "\u00fa": "u", "\u00fc": "u", "\u00f1": "n"}.items():
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
    Parsea texto libre tipo "medialunas 50, budines 20" o multilinea.
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

    productos_dict, unidades_dict, _ = cargar_productos()
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
            lines.append(f"  {prod_match} \u2014 {cantidad_str} {unit_match or 'u'}")
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
            lines.append(f"  {nombre_cap} \u2014 {cantidad_str} u (nuevo)")

    resumen = "\n".join(lines)
    return productos_lista, cantidades_lista, unidades_lista, resumen


def agregar_producto_nuevo(nombre: str, categoria: str = "Varios", unidad: str = "u"):
    try:
        _, sh = get_sheets_client()
        if not sh:
            return
        try:
            ws = sh.worksheet("Productos Envio")
        except Exception:
            try:
                ws = sh.worksheet("Productos Env\u00edo")
            except Exception:
                return
        ws.append_row([categoria, nombre, unidad, "Cocina"])
        log.info(f"Nuevo producto: {nombre}")
    except Exception as e:
        log.error(f"Error agregando producto: {e}")


# -- TECLADOS ------------------------------------------------------------------
def _main_menu_kb():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("\U0001f4e6 Enviar", callback_data="menu_enviar"),
            InlineKeyboardButton("\U0001f4e5 Recibir", callback_data="menu_recibir"),
        ],
        [
            InlineKeyboardButton("\U0001f4dd Cargar stock", callback_data="menu_cargar"),
            InlineKeyboardButton("\U0001f525 Fermentaci\u00f3n", callback_data="menu_fermentar"),
        ],
        [
            InlineKeyboardButton("\U0001f4cb Ordenes del d\u00eda", callback_data="menu_ordenes"),
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


# -- HANDLERS ------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    estado_usuario.pop(update.effective_chat.id, None)
    await update.message.reply_text(
        "\U0001f950 *Lharmonie*\n\n\u00bfQu\u00e9 hacemos?",
        reply_markup=_main_menu_kb(),
        parse_mode="Markdown",
    )


async def cmd_enviar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    estado_usuario[chat_id] = {"paso": "enviar_destino"}
    await update.message.reply_text(
        "\U0001f4e6 *Nuevo env\u00edo*\n\n\u00bfA d\u00f3nde va?",
        reply_markup=_locales_kb("enviar_dest"),
        parse_mode="Markdown",
    )


async def cmd_recibir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    estado_usuario[chat_id] = {"paso": "recibir_local"}
    await update.message.reply_text(
        "\U0001f4e5 *Recibir env\u00edo*\n\n\u00bfEn qu\u00e9 local est\u00e1s?",
        reply_markup=_locales_kb("recibir_local"),
        parse_mode="Markdown",
    )


async def cmd_cargar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    estado_usuario[chat_id] = {"paso": "cargar_local"}
    await update.message.reply_text(
        "\U0001f4dd *Cargar stock*\n\n\u00bfQu\u00e9 local?",
        reply_markup=_locales_kb("cargar_local", include_cdp=False),
        parse_mode="Markdown",
    )


async def cmd_fermentar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    estado_usuario[chat_id] = {"paso": "fermentar_local"}
    await update.message.reply_text(
        "\U0001f525 *Fermentaci\u00f3n*\n\n\u00bfQu\u00e9 local?",
        reply_markup=_locales_kb("fermentar_local", include_cdp=False),
        parse_mode="Markdown",
    )


async def cmd_ordenes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    estado_usuario[chat_id] = {"paso": "ordenes_local"}
    await update.message.reply_text(
        "\U0001f4cb *Ordenes del d\u00eda*\n\n\u00bfQu\u00e9 local?",
        reply_markup=_locales_kb("ordenes_local", include_cdp=False),
        parse_mode="Markdown",
    )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    data = query.data

    # -- MENU PRINCIPAL --------------------------------------------------------
    if data == "menu_enviar":
        estado_usuario[chat_id] = {"paso": "enviar_destino"}
        await query.edit_message_text(
            "\U0001f4e6 *Nuevo env\u00edo*\n\n\u00bfA d\u00f3nde va?",
            reply_markup=_locales_kb("enviar_dest"),
            parse_mode="Markdown",
        )
        return

    if data == "menu_recibir":
        estado_usuario[chat_id] = {"paso": "recibir_local"}
        await query.edit_message_text(
            "\U0001f4e5 *Recibir env\u00edo*\n\n\u00bfEn qu\u00e9 local est\u00e1s?",
            reply_markup=_locales_kb("recibir_local"),
            parse_mode="Markdown",
        )
        return

    if data == "menu_cargar":
        estado_usuario[chat_id] = {"paso": "cargar_local"}
        await query.edit_message_text(
            "\U0001f4dd *Cargar stock*\n\n\u00bfQu\u00e9 local?",
            reply_markup=_locales_kb("cargar_local", include_cdp=False),
            parse_mode="Markdown",
        )
        return

    if data == "menu_fermentar":
        estado_usuario[chat_id] = {"paso": "fermentar_local"}
        await query.edit_message_text(
            "\U0001f525 *Fermentaci\u00f3n*\n\n\u00bfQu\u00e9 local?",
            reply_markup=_locales_kb("fermentar_local", include_cdp=False),
            parse_mode="Markdown",
        )
        return

    if data == "menu_ordenes":
        estado_usuario[chat_id] = {"paso": "ordenes_local"}
        await query.edit_message_text(
            "\U0001f4cb *Ordenes del d\u00eda*\n\n\u00bfQu\u00e9 local?",
            reply_markup=_locales_kb("ordenes_local", include_cdp=False),
            parse_mode="Markdown",
        )
        return

    if data == "menu_principal":
        estado_usuario.pop(chat_id, None)
        await query.edit_message_text(
            "\U0001f950 *Lharmonie*\n\n\u00bfQu\u00e9 hacemos?",
            reply_markup=_main_menu_kb(),
            parse_mode="Markdown",
        )
        return

    if data == "cancelar":
        estado_usuario.pop(chat_id, None)
        await query.edit_message_text(
            "Cancelado. Mand\u00e1 /start para volver al men\u00fa."
        )
        return

    # -- FLUJO ENVIAR ----------------------------------------------------------
    if data.startswith("enviar_dest_"):
        idx = int(data.split("_")[2])
        info = estado_usuario.get(chat_id, {})
        info["destino"] = LOCALES[idx]
        info["paso"] = "enviar_lista"
        estado_usuario[chat_id] = info
        await query.edit_message_text(
            f"\U0001f4e6 Env\u00edo a *{local_corto(LOCALES[idx])}*\n\n"
            f"Dale, mand\u00e1 la lista\\. Ej:\n"
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
            "\U0001f697 \u00bfC\u00f3mo se env\u00eda?",
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
            f"\U0001f4e6 Env\u00edo a *{local_corto(info.get('destino', '?'))}*\n\n"
            f"Dale, mand\u00e1 la lista de nuevo:",
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
                f"Intent\u00e1 de nuevo con /start",
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
            f"\U0001f4e6 *Nuevo env\u00edo*\n\n"
            f"\U0001f4cd CDP \u2192 *{local_corto(info['destino'])}*\n"
            f"\U0001f697 {info['transporte']}\n"
            f"\U0001f550 {info['hora']}\n\n"
            f"\U0001f4cb *Productos:*\n{resumen}"
        )
        for cid in NOTIFY_IDS:
            try:
                await context.bot.send_message(
                    chat_id=cid, text=msg_notif, parse_mode="Markdown"
                )
            except Exception:
                pass

        await query.edit_message_text(
            f"Listo, enviado a *{local_corto(info['destino'])}* \U0001f44d\n"
            f"{n_prods} productos registrados.",
            parse_mode="Markdown",
        )
        estado_usuario.pop(chat_id, None)
        return

    # -- FLUJO RECIBIR ---------------------------------------------------------
    if data.startswith("recibir_local_"):
        idx = int(data.split("_")[2])
        local = LOCALES[idx]
        await query.edit_message_text("Buscando env\u00edos pendientes...")

        pendientes, error_msg = obtener_envios_pendientes(local)
        if error_msg:
            await query.edit_message_text(f"Error: {esc(error_msg)}", parse_mode="Markdown")
            estado_usuario.pop(chat_id, None)
            return
        if not pendientes:
            await query.edit_message_text(
                f"No hay env\u00edos pendientes para *{local_corto(local)}* \U0001f44d",
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
            label = f"{env['fecha']} {env['hora']} \u2014 {local_corto(env['origen'])} ({n_prods} prod)"
            keyboard.append([InlineKeyboardButton(label, callback_data=f"recibir_env_{i}")])
        keyboard.append([InlineKeyboardButton("Cancelar", callback_data="cancelar")])
        await query.edit_message_text(
            f"\U0001f4e5 Env\u00edos pendientes para *{local_corto(local)}*:",
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
            f"\U0001f4e5 *Env\u00edo de {local_corto(env['origen'])}*\n"
            f"{env['fecha']} {env['hora']}\n\n"
            f"\U0001f4cb *Productos:*\n{resumen}\n\n"
            f"\U0001f464 Escrib\u00ed tu nombre:",
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
            f"\u2705 *Env\u00edo recibido*\n\n"
            f"\U0001f4cd {local_corto(env.get('origen', '?'))} \u2192 {local_corto(env.get('destino', '?'))}\n"
            f"\U0001f464 {esc(resp)}\n"
            f"\u23f1 {tiempo}\n"
            f"Todo OK"
        )
        for cid in NOTIFY_IDS:
            try:
                await context.bot.send_message(chat_id=cid, text=msg_notif, parse_mode="Markdown")
            except Exception:
                pass
        await query.edit_message_text(f"Recibido, todo OK \U0001f44d\nTiempo: {tiempo}")
        estado_usuario.pop(chat_id, None)
        return

    if data == "recibir_falta":
        info = estado_usuario.get(chat_id, {})
        info["paso"] = "recibir_diferencias"
        estado_usuario[chat_id] = info
        await query.edit_message_text("Decime qu\u00e9 falta:")
        return

    # -- FLUJO CARGAR STOCK ----------------------------------------------------
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
            f"\U0001f4dd *{local_corto(local)}*\n\n\u00bfQu\u00e9 zona?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )
        return

    if data.startswith("cargar_zona_"):
        idx = int(data.split("_")[2])
        info = estado_usuario.get(chat_id, {})
        zona = ZONAS[idx]
        info["cargar_zona"] = zona
        info["paso"] = "cargar_lista"
        estado_usuario[chat_id] = info

        # Send checklist first, then ask for input
        checklist = _build_zone_checklist(info["cargar_local"], zona)
        # Send checklist as a separate message (not editable)
        await query.message.reply_text(checklist)

        # Edit original message to input prompt
        await query.edit_message_text(
            f"\U0001f4dd *{local_corto(info['cargar_local'])}* \u2014 {zona}\n\n"
            f"Mand\u00e1 lo que ten\u00e9s\\. Ej:\n"
            f"`medialunas 30, budines 10`",
            parse_mode="MarkdownV2",
        )
        return

    # -- FLUJO FERMENTACION ----------------------------------------------------
    if data.startswith("fermentar_local_"):
        idx = int(data.split("_")[2])
        local = LOCALES_RETAIL[idx]
        info = estado_usuario.get(chat_id, {})
        info["fermentar_local"] = local
        info["paso"] = "fermentar_lista"
        estado_usuario[chat_id] = info
        await query.edit_message_text(
            f"\U0001f525 *{local_corto(local)}*\n\n"
            f"\u00bfQu\u00e9 sacaste a fermentar? Ej:\n"
            f"`medialunas 100, croissants 50`",
            parse_mode="MarkdownV2",
        )
        return

    # -- FLUJO ORDENES DEL DIA -------------------------------------------------
    if data.startswith("ordenes_local_"):
        idx = int(data.split("_")[2])
        local = LOCALES_RETAIL[idx]
        await query.edit_message_text("Calculando \u00f3rdenes...")

        try:
            msg = _generar_ordenes(local)
        except Exception as e:
            log.error(f"Error generando \u00f3rdenes: {e}")
            msg = f"Error generando \u00f3rdenes: {e}"

        # Send and go back to menu
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("\u2b05 Volver al men\u00fa", callback_data="menu_principal")]
        ])
        await query.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
        estado_usuario.pop(chat_id, None)
        return

    # -- FALLBACK: estado perdido ----------------------------------------------
    await query.edit_message_text(
        "Se perdi\u00f3 la sesi\u00f3n. Mand\u00e1 /start para empezar de nuevo.",
    )
    estado_usuario.pop(chat_id, None)


async def handle_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    texto = update.message.text.strip()

    if chat_id not in estado_usuario:
        await update.message.reply_text(
            "\U0001f950 *Lharmonie*\n\n\u00bfQu\u00e9 hacemos?",
            reply_markup=_main_menu_kb(),
            parse_mode="Markdown",
        )
        return

    info = estado_usuario[chat_id]
    paso = info.get("paso", "")

    # -- ENVIAR: lista de productos --------------------------------------------
    if paso == "enviar_lista":
        prods, cants, units, resumen = _procesar_lista_texto(texto)
        if not prods:
            await update.message.reply_text(
                "No entend\u00ed ning\u00fan producto. Mand\u00e1 algo como:\n"
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
                InlineKeyboardButton("\u2705 Listo", callback_data="enviar_confirmar"),
                InlineKeyboardButton("\u270f\ufe0f Corregir", callback_data="enviar_corregir"),
            ],
        ])
        await update.message.reply_text(
            f"\U0001f4e6 *{local_corto(info['destino'])}*\n\n"
            f"{resumen}\n\n"
            f"\u00bfEst\u00e1 bien?",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
        return

    # -- RECIBIR: nombre -------------------------------------------------------
    if paso == "recibir_nombre":
        info["nombre_recibir"] = texto
        info["paso"] = "recibir_ok_o_falta"
        estado_usuario[chat_id] = info
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("\u2705 Todo OK", callback_data="recibir_todo_ok"),
                InlineKeyboardButton("\u26a0\ufe0f Falta algo", callback_data="recibir_falta"),
            ],
        ])
        await update.message.reply_text(
            f"\U0001f464 {esc(texto)}\n\n\u00bfLleg\u00f3 todo bien?",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
        return

    # -- RECIBIR: diferencias --------------------------------------------------
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
            f"\u26a0\ufe0f *Env\u00edo con diferencias*\n\n"
            f"\U0001f4cd {local_corto(env.get('origen', '?'))} \u2192 {local_corto(env.get('destino', '?'))}\n"
            f"\U0001f464 {esc(resp)}\n"
            f"\U0001f4dd {esc(texto)}"
        )
        for cid in NOTIFY_IDS:
            try:
                await context.bot.send_message(chat_id=cid, text=msg_notif, parse_mode="Markdown")
            except Exception:
                pass
        await update.message.reply_text("Anotado, el equipo fue notificado \U0001f44d")
        estado_usuario.pop(chat_id, None)
        return

    # -- CARGAR STOCK: lista ---------------------------------------------------
    if paso == "cargar_lista":
        prods, cants, units, resumen = _procesar_lista_texto(texto)
        if not prods:
            await update.message.reply_text(
                "No entend\u00ed. Mand\u00e1 algo como:\n`medialunas 30, budines 10`",
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

            # Determine stock state based on zone
            obs_zona = f"carga stock {zona.lower()}"
            if zona.lower() == "mostrador":
                obs_zona = "carga stock mostrador horneado"
            elif zona.lower() == "barra":
                obs_zona = "carga stock barra horneado"

            errores = 0
            for j, prod in enumerate(prods):
                cant = _safe_int(cants[j] if j < len(cants) else "0")
                if cant <= 0:
                    continue
                ok, msg = stock_apply_movement(
                    sh, local, prod, TIPO_AJUSTE, cant,
                    zona=zona, responsable="",
                    chat_id=chat_id, observaciones=obs_zona,
                )
                if not ok:
                    errores += 1
                    log.warning(f"Error cargando {prod}: {msg}")
                _time.sleep(1)

            if errores:
                await update.message.reply_text(
                    f"Listo, pero hubo {errores} error(es). "
                    f"Revis\u00e1 el Sheet."
                )
            else:
                await update.message.reply_text("Listo, cargado \U0001f44d")
        except Exception as e:
            log.error(f"Error cargar stock: {e}")
            await update.message.reply_text(f"Error: {esc(str(e))}", parse_mode="Markdown")

        estado_usuario.pop(chat_id, None)
        return

    # -- FERMENTACION: lista ---------------------------------------------------
    if paso == "fermentar_lista":
        prods, cants, units, resumen = _procesar_lista_texto(texto)
        if not prods:
            await update.message.reply_text(
                "No entend\u00ed. Mand\u00e1 algo como:\n`medialunas 100, croissants 50`",
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
                    chat_id=chat_id, observaciones="fermentaci\u00f3n",
                )
                if not ok:
                    errores += 1
                    log.warning(f"Error fermentaci\u00f3n {prod}: {msg}")
                _time.sleep(1)

            if errores:
                await update.message.reply_text(
                    f"Anotado, pero hubo {errores} error(es). "
                    f"Revis\u00e1 el Sheet."
                )
            else:
                await update.message.reply_text("Anotado \U0001f44d")
        except Exception as e:
            log.error(f"Error fermentaci\u00f3n: {e}")
            await update.message.reply_text(f"Error: {esc(str(e))}", parse_mode="Markdown")

        estado_usuario.pop(chat_id, None)
        return

    # -- FALLBACK --------------------------------------------------------------
    await update.message.reply_text(
        "No entend\u00ed. Mand\u00e1 /start para volver al men\u00fa."
    )
    estado_usuario.pop(chat_id, None)


# -- ERROR HANDLER -------------------------------------------------------------
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log.error(f"Error no atrapado: {context.error}", exc_info=context.error)
    try:
        if update and update.effective_chat:
            chat_id = update.effective_chat.id
            estado_usuario.pop(chat_id, None)
            msg = "Hubo un error. Mand\u00e1 /start para empezar de nuevo."
            if update.callback_query:
                await update.callback_query.message.reply_text(msg)
            elif update.message:
                await update.message.reply_text(msg)
    except Exception as e:
        log.error(f"Error en error_handler: {e}")


# -- MAIN ----------------------------------------------------------------------
def main():
    if not TELEGRAM_TOKEN:
        print("Falta ENVIOS_TELEGRAM_TOKEN")
        return
    print("Iniciando Bot Envios Lharmonie v3...")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("enviar", cmd_enviar))
    app.add_handler(CommandHandler("recibir", cmd_recibir))
    app.add_handler(CommandHandler("cargar", cmd_cargar))
    app.add_handler(CommandHandler("fermentar", cmd_fermentar))
    app.add_handler(CommandHandler("ordenes", cmd_ordenes))

    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_texto))

    app.add_error_handler(error_handler)
    print("Bot Envios corriendo.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
