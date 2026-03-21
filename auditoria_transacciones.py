#!/usr/bin/env python3
"""
Auditoría automática: cruza CAJA (RETIRO) de Transacciones Bistrosoft
con el sheet de Facturas Lharmonie. Carga faltantes con marca "Auditoría".

Uso:
  GOOGLE_SERVICE_ACCOUNT_JSON='{...}' python auditoria_transacciones.py [--desde FECHA] [--hasta FECHA] [--dry-run]
"""

import os, sys, json, re, time, argparse
from datetime import datetime, timedelta
from google.oauth2.service_account import Credentials
import gspread

# ─── CONFIG ───────────────────────────────────────────────────────────────────
TRANSACCIONES_SHEET_ID = "1RlvTiugazRb_mBbYOt0SeEa9fC9IgRYZqUZDJeDQezU"
TRANSACCIONES_TAB      = "Transacciones"

FACTURAS_SHEET_ID      = "1lZER27XWpUIaRIeosoJjMhXaclj8MS-6thOeQ3O3a8o"
FACTURAS_TAB           = "Facturas"

# Columnas Transacciones (0-indexed)
TX_DATE    = 0  # date
TX_HOUR    = 1  # hour
TX_SHOP    = 2  # shop
TX_AMOUNT  = 5  # amount
TX_PAY     = 6  # payment_method
TX_TYPE    = 7  # transaction_type
TX_USER    = 12 # user
TX_COMMENT = 13 # comments

# Columnas Facturas (0-indexed, fila de headers es la 2da fila = index 1)
# Fecha FC, Semana, Mes, Año, Proveedor, CUIT, Tipo Doc, # PV, # Factura,
# Categoría, Local, Cajero, Importe Neto, Descuento, IVA 21%, IVA 10.5%,
# Percep IIBB, Percep IVA, Total, Medio de Pago, Estado, Observaciones,
# Fecha de Pago, Procesado, Imagen

# ─── CATEGORÍAS ───────────────────────────────────────────────────────────────
# Mapeo de keywords en comments → (Categoría, emoji)
CATEGORIA_RULES = [
    # Gastos Martin y Melanie (dueños — NO es gasto de personal)
    (r'\b(melanie|martin)\b',
     '💼 Gasto Martin y Melanie'),

    # Personal / RRHH - nombres propios de empleados/pagos personales
    (r'\b(malena|cande|jaz|gabi|gabriel|nico|tomas|iara|pri prieto|sueldo|salario)\b',
     '👤 Personal / RRHH'),

    # Arreglos / Mantenimiento
    (r'\b(pintor|plomero|electricista|arreglo|reparaci|mantenimiento|obra|albañil|cerrajero)\b',
     '🔧 Arreglos / Mantenimiento'),

    # Logística / Flete
    (r'\b(uber|cabify|flete|envio|envío|delivery|moto|transporte|logistic)\b',
     '🚗 Logística / Flete'),

    # Verdulería / Frutería
    (r'\b(verduleria|verdulería|fruteria|frutería|banana|limon|limón|tomate|lechuga|papa|cebolla|verdura|fruta|naranja|manzana|palta|rucula|rúcula)\b',
     '🥬 Verdulería / Frutería'),

    # Materia Prima / Insumos (alimentos para producción)
    (r'\b(mantequilla|crema|harina|azucar|azúcar|leche|huevo|queso|jamon|jamón|materia prima|chocolate|vainilla|almendra|nuez|avena|yogurt|yogur|mani|maní|hielo)\b',
     '🍳 Materia Prima / Insumos'),

    # Compra de Insumos (insumos operativos)
    (r'\b(servilleta|vaso|bolsa|descartable|packaging|rollo|papel|filtro|pila|detergente|lavandina|alcohol|producto limpieza|insumo)\b',
     '📦 Compra de Insumos'),

    # Bebidas
    (r'\b(agua|gaseosa|cerveza|vino|coca|sprite|fernet|bebida|jugo)\b',
     '🥤 Bebidas'),

    # Proveedores conocidos
    (r'\b(proveedor|proveedores)\b',
     '🏪 Pago A Proveedores'),

    # Errores / Ajustes
    (r'\b(error|ajuste|devoluci|diferencia|faltante|sobrante|cobro tarjeta)\b',
     '⚠️ Ajustes / Errores'),

    # Prueba / Testing
    (r'\b(prueba|test)\b',
     '🧪 Prueba'),
]

