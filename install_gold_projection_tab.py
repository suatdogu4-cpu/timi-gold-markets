"""GOLD SCALP PRO — embed existing projection UI as an actual app view.

This modifies only legacy front-end navigation and embedded-page presentation.
It does not touch market data, existing strategies, server routes or order logic.
Run: python install_gold_projection_tab.py
"""
from __future__ import annotations

from pathlib import Path
import os
import tempfile

ROOT = Path(__file__).resolve().parent
APP = 'gold_app.js'
INDEX = 'index.legacy.html'
PROJECTION = 'gold_projection.html'
NEW_VIEW = 'id="v-projection"'
NEW_GO = "function go(k){if(k==='quant30'){window.location.assign('/gold30');return}page=k;"
OLD_GO = "function go(k){if(k==='projection'){window.location.assign('/gold-projection');return}if(k==='quant30'){window.location.assign('/gold30');return}page=k;"
ANALYSIS_OPTION = "['projection','↗','Fiyat Projeksiyonu']"
EXISTING_QUANT_MENU = "['quanthub','◈','7 Quant + Konsensüs']"
GROUP_ANCHOR = "['quant','freqtrade','altinquant','quanthub']"
GROUP_NEW = "['quant','freqtrade','altinquant','quanthub','projection']"
DOCK_ANCHOR = "['technical','smc','flow','depth','quant','freqtrade','altinquant','quanthub','decision'].includes(k)"
DOCK_NEW = "['technical','smc','flow','depth','quant','freqtrade','altinquant','quanthub','projection','decision'].includes(k)"
SECTION_ANCHOR = '<section class="view" id="v-quanthub">'
PAGE_STYLE = '''
/* Keep /gold-projection as an internal asset route; hide duplicate chrome inside the application. */
.projection-embedded body{padding:5px 0 20px;background:#070e1a}
.projection-embedded header,.projection-embedded footer{display:none}
.projection-embedded .shell{max-width:none}
'''
PAGE_SCRIPT = '''<script>
if(new URLSearchParams(window.location.search).has('embed')){
  document.documentElement.classList.add('projection-embedded');
}
</script>
'''
VIEW = '''
<section class="view" id="v-projection" aria-label="Fiyat Projeksiyonu">
  <div class="sectiontop"><h2>↗ Fiyat Projeksiyonu</h2><span class="chip">5–120 dk · fiyat / yüzde / zaman</span></div>
  <p class="hint">Projeksiyon artık ana uygulamanın içinde açılır. Kesikli çizgiler geçmiş fiyat dağılımlarından türetilmiştir; gerçek gelecekteki hareket değildir.</p>
  <iframe id="projectionFrame" title="Altın fiyat ve zaman projeksiyon analizi" src="/gold-projection?embed=1"
          loading="lazy" style="display:block;width:100%;height:2200px;min-height:900px;border:0;border-radius:14px;background:#070e1a"></iframe>
</section>
<script>
(function(){
  var f=document.getElementById('projectionFrame');if(!f)return;
  f.addEventListener('load',function(){
    try{
      var d=f.contentDocument;
      if(!d||!d.body)return;
      var resize=function(){
        var h=Math.max(d.documentElement.scrollHeight,d.body.scrollHeight);
        if(Number.isFinite(h)&&h>0)f.style.height=Math.max(850,Math.min(10000,h+24))+'px';
      };
      resize();
      if(window.ResizeObserver){var observer=new ResizeObserver(resize);observer.observe(d.body);f._projectionObserver=observer;}
      f.contentWindow.addEventListener('resize',resize);
    }catch(e){f.style.height='2200px';}
  });
})();
</script>
'''


def replace_once(content: str, previous: str, replacement: str, label: str) -> str:
    if replacement in content:
        return content
    if content.count(previous) != 1:
        raise RuntimeError(f'{label}: beklenen kaynak işaretçisi yok veya birden fazla; güvenli kurulum durduruldu.')
    return content.replace(previous, replacement, 1)


def atomic_write(path: Path, data: str) -> None:
    fd, tmp = tempfile.mkstemp(prefix='.gold-projection-tab-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as file:
            file.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def patch(root: Path = ROOT) -> bool:
    paths = {filename: root/filename for filename in (APP,INDEX,PROJECTION)}
    for name,path in paths.items():
        if not path.is_file():
            raise RuntimeError('Eksik dosya: '+name)
    current = {name:path.read_text(encoding='utf-8') for name,path in paths.items()}
    app,index,html = current[APP],current[INDEX],current[PROJECTION]
    if "['projection','↗ Fiyat Projeksiyonu']" not in app:
        raise RuntimeError('Ana navigasyonda projeksiyon tanımı yok; önceki kurulum eksik.')
    if '<script defer src="/gold_projection.js' not in html:
        raise RuntimeError('Fiyat projeksiyonu HTML sürümü tanınmadı; güvenli kurulum iptal.')
    if '@app' in index:
        raise RuntimeError('Index dosyası beklenen HTML değil.')
    app = replace_once(app, OLD_GO, NEW_GO, 'Harici sayfa yönlendirmesi')
    app = replace_once(app, EXISTING_QUANT_MENU, EXISTING_QUANT_MENU+','+ANALYSIS_OPTION, 'Mobil analiz menüsü') if ANALYSIS_OPTION not in app else app
    app = replace_once(app, GROUP_ANCHOR, GROUP_NEW, 'Mobil Analiz → Matematik & Quant grubu')
    app = replace_once(app, DOCK_ANCHOR, DOCK_NEW, 'Mobil alt menü aktif durumu')
    if NEW_VIEW not in index:
        index = replace_once(index, SECTION_ANCHOR, VIEW+'\n'+SECTION_ANCHOR, 'Yeni uygulama sekmesi')
    if 'projection-embedded body' not in html:
        html = replace_once(html,'</style>',PAGE_STYLE+'</style>','Projeksiyon görünümü CSS')
    if "classList.add('projection-embedded')" not in html:
        html = replace_once(html,'</head>',PAGE_SCRIPT+'</head>','Projeksiyon yerleşimi')
    if OLD_GO in app or "window.location.assign('/gold-projection')" in app:
        raise RuntimeError('Eski sayfa yönlendirmesi halen mevcut.')
    if any(x not in app for x in (NEW_GO,ANALYSIS_OPTION,GROUP_NEW,DOCK_NEW)) or NEW_VIEW not in index:
        raise RuntimeError('Sekme/menu güncellemesi eksik; hiçbir dosya yazılmadı.')
    proposed={APP:app,INDEX:index,PROJECTION:html}
    changed=[name for name in proposed if proposed[name]!=current[name]]
    for name in changed:
        atomic_write(paths[name],proposed[name])
    print('GOLD Projeksiyon: '+('sekme uygulama içine kuruldu' if changed else 'zaten kurulu')+
          '. Güncellenenler: '+(', '.join(changed) if changed else 'yok'))
    return bool(changed)

if __name__=='__main__':
    patch()
