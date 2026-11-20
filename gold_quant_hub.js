/* GOLD QUANT HUB v3.0 — independent research-only mobile interface. */
(()=>{'use strict';
 const IDS=['consensus','soloshun','quantalytics','joshua','mcm','gsquant','nautilus','riskfolio'];
 const TITLES={consensus:'◈ Konsensüs',soloshun:'Asya–Londra',quantalytics:'Quantalytics',joshua:'Gold Prediction',mcm:'MCM 2022',gsquant:'GS Quant',nautilus:'Nautilus',riskfolio:'Riskfolio'};
 const FALLBACK={soloshun:'https://github.com/soloshun/Quantitative-XAUUSD-Strategy',quantalytics:'https://github.com/abhishukla0204/Quantalytics-26',joshua:'https://github.com/Joshua-Leow/gold_prediction',mcm:'https://github.com/Junxiao-Liao/MCM2022-Trading-Strategies-for-Gold-and-Bitcoin',gsquant:'https://github.com/goldmansachs/gs-quant',nautilus:'https://github.com/nautechsystems/nautilus_trader',riskfolio:'https://github.com/dcajasn/Riskfolio-Lib'};
 const LABELS={min_pairs:'Gerekli oturum günü',min_abs_corr:'Asgari |korelasyon|',session_shift_utc:'Seans UTC kayması',rsi_low:'RSI alt eşik',rsi_high:'RSI üst eşik',min_adx:'Asgari ADX',min_votes:'Gerekli yön koşulu',horizon:'Tahmin ufku (mum)',signal_threshold:'Ham model çıktı eşiği',min_test_lift:'İleri test baz başarı farkı',momentum_days:'Momentum günü',max_gold_pct:'Azami altın payı %',tail_pct:'Kuyruk yüzdesi',es_limit_pct:'ES üst sınırı %',max_vol_pct:'Volatilite sınırı %',fee_bps:'Komisyon bps / yön',slippage_bps:'Kayma bps / yön',spread_bps:'Gidiş-dönüş spread bps',max_hold_bars:'Azami bekleme (mum)',min_sample_trades:'Asgari ileri test işlem',risk_penalty:'Risk ceza katsayısı',gold_cap_pct:'Azami altın payı %',min_directional:'Asgari yön motoru',min_agreement_pct:'Asgari uzlaşı %',min_margin_pts:'Asgari skor farkı'};
 const $=id=>document.getElementById(id);
 const escape=s=>String(s??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const n=x=>typeof x==='number'&&Number.isFinite(x)?x.toLocaleString('tr-TR',{maximumFractionDigits:3}):String(x??'—');
 let active='consensus',catalog=null,report=null,config={},busy=false,lastError='';
 const KEY='gold-quant-hub-v3-settings';
 function save(){try{localStorage.setItem(KEY,JSON.stringify(config))}catch(e){}}
 function restore(){try{const s=JSON.parse(localStorage.getItem(KEY)||'{}');return s&&typeof s==='object'?s:{}}catch(e){return {}}}
 function nav(){const root=$('qh-tabs');if(!root)return;root.innerHTML=IDS.map(k=>`<button type="button" role="tab" class="qh-tab" aria-selected="${k===active}" data-hub-tab="${k}">${TITLES[k]}</button>`).join('');const current=root.querySelector('[aria-selected="true"]');if(current)current.scrollIntoView({block:'nearest',inline:'nearest'});}
 function badge(value){const k=value==='LONG'?'long':value==='SHORT'?'short':'wait';return `<span class="qh-chip ${k}">${escape(value||'BEKLE')}</span>`}
 function formatMetric(k,v){const aliases={train_samples:'Eğitim örneği',minimum_forward_samples:'Asgari ileri test örneği',
 minimum_required_accuracy_pct:'Gerekli ileri isabet %',validation_lift_pp:'Referansa göre fark (puan)',minimum_validation_lift_pp:'Asgari ek başarı (puan)',
 raw_direction_confidence_pct:'Ham yön gücü %',required_raw_confidence_pct:'Gerekli ham yön gücü %',
 available_daily_candles:'Kapanmış günlük mum',required_daily_candles:'Gerekli günlük mum',missing_daily_candles:'Eksik günlük mum',
 available_candles:'İncelenen mum',required_candles:'Asgari mum',closed_bars:'Kapalı mum',required_bars:'Gerekli mum',
 requested_horizon_bars:'Tahmin ufku',minimum_forward_trades:'Asgari ileri işlem',
 max_cost_to_atr:'Azami maliyet/ATR',forward_net_pnl_ref:'İleri net PnL (referans)',
 fee_bps_per_side:'Komisyon (bps/yön)',slippage_bps_per_side:'Kayma (bps/yön)',spread_bps_roundtrip:'Gidiş-dönüş spread (bps)',
 cost_gate_ok:'Maliyet filtresi',forward_sample_ok:'İleri örnek yeterli',forward_gate_ok:'İleri net beklenti filtresi',completed_pairs:'Seans çifti',asia_london_corr:'Asya–Londra korelasyonu',last_asia_return_pct:'Son Asya getirisi (%)',rsi14:'RSI14',adx14:'ADX14',macd_hist:'MACD histogram',bullish_conditions:'Yükseliş koşulu',bearish_conditions:'Düşüş koşulu',atr14:'ATR14',forward_samples:'İleri test örneği',forward_accuracy_pct:'İleri test isabet %',majority_baseline_pct:'Çoğunluk referansı %',raw_class_score_pct:'Ham model çıktısı %',horizon_bars:'Gelecek mum sayısı',daily_momentum_pct:'Günlük momentum %',illustrative_cash_pct:'Nakit ağırlığı %',illustrative_gold_pct:'Altın ağırlığı %',daily_var_pct:'Günlük VaR %',daily_es_pct:'Günlük ES %',var_pct:'VaR %',es_pct:'Expected Shortfall %',vol_pct:'Bar volatilitesi %',trades:'Simülasyon işlemi',forward_trades:'İleri dönem işlem',profit_factor:'Profit Factor',pnl_ref:'Referans net sonuç',roundtrip_cost_bps:'Gidiş–dönüş toplam maliyet (bps)',cost_to_atr_ratio:'Maliyet/ATR oranı',forward_avg_pnl_ref:'İleri dönem ort. PnL (ref)',optimized_tail_loss_pct:'Optimizasyon kuyruk kaybı %',expected_daily_pct_shrunk:'Muhafazakâr günlük ortalama %',daily_samples:'Günlük örnek'};
 return aliases[k]||k.replaceAll('_',' ')}
 function metricsCard(metrics){const entries=Object.entries(metrics||{});return entries.length?`<div class="qh-cards">${entries.map(([k,v])=>`<div class="qh-card"><span>${escape(formatMetric(k,v))}</span><strong>${escape(n(v))}</strong></div>`).join('')}</div>`:'<p class="qh-muted">Doğrulanmış ölçüm henüz yok.</p>'}
 function settingsBox(id){const settings=catalog?.sources?.find(x=>x.id===id)|| (id==='consensus'?catalog?.consensus:null);
  if(!settings)return '<p class="qh-muted">Ayarlar yüklenmedi.</p>';
  const rules=settings.rules||{};const cfg=config[id]||settings.settings||{};
  return `<div class="qh-box"><h4>${id==='consensus'?'Konsensüs eşikleri':'Bu motora özel ayarlar'}</h4><div class="qh-params">${Object.entries(cfg).map(([k,v])=>{const [min,max,step]=rules[k]||[0,100,1];return `<label class="qh-param">${escape(LABELS[k]||k)}<input type="number" inputmode="decimal" data-hub-config="${id}" data-param="${k}" min="${min}" max="${max}" step="${step}" value="${escape(v)}"></label>`}).join('')}</div><div class="qh-action-row"><button class="qh-secondary" type="button" data-hub-reset="${id}">Bu motoru sıfırla</button><span class="qh-muted">Değişiklikler kaydedilir; yeniden analiz için üstteki butonu kullan.</span></div></div>`}
 function directionBar(tone,score){return `<div class="qh-progress ${tone}"><i style="width:${Math.max(0,Math.min(100,Number(score)||0))}%"></i></div>`}
 function sourceLink(k){const url=report?.modules?.[k]?.url||FALLBACK[k];return `<a class="qh-source" href="${escape(url)}" rel="noopener noreferrer" target="_blank">Orijinal GitHub projesini incele</a>`}
 function statusText(x){return x==='PASS'?'GEÇTİ':x==='BLOCK'?'ENGELLENDİ':x==='UNKNOWN'?'DOĞRULANMADI':String(x??'—')}
 function checksBox(checks){return checks?.length?`<div class="qh-box"><h4>Hangi kontrol neden geçti / engellendi?</h4><div class="qh-checklist">${checks.map(z=>`<div class="qh-check" data-status="${escape(z.status)}"><div><strong>${escape(z.label)}</strong><small>Ölçülen: ${escape(n(z.value))} ${escape(z.unit||'')} · Eşik: ${escape(n(z.limit))}</small></div><span>${escape(statusText(z.status))}</span></div>`).join('')}</div></div>`:''}
 function dailyInfoBox(){const d=report?.quality?.daily;if(!d)return '';return `<div class="qh-box"><h4>Günlük veri doğrulaması · tek kaynak</h4><div class="qh-cards"><div class="qh-card"><span>Gerçek kapanmış gün</span><strong>${escape(n(d.available_closed_days))}</strong></div><div class="qh-card"><span>MCM / Riskfolio ihtiyacı</span><strong>${escape(n(d.mcm_minimum_days))} / ${escape(n(d.riskfolio_minimum_days))}</strong></div></div><p class="qh-muted">Kaynak: ${escape(d.source||report?.quality?.source)} · İlk gün: ${escape(d.first_utc||'—')} · Son gün: ${escape(d.last_utc||'—')}</p><p class="qh-muted">Bitget geçmiş sorgusu: ${d.history_attempted?'Denendi':'Gerekmedi / bu kaynağa uygulanmaz'} · Eklenen eski gün: ${escape(n(d.history_added??0))} · Son kapalı mum yaşı: ${escape(n(d.last_candle_age_days))} gün</p>${d.history_error?`<p class="qh-muted qh-danger">Geçmiş sorgusu: ${escape(d.history_error)}</p>`:''}${d.notice?`<p class="qh-muted qh-danger">${escape(d.notice)}</p>`:''}<p class="qh-muted">Eksik 1D mumlar tahmin edilmez; başka sembolün fiyatlarıyla doldurulmaz.</p></div>`}
 function xgbResearchPanel(ml){
   if(!ml)return `<div class="qh-box"><h4>Makine öğrenimi · XGBoost</h4><p class="qh-muted">Eğitimli model dosyası henüz yüklenmedi. Verileri toplama ve ileri test GitHub Actions ile yapılır.</p></div>`;
   const z=ml.metrics||{};
   const state=ml.model_approved?'İLERİ TEST GEÇTİ':'DOĞRULAMA / VERİ BEKLİYOR';
   const forecast=ml.prediction?`<div class="qh-box"><h4>Asya → Londra · araştırma tahmini</h4>${badge(ml.prediction)}<p class="qh-muted">Ham model Londra yükseliş puanı: %${escape(n(ml.probability))}. Kalibre edilmiş işlem kazanma olasılığı DEĞİL.</p><p class="qh-muted">Seans: ${escape(ml.candidate_day||'—')} · Yalnızca Bitget XAUUSDT için aynı kaynaklı H1 ile.</p></div>`:'';
   return `<div class="qh-box"><h4>Makine öğrenimi · XGBoost (H1)</h4>
      <p class="qh-muted">Durum: ${escape(ml.status)} · ${state} · GERÇEK EMİR YOK · KONSENSÜSE OY VERMEZ</p>
      <div class="qh-cards">
         <div class="qh-card"><span>Eğitim örneği</span><strong>${escape(n(z.train_sessions))}</strong></div>
         <div class="qh-card"><span>Kronolojik ileri test örneği</span><strong>${escape(n(z.test_sessions))}</strong></div>
         <div class="qh-card"><span>İleri test isabet %</span><strong>${escape(n(z.test_accuracy_pct))}</strong></div>
         <div class="qh-card"><span>Çoğunluk referansı %</span><strong>${escape(n(z.test_majority_pct))}</strong></div>
      </div>
      <p class="qh-muted">Son ileri test günü: ${escape(z.test_end_day||'—')} · Kaynak: ${escape(ml.data_source||'—')}</p>
      <p class="qh-muted qh-danger">${escape(ml.reason||'Geçmiş veriler tamamlanmadan ve ileri test geçilmeden tahmin gösterilmez.')}</p>
   </div>${forecast}`;
 }
 function quantAiPanel(ai){
  if(!ai)return `<div class="qh-box"><h4>QUANT AI · Seans araştırması</h4><p class="qh-muted">Önce “7 Motoru Analiz Et” butonuna bas. Bu alan yalnız Asya–Londra / Soloshun sekmesinde görünür.</p></div>`;
  const audit=ai.audit||{};
  const error=ai.error?`<p class="qh-muted qh-danger">Hata: ${escape(ai.error)}</p>`:'';
  const c=ai.live_candidate;
  const candidate=c?`<p class="qh-muted">Asya tamamlandı · ${escape(c.session_date_utc||'—')} · Asya getirisi %${escape(n(c.asia_return_pct))}. Londra sonucu henüz bilinmiyor.</p>`:`<p class="qh-muted">Güncel, tamamlanmış Asya seansı adayı yok.</p>`;
  return `<div class="qh-box" id="qh-soloshun-quant-ai"><h4>QUANT AI · Asya → Londra / H1</h4>
   <p class="qh-muted">ARAŞTIRMA · ${escape(ai.mode||'VERİ BEKLENİYOR')} · GERÇEK EMİR YOK</p>
   <div class="qh-cards">
    <div class="qh-card"><span>Kapanmış ve geçerli H1 mum</span><strong>${escape(n(audit.valid_closed))}</strong></div>
    <div class="qh-card"><span>Etiketli tam seans</span><strong>${escape(n(ai.labelled_samples))}</strong></div>
    <div class="qh-card"><span>Eksik Asya / Londra</span><strong>${escape(n(audit.partial_asia_days))} / ${escape(n(audit.partial_london_days))}</strong></div>
    <div class="qh-card"><span>Eğitim için ön örnek eşiği</span><strong>${escape(n(ai.min_prototype_samples))}</strong></div>
   </div>
   <p class="qh-muted">Sabit UTC · Asya önceki gün 22:00–07:59, Londra 08:00–16:59. Yalnız kapanmış ve aynı kaynaktan gelen H1 mumlar.</p>
   ${candidate}${error}${xgbResearchPanel(ai.ml)}
   <p class="qh-muted">${escape(ai.source_warning||'Veri kaynağı kontrol ediliyor')}</p>
   <p class="qh-muted qh-danger">${ai.ml?.model_approved?"XGBoost modeli kronolojik test filtresini geçti. Bu yalnızca araştırma tahminidir; işlem olasılığı değildir. LSTM kurulu değildir. Mevcut Soloshun korelasyon motoru ve konsensüs hesabı değişmedi.":"XGBoost modeli henüz yeterli ileri test filtresi geçmedi veya veri yetersiz. LSTM kurulu değildir. Model tahmini ve işlem olasılığı sunulmaz; mevcut Soloshun korelasyon motoru ve konsensüs hesabı değişmez."}</p>
  </div>`;
 }
 function panelEngine(k){const m=report?.modules?.[k];const src=catalog?.sources?.find(x=>x.id===k);
   return `<section class="qh-panel" role="tabpanel"><div class="qh-head"><div><h3 class="qh-title">${escape(m?.name||src?.name||TITLES[k])}</h3><p class="qh-muted">${escape(m?.implementation||src?.implementation||'Uyarlanmış araştırma modülü')}</p>${sourceLink(k)}</div>${badge(m?.direction)}</div>
   <div class="qh-box"><h4>Motor durumu</h4><p class="qh-muted">${escape(m?.status||'Analiz yapılmadı')} · ${escape(m?.kind||src?.kind||'—')} · ${escape(m?.gate||'—')}</p><p class="qh-muted">${escape(m?.execution||'Orijinal kodu/model ağırlıkları değildir.')}</p>${m?.strength!=null?`<p class="qh-muted">Yön gücü: ${n(m.strength)} / 100 (başarı yüzdesi değil)</p>${directionBar(m.direction==='SHORT'?'short':'long',m.strength)}`:''}</div>
   ${checksBox(m?.checks)}${k==='soloshun'?quantAiPanel(m?.quant_ai):''}${(k==='mcm'||k==='riskfolio')?dailyInfoBox():''}${settingsBox(k)}<div class="qh-box"><h4>Kaynaklı hesaplama metrikleri</h4>${metricsCard(m?.metrics)}</div>
   <div class="qh-box"><h4>Nedenler ve sınırlar</h4>${m?.reasons?.length?`<ul class="qh-textlist">${m.reasons.map(r=>`<li>${escape(r)}</li>`).join('')}</ul>`:'<p class="qh-muted">Analiz için veri bekleniyor.</p>'}${m?.warnings?.length?`<p class="qh-muted qh-danger">${m.warnings.map(escape).join(' · ')}</p>`:''}</div></section>`}
 function panelConsensus(){const c=report?.consensus;const q=report?.quality||{};
 return `<section class="qh-panel" role="tabpanel"><div class="qh-head"><div><h3 class="qh-title">ORTAK KARAR & KONSENSÜS</h3><p class="qh-muted">Yön motorları oy kullanır; risk ve uygulama motorları veto eder.</p></div>${badge(c?.decision||'BEKLE')}</div>
 ${!c?'<div class="qh-empty">Önce "7 Motoru Analiz Et" seç. Sıfır veya boş veriyle gerçek sinyal oluşturulmaz.</div>':`<div class="qh-consensus-score"><div class="qh-card" data-tone="long"><span>LONG yön gücü</span><strong>${n(c.long_strength)}</strong>${directionBar('long',c.long_strength)}</div><div class="qh-card" data-tone="short"><span>SHORT yön gücü</span><strong>${n(c.short_strength)}</strong>${directionBar('short',c.short_strength)}</div></div><div class="qh-cards"><div class="qh-card"><span>Yön motorları</span><strong>${n(c.active_directional_engines)} / ${n(c.configured_directional_engines)}</strong></div><div class="qh-card"><span>Yön uzlaşısı</span><strong>${n(c.agreement_pct)}%</strong></div><div class="qh-card"><span>Kapsama</span><strong>${n(c.coverage_pct)}%</strong></div><div class="qh-card"><span>Kurulum</span><strong>GÖZLEM</strong></div></div>
 <div class="qh-box"><h4>Motor oyları</h4>${c.used_votes?.length?`<ul class="qh-textlist">${c.used_votes.map(v=>`<li>${escape(TITLES[v.id])}: ${badge(v.direction)} · güç ${n(v.strength)}</li>`).join('')}</ul>`:'<p class="qh-muted">Henüz uygun yön oyu yok.</p>'}<p class="qh-muted">Oy dışı: ${escape(c.excluded?.join(', ')||'Yok')}</p></div>
 <div class="qh-box"><h4>Gerekçeli veto ve karar eşikleri</h4><p class="qh-muted">Yön farkı: ${n(c.direction_margin_pts)} / asgari ${n(c.thresholds?.min_margin_pts)} · Uzlaşı: ${n(c.agreement_pct)}% / asgari ${n(c.thresholds?.min_agreement_pct)}%</p>${c.veto_details?.length?`<div class="qh-checklist">${c.veto_details.map(v=>`<div class="qh-check" data-status="BLOCK"><div><strong>${escape(v.label)}</strong><small>${escape(v.category)} · Gözlenen: ${escape(n(v.observed))} · Gereken: ${escape(n(v.required))}</small></div><span>VETO</span></div>`).join('')}</div>`:'<p class="qh-muted">Tanımlı veto yok; sistem yalnız araştırma amaçlıdır, gerçek işleme onay vermez.</p>'}<p class="qh-muted">GS risk: ${escape(c.risk_status?.gsquant||'UNKNOWN')} · Maliyet testi: ${escape(c.risk_status?.nautilus||'UNKNOWN')}</p></div>
 <div class="qh-box"><h4>Oy dışı kalan yön motorları</h4>${c.excluded_details?.length?`<ul class="qh-textlist">${c.excluded_details.map(v=>`<li><strong>${escape(TITLES[v.id]||v.id)}</strong>: ${escape(v.reason)} (${escape(v.status)})</li>`).join('')}</ul>`:'<p class="qh-muted">Oy dışı motor yok.</p>'}</div>
 <div class="qh-box"><h4>Bağlam ve günlük veri uyarıları</h4>${c.context_alerts?.length?`<ul class="qh-textlist">${c.context_alerts.map(v=>`<li>${escape(TITLES[v.id]||v.id)}: ${escape(v.message)}</li>`).join('')}</ul>`:'<p class="qh-muted">Bağlam uyarısı yok.</p>'}</div>
 <div class="qh-box"><h4>Uzun vade bağlamı</h4><p class="qh-muted">MCM günlük yön: ${escape(c.context?.mcm_daily||'—')} · Riskfolio örnek altın ağırlığı: ${n(c.context?.riskfolio_gold_pct)}%</p><p class="qh-muted">${escape(c.explanation)}</p></div>`}
 ${dailyInfoBox()}${settingsBox('consensus')}<div class="qh-box"><h4>Veri güvenilirliği</h4><p class="qh-muted">Sembol: ${escape(q.symbol||'—')} · Kaynak: ${escape(q.source||'—')} · Fiyat güncel: ${q.ticker_fresh?'Evet':'Hayır'} · Kapalı mum yeterli: ${q.candles_ok?'Evet':'Hayır'}</p><p class="qh-muted">${escape(report?.disclaimer||'İlk analiz bekleniyor')}</p></div></section>`}
 function render(){nav();const target=$('qh-content');if(!target)return;target.innerHTML=active==='consensus'?panelConsensus():panelEngine(active)}
 function setStatus(message,error=false){const e=$('qh-status');if(!e)return;e.textContent=message;e.className='qh-status '+(error?'qh-error':'qh-good')}
 async function catalogLoad(){try{const r=await fetch('/api/quant-hub/catalog',{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);catalog=await r.json();let saved=restore();for(const s of catalog.sources){config[s.id]={...s.settings,...(saved[s.id]||{})}}config.consensus={...catalog.consensus.settings,...(saved.consensus||{})};render()}catch(e){setStatus('Quant Hub katalog yüklenemedi: '+e.message,true)}}
 async function analyzeAll(){if(busy)return;busy=true;const btn=$('qh-run');btn.disabled=true;setStatus('Kapalı mumlar ve yedi motor analiz ediliyor...');try{
   const body={symbol:$('qh-symbol').value,tf:$('qh-tf').value,config};const abort=new AbortController();
   const r=await fetch('/api/quant-hub/analyze',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:abort.signal});
   const data=await r.json();if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:'Sunucu hatası HTTP '+r.status);
   report=data;setStatus('Analiz tamamlandı · '+new Date(data.requested_at_ms).toLocaleTimeString('tr-TR')+' · '+data.mode+' · Gerçek emir yok');render();
 }catch(e){lastError=e.message;setStatus('Veri veya analiz hatası: '+e.message,true)}finally{busy=false;btn.disabled=false}}
 function bind(){const root=$('qh-root');if(!root)return;root.addEventListener('click',e=>{
   const tab=e.target.closest('[data-hub-tab]');if(tab){active=tab.dataset.hubTab;render();return}
   const reset=e.target.closest('[data-hub-reset]');if(reset){const id=reset.dataset.hubReset;const source=id==='consensus'?catalog?.consensus:catalog?.sources?.find(x=>x.id===id);if(source){config[id]={...source.settings};save();render()}return}
 });root.addEventListener('change',e=>{const inp=e.target.closest('[data-hub-config]');if(!inp)return;const id=inp.dataset.hubConfig,key=inp.dataset.param;const source=id==='consensus'?catalog?.consensus:catalog?.sources?.find(x=>x.id===id);const rules=source?.rules?.[key];if(!rules)return;let val=Number(inp.value);if(!Number.isFinite(val))val=source.settings[key];val=Math.min(rules[1],Math.max(rules[0],val));config[id][key]=val;inp.value=val;save();setStatus('Ayar kaydedildi. Yeni hesap için Analiz Et butonuna bas.')});$('qh-run').addEventListener('click',analyzeAll);}
 function syncSelected(){const s=document.getElementById('symbol');if(s&&['XAUUSD','XAUUSDT'].includes(s.value))$('qh-symbol').value=s.value}
 function show(){syncSelected();if(!catalog)catalogLoad();else render()}
 window.addEventListener('gold-quant-hub-open',show);
 document.addEventListener('DOMContentLoaded',()=>{bind();nav();if(document.getElementById('v-quanthub')?.classList.contains('active'))show()});
})();