# Tipos de CAJA que hay que IGNORAR (no son egresos reales)
IGNORE_TYPES = {'CAJA (APERTURA DE CAJA)', 'CAJA (APERTURA DE TURNO)',
                'CAJA (CIERRE DE CAJA)', 'CAJA (CIERRE DE TURNO)',
                'CAJA (AJUSTE EN CIERRE TURNO)'}

# Comments que indican cierre/retiro operativo (no egreso real)
IGNORE_COMMENTS = [
    r'retiro por cierre',
    r'cierre de turno',
    r'cierre de caja',
    r'apertura de caja',
    r'apertura de turno',
    r'^retiro\s*$',
]

# ─── SHOP → LOCAL mapping ────────────────────────────────────────────────────
SHOP_TO_LOCAL = {
    'LHARMONIE - LIBERTADOR 3118': 'Lharmonie 5 – Libertador 3118',
    'LHARMONIE - MAURE 1516':     'Lharmonie 3 – Maure 1516',
    'LHARMONIE ZABALA':           'Lharmonie 4 – Zabala 1925',
    'LHARMONIE NICARAGUA':        'Lharmonie 2 – Nicaragua 6068',
}


def get_client():
    creds_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not creds_json:
        print("ERROR: GOOGLE_SERVICE_ACCOUNT_JSON not set")
        sys.exit(1)
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(json.loads(creds_json), scopes=scopes)
    return gspread.authorize(creds)


