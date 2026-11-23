"""GOLD PROJECTION v1: safe, repeatable install into the existing Gold Scalp repo.

Run only after review/tests. Never changes trading decisions or existing 30G stats.
"""
from __future__ import annotations
from pathlib import Path
import os
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent

APP_MARKER = "['quant30','◷ 30G Fiyat–Zaman']"
NEW_MENU = "['projection','↗ Fiyat Projeksiyonu']"
GO_MARKER = "function go(k){if(k==='quant30'){window.location.assign('/gold30');return}page=k;"
NEW_GO = "function go(k){if(k==='projection'){window.location.assign('/gold-projection');return}if(k==='quant30'){window.location.assign('/gold30');return}page=k;"
MAIN_MARKER = "# GOLD PRICE PROJECTION v1.0 — read-only, separate research tab"
MAIN_ROUTES = '''

# GOLD PRICE PROJECTION v1.0 — read-only, separate research tab
@app.get('/gold-projection', include_in_schema=False)
async def gold_projection_page():
    return FileResponse(ROOT / 'gold_projection.html', media_type='text/html')

@app.get('/gold_projection.js', include_in_schema=False)
async def gold_projection_js():
    return FileResponse(ROOT / 'gold_projection.js', media_type='application/javascript')
'''


def patch(root: Path = ROOT) -> bool:
    paths = [root / n for n in ('main.py', 'gold_app.js', 'gold_projection.html', 'gold_projection.js', 'gold30_quant.py')]
    missing = [p.name for p in paths if not p.is_file()]
    if missing:
        raise RuntimeError('Eksik dosyalar: ' + ', '.join(missing))

    main, js = paths[0].read_text('utf-8'), paths[1].read_text('utf-8')
    # Prepare everything before mutating either file. Explicit source anchors make it fail closed.
    if "register_gold30(app, M, closed_bars, quant_hub_daily_history)" not in main:
        raise RuntimeError('Mevcut GOLD 30G motoru henüz bağlanmamış. Kurulum durduruldu.')
    if "FileResponse" not in main or "ROOT=Path(__file__)" not in main:
        raise RuntimeError('main.py kaynak / statik dosya bağlantısı beklenenden farklı.')
    if not (APP_MARKER in js or NEW_MENU in js):
        raise RuntimeError('Ana menü başlangıç noktası bulunamadı.')
    if GO_MARKER not in js and NEW_GO not in js:
        raise RuntimeError('Güncel menü geçiş kodu beklenenden farklı; güvenli kurulum durduruldu.')
    if MAIN_MARKER in main and ("@app.get('/gold-projection'" not in main or "@app.get('/gold_projection.js'" not in main):
        raise RuntimeError('Eksik / yarım uygulama endpointi var. Dosyaya dokunulmadı.')

    revised_main = main if MAIN_MARKER in main else main.rstrip() + '\n' + MAIN_ROUTES
    revised_js = js
    if NEW_MENU not in revised_js:
        revised_js = revised_js.replace(APP_MARKER, APP_MARKER + ',' + NEW_MENU, 1)
    if NEW_GO not in revised_js:
        revised_js = revised_js.replace(GO_MARKER, NEW_GO, 1)
    if NEW_MENU not in revised_js or NEW_GO not in revised_js:
        raise RuntimeError('Menü güncellemesi doğrulanmadı. Dosyaya dokunulmadı.')

    if revised_main == main and revised_js == js:
        print('Kurulu: GOLD PROJECTION (değişiklik yok)')
        return False
    # No interim half-replaced contents; staging and atomic replace per file.
    def staged_write(path, data):
        fd, tmp = tempfile.mkstemp(dir=str(root), prefix='.goldproj-')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as fh:
                fh.write(data)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    # All validations happened above.
    if revised_main != main:
        staged_write(paths[0], revised_main)
    if revised_js != js:
        staged_write(paths[1], revised_js)
    print('Kuruldu: /gold-projection (yeni sekme). GOLD 30G ve karar motoru değişmedi.')
    return True


if __name__ == '__main__':
    patch()
