# CLAUDE_ARCHIVE.md — Lharmonie Bot Envios + Stock

> Archived lessons and resolved items from CLAUDE.md.
> Moved here 2026-04-23 to keep the main file concise.

---

## Resolved decisions / context (no longer need to be in main file)

- **17 abril 2026:** Eliminated step-by-step menus for envios and stock.
  Martin said "muy complejo". Replaced with texto libre (envios) and
  templates (stock). NUNCA volver a hacer flujos multi-step.
- **17 abril 2026:** Commands eliminated: `/stock`, `/reporte`, `/sugerencia`.
  Functions eliminated: `cmd_stock`, `cmd_reporte`, `_format_stock_for_local`,
  `_format_reporte_global`, all `cargar_*` step-by-step handlers.
- **17 abril 2026:** Bistrosoft Transacciones tab was stuck on March data.
  Fix deployed via STEP 5 in monthly_close.yml. API had no April data
  during Pesaj. Daily sync auto-adds when API has data.

---

## Detailed lessons (condensed versions in main CLAUDE.md)

1. The bot already does basic remitos + stock. Envio->recepcion->diferencia->stock
   flow exists. Bistrosoft integration for auto-audits still pending.

2. Catalog is editable from Sheets. Martin/Iara can add products without code.

3. Two bots share Railway project `satisfied-wholeness`. They share env vars
   but if one crashes the other continues.

4. Martin rejected 4-state model (CONGELADO->FERMENTANDO->HORNEADO->MOSTRADOR).
   Only CONGELADO and HORNEADO. Never propose again.

5. Martin wants everything in one Sheet. Envios, stock, movimientos — same
   Google Sheet. Never create separate sheets.

6. CDP operates separately from Nicaragua retail, even though physically same
   location. CDP is a logical unit for production/envios.

7. Products last max 2 days. Critical for transfer suggestions between locals.

8. Stock minimo comes from Bistrosoft Sheet tab "Stock Minimo" (avg qty per
   weekday x 2). Source of truth for order suggestions.

9. Lharmonie does NOT open Saturdays (Shabbat). Missing Saturday data is correct.

10. Future vision: standalone app. Martin said he wants "una sola app seria y
    prolija" eventually. For now: bot Telegram + Google Sheets.

11. TEXTO LIBRE > MENUS. Martin said menus were "muy complejo". Bot accepts
    direct text "medialunas 50, budines 20" with fuzzy matching. NEVER go back
    to multi-step flows for loading products.

12. Argentine Spanish, informal. "Dale", "manda", "listo", "anotado". Tuteo.
    Never formal ("Confirmar envio", "Desea usted").

13. Bot = INPUT, dashboard = OUTPUT. Bot does NOT show stock, reports, or
    suggestions. Only loads data. Martin: "para saber cuanto tiene que producir
    y cuanto enviar vamos a armar un dashboard".

14. Don't show summary to employee after loading. "El chiste es que no lo vean."
    Only confirm "Anotado".

15. DIRECTIVAS, not suggestions. Martin: "lo que tienen que sacar a fermentar o
    los envios no pueden ser sugerencias, tienen que ser un hecho." Renamed
    "Sugerencias" to "Ordenes del dia". Imperative tone.

16. Zone-aware product catalog. "Productos Envio" tab has 4 columns: Categoria,
    Producto, Unidad, Zona. Each product assigned to Cocina/Mostrador/Barra.

17. Bistrosoft Transacciones tab was broken (March only). RESOLVED: STEP 5 in
    monthly_close.yml restores rolling. Daily sync auto-adds new data.

18. TEMPLATE > MENUS for stock loading. Martin asked for pre-filled message.
    Bot sends template, employee fills numbers, sends back. 3 steps total
    instead of 8 per product. NEVER go back to step-by-step menus.

19. `_parsear_template()` details: Parses "Producto: N" per line. Ignores
    ": 0", ": _", emoji headers, empty lines. Strips fermentation context
    "(hay N)". Fuzzy matching against catalog for typo tolerance.

20. Cowork mount != git repo path. `bot-envios` mount is NOT the git repo
    (`cronklam-lharmonie-envios`). Must copy files to the repo mount before
    committing via GitHub Desktop.

21. TIPO_CARGA_STOCK movement type. Added "carga_stock" to distinguish manual
    stock loads from other movements. stock_apply_movement handles it by
    estado: congelado -> Congelado col, horneado -> Horneado col.

22. MarkdownV2 escaping bug. RESOLVED: switched to Markdown v1 or no parse_mode.

23. Google Forms are ABSOLUTE REFERENCE for products. Product names in code
    MUST match exactly with the 3 forms (Cocina/Mostrador/Barra).

24. CATALOG_VERSION forces re-sync. Compare against version in cell F1 of Sheet.
    If different, delete tab and recreate. To update: change _crear_productos_iniciales()
    AND bump CATALOG_VERSION.

25. Decimal quantities for kg. _parsear_template() supports float for kg items.
    Integers stay as int, decimals rounded to 3 places.

26. cargar_productos() MUST have cache and fallback. 3 layers: 10min memory cache,
    duplicate tab handling, hardcoded fallback. Bot NEVER shows "0 products".

27. Tab names with accents cause recurring bugs. "Productos Envio" vs "Productos
    Envío" are DIFFERENT names. Always search BOTH variants, create WITHOUT accent.

28. Products sourced from 3 Google Forms (85 total): Cocina (54), Mostrador (15),
    Barra (16). Visor Sheet uses IMPORTRANGE from another source Sheet.

29. Product update flow: (1) Check Google Forms, (2) Update _HARDCODED_PRODUCTS,
    (3) Bump CATALOG_VERSION, (4) Push -> Railway auto-deploy -> bot re-syncs.

30. Materia prima for CDP (19 abril 2026). Deposito zone visible ONLY for CDP.
    ~63 raw material products. Estado: "stock". LOCAL_KEYS includes "CDP".
    CATALOG_VERSION bumped to v4. Sync with products.ts in lharmonie-staff.

31. Cargar stock now shows ALL locales including CDP (19 abril 2026).

---

## Google Forms (fuente de productos)

| Form | ID | Zona | Productos |
|------|----|------|-----------|
| Stock Cocina | `1FAIpQLSfBvLTAuHOBB5ErPVWzk4INeXCjW_pdeBs7TybUvBoo6cQDgg` | Cocina | 54 |
| Stock Mostrador | `1FAIpQLSdd3jWPsStsixsDO22-BLEyn1P4XSguxKE2H6Ty_mfDSeFn6g` | Mostrador | 15 |
| Cafe y Barra | `1FAIpQLSertVa57F1w_89N73wmUCbAkUUZZFMZ322voaVaxIfpujYkCg` | Barra | 16 |

Visor Sheet: `1-M8WkjTjfVIpRI1ZFHgpMx7xsFLkwhvLM7-O0xfYSek`
