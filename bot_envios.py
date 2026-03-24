#!/usr/bin/env python3
"""
Bot de Telegram — Envíos entre locales Lharmonie
=================================================
Registra envíos de mercadería entre el centro de producción y los locales.
Catálogo de productos editable desde Google Sheets.
"""
import os
import io
import re
import json
import logging
import asyncio
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
LOCALES = [
    "Lharmonie 2 - Nicaragua 6068",
    "Lharmonie 3 - Maure 1516",
    "Lharmonie 4 - Zabala 1925",
    "Lharmonie 5 - Libertador 3118",
]
TRANSPORTES = ["🚗 Ezequiel (Mister)", "🚕 Uber"]
# IDs para notificaciones (Martín + Iaras)
NOTIFY_IDS = [
    6457094702,   # Martín
    5358183977,   # Iara Zayat
    7354049230,   # Iara Rodriguez
]
logging.basicConfig(format="%(asctime)s — %(levelname)s — %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)
# ── ESTADO DE USUARIOS ────────────────────────────────────────────────────────
estado_usuario = {}  # chat_id → {paso, datos del envío en curso...}
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
def cargar_productos() -> tuple:
    """
    Lee la pestaña 'Productos Envío' del Sheet.
    Retorna (dict categorías, dict unidades):
      - categorías: {categoría: [producto1, producto2, ...]}
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
        log.info(f"✅ Productos cargados: {sum(len(v) for v in productos.values())} en {len(productos)} categorías")
        return productos, unidades
    except Exception as e:
        log.error(f"❌ Error cargando productos: {e}")
        return {}, {}
def _crear_productos_iniciales(ws):
    """Crea el catálogo inicial de productos."""
    productos = [
        # Pastelería
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
    log.info(f"✅ Catálogo inicial creado: {len(rows)} productos")
EXPECTED_HEADERS = [
    "Fecha", "Hora", "Origen", "Destino", "Responsable envío",
    "Transporte", "Productos", "Cantidades", "Unidades",
    "Bultos", "Estado", "Responsable recepción", "Fecha recepción",
    "Recibido OK", "Diferencias", "Observaciones"
]


def _get_or_create_envios_ws(sh):
    """
    Obtiene o crea la pestaña 'Envíos'. Retorna (worksheet, created_bool).
    Levanta excepción si falla.
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
            log.info("✅ Pestaña 'Envíos' creada")
            return ws, True
        else:
            raise


def guardar_envio(datos: dict) -> tuple:
    """
    Guarda un envío en la pestaña 'Envíos' del Sheet.
    Retorna (True, None) si OK, o (False, "mensaje de error") si falló.
    """
    try:
        gc, sh = get_sheets_client()
        if not sh:
            return (False, "No se pudo conectar a Google Sheets. Verificá las credenciales.")

        ws, created = _get_or_create_envios_ws(sh)

        # Leer headers actuales y construir fila por nombre
        headers = ws.row_values(1)
        log.info(f"Headers actuales: {headers}")

        # FIX: Usar " | " como separador en vez de "\n" para que el sheet no
        # expanda filas y get_all_values() devuelva 1 fila por envío
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
        log.info(f"✅ Envío guardado: {datos.get('origen')} → {datos.get('destino')}")
        return (True, None)
    except Exception as e:
        log.error(f"❌ Error guardando envío: {e}")
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
    Trae envíos pendientes de recepción para un local.
    Retorna (lista_pendientes, error_msg_o_None).
    """
    try:
        gc, sh = get_sheets_client()
        if not sh:
            return ([], "No se pudo conectar a Google Sheets.")

        try:
            ws = sh.worksheet("Envíos")
        except Exception:
            return ([], None)  # No hay pestaña = no hay envíos, no es error

        all_values = ws.get_all_values()
        log.info(f"📊 Envíos sheet: {len(all_values)} filas totales")

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

            # FIX: Matching más robusto para Estado — busca "Enviado" en
            # cualquier formato: "📦 Enviado", "Enviado", etc.
            es_enviado = "enviado" in estado.lower() and "recibido" not in estado.lower() and "diferencia" not in estado.lower() and "congelado" not in estado.lower()

            # FIX: Matching de destino más flexible — compara por nombre corto
            destino_match = False
            if destino and local_destino:
                # Comparar nombre completo
                if local_destino.lower() in destino.lower() or destino.lower() in local_destino.lower():
                    destino_match = True
                # Comparar por nombre corto (solo la dirección)
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
        log.error(f"❌ Error obteniendo envíos pendientes: {e}")
        return ([], f"Error al buscar envíos: {e}")
def marcar_recibido(fila: int, responsable: str, recibido_ok: bool, diferencias: str = ""):
    """Marca un envío como recibido en el Sheet."""
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
        col_estado = col_idx("Estado")
        col_resp = col_idx("Responsable recepción")
        col_fecha = col_idx("Fecha recepción")
        col_ok = col_idx("Recibido OK")
        col_dif = col_idx("Diferencias")
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
        log.info(f"✅ Envío fila {fila} marcado como {estado}")
    except Exception as e:
        log.error(f"❌ Error marcando recibido: {e}")
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
    """Formatea una línea de producto con cantidad y unidad."""
    p = info["productos_lista"][j]
    c = info["cantidades_lista"][j]
    u = info["unidades_lista"][j] if j < len(info.get("unidades_lista", [])) else "u"
    return f"{p}: {c} {u}"
def _normalizar(texto: str) -> str:
    """Normaliza texto para comparación: minúsculas, sin acentos básicos."""
    t = texto.lower().strip()
    reemplazos = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ü": "u", "ñ": "n"}
    for k, v in reemplazos.items():
        t = t.replace(k, v)
    return t
def _buscar_producto_similar(nombre: str, productos_dict: dict, unidades_dict: dict = None, umbral: float = 0.6) -> tuple:
    """
    Busca el producto más similar en el catálogo.
    Retorna (nombre_encontrado, categoría, unidad) o (None, None, None) si no hay match.
    """
    nombre_norm = _normalizar(nombre)
    mejor_score = 0
    mejor_prod = None
    mejor_cat = None
    for cat, prods in productos_dict.items():
        for prod in prods:
            prod_norm = _normalizar(prod)
            # Match exacto normalizado
            if nombre_norm == prod_norm:
                return prod, cat, (unidades_dict or {}).get(prod, "u")
            # Uno contiene al otro
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
    # Separar por líneas, comas, o punto y coma
    partes = re.split(r'[,;\n]+', texto)
    for parte in partes:
        parte = parte.strip().lstrip('-•·').strip()
        if not parte:
            continue
        # Patrón: "10 medialunas" o "10x medialunas" o "10 x medialunas"
        m = re.match(r'^(\d+[\.,]?\d*)\s*[xX]?\s+(.+)$', parte)
        if m:
            items.append((m.group(1).strip(), m.group(2).strip()))
            continue
        # Patrón: "medialunas 10" o "medialunas: 10" o "medialunas x10"
        m = re.match(r'^(.+?)\s*[:xX]?\s*(\d+[\.,]?\d*)$', parte)
        if m and m.group(2):
            items.append((m.group(2).strip(), m.group(1).strip()))
            continue
        # Si no matchea nada, asumir cantidad 1
        items.append(("1", parte))
    return items
async def _mostrar_resumen_editable(query_or_msg, info, is_message=False):
    """Muestra el resumen editable con botones para editar/eliminar cada producto y datos del envío."""
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
    keyboard.append([InlineKeyboardButton("➕ Agregar más", callback_data="resumen_agregar_mas")])
    keyboard.append([InlineKeyboardButton(f"✅ Confirmar ({len(info['productos_lista'])})", callback_data="resumen_ok")])
    keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
    text = (
        f"📋 *Revisá antes de continuar:*\n\n"
        f"📍 *{local_corto(info['origen'])}* → *{local_corto(info['destino'])}*\n"
        f"👤 {esc(info.get('responsable', ''))}\n\n"
        f"{resumen}\n\n"
        f"_Tocá para editar cualquier dato._"
    )
    if is_message:
        await query_or_msg.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await query_or_msg.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
def agregar_producto_nuevo(nombre: str, categoria: str = "Varios", unidad: str = "u"):
    """Agrega un producto nuevo a la pestaña 'Productos Envío' del Sheet."""
    try:
        gc, sh = get_sheets_client()
        if not sh:
            return
        try:
            ws = sh.worksheet("Productos Envío")
        except:
            return
        ws.append_row([categoria, nombre, unidad])
        log.info(f"✅ Nuevo producto agregado al catálogo: {nombre} ({categoria})")
    except Exception as e:
        log.error(f"❌ Error agregando producto: {e}")
# ── HANDLERS ──────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📦 Nuevo envío", callback_data="menu_envio")],
        [InlineKeyboardButton("📥 Recibir envío", callback_data="menu_recibir")],
    ]
    await update.message.reply_text(
        "🥐 *Envíos Lharmonie*\n\n"
        "Registrá envíos de mercadería entre locales.\n\n"
        "¿Qué querés hacer?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    data = query.data
    # ── MENÚ PRINCIPAL ─────────────────────────────────────────────────
    if data == "menu_envio":
        estado_usuario[chat_id] = {"paso": "eligiendo_origen", "productos_lista": [], "cantidades_lista": [], "tipos_lista": [], "unidades_lista": []}
        keyboard = [[InlineKeyboardButton(local_corto(l), callback_data=f"origen_{i}")] for i, l in enumerate(LOCALES)]
        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
        await query.edit_message_text("📍 *¿De dónde sale el envío?*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return
    if data == "menu_recibir":
        estado_usuario[chat_id] = {"paso": "eligiendo_local_recibir"}
        keyboard = [[InlineKeyboardButton(local_corto(l), callback_data=f"recibir_local_{i}")] for i, l in enumerate(LOCALES)]
        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
        await query.edit_message_text("📍 *¿En qué local estás?*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return
    if data == "cancelar":
        estado_usuario.pop(chat_id, None)
        await query.edit_message_text("Cancelado.")
        return
    # ── FLUJO ENVÍO ────────────────────────────────────────────────────
    info = estado_usuario.get(chat_id)
    if info is None:
        # El bot se reinició y perdió el estado — volver al menú
        keyboard = [
            [InlineKeyboardButton("📦 Nuevo envío", callback_data="menu_envio")],
            [InlineKeyboardButton("📥 Recibir envío", callback_data="menu_recibir")],
        ]
        await query.edit_message_text(
            "⚠️ Se perdió la sesión (el bot se reinició).\n\n¿Qué querés hacer?",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return

    if data.startswith("origen_"):
        idx = int(data.split("_")[1])
        info["origen"] = LOCALES[idx]
        info["paso"] = "eligiendo_destino"
        keyboard = [[InlineKeyboardButton(local_corto(l), callback_data=f"destino_{i}")] for i, l in enumerate(LOCALES) if i != idx]
        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
        await query.edit_message_text(
            f"📍 Origen: *{local_corto(info['origen'])}*\n\n¿A dónde va el envío?",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return
    if data.startswith("destino_"):
        idx = int(data.split("_")[1])
        info["destino"] = LOCALES[idx]
        info["paso"] = "esperando_nombre"
        await query.edit_message_text(
            f"📦 *{local_corto(info['origen'])}* → *{local_corto(info['destino'])}*\n\n👤 Escribí tu nombre:",
            parse_mode="Markdown"
        )
        return
    # Elegir categoría
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
        keyboard.append([InlineKeyboardButton("⬅️ Volver a categorías", callback_data="volver_categorias")])
        keyboard.append([InlineKeyboardButton("✅ Terminar y enviar", callback_data="terminar_productos")])
        resumen = ""
        if info["productos_lista"]:
            lines = [f"  · {_fmt_prod_line(info, j)}" for j in range(len(info["productos_lista"]))]
            resumen = "\n\n📋 *Agregados:*\n" + "\n".join(lines)
        await query.edit_message_text(
            f"📦 *{local_corto(info['origen'])}* → *{local_corto(info['destino'])}*\n"
            f"🏷️ Categoría: *{cat}*\n\n"
            f"Elegí un producto:{resumen}",
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
            f"Elegí una categoría:{resumen}",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return
    if data == "carga_manual":
        info["paso"] = "esperando_carga_manual"
        await query.edit_message_text(
            "✏️ *Carga manual*\n\n"
            "Escribí los productos con cantidades, separados por coma o en líneas distintas.\n\n"
            "*Ejemplos:*\n"
            "  `10 medialunas, 5 brownies, 3 pan brioche`\n"
            "  `medialunas 10, croissants 5`\n"
            "  `10 x alfajores, 20 x cookies`\n\n"
            "Si el producto no existe en el catálogo, se agrega automáticamente.",
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
                f"Escribí la cantidad:",
                parse_mode="Markdown"
            )
        return
    # Terminar productos → resumen editable
    if data == "terminar_productos":
        if not info.get("productos_lista"):
            await query.answer("Agregá al menos un producto", show_alert=True)
            return
        info["paso"] = "resumen_editable"
        await _mostrar_resumen_editable(query, info)
        return
    # Editar un producto en el resumen — mostrar opciones
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
                f"¿Qué querés corregir?",
                reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
            )
        return
    # Sub-edición: cantidad
    if data.startswith("editcant_"):
        idx = int(data.split("_")[1])
        info["editando_idx"] = idx
        info["paso"] = "editando_cantidad"
        prod = info["productos_lista"][idx]
        u = info["unidades_lista"][idx] if idx < len(info.get("unidades_lista", [])) else "u"
        await query.edit_message_text(
            f"🔢 *{esc(prod)}* — Actual: *{info['cantidades_lista'][idx]} {u}*\n\n"
            f"Escribí la nueva cantidad:",
            parse_mode="Markdown"
        )
        return
    # Sub-edición: unidad
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
            f"📏 *{esc(prod)}* — Unidad actual: *{u_actual}*\n\nElegí la unidad correcta:",
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
    # Sub-edición: nombre del producto
    if data.startswith("editname_"):
        idx = int(data.split("_")[1])
        info["editando_idx"] = idx
        info["paso"] = "editando_nombre_prod"
        prod = info["productos_lista"][idx]
        await query.edit_message_text(
            f"📦 Producto actual: *{esc(prod)}*\n\n"
            f"Escribí el nombre correcto:",
            parse_mode="Markdown"
        )
        return
    # Volver al resumen desde sub-edición
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
            f"📍 Destino actual: *{local_corto(info['destino'])}*\n\n¿Cuál es el destino correcto?",
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
            f"Escribí el nombre correcto:",
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
                # Sin productos, volver a categorías
                info["paso"] = "eligiendo_categoria"
                productos, _ = cargar_productos()
                categorias = list(productos.keys())
                keyboard = [[InlineKeyboardButton(f"🏷️ {cat}", callback_data=f"cat_{cat}")] for cat in categorias]
                keyboard.append([InlineKeyboardButton("✏️ Carga manual", callback_data="carga_manual")])
                keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
                await query.edit_message_text(
                    "Se eliminaron todos los productos.\n\nElegí una categoría para agregar:",
                    reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
                )
                return
            await _mostrar_resumen_editable(query, info)
        return
    # Confirmar resumen → preguntar bultos
    if data == "resumen_ok":
        info["paso"] = "esperando_bultos_total"
        lines = [f"  · {_fmt_prod_line(info, j)}" for j in range(len(info["productos_lista"]))]
        resumen = "\n".join(lines)
        await query.edit_message_text(
            f"📦 *{local_corto(info['origen'])}* → *{local_corto(info['destino'])}*\n\n"
            f"📋 *Productos:*\n{resumen}\n\n"
            f"📦 ¿Cuántos bultos son en total?",
            parse_mode="Markdown"
        )
        return
    # Agregar más productos desde el resumen
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
            f"Elegí una categoría para agregar más:",
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
            [InlineKeyboardButton("✅ Confirmar envío", callback_data="confirmar_envio")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")],
        ]
        await query.edit_message_text(
            f"📦 *Confirmar envío*\n\n"
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

        # FIX: Ahora guardar_envio retorna (ok, error_msg)
        ok, error_msg = guardar_envio(info)

        if not ok:
            await query.edit_message_text(
                f"❌ *No se pudo guardar el envío*\n\n{esc(error_msg or 'Error desconocido')}\n\n"
                f"Intentá de nuevo con /start",
                parse_mode="Markdown"
            )
            estado_usuario.pop(chat_id, None)
            return

        # Notificar
        lines = [f"  · {_fmt_prod_line(info, j)}" for j in range(len(info["productos_lista"]))]
        resumen = "\n".join(lines)
        msg_notif = (
            f"📦 *Nuevo envío*\n\n"
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
            f"✅ *Envío registrado y guardado*\n\n"
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

        # FIX: Ahora obtener_envios_pendientes retorna (lista, error_msg)
        pendientes, error_msg = obtener_envios_pendientes(local)

        if error_msg:
            await query.edit_message_text(
                f"❌ *Error buscando envíos*\n\n{esc(error_msg)}",
                parse_mode="Markdown"
            )
            estado_usuario.pop(chat_id, None)
            return

        if not pendientes:
            await query.edit_message_text(
                f"✅ No hay envíos pendientes para *{local_corto(local)}*\\.",
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
            f"📥 *Envíos pendientes para {local_corto(local)}:*",
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
            f"📥 *Envío de {local_corto(env['origen'])}*\n"
            f"📅 {env['fecha']} {env['hora']}\n"
            f"👤 Envió: {esc(env['responsable'])}\n"
            f"🚗 {env['transporte']}\n"
            f"📦 Bultos: {bultos_str}\n\n"
            f"📋 *Productos:*\n{resumen}\n\n"
            f"👤 Escribí tu nombre para confirmar recepción:",
            parse_mode="Markdown"
        )
        return
    if data == "recibir_todo_ok":
        env = info.get("envio_a_recibir", {})
        resp = info.get("nombre_recibir", "")
        marcar_recibido(env["fila"], resp, recibido_ok=True)
        msg_notif = (
            f"✅ *Envío recibido*\n\n"
            f"📍 {local_corto(env['origen'])} → {local_corto(env['destino'])}\n"
            f"👤 Recibió: {esc(resp)}\n"
            f"📋 Todo OK"
        )
        for cid in NOTIFY_IDS:
            try:
                await context.bot.send_message(chat_id=cid, text=msg_notif, parse_mode="Markdown")
            except:
                pass
        await query.edit_message_text(f"✅ *Envío recibido correctamente.*", parse_mode="Markdown")
        estado_usuario.pop(chat_id, None)
        return
    if data == "recibir_con_diferencias":
        info["paso"] = "esperando_diferencias"
        await query.edit_message_text(
            "⚠️ Escribí qué diferencias encontraste:\n\n"
            "Ejemplo: _Faltaron 3 medialunas, llegaron 2 brownies de más_",
            parse_mode="Markdown"
        )
        return
async def handle_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    texto = update.message.text.strip()
    if chat_id not in estado_usuario:
        # Si no hay estado, mostrar menú
        keyboard = [
            [InlineKeyboardButton("📦 Nuevo envío", callback_data="menu_envio")],
            [InlineKeyboardButton("📥 Recibir envío", callback_data="menu_recibir")],
        ]
        await update.message.reply_text(
            "🥐 *Envíos Lharmonie*\n\n¿Qué querés hacer?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return
    info = estado_usuario[chat_id]
    paso = info.get("paso", "")
    # Nombre del que envía
    if paso == "esperando_nombre":
        info["responsable"] = texto
        info["paso"] = "eligiendo_categoria"
        productos, _ = cargar_productos()
        categorias = list(productos.keys())
        keyboard = [[InlineKeyboardButton(f"🏷️ {cat}", callback_data=f"cat_{cat}")] for cat in categorias]
        keyboard.append([InlineKeyboardButton("✏️ Carga manual", callback_data="carga_manual")])
        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
        await update.message.reply_text(
            f"👤 {esc(texto)}\n\nElegí una categoría de productos:",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return
    # Carga manual de productos
    if paso == "esperando_carga_manual":
        items = _parsear_carga_manual(texto)
        if not items:
            await update.message.reply_text(
                "❌ No pude interpretar ningún producto. Intentá de nuevo.\n\n"
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
            resumen_lines.append("*Productos nuevos (agregados al catálogo):*\n" + "\n".join(nuevos))
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
            f"Seguí agregando o terminá:",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return
    # Editando cantidad desde resumen editable
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
    # Editando nombre del producto
    if paso == "editando_nombre_prod":
        idx = info.get("editando_idx", 0)
        if idx < len(info["productos_lista"]):
            old = info["productos_lista"][idx]
            info["productos_lista"][idx] = texto.strip()
            info["paso"] = "resumen_editable"
            await update.message.reply_text(f"✅ *{esc(old)}* → *{esc(texto.strip())}*", parse_mode="Markdown")
            await _mostrar_resumen_editable(update.message, info, is_message=True)
        return
    # Editando responsable
    if paso == "editando_responsable":
        info["responsable"] = texto.strip()
        info["paso"] = "resumen_editable"
        await update.message.reply_text(f"✅ Responsable: *{esc(texto.strip())}*", parse_mode="Markdown")
        await _mostrar_resumen_editable(update.message, info, is_message=True)
        return
    # Cantidad del producto → agregar y volver a categorías
    if paso == "esperando_cantidad":
        prod = info.get("producto_actual", "")
        unidad = info.get("unidad_actual", "u")
        info["productos_lista"].append(prod)
        info["cantidades_lista"].append(texto)
        info["unidades_lista"].append(unidad)
        # Auto-assign type from category
        cat = info.get("categoria_actual", "Varios")
        tipo = cat if cat != "Varios" else "Producto Terminado"
        info["tipos_lista"].append(tipo)
        info["paso"] = "eligiendo_categoria"
        # Volver a categorías
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
            f"Elegí otra categoría o terminá:",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return
    # Bultos totales → elegir transporte
    if paso == "esperando_bultos_total":
        info["bultos_total"] = texto
        info["paso"] = "eligiendo_transporte"
        keyboard = [[InlineKeyboardButton(t, callback_data=f"transporte_{i}")] for i, t in enumerate(TRANSPORTES)]
        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
        await update.message.reply_text(
            f"📦 Bultos: *{texto}*\n\n🚗 ¿Cómo se envía?",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return
    # Nombre del que recibe
    if paso == "esperando_nombre_recibir":
        info["nombre_recibir"] = texto
        keyboard = [
            [InlineKeyboardButton("✅ Todo OK", callback_data="recibir_todo_ok")],
            [InlineKeyboardButton("⚠️ Hay diferencias", callback_data="recibir_con_diferencias")],
        ]
        await update.message.reply_text(
            f"👤 {esc(texto)}\n\n¿Llegó todo bien?",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return
    # Diferencias
    if paso == "esperando_diferencias":
        env = info.get("envio_a_recibir", {})
        resp = info.get("nombre_recibir", "")
        marcar_recibido(env["fila"], resp, recibido_ok=False, diferencias=texto)
        msg_notif = (
            f"⚠️ *Envío recibido con diferencias*\n\n"
            f"📍 {local_corto(env['origen'])} → {local_corto(env['destino'])}\n"
            f"👤 Recibió: {esc(resp)}\n"
            f"📝 Diferencias: {esc(texto)}"
        )
        for cid in NOTIFY_IDS:
            try:
                await context.bot.send_message(chat_id=cid, text=msg_notif, parse_mode="Markdown")
            except:
                pass
        await update.message.reply_text(f"⚠️ *Envío registrado con diferencias.*\nEl equipo fue notificado.", parse_mode="Markdown")
        estado_usuario.pop(chat_id, None)
        return
# ── MAIN ──────────────────────────────────────────────────────────────────────
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler global de errores — avisa al usuario en vez de quedar mudo."""
    log.error(f"❌ Error no atrapado: {context.error}", exc_info=context.error)
    try:
        if update and update.effective_chat:
            chat_id = update.effective_chat.id
            estado_usuario.pop(chat_id, None)
            keyboard = [
                [InlineKeyboardButton("📦 Nuevo envío", callback_data="menu_envio")],
                [InlineKeyboardButton("📥 Recibir envío", callback_data="menu_recibir")],
            ]
            if update.callback_query:
                await update.callback_query.message.reply_text(
                    "⚠️ Ocurrió un error. Empezá de nuevo:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            elif update.message:
                await update.message.reply_text(
                    "⚠️ Ocurrió un error. Empezá de nuevo:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
    except Exception as e:
        log.error(f"❌ Error en el error handler: {e}")


def main():
    if not TELEGRAM_TOKEN:
        print("❌ Falta ENVIOS_TELEGRAM_TOKEN")
        return
    print("🚚 Iniciando Bot Envíos Lharmonie...")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_texto))
    app.add_error_handler(error_handler)
    print("✅ Bot Envíos corriendo.")
    app.run_polling(drop_pending_updates=True)
if __name__ == "__main__":
    main()
