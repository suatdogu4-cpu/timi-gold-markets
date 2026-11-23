"""Idempotent, fail-closed repo patcher: GOLD 30G API and app navigation."""
from pathlib import Path

ROOT=Path(__file__).resolve().parent
MAIN=ROOT/'main.py'
APP=ROOT/'gold_app.js'
PAGE=ROOT/'gold30.html'
MODULE=ROOT/'gold30_quant.py'

def patch():
    for f in (MAIN,APP,PAGE,MODULE):
        if not f.is_file():
            raise RuntimeError(f'Gerekli dosya eksik: {f.name}')
    # Verify exact known version anchors before writing ANY file.
    main=MAIN.read_text('utf-8')
    app=APP.read_text('utf-8')
    marker='from gold30_quant import register as register_gold30'
    nav="['quanthub','◈ 7 Quant + Konsensüs']"
    function='function go(k){page=k;'
    if marker not in main and 'async def quant_hub_daily_history(symbol):' not in main:
        raise RuntimeError('main.py Quant Hub tarihsel veri fonksiyonunu içermiyor. Güvenli kurulum durduruldu.')
    if "['quant30','◷ 30G Fiyat–Zaman']" not in app and nav not in app:
        raise RuntimeError('gold_app.js menü yapısı beklenenden farklı. Güvenli kurulum durduruldu.')
    if "window.location.assign('/gold30')" not in app and function not in app:
        raise RuntimeError('gold_app.js go() işlevi bulunamadı. Güvenli kurulum durduruldu.')
    if marker not in main:
        main+='\n\n# GOLD 30G QUANT v1.0 — isolated research page and API.\n'
        main+=marker+'\nregister_gold30(app, M, closed_bars, quant_hub_daily_history)\n'
    if "['quant30','◷ 30G Fiyat–Zaman']" not in app:
        app=app.replace(nav,nav+",['quant30','◷ 30G Fiyat–Zaman']",1)
    if "window.location.assign('/gold30')" not in app:
        app=app.replace(function,"function go(k){if(k==='quant30'){window.location.assign('/gold30');return}page=k;",1)
    MAIN.write_text(main,'utf-8')
    APP.write_text(app,'utf-8')
    print('GOLD 30G kayıt edildi: /gold30 ve /api/gold30. Mevcut karar motorları değiştirilmedi.')

if __name__=='__main__':
    patch()