def parse_date(s):
    """Parse DD-MM-YYYY or DD/MM/YYYY or YYYY-MM-DD."""
    for fmt in ('%d-%m-%Y', '%d/%m/%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    return None


def parse_money(s):
    """Parse Argentine money format: $1.234,56 or -$5.000,00 → float."""
    if not s:
        return 0.0
    s = s.strip().replace('$', '').replace('.', '').replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return 0.0


def categorize(comment):
    """Asigna categoría basada en el texto del comment."""
    if not comment:
        return '❓ Otro'
    c = comment.lower().strip()
    for pattern, cat in CATEGORIA_RULES:
        if re.search(pattern, c):
            return cat
    return '❓ Otro'


def extract_proveedor(comment):
    """Extrae nombre del proveedor del comment.
    Formato típico: 'COMPRA DE INSUMOS – limones' → 'Compra De Insumos – Limones'
    o 'PAGO A PROVEEDORES – hielo' → 'Pago A Proveedores – Hielo'
    o 'OTROS – uber' → 'Otros – Uber'
    """
    if not comment:
        return 'Sin detalle'
    # Limpiar y capitalizar
    return comment.strip().title()


def is_ignored_comment(comment):
    """Retorna True si el comment es un retiro/cierre que hay que ignorar."""
    if not comment:
        return True
    c = comment.lower().strip()
    for pat in IGNORE_COMMENTS:
        if re.search(pat, c):
            return True
    return False


def date_to_week(dt):
    """Retorna el número de semana del año."""
    return dt.isocalendar()[1]


def get_egresos_from_transacciones(gc, desde, hasta):
    """Lee CAJA (RETIRO) del sheet de Transacciones y filtra egresos reales."""
    print(f"  Leyendo Transacciones desde {desde.strftime('%d/%m/%Y')} hasta {hasta.strftime('%d/%m/%Y')}...")
    sh = gc.open_by_key(TRANSACCIONES_SHEET_ID)
    ws = sh.worksheet(TRANSACCIONES_TAB)
    all_rows = ws.get_all_values()

    headers = all_rows[0]
    data = all_rows[1:]
    print(f"  Total filas en Transacciones: {len(data)}")

    egresos = []
    for row in data:
        tx_type = row[TX_TYPE] if len(row) > TX_TYPE else ''
        # Solo CAJA (RETIRO)
        if tx_type != 'CAJA (RETIRO)':
            continue

        date_str = row[TX_DATE] if len(row) > TX_DATE else ''
        dt = parse_date(date_str)
        if not dt:
            continue

        # Filtrar por rango de fechas
        if dt < desde or dt > hasta:
            continue

        comment = row[TX_COMMENT] if len(row) > TX_COMMENT else ''

        # Ignorar retiros de cierre/apertura
        if is_ignored_comment(comment):
            continue

        amount = parse_money(row[TX_AMOUNT] if len(row) > TX_AMOUNT else '0')
        # Los retiros son negativos en Transacciones, los queremos positivos
        amount = abs(amount)

        if amount == 0:
            continue

        shop = row[TX_SHOP] if len(row) > TX_SHOP else ''
        hour = row[TX_HOUR] if len(row) > TX_HOUR else ''
        user = row[TX_USER] if len(row) > TX_USER else ''

        egresos.append({
            'fecha': dt,
            'fecha_str': dt.strftime('%d/%m/%Y'),
            'hora': hour,
            'shop': shop,
            'local': SHOP_TO_LOCAL.get(shop, shop),
            'amount': amount,
            'comment': comment,
            'proveedor': extract_proveedor(comment),
            'categoria': categorize(comment),
            'user': user,
        })

    print(f"  Egresos reales encontrados: {len(egresos)}")
    return egresos


def get_existing_facturas(gc, desde):
    """Lee facturas existentes para el cruce."""
    print(f"  Leyendo Facturas existentes...")
    sh = gc.open_by_key(FACTURAS_SHEET_ID)
    ws = sh.worksheet(FACTURAS_TAB)
    all_rows = ws.get_all_values()

    # Headers en fila 2 (index 1), data desde fila 3 (index 2)
    headers = all_rows[1] if len(all_rows) > 1 else []
    data = all_rows[2:] if len(all_rows) > 2 else []
    print(f"  Total facturas existentes: {len(data)}")

    facturas = []
    for i, row in enumerate(data):
        fecha_str = row[0] if row else ''
        dt = parse_date(fecha_str)
        if not dt:
            continue

        if dt < desde:
            continue

        proveedor = row[4] if len(row) > 4 else ''
        importe_neto = parse_money(row[12] if len(row) > 12 else '0')
        total = parse_money(row[18] if len(row) > 18 else '0')
        local = row[10] if len(row) > 10 else ''

        facturas.append({
            'row_idx': i + 3,  # 1-based, offset by title + headers
            'fecha': dt,
            'fecha_str': fecha_str,
            'proveedor': proveedor,
            'importe_neto': importe_neto,
            'total': total,
            'local': local,
        })

    return facturas


def find_match(egreso, facturas, tolerance=0.15):
    """Busca si un egreso ya existe en facturas.
    Matching: misma fecha + monto similar (±15%) + local compatible.
    """
    for f in facturas:
        # Misma fecha
        if f['fecha'].date() != egreso['fecha'].date():
            continue

        # Monto similar (±tolerance)
        if f['total'] == 0 and egreso['amount'] == 0:
            continue
        if f['total'] > 0:
            diff = abs(f['total'] - egreso['amount']) / max(f['total'], egreso['amount'])
            if diff > tolerance:
                continue
        else:
            continue

        # Si llegamos acá, es un match probable
        return f

    return None


def build_factura_row(egreso):
    """Construye una fila para insertar en el sheet de Facturas."""
    dt = egreso['fecha']
    semana = date_to_week(dt)
    mes = dt.strftime('%B').capitalize()
    anio = dt.year

    # Formato: $ X.XXX,XX (argentino)
    def fmt_money(v):
        if v == 0:
            return '$ 0'
        # Formato con punto de miles y coma decimal
        int_part = int(v)
        dec_part = round((v - int_part) * 100)
        int_str = f"{int_part:,}".replace(',', '.')
        if dec_part > 0:
            return f"$ {int_str},{dec_part:02d}"
        return f"$ {int_str}"

    return [
        egreso['fecha_str'],           # Fecha FC
        str(semana),                    # Semana
        mes,                            # Mes
        str(anio),                      # Año
        egreso['proveedor'],            # Proveedor
        '',                             # CUIT
        'Retiro Bistrosoft',            # Tipo Doc
        '',                             # # PV
        'AUDIT-0',                      # # Factura
        egreso['categoria'],            # Categoría
        egreso['local'],                # Local
        egreso['user'] or 'Bistrosoft', # Cajero
        fmt_money(egreso['amount']),    # Importe Neto
        '$ 0',                          # Descuento
        '$ 0',                          # IVA 21%
        '$ 0',                          # IVA 10.5%
        '$ 0',                          # Percep IIBB
        '$ 0',                          # Percep IVA
        fmt_money(egreso['amount']),    # Total
        '💰 Pagado – Efectivo',         # Medio de Pago
        '✅ Pagado previamente (Auditoría)',  # Estado
        f'Cargado por auditoría automática | Bistrosoft: {egreso["comment"]}',  # Observaciones
        egreso['fecha_str'],            # Fecha de Pago
        'auditoría',                    # Procesado
    ]


def append_facturas(gc, rows, dry_run=False):
    """Agrega filas al final del sheet de Facturas."""
    if not rows:
        print("  No hay filas para agregar.")
        return

    if dry_run:
        print(f"  [DRY RUN] Se agregarían {len(rows)} filas:")
        for r in rows:
            print(f"    {r[0]} | {r[4]} | {r[9]} | {r[18]} | {r[10]}")
        return

    print(f"  Agregando {len(rows)} filas a Facturas...")
    sh = gc.open_by_key(FACTURAS_SHEET_ID)
    ws = sh.worksheet(FACTURAS_TAB)

    # Agregar en lotes de 10 para evitar rate limiting
    batch_size = 10
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i+batch_size]
        ws.append_rows(batch, value_input_option='USER_ENTERED')
        print(f"    Lote {i//batch_size + 1}: {len(batch)} filas agregadas")
        if i + batch_size < len(rows):
            time.sleep(3)

    print(f"  ✅ {len(rows)} facturas agregadas exitosamente")


