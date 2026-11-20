"""Idempotent minimal patch for GOLD ML V3 Binance archive fallback and mobile UI.
Operates only on four allowlisted local files in an Actions checkout.
No secrets, orders, workflow rewrites or external code downloads.
"""
from __future__ import annotations
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def once(text, old, new, label):
    if old not in text:
        if new in text:
            return text  # idempotent rerun
        raise RuntimeError(f'Expected {label} anchor not found — refusing patch')
    if text.count(old)!=1:
        raise RuntimeError(f'{label} anchor count unexpected: {text.count(old)}')
    return text.replace(old,new,1)


def patch_pipeline(s: str):
    api = "        response=_get_json('https://fapi.binance.com/fapi/v1/klines?'+params)"
    fallback = """        try:
            response=_get_json('https://fapi.binance.com/fapi/v1/klines?'+params)
        except RuntimeError as exc:
            # Official Binance public Vision files only; stop on archive 403/451.
            # No proxies, other exchanges, synthetic candles or model overclaims.
            from tools.binance_vision_archive import collect_official_archive
            return collect_official_archive(path, ROOT, rest_error=str(exc))"""
    s=once(s,api,fallback,'Binance HTTP REST fallback')
    print_line="    print('BINANCE_HISTORY',json.dumps(result,ensure_ascii=False))"
    updated="""    from tools.binance_vision_archive import record_rest_success
    record_rest_success(ROOT,result)
    print('BINANCE_HISTORY',json.dumps(result,ensure_ascii=False))"""
    s=once(s,print_line,updated,'Binance REST data health')
    manifest="    manifest=ARCHIVE/'manifest.json'"
    health="""    try:
        source_health=json.loads(SOURCE_STATUS.read_text(encoding='utf-8')) if SOURCE_STATUS.exists() else {}
        if not isinstance(source_health,dict):source_health={}
    except (OSError,ValueError):source_health={}
    manifest=ARCHIVE/'manifest.json'"""
    s=once(s,manifest,health,'ML V3 health read')
    sources="        'sources':all_reports,'storage':storage,'errors':errors,'no_trade':True,'no_live_prediction':True}"
    revised="        'sources':all_reports,'storage':storage,'source_health':source_health,'errors':errors,'no_trade':True,'no_live_prediction':True}"
    s=once(s,sources,revised,'ML V3 health report')
    return s


def patch_ui(s: str):
    old=" function multiModelResearchPanel(report){"
    new=""" function modelAuditCard(name,val){
   const t=val.final_holdout||{},score=Number(t.accuracy_pct),ref=Number(t.test_majority_pct);
   const known=Number.isFinite(score)&&Number.isFinite(ref);
   const ahead=known&&score>ref;
   const tone=known?(ahead?'#48afc7':'#eb8293'):'#8293aa';
   const pct=Number.isFinite(score)?Math.max(0,Math.min(100,score)):0;
   const difference=known?(score-ref):null;
   return `<div class="qh-card" style="border-left:3px solid ${tone};overflow-wrap:anywhere;min-width:0">
     <span>${escape(name)}</span><strong>${known?'%'+escape(n(score)):'—'}</strong>
     <div aria-label="Son test isabet yüzdesi" style="height:7px;overflow:hidden;border-radius:8px;background:#273c54;margin:8px 0"><div style="height:100%;width:${pct}%;background:linear-gradient(90deg,#334969,${tone})"></div></div>
     <small>Referans: %${escape(n(t.test_majority_pct))} · Fark: ${difference===null?'—':(difference>=0?'+':'')+escape(n(difference))} puan</small>
     <small>${escape(n(t.samples))} ileri test · Brier ${escape(n(t.brier))} / ref ${escape(n(t.baseline_brier))}</small>
   </div>`;
 }
 function multiModelResearchPanel(report){"""
    s=once(s,old,new,'mobile model metric formatting')
    old_row="return `<div class=\"qh-card\"><span>${escape(name)}</span><strong>${t.accuracy_pct==null?'—':'%'+escape(n(t.accuracy_pct))}</strong><small>İleri test ${escape(n(t.samples))} örnek · Brier ${escape(n(t.brier))} · Referans ${escape(n(t.baseline_brier))}</small></div>`"
    new_row="return modelAuditCard(name,val)"
    s=once(s,old_row,new_row,'mobile model scores')
    s=once(s,"   const sources=Object.entries(report.sources||{});","   const sources=Object.entries(report.sources||{});const health=report.source_health||{};",'source health variable')
    look="<p class=\"qh-muted\">Doğrulama dönemine göre seçilen model:"
    health_line="""${health[key]?.status?`<p class="qh-muted">Kaynak erişimi: ${escape(health[key].status)} · Arşiv doğrulanan paket: ${escape(n(health[key].packages_verified||0))} · ${escape((health[key].errors||[]).slice(0,2).join(' / '))}</p>`:''}
        <p class="qh-muted">Doğrulama dönemine göre seçilen model:"""
    s=once(s,look,health_line,'mobile source health')
    old_panel='${candidate}${error}${xgbResearchPanel(ai.ml)}'
    new_panel='${candidate}${error}<details class="qh-box"><summary style="cursor:pointer;font-weight:700">Eski XGBoost v1 · Ayrıntıları göster</summary>${xgbResearchPanel(ai.ml)}</details>'
    s=once(s,old_panel,new_panel,'collapse legacy model card')
    old_text='<p class="qh-muted">Model eğitim raporu UTC:'
    note='<p class="qh-muted">Renkler yalnız geçmiş test isabetini gösterir; canlı yön onayı veya kâr olasılığı DEĞİLDİR.</p>\n      <p class="qh-muted">Model eğitim raporu UTC:'
    s=once(s,old_text,note,'model score disclaimer')
    return s


def patch_report_reader(s: str):
    old="'storage':raw.get('storage',{}),'signal_policy':'NO_V3_LIVE_SIGNAL'}"
    new="'storage':raw.get('storage',{}),'source_health':{k:v for k,v in (raw.get('source_health') or {}).items() if k in allowed},'signal_policy':'NO_V3_LIVE_SIGNAL'}"
    return once(s,old,new,'per-symbol Binance source health isolation')


def patch_index(s: str):
    return once(s,'gold_quant_hub.js?v=3400','gold_quant_hub.js?v=3500','script cache buster')


def apply(root=ROOT):
    changes={
      'tools/gold_ml_v3_pipeline.py':patch_pipeline,
      'gold_quant_hub.js':patch_ui,
      'index.html':patch_index,
      'gold_ml_v3.py':patch_report_reader,
    }
    output={}
    for name,fn in changes.items():
        path=root/name
        original=path.read_text(encoding='utf-8')
        patched=fn(original)
        if patched==original:raise RuntimeError(f'No intended change for {name}')
        output[path]=patched
    # Commit only after all anchor checks succeeded: no partial mutations.
    for path,text in output.items():
        path.write_text(text,encoding='utf-8')
        print('PATCHED',path.relative_to(root))


if __name__=='__main__':apply()
