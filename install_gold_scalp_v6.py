"""Safely add read-only GOLD SCALP V6 research panel to existing Soloshun."""
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def change_file(name, old, new):
    p=ROOT/name
    src=p.read_text(encoding='utf-8')
    if src.count(old)!=1:raise RuntimeError(f'Cannot safely locate exact V6 patch point: {name} count={src.count(old)}')
    p.write_text(src.replace(old,new),encoding='utf-8')

MAIN_OLD="    out['requested_at_ms']=nowms()\n    return out"
MAIN_NEW="""    # GOLD SCALP V6: read-only minute-scale research report. Zero trade actions.
    if isinstance(soloshun_mod,dict):
        try:
            from gold_scalp_v6_view import read_research
            if not isinstance(soloshun_mod.get('quant_ai'),dict):
                soloshun_mod['quant_ai']={'mode':'RESEARCH','orders_enabled':False}
            soloshun_mod['quant_ai']['scalp_v6']=await asyncio.to_thread(read_research,ROOT,symbol)
        except Exception as v6_exc:
            if isinstance(soloshun_mod.get('quant_ai'),dict):
                soloshun_mod['quant_ai']['scalp_v6']={'status':'ERROR','reason':err_text(v6_exc),
                    'live_signal':False,'trade_decision':'BEKLE','no_orders':True}
    out['requested_at_ms']=nowms()
    return out"""

JS_FUNC=r''' function scalpV6Panel(info){
   if(!info||info.status==='NO_REPORT')return `<details class="qh-box"><summary style="cursor:pointer;font-weight:700">GOLD SCALP LEARNING V6 · 1/3/5/15 dakika</summary><p class="qh-muted">Araştırma altyapısı kuruldu. İlk doğrulanmış 1 dakikalık geçmiş veri ve makine öğrenimi raporu bekleniyor. İşlem kararı: BEKLE.</p></details>`;
   if(info.status!=='RESEARCH_READY')return `<details class="qh-box"><summary>GOLD SCALP LEARNING V6 · Rapor sağlığı</summary><p class="qh-muted qh-danger">${escape(info.status)} · ${escape(info.reason||'')}</p></details>`;
   const labels={binance:'Binance · XAUUSDT Futures',bitget:'Bitget · XAUUSDT Futures'};
   const name={trend:'EMA + RSI + MACD',breakout:'Donchian kırılımı + momentum',reversion:'RSI + Bollinger dönüşü'};
   const rows=Object.entries(info.sources||{}).map(([id,s])=>{
     const tf=Object.entries(s.timeframes||{}).map(([period,m])=>{
       const best=m.best||{},cf=best.configuration||{},hold=best.holdout||{};
       const ml=m.ml||{},picked=ml.models?.[ml.selected_by_validation]?.final_holdout||{};
       const ok=m.status==='RETROSPECTIVE_GATE_PASSED';
       return `<div class="qh-box" style="min-width:0"><h4>${escape(period)} · ${ok?'Tarihsel filtre geçti':'Araştırma / BEKLE'}</h4>
        <p class="qh-muted">Doğrulanmış mum: ${escape(n(m.bars))} · Denenen kombinasyon: ${escape(n(m.tested_configurations||0))} · Uygun: ${escape(n(m.eligible_configurations||0))}</p>
        <p class="qh-muted">Seçilen: <strong>${escape(name[cf.family]||'Yok')}</strong> · Hacim x${escape(n(cf.vol_min))} · Saat: ${escape(cf.session||'—')} · Hassasiyet: ${escape(n(cf.sensitivity))}</p>
        <div class="qh-cards"><div class="qh-card"><span>Son bağımsız test · işlem</span><strong>${escape(n(hold.trades))}</strong></div>
        <div class="qh-card"><span>Net beklenti (bps/işlem)</span><strong>${escape(n(hold.expectancy_bps))}</strong></div>
        <div class="qh-card"><span>Profit Factor</span><strong>${escape(n(hold.profit_factor))}</strong></div>
        <div class="qh-card"><span>Maksimum düşüş (bps)</span><strong>${escape(n(hold.max_drawdown_bps))}</strong></div></div>
        <p class="qh-muted">ML seçimi: ${escape(ml.selected_by_validation||'—')} · ML isabet: ${escape(n(picked.accuracy_pct))}% · Çoğunluk ref.: ${escape(n(picked.majority_pct))}% · Test öncesi seçim</p>
        <p class="qh-muted qh-danger">${ok?'Geçmişte geçerli; gelecekte doğrulanmadı.':'Geçmiş test filtresini geçmedi.'} Gerçek işlem yok, otomatik LONG/SHORT onayı yok.</p></div>`;
     }).join('');
     return `<div class="qh-box"><h4>${escape(labels[id]||id)}</h4><p class="qh-muted">Kayıtlı gerçek 1m OHLCV: ${escape(n(s.one_minute_bars||0))} · Ayrı borsa veri seti</p>${tf||'<p class="qh-muted">1m veri bekleniyor.</p>'}</div>`;
   }).join('');
   return `<details class="qh-box" id="qh-scalp-v6"><summary style="cursor:pointer;font-weight:700">GOLD SCALP LEARNING V6 · 1/3/5/15 dakika</summary>
    <p class="qh-muted">Araştırma: indikatör + saat + hacim kombinasyonları · 3 kronolojik doğrulama dönemi · bağımsız son test. Rapora yazılma (UTC): ${escape(info.generated_utc||'—')}</p>
    <p class="qh-muted">Varsayılan maliyet (bps): yön başına komisyon ${escape(n(info.costs?.fee_bps_per_side))}, kayma ${escape(n(info.costs?.slippage_bps_per_side))}, gidiş-dönüş spread ${escape(n(info.costs?.spread_bps_roundtrip))}</p>
    ${rows}<p class="qh-muted qh-danger">BÜTÜN V6 DEĞERLERİ GEÇMİŞ TEST ARAŞTIRMASIDIR. İşleme uygunluk: BEKLE. Konsensüs oyu veya gerçek emir yoktur.</p></details>`;
 }
'''

def main():
    if 'GOLD SCALP V6: read-only' in (ROOT/'main.py').read_text(encoding='utf-8'):
        raise RuntimeError('V6 already installed: refusing duplicate patch')
    change_file('main.py',MAIN_OLD,MAIN_NEW)
    p=ROOT/'gold_quant_hub.js';s=p.read_text(encoding='utf-8')
    anchor=' function quantAiPanel(ai){'
    if s.count(anchor)!=1:raise RuntimeError('Cannot find Soloshun anchor')
    s=s.replace(anchor,JS_FUNC+anchor)
    old='${multiModelResearchPanel(ai.compare)}'
    if s.count(old)!=1:raise RuntimeError('Cannot find research panel render anchor')
    s=s.replace(old,old+'${scalpV6Panel(ai.scalp_v6)}')
    p.write_text(s,encoding='utf-8')
    idx=ROOT/'index.html';s=idx.read_text(encoding='utf-8')
    old='gold_quant_hub.js?v=3600';new='gold_quant_hub.js?v=3700'
    if s.count(old)!=1:raise RuntimeError('Cannot find current V5 JS cache version')
    idx.write_text(s.replace(old,new),encoding='utf-8')
    print('GOLD_V6_UI_INSTALLED Existing Soloshun panel; no order endpoint altered.')
if __name__=='__main__':main()