def main():
    parser = argparse.ArgumentParser(description='Auditoría Transacciones → Facturas')
    parser.add_argument('--desde', default='08-03-2026',
                        help='Fecha inicio DD-MM-YYYY (default: 08-03-2026)')
    parser.add_argument('--hasta', default=None,
                        help='Fecha fin DD-MM-YYYY (default: ayer)')
    parser.add_argument('--dry-run', action='store_true',
                        help='No escribir, solo mostrar qué se haría')
    parser.add_argument('--tolerance', type=float, default=0.15,
                        help='Tolerancia para matching de montos (default: 0.15 = 15%%)')
    args = parser.parse_args()

    desde = parse_date(args.desde)
    if not desde:
        print(f"ERROR: fecha inválida: {args.desde}")
        sys.exit(1)

    if args.hasta:
        hasta = parse_date(args.hasta)
    else:
        hasta = datetime.now() - timedelta(days=1)
        hasta = hasta.replace(hour=23, minute=59, second=59)

    print(f"═══ Auditoría Transacciones Bistrosoft ═══")
    print(f"  Período: {desde.strftime('%d/%m/%Y')} – {hasta.strftime('%d/%m/%Y')}")
    print(f"  Tolerancia matching: {args.tolerance*100:.0f}%")
    if args.dry_run:
        print(f"  ⚠️  MODO DRY RUN (no se escribirá nada)")
    print()

    gc = get_client()

    # 1. Obtener egresos de Transacciones
    print("PASO 1: Leyendo egresos de Transacciones Bistrosoft...")
    egresos = get_egresos_from_transacciones(gc, desde, hasta)
    if not egresos:
        print("  No se encontraron egresos en el período. ¿Tomás cargó las transacciones?")
        # Exit code 2 = no data (para retry logic)
        sys.exit(2)
    print()

    # 2. Obtener facturas existentes
    print("PASO 2: Leyendo facturas existentes...")
    facturas = get_existing_facturas(gc, desde)
    print()

    # 3. Cruzar y encontrar faltantes
    print("PASO 3: Cruzando datos...")
    faltantes = []
    matched = []
    for eg in egresos:
        match = find_match(eg, facturas, tolerance=args.tolerance)
        if match:
            matched.append((eg, match))
        else:
            faltantes.append(eg)

    print(f"  Egresos ya existentes en Facturas: {len(matched)}")
    print(f"  Faltantes a cargar: {len(faltantes)}")
    print()

    if matched:
        print("  Matches encontrados:")
        for eg, f in matched[:5]:
            print(f"    ✓ {eg['fecha_str']} {eg['proveedor']} ${eg['amount']:,.0f} ≈ {f['proveedor']} ${f['total']:,.0f}")
        if len(matched) > 5:
            print(f"    ... y {len(matched)-5} más")
        print()

    if faltantes:
        print("  Faltantes a cargar:")
        for eg in faltantes:
            print(f"    ✗ {eg['fecha_str']} | {eg['local']} | {eg['proveedor']} | {eg['categoria']} | ${eg['amount']:,.0f}")
        print()

    # 4. Construir filas y cargar
    print("PASO 4: Cargando faltantes...")
    new_rows = [build_factura_row(eg) for eg in faltantes]
    append_facturas(gc, new_rows, dry_run=args.dry_run)

    print()
    print(f"═══ Auditoría completada ═══")
    print(f"  Egresos analizados: {len(egresos)}")
    print(f"  Ya existían: {len(matched)}")
    print(f"  Nuevos cargados: {len(faltantes)}")

    # Resumen por categoría
    if faltantes:
        cats = {}
        for eg in faltantes:
            cats[eg['categoria']] = cats.get(eg['categoria'], 0) + 1
        print(f"\n  Por categoría:")
        for cat, count in sorted(cats.items(), key=lambda x: -x[1]):
            print(f"    {cat}: {count}")


if __name__ == '__main__':
    main()
