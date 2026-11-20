"""Apply V5 shadow-only additions to existing GOLD SCALP PRO files.

Anchored patching fails closed if the existing UI/backend source has drifted.
Never changes existing seven voting engines, model gates or trading endpoints.
"""
from pathlib import Path
ROOT=Path(__file__).resolve().parent


def replace_one(path,old,new):
    p=ROOT/path
    text=p.read_text(encoding='utf-8')
    count=text.count(old)
    if count!=1:raise RuntimeError(f'UNSAFE_PATCH_ANCHOR {path}: {count} occurrences of {old[:65]!r}')
    p.write_text(text.replace(old,new),encoding='utf-8')
    print('SHADOW_V5_PATCHED',path)

UI_FN=r''' function shadowV5Panel(s){
   if(!s||s.status==='NO_SHADOW_RECORD')return `<div class="qh-box"><h4>V5 · İleriye dönük gölge testi</h4><p class="qh-muted">Henüz ilk gerçek, önceden kaydedilmiş seans tahmini yok. Telefon/Render yerine GitHub Actions çalıştıracak.</p><p class="qh-muted">İşlem kararı: BEKLE · Gerçek emir yok.</p></div>`;
   if(s.status==='SOURCE_NOT_AVAILABLE_FOR_SYMBOL')return `<div class="qh-box"><h4>V5 · Gölge test</h4><p class="qh-muted">Bu gölge tahmin motoru yalnız Bitget XAUUSDT kaynağında etkin; XAUUSD spot ile birleştirilmez.</p></div>`;
   const f=s.latest_forecast||{},previous=s.last_settlement||{};
   const liveToday=Boolean(s.latest_forecast_is_today);
   const rawDirection=liveToday?(f.direction||'BEKLE'):'BEKLE';
   const tint=rawDirection==='LONG'?'#42b99d':rawDirection==='SHORT'?'#ef7c93':'#8d9fb6';
   const isCurrent=liveToday&&s.status==='SHADOW_RESEARCH_ONLY';
   return `<div class="qh-box" style="border:1px solid #385b73"><h4>V5 · İleriye dönük gölge tahmin</h4>
     <p class="qh-muted">GitHub bulut kaydı · Kaynak: ${escape(s.market||'Bitget XAUUSDT')} · ${escape(s.session_clock||'sabit UTC')}</p>
     <div class="qh-cards">
       <div class="qh-card" style="border-left:4px solid ${tint}"><span>Ham araştırma yönü (bugün)</span><strong style="color:${tint}">${escape(rawDirection)}</strong><small>Son kaydedilen gün: ${escape(f.day||'—')}</small></div>
       <div class="qh-card"><span>İşleme uygunluk</span><strong>BEKLE</strong><small>Canlı onay yok, gerçek emir yok</small></div>
       <div class="qh-card"><span>İleriye dönük kayıt</span><strong>${escape(n(s.forecasts_recorded??0))}</strong><small>Sonuçlanan: ${escape(n(s.sessions_settled??0))}</small></div>
       <div class="qh-card"><span>Kaçırılan seans</span><strong>${escape(n(s.sessions_missed??0))}</strong><small>GitHub gecikmesi/eksik veri izlenir</small></div>
     </div>
     ${isCurrent?`<p class="qh-muted">Ham yukarı yön skoru: %${escape(n((Number(f.raw_up_score)||0)*100))} — <strong>işlem kazanma olasılığı DEĞİL</strong>.</p>`:'<p class="qh-muted">Bugün için geçerli yeni gölge kaydı yok. Geçmiş tahmin güncel sinyal gibi kullanılmaz.</p>'}
     <p class="qh-muted">Model ${escape(f.model||'XGBoost')} · Eğitim örneği ${escape(n(f.train_sessions))} · Son tahmin UTC ${escape(f.timestamp_utc||'—')}</p>
     <p class="qh-muted">Örneklenmiş yön tahmininde ileri test isabeti: ${s.directional_accuracy_pct==null?'henüz hesaplanmadı':'%'+escape(n(s.directional_accuracy_pct))} · Brier: ${escape(n(s.brier))} · Hedef en az ${escape(n(s.min_forward_sessions_before_review))} ileri test gözlemi.</p>
     ${previous.day?`<p class="qh-muted">Son kapanmış Londra seansı: ${escape(previous.day)} · Tahmin ${escape(previous.forecast_direction)} / Gerçekleşen ${escape(previous.actual_direction)} · ${previous.correct==null?'BEKLE':'Yön '+(previous.correct?'doğru':'yanlış')}</p>`:''}
     <p class="qh-muted qh-danger">${escape(s.note||'Araştırma yönü, canlı alım satım onayı değildir.')} </p>
   </div>`;
 }
'''

def install():
    main='main.py'
    main_anchor="    out['requested_at_ms']=nowms()\n    return out"
    main_extra='''    # GOLD SHADOW V5: read-only, cloud-generated independent prospective journal.
    # Never modifies existing Soloshun/Quant Hub voting or orders.
    if isinstance(soloshun_mod,dict):
        try:
            from gold_shadow_v5 import public_status
            if not isinstance(soloshun_mod.get('quant_ai'),dict):
                soloshun_mod['quant_ai']={'mode':'ERROR','orders_enabled':False}
            soloshun_mod['quant_ai']['shadow_v5']=await asyncio.to_thread(public_status,symbol,ROOT)
        except Exception as shadow_exc:
            if isinstance(soloshun_mod.get('quant_ai'),dict):
                soloshun_mod['quant_ai']['shadow_v5']={
                   'status':'ERROR','error':err_text(shadow_exc),'orders_enabled':False,
                   'consensus_vote':False,'live_trade_signal':False}
'''
    replace_one(main,main_anchor,main_extra+main_anchor)
    js='gold_quant_hub.js'
    replace_one(js,' function quantAiPanel(ai){',UI_FN+' function quantAiPanel(ai){')
    replace_one(js,'   ${candidate}${error}<details','   ${candidate}${error}${shadowV5Panel(ai.shadow_v5)}<details')
    replace_one('index.html','gold_quant_hub.js?v=3500','gold_quant_hub.js?v=3600')
    print('V5_INSTALLED_READ_ONLY')

if __name__=='__main__':install()
