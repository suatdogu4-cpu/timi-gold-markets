"""Installer operates ONLY on current Soloshun panel, preserves all seven engines.

The GitHub Actions installer materializes source files and runs this script in the
repo root; no admin privileges or exchange trading keys are required.
"""
from pathlib import Path

BASE=Path(__file__).resolve().parents[1]

def exact_replace(path, old, new):
    p=BASE/path
    if not p.exists():raise RuntimeError(f'Required original missing: {p}')
    text=p.read_text(encoding='utf-8')
    if new in text:
        print('ALREADY_PATCHED',path);return
    count=text.count(old)
    if count!=1:
        raise RuntimeError(f'Unsafe patch: {path}: expected exactly one anchor, got {count}')
    p.write_text(text.replace(old,new),encoding='utf-8')


def install():
    anchor="    out['requested_at_ms']=nowms()\n    return out"
    addition='''    # GOLD ML V3: standard-library comparison report, research only, no new signal.
    if isinstance(soloshun_mod, dict):
        try:
            from gold_ml_v3 import report_for_symbol
            if not isinstance(soloshun_mod.get('quant_ai'), dict):
                soloshun_mod['quant_ai']={'mode':'ERROR','orders_enabled':False}
            soloshun_mod['quant_ai']['compare']=await asyncio.to_thread(report_for_symbol,symbol,ROOT)
        except Exception as compare_exc:
            if isinstance(soloshun_mod.get('quant_ai'), dict):
                soloshun_mod['quant_ai']['compare']={'status':'ERROR','error':err_text(compare_exc),
                    'orders_enabled':False,'consensus_vote':False,'prediction':None}
'''
    exact_replace('main.py',anchor,addition+anchor)
    helper=r''' function multiModelResearchPanel(report){
   if(!report||report.status==='NO_REPORT')return `<div class="qh-box"><h4>Çoklu ML · 26 özellik</h4><p class="qh-muted">XGBoost, LightGBM ve lojistik regresyonun yeni kronolojik raporu henüz üretilmedi. Araştırma sinyali kapalıdır.</p></div>`;
   if(report.status!=='RESEARCH_COMPARISON')return `<div class="qh-box"><h4>Çoklu ML · veri/rapor durumu</h4><p class="qh-muted qh-danger">${escape(report.status||'UNKNOWN')} · ${escape(report.error||'Rapor okunamadı')}</p></div>`;
   const sources=Object.entries(report.sources||{});
   const summary=sources.length?sources.map(([key,s])=>{
      const models=Object.entries(s.models||{});
      const rows=models.map(([name,val])=>{
        const t=val.final_holdout||{};
        return `<div class="qh-card"><span>${escape(name)}</span><strong>${t.accuracy_pct==null?'—':'%'+escape(n(t.accuracy_pct))}</strong><small>İleri test ${escape(n(t.samples))} örnek · Brier ${escape(n(t.brier))} · Referans ${escape(n(t.baseline_brier))}</small></div>`
      }).join('');
      return `<div class="qh-box"><h4>${escape(s.source?.exchange||key)} · ${escape(s.source?.symbol||'')}</h4><p class="qh-muted">H1 kapanmış mum: ${escape(n(s.audit?.valid_closed_h1))} · Seans: ${escape(n(s.samples))} · Özellik: ${escape(n(s.feature_count))}</p>
        <p class="qh-muted">Doğrulama dönemine göre seçilen model: <strong>${escape(s.selected_by_validation||'Yok')}</strong> · Geçmiş test kapısı: ${s.approved?'Geçti (canlıya kapalı)':'Geçmedi'}</p>
        <div class="qh-cards">${rows||'<p class="qh-muted">Yeterli veya doğrulanmış eğitim örneği yok.</p>'}</div>
        ${s.reason?`<p class="qh-muted">${escape(s.reason)}</p>`:''}</div>`;
   }).join(''):'<p class="qh-muted">Bu sembol için eğitim kaynağı bulunamadı.</p>';
   const storage=report.storage||{};
   return `<div class="qh-box"><h4>Çoklu ML · RSI / MACD / ATR / EMA / Rejim</h4>
      <p class="qh-muted">26 öznitelik · XGBoost / LightGBM / Lojistik Regresyon · 3 artan pencereli doğrulama + son %25 ileri test.</p>
      <p class="qh-muted">Model eğitim raporu UTC: ${escape(report.last_run_utc||'—')}</p>
      <p class="qh-muted">Kalıcı veri türü: ${escape(storage.storage_type||'HENÜZ ARŞİV YOK')}</p>
      ${summary}
      <p class="qh-muted qh-danger">BÜTÜN V3 MODELLERİ SADECE ARAŞTIRMA. Bu karşılaştırma konsensüse oy vermez, gerçek emir açmaz veya canlı LONG/SHORT tahmini üretmez.</p></div>`;
 }
'''
    # Insert a helper adjacent to other view functions. Existing code / tabs untouched.
    exact_replace('gold_quant_hub.js',' function quantAiPanel(ai){',helper+' function quantAiPanel(ai){')
    exact_replace('gold_quant_hub.js','${candidate}${error}${xgbResearchPanel(ai.ml)}',
                  '${candidate}${error}${xgbResearchPanel(ai.ml)}${multiModelResearchPanel(ai.compare)}')
    exact_replace('index.html','gold_quant_hub.js?v=3300','gold_quant_hub.js?v=3400')
    print('GOLD_ML_V3_INSTALL_PASS: existing Soloshun card extended only, read-only')

if __name__=='__main__':install()
