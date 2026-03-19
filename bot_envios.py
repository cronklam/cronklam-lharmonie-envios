#!/usr/bin/env python3
"""
Bot de Telegram â EnvÃ­os entre locales Lharmonie
=================================================
Registra envÃ­os de mercaderÃ­a entre el centro de producciÃ³n y los locales.
CatÃ¡logo de productos editable desde Google Sheets.
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

# ââ CONFIG ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
TELEGRAM_TOKEN = os.environ.get("ENVIOS_TELEGRAM_TOKEN", "8631530577:AAGM0J5qq2VqcZ7FaSeXP_UAtinPcAYW9jc")
SHEETS_ID      = os.environ.get("ENVIOS_SHEETS_ID", "")
GOOGLE_CREDS   = os.environ.get("GOOGLE_CREDENTIALS", "")

LOCALES = [
    "Lharmonie 2 - Nicaragua 6068",
    "Lharmonie 3 - Maure 1516",
    "Lharmonie 4 - Zabala 1925",
    "Lharmonie 5 - Libertador 3118",
]

TRANSPORTES = ["ð Ezequiel (Mister)", "ð Uber"]

# IDs para notificaciones (MartÃ­n + Iaras)
NOTIFY_IDS = [
    6457094702,   # MartÃ­n
    5358183977,   # Iara Zayat
    7354049230,   # Iara Rodriguez
]

logging.basicConfig(format="%(asctime)s â %(levelname)s â %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

# ââ ESTADO DE USUARIOS ââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
estado_usuario = {}  # chat_id â {paso, datos del envÃ­o en curso...}

# ââ GOOGLE SHEETS âââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
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
        log.error(f"â Error conectando a Sheets: {e}")
        return None, None

def cargar_productos() -> dict:
    """
    Lee la pestaÃ±a 'Productos EnvÃ­o' del Sheet.
    Retorna dict: {categorÃ­a: [producto1, producto2, ...]}
    """
    try:
        gc, sh = get_sheets_client()
        if not sh:
            return {}
        try:
            ws = sh.worksheet("Productos EnvÃ­o")
        except:
            # Crear pestaÃ±a con los productos iniciales si no existe
            ws = sh.add_worksheet("Productos EnvÃ­o", rows=200, cols=3)
            ws.append_row(["CategorÃ­a", "Producto", "Unidad"])
            _crear_productos_iniciales(ws)

        vals = ws.get_all_values()
        header_idx = 0
        for i, row in enumerate(vals):
            if "CategorÃ­a" in row or "Categoria" in row:
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
        log.info(f"â Productos cargados: {sum(len(v) for v in productos.values())} en {len(productos)} categorÃ­as")
        return productos
    except Exception as e:
        log.error(f"â Error cargando productos: {e}")
        return {}


def _crear_productos_iniciales(ws):
    """Crea el catÃ¡logo inicial de productos."""
    productos = [
        # PastelerÃ­a
        ("PastelerÃ­a", "Alfajor de chocolate", "u"),
        ("PastelerÃ­a", "Alfajor de nuez", "u"),
        ("PastelerÃ­a", "Alfajor de pistacho", "u"),
        ("PastelerÃ­a", "Barritas proteÃ­na", "u"),
        ("PastelerÃ­a", "Brownie", "u"),
        ("PastelerÃ­a", "BudÃ­n", "u"),
        ("PastelerÃ­a", "Cookie chocolate", "u"),
        ("PastelerÃ­a", "Cookie de manÃ­", "u"),
        ("PastelerÃ­a", "Cookie melu", "u"),
        ("PastelerÃ­a", "Cookie nuez", "u"),
        ("PastelerÃ­a", "Cookie red velvet", "u"),
        ("PastelerÃ­a", "Cuadrado de coco", "u"),
        ("PastelerÃ­a", "Muffin", "u"),
        ("PastelerÃ­a", "PorciÃ³n de dÃ¡tiles", "u"),
        ("PastelerÃ­a", "PorciÃ³n de torta", "u"),
        ("PastelerÃ­a", "Tarteleta", "u"),
        # Elaborados", "Bavka choco", "u"),
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
        ("Elaborados", "Tarta del dÃ­a", "u"),
        # Varios
        ("Varios", "Aceite de girasol", "u"),
        ("Varios", "Aceite de oliva cocina", "u"),
        ("Varios", "Aderezo caesar", "u"),
        ("Varios", "Almendras", "kg"),
        ("Varios", "Almendras fileteadas", "kg"),
        ("Varios", "Arroz yamani cocido", "kg"),
        ("Varios", "Arroz yamani crudo", "kg"),
        ("Varios", "Arvejas", "u"),
        ("Varios", "AzÃºcar comÃºn", "kg"),
        ("Varios", "AzÃºcar impalpable", "kg"),
        ("Varios", "Chocolate en barra", "u"),
        ("Varios", "Chocolate en trozos", "kg"),
        ("Varios", "Crema bariloche", "u"),
        ("Varios", "Crema pastelera de chocolate", "kg"),
        ("Varios", "Crema pastelera de panaderÃ­a", "kg"),
        ("Varios", "Dulce de leche", "kg"),
        ("Varios", "Frangipane", "kg"),
        ("Varios", "Frosting de queso", "g"),
        ("Varios", "Granola", "kg"),
        ("Varios", "Hongos cocidos", "u"),
        ("Varios", "Lomitos de atÃºn", "u"),
        ("Varios", "Maple de huevos", "u"),
        ("Varios", "Manteca comÃºn", "u"),
        ("Varios", "Manteca saborizada", "u"),
        ("Varios", "Mermelada de cocina", "u"),
        ("Varios", "Mermelada de frambuesa", "u"),
        ("Varios", "Miel", "u"),
        ("Varios", "Pasta de atÃºn", "g"),
        ("Varios", "Pasta de pistacho", "g"),
        ("Varios", "Pesto", "g"),
        ("Varios", "Picles de pepino", "u"),
        ("Varios", "Pistacho procesado", "g"),
        ("Varios", "PorciÃ³n de trucha grill", "u"),
        ("Varios", "Queso crema", "u"),
        ("Varios", "Queso sardo", "u"),
        ("Varios", "Queso tybo", "u"),
        ("Varios", "Quinoa cocida", "kg"),
        ("Varios", "Quinoa crocante", "kg"),
        ("Varios", "Salsa holandesa", "u"),
        ("Varios", "Vinagre", "u"),
        ("Varios", "Wraps de espinaca", "u"),
        ("Varios", "ManÃ­", "kg"),
        ("Varios", "Sal", "kg"),
    ]
    rows = [[cat, prod, unidad] for cat, prod, unidad in productos]
    ws.append_rows(rows)
    log.info(f"â CatÃ¡logo inicial creado: {len(rows)} productos")


def guardar_envio(datos: dict):
    """Guarda un envÃ­o en la pestaÃ±a 'EnvÃ­os' del Sheet."""
    try:
        gc, sh = get_sheets_client()
        if not sh:
            return
        try:
            ws = sh.worksheet("EnvÃ­os")
        except:
            ws = sh.add_worksheet("EnvÃ­os", rows=2000, cols=15)
            ws.append_row([
                "Fecha", "Hora", "Origen", "Destino", "Responsable envÃ­o",
                "Transporte", "Productos", "Cantidades", "Bultos",
                "Estado", "Responsable recepciÃ³n", "Fecha recepciÃ³n",
                "Recibido OK", "Diferencias", "Observaciones"
            ])

        productos_str = "\n".join(datos.get("productos_lista", []))
        cantidades_str = "\n".join(datos.get("cantidades_lista", []))
        bultos_str = datos.get("bultos_total", "")

        ws.append_row([
            datos.get("fecha", ""),
            datos.get("hora", ""),
            datos.get("origen", ""),
            datos.get("destino", ""),
            datos.get("responsable", ""),
            datos.get("transporte", ""),
            productos_str,
            cantidades_str,
            bultos_str,
            "ð¦ Enviado",
            "",  # responsable recepciÃ³n
            "",  # fecha recepciÃ³n
            "",  # recibido OK
            "",  # diferencias
            datos.get("observaciones", ""),
        ])
        log.info(f"â EnvÃ­o guardado: {datos.get('origen')} â {datos.get('destino')}")
    except Exception as e:
        log.error(f"â Error guardando envÃ­o: {e}")


def obtener_envios_pendientes(local_destino: str) -> list:
    """Trae envÃ­os pendientes de recepciÃ³n para un local."""
    try:
        gc, sh = get_sheets_client()
        if not sh:
            return []
        ws = sh.worksheet("EnvÃ­os")
        all_values = ws.get_all_values()
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
            if "Enviado" in estado and local_destino.lower() in destino.lower():
                pendientes.append({
                    "fila": i,
                    "fecha": gcol(row, "Fecha"),
                    "hora": gcol(row, "Hora"),
                    "origen": gcol(row, "Origen"),
                    "destino": destino,
                    "responsable": gcol(row, "Responsable envÃ­o"),
                    "transporte": gcol(row, "Transporte"),
                    "productos": gcol(row, "Productos"),
                    "cantidades": gcol(row, "Cantidades"),
                    "bultos": gcol(row, "Bultos"),
                })
        return pendientes
    except Exception as e:
        log.error(f"â Error obteniendo envÃ­os pendientes: {e}")
        return []


def marcar_recibido(fila: int, responsable: str, recibido_ok: bool, diferencias: str = ""):
    """Marca un envÃ­o como recibido en el Sheet."""
    try:
        gc, sh = get_sheets_client()
        if not sh:
            return
        ws = sh.worksheet("EnvÃ­os")
        headers = ws.row_values(1)

        def col_idx(name):
            try:
                return headers.index(name) + 1
            except:
                return None

        ahora = datetime.now()
        estado = "â Recibido" if recibido_ok else "â ï¸ Con diferencias"

        col_estado = col_idx("Estado")
        col_resp = col_idx("Responsable recepciÃ³n")
        col_fecha = col_idx("Fecha recepciÃ³n")
        col_ok = col_idx("Recibido OK")
        col_dif = col_idx("Diferencias")

        if col_estado:
            ws.update_cell(fila, col_estado, estado)
        if col_resp:
            ws.update_cell(fila, col_resp, responsable)
        if col_fecha:
            ws.update_cell(fila, col_fecha, ahora.strftime("%d/%m/%Y %H:%M"))
        if col_ok:
            ws.update_cell(fila, col_ok, "SÃ­" if recibido_ok else "No")
        if col_dif and diferencias:
            ws.update_cell(fila, col_dif, diferencias)

        log.info(f"â EnvÃ­o fila {fila} marcado como {estado}")
    except Exception as e:
        log.error(f"â Error marcando recibido: {e}")


# ââ HELPERS âââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
def esc(t) -> str:
    if t is None:
        return "-"
    s = str(t)
    for c in ["*", "_", "`", "["]:
        s = s.replace(c, "\\" + c)
    return s

def local_corto(local: str) -> str:
    return local.split(" - ")[-1].strip() if " - " in local else local


# ââ HANDLERS ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("ð¦ Nuevo envÃ­o", callback_data="menu_envio")],
        [InlineKeyboardButton("ð¥ Recibir envÃ­o", callback_data="menu_recibir")],
    ]
    await update.message.reply_text(
        "ð¥ *EnvÃ­os Lharmonie*\n\n"
        "RegistrÃ¡ envÃ­os de mercaderÃ­a entre locales.\n\n"
        "Â¿QuÃ© querÃ©s hacer?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    data = query.data

    # ââ MENÃ PRINCIPAL âââââââââââââââââââââââââââââââââââââââââââââââââ
    if data == "menu_envio":
        estado_usuario[chat_id] = {"paso": "eligiendo_origen", "productos_lista": [], "cantidades_lista": []}
        keyboard = [[InlineKeyboardButton(local_corto(l), callback_data=f"origen_{i}")] for i, l in enumerate(LOCALES)]
        keyboard.append([InlineKeyboardButton("â Cancelar", callback_data="cancelar")])
        await query.edit_message_text("ð *Â¿De dÃ³nde sale el envÃ­o?*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return

    if data == "menu_recibir":
        estado_usuario[chat_id] = {"paso": "eligiendo_local_recibir"}
        keyboard = [[InlineKeyboardButton(local_corto(l), callback_data=f"recibir_local_{i}")] for i, l in enumerate(LOCALES)]
        keyboard.append([InlineKeyboardButton("â Cancelar", callback_data="cancelar")])
        await query.edit_message_text("ð *Â¿En quÃ© local estÃ¡s?*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return

    if data == "cancelar":
        estado_usuario.pop(chat_id, None)
        await query.edit_message_text("Cancelado.")
        return

    # ââ FLUJO ENVÃO ââââââââââââââââââââââââââââââââââââââââââââââââââââ
    info = estado_usuario.get(chat_id, {})

    if data.startswith("origen_"):
        idx = int(data.split("_")[1])
        info["origen"] = LOCALES[idx]
        info["paso"] = "eligiendo_destino"
        keyboard = [[InlineKeyboardButton(local_corto(l), callback_data=f"destino_{i}")] for i, l in enumerate(LOCALES) if i != idx]
        keyboard.append([InlineKeyboardButton("â Cancelar", callback_data="cancelar")])
        await query.edit_message_text(
            f"ð Origen: *{local_corto(info['origen'])}*\n\nÂ¿A dÃ³nde va el envÃ­o?",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return

    if data.startswith("destino_"):
        idx = int(data.split("_")[1])
        info["destino"] = LOCALES[idx]
        info["paso"] = "esperando_nombre"
        await query.edit_message_text(
            f"ð¦ *{local_corto(info['origen'])}* â *{local_corto(info['destino'])}*\n\nð¤ EscribÃ­ tu nombre:",
            parse_mode="Markdown"
        )
        return

    # Elegir categorÃ­a
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
        keyboard.append([InlineKeyboardButton("â¬ï¸ Volver a categorÃ­as", callback_data="volver_categorias")])
        keyboard.append([InlineKeyboardButton("â Terminar y enviar", callback_data="terminar_productos")])

        resumen = ""
        if info["productos_lista"]:
            lines = []
            for j, p in enumerate(info["productos_lista"]):
                lines.append(f"  Â· {p}: {info['cantidades_lista'][j]}")
            resumen = "\n\nð *Agregados:*\n" + "\n".join(lines)

        await query.edit_message_text(
            f"ð¦ *{local_corto(info['origen'])}* â *{local_corto(info['destino'])}*\n"
            f"ð·ï¸ CategorÃ­a: *{cat}*\n\n"
            f"ElegÃ­ un producto:{resumen}",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return

    if data == "volver_categorias":
        productos = cargar_productos()
        categorias = list(productos.keys())
        keyboard = [[InlineKeyboardButton(f"ð·ï¸ {cat}", callback_data=f"cat_{cat}")] for cat in categorias]
        if info.get("productos_lista"):
            keyboard.append([InlineKeyboardButton(f"â Terminar y enviar ({len(info['productos_lista'])} productos)", callback_data="terminar_productos")])
        keyboard.append([InlineKeyboardButton("â Cancelar", callback_data="cancelar")])

        resumen = ""
        if info["productos_lista"]:
            lines = []
            for j, p in enumerate(info["productos_lista"]):
                lines.append(f"  Â· {p}: {info['cantidades_lista'][j]}")
            resumen = "\n\nð *Agregados:*\n" + "\n".join(lines)

        await query.edit_message_text(
            f"ð¦ *{local_corto(info['origen'])}* â *{local_corto(info['destino'])}*\n\n"
            f"ElegÃ­ una categorÃ­a:{resumen}",
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
                f"ð¦ *{info['producto_actual']}*\n\n"
                f"EscribÃ­ la cantidad (nÃºmero):",
                parse_mode="Markdown"
            )
        return

    # Terminar productos â preguntar bultos totales
    if data == "terminar_productos":
        if not info.get("productos_lista"):
            await query.answer("AgregÃ¡ al menos un producto", show_alert=True)
            return
        info["paso"] = "esperando_bultos_total"

        lines = []
        for j, p in enumerate(info["productos_lista"]):
            lines.append(f"  Â· {p}: {info['cantidades_lista'][j]}")
        resumen = "\n".join(lines)

        await query.edit_message_text(
            f"ð¦ *{local_corto(info['origen'])}* â *{local_corto(info['destino'])}*\n\n"
            f"ð *Productos:*\n{resumen}\n\n"
            f"ð¦ Â¿CuÃ¡ntos bultos son en total?",
            parse_mode="Markdown"
        )
        return

    if data.startswith("transporte_"):
        idx = int(data.split("_")[1])
        info["transporte"] = TRANSPORTES[idx]
        info["paso"] = "confirmando_envio"

        lines = []
        for j, p in enumerate(info["productos_lista"]):
            lines.append(f"  Â· {p}: {info['cantidades_lista'][j]}")
        resumen = "\n".join(lines)

        keyboard = [
            [InlineKeyboardButton("â Confirmar envÃ­o", callback_data="confirmar_envio")],
            [InlineKeyboardButton("â Cancelar", callback_data="cancelar")],
        ]
        await query.edit_message_text(
            f"ð¦ *Confirmar envÃ­o*\n\n"
¼'äãH
ÛØØ[ØÛÜÊ[ÖÉÛÜYÙ[×J_J8¡¤
ÛØØ[ØÛÜÊ[ÖÉÙ\Ý[É×J_J¼'äiÙ\ØÊ[ËÙ]
	Ü\ÜÛØXIË	ÉÊJ_W¼'æ¥ÈÚ[ÖÉÝ[ÜÜI×_W¼'äé[ÜÎÚ[ËÙ]
	Ø[Ü×ÝÝ[	Ë	ÏÉÊ_W¼'äâÈ
ÙXÝÜÎÜ\Ý[Y[H\WÛX\Ý\R[[RÙ^XØ\X\Ý\
Ù^XØ\
K\ÙWÛ[ÙOHX\ÙÝÛ
B]\Y]HOHÛÛ\X\Ù[[ÈZÜHH]][YKÝÊ
B[ÖÈXÚHHHZÜKÝ[YJYÉ[KÉVHB[ÖÈÜHHHZÜKÝ[YJRSHBÝX\\Ù[[Ê[ÊBÈÝYXØ\[\ÈH×BÜ[[[Y\]J[ÖÈÙXÝÜ×Û\ÝHJN[\Ë\[
0­ÈÜNÚ[ÖÉØØ[YY\×Û\ÝI×VÚ_HB\Ý[Y[HÚ[[\ÊB\Ù×ÛÝYH
¼'äé
Y]È[°ë[Ê¼'äãH
ÛØØ[ØÛÜÊ[ÖÉÛÜYÙ[×J_J8¡¤
ÛØØ[ØÛÜÊ[ÖÉÙ\Ý[É×J_J¼'äiÙ\ØÊ[ËÙ]
	Ü\ÜÛØXIË	ÉÊJ_W¼'æ¥ÈÚ[ÖÉÝ[ÜÜI×_W¼'äé[ÜÎÚ[ËÙ]
	Ø[Ü×ÝÝ[	Ë	ÏÉÊ_W¼'ådÚ[ÖÉÚÜI×_W¼'äâÈ
ÙXÝÜÎÜ\Ý[Y[H
BÜÚY[ÕQWÒQÎN]ØZ]ÛÛ^ÝÙ[ÛY\ÜØYÙJÚ]ÚYXÚY^[\Ù×ÛÝY\ÙWÛ[ÙOHX\ÙÝÛB^Ù\\ÜÂ]ØZ]]Y\KY]ÛY\ÜØYÙWÝ^
¸§!H
[°ë[ÈYÚ\ÝYÊ¼'äãHÛØØ[ØÛÜÊ[ÖÉÛÜYÙ[×J_H8¡¤ÛØØ[ØÛÜÊ[ÖÉÙ\Ý[É×J_W¼'äâÈÛ[[ÖÉÜÙXÝÜ×Û\ÝI×J_HÙXÝÜ×¼'æ¥ÈÚ[ÖÉÝ[ÜÜI×_H\ÙWÛ[ÙOHX\ÙÝÛ
B\ÝY×Ý\ÝX\[ËÜ
Ú]ÚYÛJB]\È8¥ 8¥ RÈPÒPT8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ Y]KÝ\ÝÚ]
XÚX\ÛØØ[ÈNYH[
]KÜ]
ÈVÌJBØØ[HÐÐSTÖÚYB[Y[\ÈHØ[\Ù[[Ü×Ü[Y[\ÊØØ[
BYÝ[Y[\Î]ØZ]]Y\KY]ÛY\ÜØYÙWÝ^
¸§!HÈ^H[°ë[ÜÈ[Y[\È\HÛØØ[ØÛÜÊØØ[
_KB\ÝY×Ý\ÝX\[ËÜ
Ú]ÚYÛJB]\[ÖÈØØ[ÜXÚX\HHØØ[[ÖÈ[Y[\ÈHH[Y[\ÂÙ^XØ\H×BÜK[[[[Y\]J[Y[\ÊNÜÙÈH[[ÈÙXÝÜÈKÜ]
JHY[ÈÙXÝÜÈH[ÙHÙ^XØ\\[
Ò[[RÙ^XØ\]ÛÙ[ÉÙXÚI×_HÙ[ÉÚÜI×_H8 %ÛØØ[ØÛÜÊ[ÉÛÜYÙ[×J_H
ÛÜÙßHÙ
HØ[XÚ×Ù]OYXÚX\Ù[ÞÚ_H
WJBÙ^XØ\\[
Ò[[RÙ^XØ\]Û¸§cØ[Ù[\Ø[XÚ×Ù]OHØ[Ù[\WJB]ØZ]]Y\KY]ÛY\ÜØYÙWÝ^
¼'äéH
[°ë[ÜÈ[Y[\È\HÛØØ[ØÛÜÊØØ[
_N\WÛX\Ý\R[[RÙ^XØ\X\Ý\
Ù^XØ\
K\ÙWÛ[ÙOHX\ÙÝÛ
B]\Y]KÝ\ÝÚ]
XÚX\Ù[ÈNYH[
]KÜ]
ÈVÌJB[Y[\ÈH[ËÙ]
[Y[\È×JBYYH[[Y[\ÊN]\[H[Y[\ÖÚYB[ÖÈ[[×ØWÜXÚX\HH[[ÖÈ\ÛÈHH\Ü\[×ÛÛXWÜXÚX\ÙÈH[ÈÙXÝÜÈKÜ]
BØ[ÈH[ÈØ[YY\ÈKÜ]
B[ÜÈH[È[ÜÈKÜ]
B[\ÈH×BÜ[[[Y\]JÙÊNÈHØ[ÖÚHY[Ø[ÊH[ÙHÈH[ÜÖÚHY[[ÜÊH[ÙHÈ[\Ë\[
0­ÈÜNØßH8 %ØH[ÜÈB\Ý[Y[HÚ[[\ÊB]ØZ]]Y\KY]ÛY\ÜØYÙWÝ^
¼'äéH
[°ë[ÈHÛØØ[ØÛÜÊ[ÉÛÜYÙ[×J_J¼'äáHÙ[ÉÙXÚI×_HÙ[ÉÚÜI×_W¼'äi[pìÎÙ\ØÊ[ÉÜ\ÜÛØXI×J_W¼'æ¥ÈÙ[ÉÝ[ÜÜI×_W¼'äâÈ
ÙXÝÜÎÜ\Ý[Y[W¼'äi\ØÜX°ëHHÛXH\HÛÛ\X\XÙ\ÚpìÛ\ÙWÛ[ÙOHX\ÙÝÛ
B]\Y]HOHXÚX\ÝÙ×ÛÚÈ[H[ËÙ]
[[×ØWÜXÚX\ßJB\ÜH[ËÙ]
ÛXWÜXÚX\BX\Ø\ÜXÚXYÊ[È[HK\ÜXÚXY×ÛÚÏUYJB\Ù×ÛÝYH
¸§!H
[°ë[ÈXÚXYÊ¼'äãHÛØØ[ØÛÜÊ[ÉÛÜYÙ[×J_H8¡¤ÛØØ[ØÛÜÊ[ÉÙ\Ý[É×J_W¼'äiXÚXpìÎÙ\ØÊ\Ü
_W¼'äâÈÙÈÒÈ
BÜÚY[ÕQWÒQÎN]ØZ]ÛÛ^ÝÙ[ÛY\ÜØYÙJÚ]ÚYXÚY^[\Ù×ÛÝY\ÙWÛ[ÙOHX\ÙÝÛB^Ù\\ÜÂ]ØZ]]Y\KY]ÛY\ÜØYÙWÝ^
¸§!H
[°ë[ÈXÚXYÈÛÜXÝ[Y[K\ÙWÛ[ÙOHX\ÙÝÛB\ÝY×Ý\ÝX\[ËÜ
Ú]ÚYÛJB]\Y]HOHXÚX\ØÛÛÙY\[ÚX\È[ÖÈ\ÛÈHH\Ü\[×ÙY\[ÚX\È]ØZ]]Y\KY]ÛY\ÜØYÙWÝ^
¸¦¨;î#È\ØÜX°ëH]pêHY\[ÚX\È[ÛÛ\ÝNZ[\ÎÑ[\ÛÈYYX[[\ËYØ\ÛÝÛY\ÈHpè\×È\ÙWÛ[ÙOHX\ÙÝÛ
B]\\Þ[ÈY[WÝ^Ê\]N\]KÛÛ^ÛÛ^\\ËQUSÕTJNÚ]ÚYH\]KYXÝ]WØÚ]Y^ÈH\]KY\ÜØYÙK^Ý\

BYÚ]ÚYÝ[\ÝY×Ý\ÝX\[ÎÈÚHÈ^H\ÝYË[ÜÝ\Y[°îÙ^XØ\HÂÒ[[RÙ^XØ\]Û¼'äéY]È[°ë[ÈØ[XÚ×Ù]OHY[WÙ[[ÈWKÒ[[RÙ^XØ\]Û¼'äéHXÚX\[°ë[ÈØ[XÚ×Ù]OHY[WÜXÚX\WKB]ØZ]\]KY\ÜØYÙK\WÝ^
¼'éd
[°ë[ÜÈ\[ÛYJ°¯Ô]pêH]Y\°ê\ÈXÙ\È\WÛX\Ý\R[[RÙ^XØ\X\Ý\
Ù^XØ\
K\ÙWÛ[ÙOHX\ÙÝÛ
B]\[ÈH\ÝY×Ý\ÝX\[ÖØÚ]ÚYB\ÛÈH[ËÙ]
\ÛÈBÈÛXH[]YH[°ëXBY\ÛÈOH\Ü\[×ÛÛXH[ÖÈ\ÜÛØXHHH^Â[ÖÈ\ÛÈHH[YÚY[×ØØ]YÛÜXHÙXÝÜÈHØ\Ø\ÜÙXÝÜÊ
BØ]YÛÜX\ÈH\Ý
ÙXÝÜËÙ^\Ê
JBÙ^XØ\HÖÒ[[RÙ^XØ\]Û¼'ãíûî#ÈØØ]HØ[XÚ×Ù]OYØ]ÞØØ]HWHÜØ][Ø]YÛÜX\×BÙ^XØ\\[
Ò[[RÙ^XØ\]Û¸§cØ[Ù[\Ø[XÚ×Ù]OHØ[Ù[\WJB]ØZ]\]KY\ÜØYÙK\WÝ^
¼'äiÙ\ØÊ^Ê_W[YðëH[HØ]YÛÜ°ëXHHÙXÝÜÎ\WÛX\Ý\R[[RÙ^XØ\X\Ý\
Ù^XØ\
K\ÙWÛ[ÙOHX\ÙÝÛ
B]\ÈØ[YY[ÙXÝÈ8¡¤YÜYØ\HÛ\HØ]YÛÜ°ëX\ÂY\ÛÈOH\Ü\[×ØØ[YYÙH[ËÙ]
ÙXÝ×ØXÝX[B[ÖÈÙXÝÜ×Û\ÝHK\[
Ù
B[ÖÈØ[YY\×Û\ÝHK\[
^ÊB[ÖÈ\ÛÈHH[YÚY[×ØØ]YÛÜXHÈÛ\HØ]YÛÜ°ëX\ÂÙXÝÜÈHØ\Ø\ÜÙXÝÜÊ
BØ]YÛÜX\ÈH\Ý
ÙXÝÜËÙ^\Ê
JBÙ^XØ\HÖÒ[[RÙ^XØ\]Û¼'ãíûî#ÈØØ]HØ[XÚ×Ù]OYØ]ÞØØ]HWHÜØ][Ø]YÛÜX\×BÙ^XØ\\[
Ò[[RÙ^XØ\]Û¸§!H\Z[\H[X\
Û[[ÖÉÜÙXÝÜ×Û\ÝI×J_HÙXÝÜÊHØ[XÚ×Ù]OH\Z[\ÜÙXÝÜÈWJBÙ^XØ\\[
Ò[[RÙ^XØ\]Û¸§cØ[Ù[\Ø[XÚ×Ù]OHØ[Ù[\WJB[\ÈH×BÜ[[[Y\]J[ÖÈÙXÝÜ×Û\ÝHJN[\Ë\[
0­ÈÜNÚ[ÖÉØØ[YY\×Û\ÝI×VÚ_HB\Ý[Y[HÚ[[\ÊB]ØZ]\]KY\ÜØYÙK\WÝ^
¸§!HYÜYØYÎ
ÜÙJ8 %Ý^ßW¼'äâÈ
ÙXÝÜÎÜ\Ý[Y[W[YðëHÝHØ]YÛÜ°ëXHÈ\Z[°èN\WÛX\Ý\R[[RÙ^XØ\X\Ý\
Ù^XØ\
K\ÙWÛ[ÙOHX\ÙÝÛ
B]\È[ÜÈÝ[\È8¡¤[YÚ\[ÜÜBY\ÛÈOH\Ü\[×Ø[Ü×ÝÝ[[ÖÈ[Ü×ÝÝ[HH^Â[ÖÈ\ÛÈHH[YÚY[×Ý[ÜÜHÙ^XØ\HÖÒ[[RÙ^XØ\]ÛØ[XÚ×Ù]OY[ÜÜWÞÚ_HWHÜK[[[Y\]JSÔÔTÊWBÙ^XØ\\[
Ò[[RÙ^XØ\]Û¸§cØ[Ù[\Ø[XÚ×Ù]OHØ[Ù[\WJB]ØZ]\]KY\ÜØYÙK\WÝ^
¼'äé[ÜÎ
Ý^ßJ¼'æ¥È0¯ÐðìÛ[ÈÙH[°ëXOÈ\WÛX\Ý\R[[RÙ^XØ\X\Ý\
Ù^XØ\
K\ÙWÛ[ÙOHX\ÙÝÛ
B]\ÈÛXH[]YHXÚXBY\ÛÈOH\Ü\[×ÛÛXWÜXÚX\[ÖÈÛXWÜXÚX\HH^ÂÙ^XØ\HÂÒ[[RÙ^XØ\]Û¸§!HÙÈÒÈØ[XÚ×Ù]OHXÚX\ÝÙ×ÛÚÈWKÒ[[RÙ^XØ\]Û¸¦¨;î#È^HY\[ÚX\ÈØ[XÚ×Ù]OHXÚX\ØÛÛÙY\[ÚX\ÈWKB]ØZ]\]KY\ÜØYÙK\WÝ^
¼'äiÙ\ØÊ^Ê_W°¯ÓYðìÈÙÈY[È\WÛX\Ý\R[[RÙ^XØ\X\Ý\
Ù^XØ\
K\ÙWÛ[ÙOHX\ÙÝÛ
B]\ÈY\[ÚX\ÂY\ÛÈOH\Ü\[×ÙY\[ÚX\È[H[ËÙ]
[[×ØWÜXÚX\ßJB\ÜH[ËÙ]
ÛXWÜXÚX\BX\Ø\ÜXÚXYÊ[È[HK\ÜXÚXY×ÛÚÏQ[ÙKY\[ÚX\Ï]^ÊB\Ù×ÛÝYH
¸¦¨;î#È
[°ë[ÈXÚXYÈÛÛY\[ÚX\Ê¼'äãHÛØØ[ØÛÜÊ[ÉÛÜYÙ[×J_H8¡¤ÛØØ[ØÛÜÊ[ÉÙ\Ý[É×J_W¼'äiXÚXpìÎÙ\ØÊ\Ü
_W¼'äçHY\[ÚX\ÎÙ\ØÊ^Ê_H
BÜÚY[ÕQWÒQÎN]ØZ]ÛÛ^ÝÙ[ÛY\ÜØYÙJÚ]ÚYXÚY^[\Ù×ÛÝY\ÙWÛ[ÙOHX\ÙÝÛB^Ù\\ÜÂ]ØZ]\]KY\ÜØYÙK\WÝ^
¸¦¨;î#È
[°ë[ÈYÚ\ÝYÈÛÛY\[ÚX\Ë[\]Z\ÈYHÝYXØYË\ÙWÛ[ÙOHX\ÙÝÛB\ÝY×Ý\ÝX\[ËÜ
Ú]ÚYÛJB]\È8¥ 8¥ PRS8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ 8¥ YXZ[
NYÝSQÔSWÕÒÑS[
¸§c[HSSÔ×ÕSQÔSWÕÒÑSB]\[
¼'æ¦[XÚX[ÈÝ[°ë[ÜÈ\[ÛYKB\H\XØ][ÛZ[\
KÚÙ[SQÔSWÕÒÑSKZ[

B\YÚ[\ÛÛ[X[[\Ý\ÛYÜÝ\
JB\YÚ[\Ø[XÚÔ]Y\R[\Ø[XÚ×Ú[\JB\YÚ[\Y\ÜØYÙR[\[\ËV	[\ËÓÓSPS[WÝ^ÊJB[
¸§!HÝ[°ë[ÜÈÛÜY[ËB\[ÜÛ[ÊÜÜ[[×Ý\]\ÏUYJBY×Û[YW×ÈOH×ÛXZ[×ÈXZ[
B
