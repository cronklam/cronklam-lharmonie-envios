#!/usr/bin/env python3
"""
Bot de Telegram — Envíos entre locales Lharmonie
=================================================
Registra envíos de mercadería entre el centro de producción y los locales.
Catálogo de productos editable desde Google Sheets.
"""
import os
import io
import json
import logging
import asyncio
from datetime import datetime

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
    now = datetime.now().timestamp()
    if _sheets_cache["gc"] and (now - _sheets_cache["ts"]) < SHEETS_CACHE_TTL:
        return _sheets_cache["gc"], _sheets_cache["sh"]
    creds_json = GOOGLE_CREDS
    if not creds_json:
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

def cargar_productos() -> dict:
    """
    Lee la pestaña 'Productos Envío' del Sheet.
    Retorna dict: {categoría: [producto1, producto2, ...]}
    """
    try:
        gc, sh = get_sheets_client()
        if not sh:
            return {}
        try:
            ws = sh.worksheet("Productos Envío")
        except:
            # Crear pestaña con los productos iniciales si no existe
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
        for row in vals[header_idx + 1:]:
            if not any(row):
                continue
            cat = row[0].strip() if len(row) > 0 else ""
            prod = row[1].strip() if len(row) > 1 else ""
            if cat and prod:
                if cat not in productos:
                    productos[cat] = []
                productos[cat].append(prod)
        log.info(f"✅ Productos cargados: {sum(len(v) for v in productos.values())} en {len(productos)} categorías")
        return productos
    except Exception as e:
        log.error(f"❌ Error cargando productos: {e}")
        return {}


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
        ("Varios","
            if cat and prod:
                if cat not in productos:
                    productos[cat] = []
                productos[cat].append(prod)
        log.info(f"✅ Productos cargados: {sum(len(v) for v in productos.values())} en {len(productos)} categorías")
        return productos
    except Exception as e:
        log.error(f"❌ Error cargando productos: {e}")
        return {}


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
        ("Varios",                   "transporte": gcol(row, "Transporte"),
                    "productos": gcol(row, "Productos"),
                    "cantidades": gcol(row, "Cantidades"),
                    "bultos": gcol(row, "Bultos"),
                })
        return pendientes
    except Exception as e:
        log.error(f"❌ Error obteniendo envíos pendientes: {e}")
        return []


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

        ahora = datetime.now()
        estado = "✅ Recibido" if recibido_ok else "⚠️ Con diferencias"

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
        estado_usuario[chat_id] = {"paso": "eligiendo_origen", "productos_lista": [], "cantidades_lista": []}
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
    info = estado_usuario.get(chat_id, {})

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
        productos = cargar_productos()
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
            lines = []
            for j, p in enumerate(info["productos_lista"]):
                lines.append(f"  · {p}: {info['cantidades_lista'][j]}")
            resumen = "\n\n📋 *Agregados:*\n" + "\n".join(lines)

        await query.edit_message_text(
            f"📦 *{local_corto(info['origen'])}* → *{local_corto(info['destino'])}*\n"
            f"🏷️ Categoría: *{cat}*\n\n"
            f"Elegí un producto:{resumen}",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return

    if data == "volver_categorias":
        productos = cargar_productos()
        categorias = list(productos.keys())
        keyboard = [[InlineKeyboardButton(f"🏷️ {cat}", callback_data=f"cat_{cat}")] for cat in categorias]
        if info.get("productos_lista"):
            keyboard.append([InlineKeyboardButton(f"✅ Terminar y enviar ({len(info['productos_lista'])} productos)", callback_data="terminar_productos")])
        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])

        resumen = ""
        if info["productos_lista"]:
            lines = []
            for j, p in enumerate(info["productos_lista"]):
                lines.append(f"  · {p}: {info['cantidades_lista'][j]}")
            resumen = "\n\n📋 *Agregados:*\n" + "\n".join(lines)

        await query.edit_message_text(
            f"📦 *{local_corto(info['origen'])}* → *{local_corto(info['destino'])}*\n\n"
            f"Elegí una categoría:{resumen}",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return

    if data.startswith("prod_"):
        idx = int(data.split("_")[1])
        productos = cargar_productos()
        cat = info.get("categoria_actual", "")
        prods = productos.get(cat, [])
        if idx < len(prods):
            info["producto_actual"] = prods[idx]
            info["paso"] = "esperando_cantidad"
            await query.edit_message_text(
                f"📦 *{info['producto_actual']}*\n\n"
                f"Escribí la cantidad (número):",
                parse_mode="Markdown"
            )
        return

    # Terminar productos → preguntar bultos totales
    if data == "terminar_productos":
        if not info.get("productos_lista"):
            await query.answer("Agregá al menos un producto", show_alert=True)
            return
        info["paso"] = "esperando_bultos_total"

        lines = []
        for j, p in enumerate(info["productos_lista"]):
            lines.append(f"  · {p}: {info['cantidades_lista'][j]}")
        resumen = "\n".join(lines)

        await query.edit_message_text(
            f"📦 *{local_corto(info['origen'])}* → *{local_corto(info['destino'])}*\n\n"
            f"📋 *Productos:*\n{resumen}\n\n"
            f"📦 ¿Cuántos bultos son en total?",
            parse_mode="Markdown"
        )
        return

    if data.startswith("transporte_"):
        idx = int(data.split("_")[1])
        info["transporte"] = TRANSPORTES[idx]
        info["paso"] = "confirmando_envio"

        lines = []
        for j, p in enumerate(info["productos_lista"]):
            lines.append(f"  · {p}: {info['cantidades_lista'][j]}")
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
        ahora = datetime.now()
        info["fecha"] = ahora.strftime("%d/%m/%Y")
        info["hora"] = ahora.strftime("%H:%M")
        guardar_envio(info)

        # Notificar
        lines = []
        for j, p in enumerate(info["productos_lista"]):
            lines.append(f"  · {p}: {info['cantidades_lista'][j]}")
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
            f"✅ *Envío registrado*\n\n"
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
        pendientes = obtener_envios_pendientes(local)

        if not pendientes:
            await query.edit_message_text(f"✅ No hay envíos pendientes para {local_corto(local)}.")
            estado_usuario.pop(chat_id, None)
            return

        info["local_recibir"] = local
        info["pendientes"] = pendientes
        keyboard = []
        for i, env in enumerate(pendientes):
            n_prods = len(env["productos"].split("\n")) if env["productos"] else 0
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

        prods = env["productos"].split("\n")
        cants = env["cantidades"].split("\n")
        bultos = env["bultos"].split("\n")
        lines = []
        for j, p in enumerate(prods):
            c = cants[j] if j < len(cants) else "?"
            b = bultos[j] if j < len(bultos) else "?"
            lines.append(f"  · {p}: {c} — {b} bultos")
        resumen = "\n".join(lines)

        await query.edit_message_text(
            f"📥 *Envío de {local_corto(env['origen'])}*\n"
            f"📅 {env['fecha']} {env['hora']}\n"
            f"👤 Envió: {esc(env['responsable'])}\n"
            f"🚗 {env['transporte']}\n\n"
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
        productos = cargar_productos()
        categorias = list(productos.keys())
        keyboard = [[InlineKeyboardButton(f"🏷️ {cat}", callback_data=f"cat_{cat}")] for cat in categorias]
        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
        await update.message.reply_text(
            f"👤 {esc(texto)}\n\nElegí una categoría de productos:",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return

    # Cantidad del producto → agregar y volver a categorías
    if paso == "esperando_cantidad":
        prod = info.get("producto_actual", "")
        info["productos_lista"].append(prod)
        info["cantidades_lista"].append(texto)
        info["paso"] = "eligiendo_categoria"

        # Volver a categorías
        productos = cargar_productos()
        categorias = list(productos.keys())
        keyboard = [[InlineKeyboardButton(f"🏷️ {cat}", callback_data=f"cat_{cat}")] for cat in categorias]
        keyboard.append([InlineKeyboardButton(f"✅ Terminar y enviar ({len(info['productos_lista'])} productos)", callback_data="terminar_productos")])
        keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])

        lines = []
        for j, p in enumerate(info["productos_lista"]):
            lines.append(f"  · {p}: {info['cantidades_lista'][j]}")
        resumen = "\n".join(lines)

        await update.message.reply_text(
            f"✅ Agregado: *{prod}* — {texto}\n\n"
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
def main():
    if not TELEGRAM_TOKEN:
        print("❌ Falta ENVIOS_TELEGRAM_TOKEN")
        return
    print("🚚 Iniciando Bot Envíos Lharmonie...")

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_texto))

    print("✅ Bot Envíos corriendo.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
