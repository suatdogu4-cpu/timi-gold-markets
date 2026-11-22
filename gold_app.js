'use strict';
const $=id=>document.getElementById(id);
const navs=[['dashboard','◈ Kokpit'],['chart','▤ Grafik'],['technical','▧ Teknik'],['smc','◇ SMC / ICT'],['flow','⇄ Order Flow'],['depth','▥ DOM'],['derivatives','◉ Vadeli'],['macro','◎ Makro & Haber'],['quant','∑ Quant'],['altinquant','✦ ALTIN QUANT v2'],['quanthub','◈ 7 Quant + Konsensüs'],['strategies','▣ Stratejiler'],['decision','✦ Karar Motoru'],['performance','▱ Performans'],['health','● Veri Sağlığı'],['settings','⚙ Ayarlar']];
const tfs=['1m','3m','5m','15m','30m','1H','4H','1D'];
const repoLinks=[['order-flow-platform','https://github.com/justaksi7/order-flow-platform'],['Gold-Dashboard','https://github.com/Econ-G/Gold-Dashboard'],['gold-sweep-backtester','https://github.com/baturdenada/gold-sweep-backtester'],['smc-backtester','https://github.com/Yousuf6273/smc-backtester'],['GoldBot','https://github.com/shrijeet-lokhande/GoldBot'],['aurum-intelligence','https://github.com/Pestador/aurum-intelligence'],['PickleChart','https://github.com/ikarisz/PickleChart'],['dukascopy-tools','https://github.com/Tradelyy/dukascopy-tools'],['lightweight-charts','https://github.com/tradingview/lightweight-charts'],['TA-Lib','https://github.com/TA-Lib/ta-lib'],['vectorbt','https://github.com/polakowo/vectorbt'],['quantstats','https://github.com/ranaroussi/quantstats']];
let symbol='XAUUSDT',tf='1m',page='dashboard',snap=null,ana=null,candleData=[],plots={},osc={},clientWs=null,retryMs=1200,lastBT=null,inflight=0,firstLoad=true,lastRollRefresh=0;
const togglesConfig=[['EMA20','ema20',true],['EMA50','ema50',true],['EMA200','ema200',false],['BB','bb',true],['VWAP50','vwap50',false],['SUPERTREND','supertrend',false]];
const opts=Object.fromEntries(togglesConfig.map(x=>[x[1],localStorage.getItem('gold-'+x[1])===null?x[2]:localStorage.getItem('gold-'+x[1])==='true']));
const fmt=(x,d=2)=>x===null||x===undefined||!Number.isFinite(Number(x))?'—':Number(x).toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});
const short=x=>x===null||x===undefined||!Number.isFinite(Number(x))?'—':Math.abs(x)>=1e9?fmt(x/1e9,2)+'B':Math.abs(x)>=1e6?fmt(x/1e6,2)+'M':Math.abs(x)>=1000?fmt(x/1000,2)+'K':fmt(x,2);
const age=x=>x===null||x===undefined?'—':fmt(x,1)+'s';
const pct=x=>x===null||x===undefined?'—':fmt(x,2)+'%';
const showError=s=>{let e=$('err');e.style.display=s?'block':'none';e.textContent=s||''};
const escaped=s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');
const time=x=>{try{return new Date(x).toLocaleTimeString('tr-TR')}catch{return '—'}};
const date=x=>{try{return new Date(x*1000).toLocaleString('tr-TR',{month:'short',day:'2-digit',hour:'2-digit',minute:'2-digit'})}catch{return '—'}};
async function getJSON(url){let r=await fetch(url,{cache:'no-store'});let j=await r.json().catch(()=>({detail:'Yanıt JSON değil'}));if(!r.ok)throw new Error(j.detail||r.status+' HTTP');return j}
function initNav(){ $('nav').innerHTML=navs.map(([k,v])=>`<button data-page="${k}" class="${k==='dashboard'?'active':''}">${v}</button>`).join('');
$('nav').addEventListener('click',e=>{let b=e.target.closest('[data-page]');if(b)go(b.dataset.page)});
document.body.addEventListener('click',e=>{let b=e.target.closest('[data-go]');if(b)go(b.dataset.go)});
$('tfbar').innerHTML=tfs.map(x=>`<button data-tf="${x}" class="${x===tf?'active':''}">${x}</button>`).join('');
$('tfbar').onclick=e=>{let b=e.target.closest('[data-tf]');if(b){tf=b.dataset.tf; $('tfbar').querySelectorAll('button').forEach(x=>x.classList.toggle('active',x===b));reloadAll()}};
$('symbol').onchange=e=>{symbol=e.target.value;reloadAll()};$('reload').onclick=()=>reloadAll(true);
for(let id of ['toggles','toggles-detail']){$(id).innerHTML=togglesConfig.map(([lab,k])=>`<label class="switch"><input data-opt="${k}" type="checkbox" ${opts[k]?'checked':''}>${lab}</label>`).join('');$(id).onchange=e=>{if(!e.target.dataset.opt)return;let k=e.target.dataset.opt;opts[k]=e.target.checked;localStorage.setItem('gold-'+k,String(opts[k]));document.querySelectorAll(`[data-opt="${k}"]`).forEach(x=>x.checked=opts[k]);renderPlots()}}
$('repoList').innerHTML=repoLinks.map(([name,u])=>`<a href="${u}" target="_blank" rel="noopener noreferrer">${escaped(name)}</a>`).join('');
$('resetPrefs').onclick=()=>{for(let k in opts)localStorage.removeItem('gold-'+k);location.reload()};
$('healthReload').onclick=loadHealth;$('macroReload').onclick=loadMacro;
$('mtfReload').onclick=loadMTF;
$('runTest').onclick=runBacktest; $('aqRefresh').onclick=loadAltinQuant; $('aqRiskBtn').onclick=aqRiskCalc;
$('strategy').innerHTML=Object.entries({'ema_trend':'EMA Trend + RSI','rsi_revert':'RSI Reversal','donchian':'Donchian Breakout','vwap_revert':'VWAP Return','smc_sweep':'Liquidity Sweep','bb_break':'Bollinger Break','momentum':'Price Momentum','macd_cross':'MACD Cross'}).map(([k,v])=>`<option value="${k}">${v}</option>`).join('');
}
function go(k){page=k;document.querySelectorAll('.view').forEach(x=>x.classList.toggle('active',x.id==='v-'+k));$('nav').querySelectorAll('button').forEach(x=>x.classList.toggle('active',x.dataset.page===k));
 g32Highlight(k);
 if(['dashboard','chart'].includes(k)){setTimeout(()=>{ensureCharts();renderPlots()},70)}
 if(k==='health')loadHealth();if(k==='macro')loadMacro();if(k==='altinquant')loadAltinQuant();if(k==='technical')loadMTF();if(k==='strategies'&&lastBT)renderBT(lastBT); if(k==='quanthub')window.dispatchEvent(new Event('gold-quant-hub-open'));
 window.scrollTo({top:0,behavior:'instant'});
}
function chartOptions(){return {autoSize:true,layout:{background:{type:'solid',color:'#0d172b'},textColor:'#92aacb',fontFamily:'system-ui',fontSize:11,attributionLogo:false},
 grid:{vertLines:{color:'#1a2a42'},horzLines:{color:'#1a2a42'}},rightPriceScale:{borderColor:'#2b4362'},
 timeScale:{borderColor:'#2b4362',timeVisible:true,secondsVisible:false},crosshair:{mode:0},handleScale:true,handleScroll:true,
 localization:{priceFormatter:p=>fmt(p,2)}}}
function createPrice(id){const L=window.LightweightCharts;if(!L)return null;const chart=L.createChart($(id),chartOptions());
 const main=chart.addSeries(L.CandlestickSeries,{upColor:'#20d9b2',downColor:'#fa5f7e',borderVisible:false,wickUpColor:'#28e4ba',wickDownColor:'#fa5f7e',priceLineVisible:true});
 const lines={};for(let k of ['ema20','ema50','ema200','bb_up','bb_low','vwap50','supertrend'])lines[k]=chart.addSeries(L.LineSeries,{color:{ema20:'#54bdff',ema50:'#b788fe',ema200:'#ffce74',bb_up:'#346fc9',bb_low:'#346fc9',vwap50:'#f3c969',supertrend:'#f590a8'}[k],lineWidth:1,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});
 return {chart,main,lines,id};}
function createOsc(id,keys){const L=window.LightweightCharts;if(!L)return null;const chart=L.createChart($(id),{...chartOptions(),rightPriceScale:{borderColor:'#253550',scaleMargins:{top:.12,bottom:.11}},timeScale:{visible:false},handleScroll:true});
 const colors={'macd':'#5fb6ff','macd_signal':'#e9a363','macd_hist':'#17d6a0','rsi14':'#ab78f6','stoch_k':'#6bacfd','stoch_d':'#e2a470'};
 let lines={};for(let k of keys)lines[k]=chart.addSeries(k==='macd_hist'?L.HistogramSeries:L.LineSeries,{color:colors[k],lineWidth:2,priceLineVisible:false,lastValueVisible:false});
 return {chart,lines};}
function ensureCharts(){if(!window.LightweightCharts){$('empty-home').textContent='Grafik kütüphanesi yüklenemedi (CDN bağlantısını kontrol edin).';$('empty-detail').textContent='Grafik CDN erişilemiyor';return}
 if(!plots.home)plots.home=createPrice('plot-home');if(!plots.detail&&$('v-chart').classList.contains('active'))plots.detail=createPrice('plot-detail');
 if(!osc.macd)osc.macd=createOsc('osc-macd',['macd','macd_signal','macd_hist']);
 if(!osc.rsi)osc.rsi=createOsc('osc-rsi',['rsi14']);if(!osc.stoch)osc.stoch=createOsc('osc-stoch',['stoch_k','stoch_d']);
}
function drawLines(lines,serie){if(!ana?.indicators?.series)return;for(let [key,s] of Object.entries(lines)){const set=ana.indicators.series[key]||[];const vis=key.startsWith('bb_')?opts.bb:opts[key]??true;s.applyOptions({visible:vis});if(vis)s.setData(set.filter(x=>x.v!==null&&Number.isFinite(x.v)).map(x=>({time:x.t,value:x.v})))}}
function renderPlots(){if(!candleData.length)return;ensureCharts();let b=candleData.filter(x=>x.t&&x.c>0).map(x=>({time:x.t,open:x.o,high:x.h,low:x.l,close:x.c}));
 for(let key of Object.keys(plots)){let p=plots[key];if(!p)continue;try{p.main.setData(b);drawLines(p.lines);(key==='home'||!window.__uxZoomTouched)&&p.chart.timeScale().fitContent()}catch(ex){console.warn('price chart',ex)}}
 for(let [name,ob] of Object.entries(osc)){if(!ob||!ana?.indicators?.series)continue;for(let [k,series] of Object.entries(ob.lines)){let d=ana.indicators.series[k]||[];try{series.setData(d.filter(x=>x.v!==null).map(x=>({time:x.t,value:x.v,color:k==='macd_hist'?(x.v>=0?'#1bb78f':'#da6073'):undefined})));}catch(ex){console.warn('oscillator',ex)}}}
 $('empty-home').style.display='none';$('empty-detail').style.display='none';
}
function tickPlot(price,ms){if(!price||symbol!=='XAUUSDT'||!candleData.length)return;let step={'1m':60,'3m':180,'5m':300,'15m':900,'30m':1800,'1H':3600,'4H':14400,'1D':86400}[tf];let sec=Math.floor(ms/1000),start=Math.floor(sec/step)*step,last=candleData[candleData.length-1];if(start<last.t)return;
 if(start>last.t){if(lastRollRefresh!==start){lastRollRefresh=start;reloadAll(true)}return;}
 else{last.h=Math.max(last.h,price);last.l=Math.min(last.l,price);last.c=price}
 let x=candleData[candleData.length-1],data={time:x.t,open:x.o,high:x.h,low:x.l,close:x.c};
 for(let chart of Object.values(plots))if(chart)try{chart.main.update(data)}catch(e){}
}
function setMetric(id,value,unit=''){if($(id))$(id).textContent=value===null||value===undefined?'—':value+unit}
function clsDecision(v){return v==='LONG'?'green':v==='SHORT'?'red':''}
function setClass(el,kind){if(!$(el))return;$(el).classList.remove('green','red','gold','cyan');if(kind)$(el).classList.add(kind)}

// GOLD v2.2.4 — DISPLAY-ONLY proportion and intensity coloring.
// These values NEVER change strategy, signal, risk, market data or API decisions.
const GOLD_HEAT_VERSION='2.2.4';
const HEAT_TONES={up:'21,176,137',down:'226,85,111',neutral:'69,137,199',caution:'222,170,74'};
const heatN=x=>x===null||x===undefined||x===''?null:(Number.isFinite(Number(x))?Number(x):null);
const heatP=x=>Math.round(Math.max(0,Math.min(100,Number(x)||0)));
function heatVars(p,tone){const q=heatP(p),rgb=HEAT_TONES[tone]||HEAT_TONES.neutral;
 return `--heat-rgb:${rgb};--heat-opacity:${(.025+.27*q/100).toFixed(3)};--heat-fill:${q}%`;
}
function heatCard(label,display,opt={}){
 const n=heatN(opt.pct),valid=n!==null,tone=valid?(opt.tone||'neutral'):'neutral';
 const badge=valid?`<span class="heat-badge" title="${escaped(opt.title||'Yalnız görsel yoğunluk; başarı ihtimali değildir')}">${heatP(n)}% <em>görsel</em></span>`:'';
 return `<div class="metric heat-surface ${valid?'':'heat-empty'}" style="${heatVars(valid?n:0,tone)}"><div class="heat-head"><small>${escaped(label)}</small>${badge}</div><b>${display??'—'}</b>${opt.unit?`<p>${escaped(opt.unit)}</p>`:''}${opt.note?`<p class="heat-hint">${escaped(opt.note)}</p>`:''}</div>`;
}
function heatBox(id,p,tone,show=true){
 const el=typeof id==='string'?document.getElementById(id):id;if(!el)return;
 let node=el.classList.contains('metric')||el.classList.contains('signal')||el.classList.contains('card')?el:el.closest('.metric,.signal,.card');
 if(!node)return;
 const q=heatN(p);if(q===null){node.classList.remove('heat-surface');node.querySelector(':scope > .heat-badge')?.remove();return}
 node.classList.add('heat-surface');node.style.setProperty('--heat-rgb',HEAT_TONES[tone]||HEAT_TONES.neutral);node.style.setProperty('--heat-opacity',(.025+.27*heatP(q)/100).toFixed(3));node.style.setProperty('--heat-fill',heatP(q)+'%');
 let badge=node.querySelector(':scope > .heat-badge');if(show){if(!badge){badge=document.createElement('span');badge.className='heat-badge heat-card-tag';node.append(badge)}badge.textContent=heatP(q)+'% görsel';badge.title='Göstergeye göre normalize edilmiş görsel değer; işlem kâr olasılığı değildir'}else badge?.remove();
}
function heatTechnical(k,value,ind){
 const v=heatN(value);if(v===null)return null;
 const close=heatN(ind.close)||heatN(snap?.price?.last);const atr=heatN(ind.atr14);
 const bounded=['rsi14','rsi7','stoch_k','stoch_d','mfi14','plus_di','minus_di'];
 if(bounded.includes(k)){let p=heatP(v),tone=k==='minus_di'?'down':k==='plus_di'?'up':v>55?'up':v<45?'down':'neutral';return {pct:p,tone,note:'0–100 ölçeği'}}
 if(k==='williams14'){let p=heatP(v+100);return {pct:p,tone:p>=50?'up':'down',note:'−100…0 ölçeği'}}
 if(k==='cmf20'){return {pct:heatP(Math.abs(v)*100),tone:v>=0?'up':'down',note:'Mutlak akış / ±1'}}
 if(k==='adx14'){return {pct:heatP(v/50*100),tone:'neutral',note:'50 ADX referansı'}}
 if(k==='supertrend_dir'){return {pct:null,tone:v>0?'up':'down',note:'Yön kodu, yüzde değil'}}
 if(k==='zscore20'||k==='cci20'){return {pct:heatP(Math.abs(v)/(k==='zscore20'?3:200)*100),tone:v>=0?'up':'down',note:'Mutlak sapma referansı'}}
 if(k==='atr_pct'||k==='bb_width_pct'||k==='realized_vol_ann_pct'){let cap=k==='realized_vol_ann_pct'?60:k==='bb_width_pct'?3:1;return {pct:heatP(Math.abs(v)/cap*100),tone:'caution',note:'Volatilite referans ölçeği'}}
 if(k==='roc12'){return {pct:heatP(Math.abs(v)/2*100),tone:v>=0?'up':'down',note:'±2% referans'}}
 if(k==='macd'||k==='macd_signal'||k==='macd_hist'){if(!atr)return null;return {pct:heatP(Math.abs(v)/atr*100),tone:v>=0?'up':'down',note:'ATR’a göre mutlak büyüklük'}}
 if(/^(ema|bb_|vwap|supertrend$|donchian|close$)/.test(k)&&close&&atr&&atr>0){return {pct:heatP(Math.abs(close-v)/(2*atr)*100),tone:k==='close'?'neutral':close>=v?'up':'down',note:'Fiyata uzaklık / 2 ATR'}}
 return null;
}
function heatRowAttrs(info){if(!info||info.pct===null||info.pct===undefined)return '';
 return ` class="heat-row" style="${heatVars(info.pct,info.tone||'neutral')}"`;
}
function heatQuant(label,v){const x=heatN(v);if(x===null)return null;
 const a=Math.abs(x);
 if(label.startsWith('Log getiri'))return {pct:heatP(a/0.2*100),tone:x>=0?'up':'down',note:'%0,20 görsel referans'};
 if(label.startsWith('Yıllıklandırılmış'))return {pct:heatP(a/60*100),tone:'caution',note:'%60 görsel referans'};
 if(label.includes('VaR'))return {pct:heatP(a/0.3*100),tone:'caution',note:'%0,30 görsel referans'};
 if(label.includes('Max fiyat'))return {pct:heatP(a/3*100),tone:'down',note:'%3 görsel referans'};
 if(label.includes('momentum'))return {pct:heatP(a/1*100),tone:x>=0?'up':'down',note:'%1 görsel referans'};
 if(label.includes('Z-Score'))return {pct:heatP(a/3*100),tone:x>=0?'up':'down',note:'|Z| / 3'};
 if(label==='ADX')return {pct:heatP(a/50*100),tone:'neutral',note:'ADX / 50'};
 if(label.startsWith('ATR'))return {pct:heatP(a/1*100),tone:'caution',note:'%1 görsel referans'};
 return null;
}
function heatStatusTone(s){return /SHORT|SAT|DÜŞ/i.test(s||'')?'down':/LONG|AL|YÜKSEL/i.test(s||'')?'up':/VETO|HATA/i.test(s||'')?'caution':'neutral'}
function heatSetupToggle(){
 try{document.documentElement.classList.toggle('heat-off',localStorage.getItem('gold_heat_on')==='0')}catch(e){}
 const settings=document.querySelector('#v-settings .body');
 if(settings&&!document.getElementById('heatToggle')){
  let wrap=document.createElement('div');wrap.className='heat-setting';wrap.innerHTML='<label for="heatToggle">Renkli yüzde yoğunlukları</label><input id="heatToggle" type="checkbox" aria-label="Gösterge kartlarının yüzdelik renk yoğunluğunu göster"><p>Yeşil/yön, kırmızı/karşı yön, amber/risk, mavi/nötr ölçüm. Yüzdeler görsel ölçek veya gerçek oranlardır; başarı olasılığı değildir.</p>';
  settings.append(wrap);const ctrl=document.getElementById('heatToggle');ctrl.checked=!document.documentElement.classList.contains('heat-off');
  ctrl.addEventListener('change',()=>{document.documentElement.classList.toggle('heat-off',!ctrl.checked);try{localStorage.setItem('gold_heat_on',ctrl.checked?'1':'0')}catch(e){}})
 }
 for(const id of ['technical','flow','quant','altinquant','decision','derivatives']){
  let section=document.getElementById('v-'+id);if(!section||section.querySelector('.heat-legend'))continue;
  let heading=section.querySelector('.sectiontop');if(!heading)continue;
  let legend=document.createElement('div');legend.className='heat-legend';legend.innerHTML='<span class="heat-dot up"></span>Yukarı/alış <span class="heat-dot down"></span>Aşağı/satış <span class="heat-dot caution"></span>Risk <span class="heat-dot neutral"></span>Ölçüm <small>0–100 görsel yoğunluk; kazanma olasılığı değil</small>';
  heading.after(legend)
 }
}

function updateSnap(s){snap=s;let valid=s.valid||{},price=s.price,spot=s.spot,fl=s.flow;
 $('conn').textContent=valid.ticker&&s.ws_connected?'CANLI WS':valid.ticker?'REST / SINIRLI':'VERİ GECİKMELİ';$('led').className='dot '+(valid.ticker?(s.ws_connected?'ok':''):'bad');
 if(symbol==='XAUUSD'){$('k-price').textContent=spot?fmt(spot.last):'—';$('k-change').textContent='OANDA Spot · 15 sn REST';} else {$('k-price').textContent=price?fmt(price.last):'—';$('k-change').textContent=price?`24s ${pct(price.change24_pct)}`:'Fiyat doğrulanmadı'}
 $('k-spot').textContent=spot?fmt(spot.last):'—';$('k-spot-sub').textContent=s.spot_status+' · '+age(s.spot_age_s);
 $('k-mark').textContent=price&&price.mark?fmt(price.mark):'—';$('k-index').textContent='INDEX '+(price&&price.index?fmt(price.index):'—');
 $('k-volume').textContent=price?short(price.volume24):'—';$('k-dayrange').textContent=price?fmt(price.low24)+' → '+fmt(price.high24):'—';
 $('k-imb').textContent=fl&&fl.imbalance!==null?pct(fl.imbalance*100):'—';setClass('k-imb',fl?.imbalance>0.08?'green':fl?.imbalance<-.08?'red':null);
 let buy=fl?.buy_notional60||0,sell=fl?.sell_notional60||0,percent=buy+sell?buy/(buy+sell)*100:50;
 $('donut').style.background=`conic-gradient(var(--green) 0 ${percent}%,var(--red) ${percent}% 100%)`;
 $('donutTxt').textContent=fl?fmt(percent,0)+'%':'—';$('flowBuy').textContent=fl?short(buy):'—';$('flowSell').textContent=fl?short(sell):'—';$('flowDelta').textContent=fl?short(fl.delta60):'—';
 $('basis').textContent=(price&&spot)?fmt(price.last-spot.last,3):'—';$('basisNote').textContent=(price&&spot)?'XAUUSDT − XAUUSD, anlık kaynak farkı':'OANDA spot bağlantısı yok';
 $('overviewHealth').innerHTML=`<p>${valid.ticker?'🟢':'🔴'} Fiyat: ${age(s.age_s.ticker)}</p><p>${valid.book?'🟢':'🔴'} Derinlik: ${age(s.age_s.book)}</p><p>${valid.trades?'🟢':'🔴'} İşlemler: ${age(s.age_s.trades)}</p>`;
 updateOrderBook(s);updateTrades(s);updateDerivatives(s);updateFlow(s);g32FlowUpdate(s);$('chartUpdated').textContent=valid.ticker?'Fiyat güncel · '+age(s.age_s.ticker):'Fiyat gecikmeli';
 if(price&&valid.ticker&&symbol==='XAUUSDT')tickPlot(price.last,s.server_time);
 if(symbol==='XAUUSD'&&!spot&&ana)$('k-decision').textContent='BEKLE';
}
function updateOrderBook(s){const render=(id,rows,color)=>{let body=$(id);if(!body)return;body.innerHTML=rows.slice(0,40).map(([p,q])=>`<tr><td class="${color}">${fmt(p)}</td><td>${fmt(q,4)}</td><td>${short(p*q)}</td></tr>`).join('')||'<tr><td colspan="3">Canlı derinlik yok</td></tr>'};render('bidsTable',s.bids||[],'green');render('asksTable',s.asks||[],'red');$('bookBidTotal').textContent=s.flow?'BUY '+short(s.flow.bid_notional20):'—';$('bookAskTotal').textContent=s.flow?'SELL '+short(s.flow.ask_notional20):'—'}
function updateTrades(s){$('tradesTable').innerHTML=(s.trades||[]).slice(-48).reverse().map(x=>`<tr><td>${time(x.t)}</td><td>${fmt(x.p)}</td><td>${fmt(x.v,4)}</td><td class="${x.side==='buy'?'green':'red'}">${x.side?.toUpperCase()}</td></tr>`).join('')||'<tr><td colspan="4">Canlı işlem yok</td></tr>'}
function updateDerivatives(s){let p=s.price;let values=[['Mark Price',p?.mark],['Index Price',p?.index],['Funding Rate',p&&p.funding!==undefined?p.funding*100:null,'%'],['Open Interest',p?.oi],['Best Bid',p?.bid],['Best Ask',p?.ask],['Fiyat Spread',p?.bid&&p?.ask?(p.ask-p.bid)/p.ask*100:null,'%'],['24s Turnover',p?.turnover24]];
 $('futuresMetrics').innerHTML=values.map(([k,v,suff])=>{
   const n=heatN(v),lo=heatN(p?.low24),hi=heatN(p?.high24);
   let q=null,tone='neutral',note='Ham fiyat/tutar: doğrulanmış yüzde yok';
   if(n!==null&&lo!==null&&hi!==null&&hi>lo&&['Mark Price','Index Price','Best Bid','Best Ask'].includes(k)){
     q=100*(n-lo)/(hi-lo);note='24s fiyat aralığındaki konum';
   }else if(n!==null&&k==='Funding Rate'){
     q=Math.abs(n)/0.05*100;tone='caution';note='%0,05 görsel referans';
   }else if(n!==null&&k==='Fiyat Spread'){
     q=100-Math.min(100,n/0.12*100);tone=n>0.12?'down':'up';note='Dar spread: daha yüksek kalite';
   }
   let display=n===null?'—':fmt(n,k==='Funding Rate'?5:k==='Fiyat Spread'?4:2)+(suff||'');
   return heatCard(k,display,{pct:q,tone,note:n===null?'Veri yok':note});
 }).join('')}
function updateFlow(s){let f=s.flow,arr=[['BUY (60s)',f?.buy_notional60,'USDT'],['SELL (60s)',f?.sell_notional60,'USDT'],['DELTA (60s)',f?.delta60,'USDT'],['Taker imbalance',f?.aggressor_ratio,'ratio'],['Book imbalance',f?.imbalance,'ratio'],['İşlem sayısı',f?.trades60,'işlem'],['Spread',f?.spread_pct,'%'],['Book Bid Notional',f?.bid_notional20,'USDT']];
 const total=(heatN(f?.buy_notional60)||0)+(heatN(f?.sell_notional60)||0);
 const bookTotal=(heatN(f?.bid_notional20)||0)+(heatN(f?.ask_notional20)||0);
 $('flowMetrics').innerHTML=arr.map(([name,x,unit])=>{
   const n=heatN(x);let p=null,tone='neutral',note='Ölçek karşılaştırması yok';
   if(n!==null){
     if(name==='BUY (60s)'&&total>0){p=n/total*100;tone='up';note='Son 60 sn işlem payı'}
     else if(name==='SELL (60s)'&&total>0){p=n/total*100;tone='down';note='Son 60 sn işlem payı'}
     else if(name==='DELTA (60s)'&&total>0){p=Math.abs(n)/total*100;tone=n>=0?'up':'down';note='Mutlak delta / işlem hacmi'}
     else if(name==='Taker imbalance'||name==='Book imbalance'){p=Math.abs(n)*100;tone=n>=0?'up':'down';note='Mutlak dengesizlik oranı'}
     else if(name==='Book Bid Notional'&&bookTotal>0){p=n/bookTotal*100;tone='up';note='DOM20 alış payı'}
     else if(name==='İşlem sayısı'){p=n/120*100;tone='neutral';note='120 işlem/60sn görsel referans'}
     else if(name==='Spread'){p=100-Math.min(100,Math.abs(n)/0.12*100);tone=n>0.12?'down':'up';note='Dar spread: daha yüksek kalite'}
   }
   const display=n===null?'—':fmt(n,name==='Spread'||unit==='ratio'?4:2);
   return heatCard(name,display,{pct:p,tone,unit,note:n===null?'Veri yok':note});
 }).join('');
 let fp=f?.footprint||[];$('overviewFP').textContent=fp.length?`${fp.length} fiyat kovası · en yüksek alış ${short(Math.max(...fp.map(x=>x.buy)))} · en yüksek satış ${short(Math.max(...fp.map(x=>x.sell)))}`:'Veri yok';
 $('fpTable').innerHTML='<div class="fp-row head"><div class="fp-cell">FİYAT</div><div class="fp-cell">BUY</div><div class="fp-cell">SELL</div><div class="fp-cell">DELTA</div></div>'+fp.slice(0,45).map(x=>`<div class="fp-row"><div class="fp-cell">${fmt(x.price)}</div><div class="fp-cell green">${fmt(x.buy,3)}</div><div class="fp-cell red">${fmt(x.sell,3)}</div><div class="fp-cell ${x.delta>=0?'green':'red'}">${fmt(x.delta,3)}</div></div>`).join('')}
function updateAnalysis(a){ana=a;let ind=a.indicators?.latest||{},q=a.quant||{},d=a.decision||{},sm=a.smc||{};
 $('chartTitle').textContent=symbol+' · '+tf;$('overviewAtr').textContent=fmt(ind.atr14,3);$('overviewBB').textContent=pct(ind.bb_width_pct);$('overviewZ').textContent=fmt(ind.zscore20,2);$('overviewVar').textContent=pct(q.var95_1bar_pct);
 $('regimeName').textContent=q.regime||'Veri yetersiz';
 const rangeHigh=heatN(sm.swing_high),rangeLow=heatN(sm.swing_low),lastClose=heatN(ind.close)||heatN(snap?.price?.last);
 const rangePosition=rangeHigh!==null&&rangeLow!==null&&lastClose!==null&&rangeHigh>rangeLow?heatP((lastClose-rangeLow)/(rangeHigh-rangeLow)*100):null;
 $('overviewSMC').innerHTML=`<div class="heat-stat-row" style="${heatVars(rangePosition,'down')}"><span>Swing High</span><b class="cyan">${fmt(sm.swing_high)}</b>${rangePosition===null?'':`<small>${rangePosition}% aralık konumu</small>`}</div>`+
 `<div class="heat-stat-row" style="${heatVars(rangePosition===null?null:100-rangePosition,'up')}"><span>Swing Low</span><b class="cyan">${fmt(sm.swing_low)}</b>${rangePosition===null?'':`<small>${100-rangePosition}% aralık konumu</small>`}</div>`+
 `<div class="heat-stat-row" style="${heatVars(null,'neutral')}"><span>Son SMC olayları</span><b>${sm.events?.length||0}</b></div>`+
 `<p class="heat-hint">Aralık yüzdesi fiyatın son swing içindeki konumudur; destek/direnç başarı oranı değildir.</p><button class="btn" data-go="smc">SMC detayları</button>`;
 $('swingHi').textContent=fmt(sm.swing_high);$('swingLo').textContent=fmt(sm.swing_low);$('swingMid').textContent=fmt(sm.range_mid);
 let ev=sm.events||[];$('smcEvents').innerHTML=ev.length?ev.slice().reverse().map(x=>`<div class="event"><b class="${x.type.startsWith('FVG')?'fvg':'sweep'}">${escaped(x.type)}</b> <span>${x.price?fmt(x.price):fmt(x.low)+' – '+fmt(x.high)}</span><small class="muted" style="float:right">${date(x.t)}</small></div>`).join(''):'Son örneklemde doğrulanmış SMC olayı yok.';
 const info={'close':['Son kapanmış mum'], 'ema9':['Hızlı üssel ort.'], 'ema20':['Kısa trend'], 'ema50':['Orta trend'],'ema200':['Büyük trend'],'rsi14':['Momentum 0–100'],'rsi7':['Hızlı momentum'],'atr14':['Gerçek aralık'],'macd':['12−26 EMA'],'macd_signal':['9 EMA sinyal'],'macd_hist':['MACD−sinyal'],'bb_mid':['Bollinger 20'],'bb_up':['Bollinger +2σ'],'bb_low':['Bollinger −2σ'],'bb_width_pct':['Bant genişlik %'],'stoch_k':['Stoch K'],'stoch_d':['Stoch D'],'adx14':['Trend kuvveti'],'plus_di':['Pozitif yön'],'minus_di':['Negatif yön'],'cci20':['Commodity Channel Index'],'roc12':['12 mum hız %'],'williams14':['Williams %R'],'obv':['On-balance volume'],'cmf20':['Chaikin Money Flow'],'mfi14':['Money Flow Index'],'vwap50':['50 mum VWAP yaklaşımı'],'supertrend':['ATR tabanlı trend'],'supertrend_dir':['Yön +1/−1'],'donchian_high':['20 mum maksimum'],'donchian_low':['20 mum minimum'],'realized_vol_ann_pct':['Yıllıklaştırılmış vol %'],'zscore20':['20 bar z-skor'],'atr_pct':['ATR / fiyat %'],'volume_sma20':['20 bar hacim ort.'],'last_volume':['Son hacim']};
 $('techTable').innerHTML=Object.entries(ind).map(([k,v])=>{
   const h=heatTechnical(k,v,ind),pct=h&&h.pct!==null&&h.pct!==undefined?`<span class="heat-table-badge">${heatP(h.pct)}% görsel</span>`:'';
   const note=escaped((info[k]||['—'])[0])+(h?.note?' · '+escaped(h.note):'');
   return `<tr${heatRowAttrs(h)} data-g32-key="${escaped(k)}"><td>${escaped(k)}<small class="g32-mobile-note">${note}</small></td><td>${fmt(v,k==='supertrend_dir'?0:4)}<span class="g32-mobile-heat">${pct}</span></td><td class="muted">${note}${pct}</td></tr>`;
 }).join('');$('techCount').textContent=Object.keys(ind).length+' gösterge/metrik';
 $('macdValue').textContent=fmt(ind.macd_hist,4);$('rsiValue').textContent=fmt(ind.rsi14,2);$('stochValue').textContent=fmt(ind.stoch_k,2);
 $('quantMetrics').innerHTML=[['Log getiri (bar)',q.mean_return_pct,'%'],['Yıllıklandırılmış vol.',q.vol_annualized_pct,'%'],['%95 VaR (1 bar)',q.var95_1bar_pct,'%'],['Max fiyat düşüşü',q.max_price_drawdown_pct,'%'],['20 bar momentum',q.momentum20_pct,'%'],['Z-Score 20',ind.zscore20,''],['ADX',ind.adx14,''],['ATR %',ind.atr_pct,'%']].map(([k,v,u])=>{
   const h=heatQuant(k,v);return heatCard(k,heatN(v)===null?'—':fmt(v,3)+u,{...(h||{}),note:h?.note||'Veri ölçülemedi'});
 }).join('');$('quantExtra').textContent=q.note||'';g32AnalysisUpdate(a);
 $('decisionTF').textContent=tf;$('bigDecision').textContent=d.decision||'BEKLE';setClass('bigDecision',clsDecision(d.decision));
 $('k-decision').textContent=d.decision||'BEKLE';setClass('k-decision',clsDecision(d.decision));
 $('k-risk').textContent=(d.veto||[]).length?'VETO: '+d.veto.length:'Koşullar gözden geçirildi';$('decisionData').textContent=a.data?.candles_valid?'Mum güncel · '+a.data.closed_bars+' kapalı':'Kapanmış mum gecikmeli';
 $('longScore').textContent=d.long===null?'—':fmt(d.long,1);$('shortScore').textContent=d.short===null?'—':fmt(d.short,1);$('netScore').textContent=d.score===null?'—':fmt(d.score,1);
 $('stop').textContent=fmt(d.stop);$('target').textContent=fmt(d.take_profit);
 $('reasonList').innerHTML=d.reasons?.length?d.reasons.map(x=>`<div class="reason heat-reason ${/^\s*\+/.test(x)?'heat-reason-up':/^\s*[−-]/.test(x)?'heat-reason-down':'heat-reason-neutral'}">${escaped(x)}</div>`).join(''):'Gerekçe verisi yok';
 $('vetoList').innerHTML=d.veto?.length?d.veto.map(x=>`<div class="reason negative">${escaped(x)}</div>`).join(''):'<span class="chip green">Belirlenen veto yok</span>';
 // Card color intensities are visual-only; existing scores, vetoes and strategy outputs remain unchanged.
 heatBox('longScore',d.long,'up');heatBox('shortScore',d.short,'down');
 heatBox('netScore',heatN(d.score)===null?null:Math.abs(d.score),d.score>=0?'up':'down');
 heatBox('bigDecision',Math.max(0,heatN(d.long)||0,heatN(d.short)||0),heatStatusTone(d.decision),false);
 heatBox('overviewAtr',heatN(ind.atr_pct)===null?null:ind.atr_pct/1*100,'caution');
 heatBox('overviewBB',heatN(ind.bb_width_pct)===null?null:ind.bb_width_pct/3*100,'caution');
 heatBox('overviewZ',heatN(ind.zscore20)===null?null:Math.abs(ind.zscore20)/3*100,ind.zscore20>=0?'up':'down');
 heatBox('overviewVar',heatN(q.var95_1bar_pct)===null?null:q.var95_1bar_pct/.3*100,'caution');
 renderPlots();
}
function updateUnifiedDecision(u){
 if(!u)return;
 const direction=u.direction||'BEKLE';
 if($('k-decision')){$('k-decision').textContent=direction;setClass('k-decision',clsDecision(direction))}
 if($('k-risk'))$('k-risk').textContent=u.model_approved?'ML doğrulama geçti':'Gölge öğrenme / doğrulama';
 if($('bigDecision')){$('bigDecision').textContent=direction;setClass('bigDecision',clsDecision(direction))}
 if($('decisionTF'))$('decisionTF').textContent=u.tf||tf;
 if($('decisionData'))$('decisionData').textContent=`${u.mode||'GÖLGE'} · ${u.learning?.samples||0} ileri kapanış`;
 if($('longScore'))$('longScore').textContent=u.probability_up!=null?((u.probability_up*100).toFixed(1)+'%'):'—';
 if($('shortScore'))$('shortScore').textContent=u.probability_up!=null?(((1-u.probability_up)*100).toFixed(1)+'%'):'—';
 if($('netScore'))$('netScore').textContent=direction;
 if($('stop'))$('stop').textContent=u.stop!=null?Number(u.stop).toFixed(2):'—';
 if($('target'))$('target').textContent=u.target!=null?Number(u.target).toFixed(2):'—';
 if($('reasonList'))$('reasonList').innerHTML=(u.reasons||[]).map(x=>`<div>• ${escaped(x)}</div>`).join('')||'—';
 if($('vetoList'))$('vetoList').innerHTML=(u.veto||[]).map(x=>`<div class="red">• ${escaped(x)}</div>`).join('')||'<div class="green">Veto yok · emir yetkisi kapalı</div>';
}
async function reloadAll(force=false){let seq=++inflight;showError('');$('chartTitle').textContent=symbol+' · '+tf;
 try{let [c,a,ml,unified]=await Promise.all([getJSON(`/api/candles?symbol=${symbol}&tf=${tf}&limit=550&refresh=${force}`),getJSON(`/api/analysis?symbol=${symbol}&tf=${tf}&refresh=${force}`),getJSON(`/api/ml-status?symbol=${symbol}`),getJSON(`/api/unified-decision?symbol=${symbol}&tf=${tf}`)]);if(seq!==inflight)return;
 candleData=c.bars||[];ana=a;updateAnalysis(a);updateUnifiedDecision(unified);firstLoad=false;
 updateMLStatus(ml);
 }catch(e){if(seq!==inflight)return;showError(symbol+': '+e.message);if(symbol==='XAUUSD')showError('XAUUSD spot için OANDA erişimi gerekiyor: '+e.message);candleData=[];ana=null;for(let e of ['empty-home','empty-detail']){$(e).style.display='grid';$(e).textContent='Doğrulanmış mum verisi yok'}
 }if(page==='technical')loadMTF(); if(page==='altinquant')loadAltinQuant();}
function updateMLStatus(j){
 if(!$('mlStatusDecision')||!j)return;
 $('mlStatusDecision').textContent=j.trade_decision||'BEKLE';
 setClass('mlStatusDecision',clsDecision(j.trade_decision||'BEKLE'));
 $('mlStatusAge').textContent=j.feed_fresh?'Canlı veri · '+(j.candles_closed||0)+' mum':'Veri gecikmeli';
 const v1=j.ml_v1||{},v3=j.ml_v3||{},v5=j.shadow_v5||{},v6=j.scalp_v6||{};
 const status=v1.status||'BİLİNMİYOR';
 const reason=v1.reason||v3.reason||'Güncel model / geriye dönük doğrulama sonucu bekleniyor.';
 $('mlStatusDetail').innerHTML=[
  `<p><b>V1:</b> ${escaped(status)} · ${escaped(reason)}</p>`,
  `<p><b>V3:</b> ${escaped(v3.status||'NO_REPORT')} · canlı tahmin kapalı</p>`,
  `<p><b>V5:</b> ${escaped(v5.status||'SHADOW_RESEARCH_ONLY')} · emre dönüştürülmez</p>`,
  `<p><b>V6:</b> ${escaped(v6.status||'NO_REPORT')} · canlı sinyal ${v6.live_signal?'açık':'kapalı'}</p>`,
  '<p class="note">Araştırma/ML çıktısı yatırım emri değildir.</p>'
 ].join('');
}
async function loadMTF(){try{let j=await getJSON('/api/mtf?symbol='+symbol);$('mtfCards').innerHTML=j.rows.map(x=>`<div class="metric row" style="margin:5px 0"><b style="font-size:12px">${x.tf}</b><span class="${clsDecision(x.direction)}">${x.direction}</span><small>RSI ${fmt(x.rsi,1)}</small></div>`).join('')}catch(e){$('mtfCards').textContent=e.message}}
async function loadHealth(){try{let h=await getJSON('/api/health');$('healthCards').innerHTML=[['Gateway',h.status],['Bitget WS',h.bitget_ws?'BAĞLI':'BAĞLI DEĞİL'],['Fiyat',h.feed_valid?.ticker?'GÜNCEL':'GECİKMELİ'],['Emir defteri',h.feed_valid?.book?'GÜNCEL':'GECİKMELİ'],['İşlemler',h.feed_valid?.trades?'GÜNCEL':'GECİKMELİ'],['OANDA',h.spot_configured?'YAPILANDIRILDI':'KAPALI'],['WS son fiyat',age(h.feed_age_seconds?.ticker)],['Son olay',h.time_utc]].map(([n,v])=>`<div class="metric"><small>${n}</small><b style="font-size:15px">${escaped(v)}</b></div>`).join('');$('healthRaw').textContent=JSON.stringify(h,null,2)}catch(e){$('healthRaw').textContent=e.message}}
async function loadMacro(){let macro=$('macroGrid'),news=$('newsList');macro.innerHTML='<div class="hint">FRED sorgulanıyor...</div>';news.textContent='GDELT sorgulanıyor...';
 let [a,b]=await Promise.allSettled([getJSON('/api/macro'),getJSON('/api/news')]);
 if(a.status==='fulfilled'){macro.innerHTML=Object.entries(a.value.data||{}).map(([k,x])=>`<div class="metric"><small>${escaped(x.label||k)}</small><b>${fmt(x.last,3)}</b><p>${escaped(x.date||x.error||'—')} · ${k}</p></div>`).join('')}else macro.textContent=a.reason.message;
 if(b.status==='fulfilled'){let items=b.value.items||[];news.innerHTML='';if(!items.length)news.textContent=b.value.error?'Kaynak erişim hatası: '+b.value.error:'Son 24 saatte doğrulanmış haber bulunamadı';
  for(let x of items){let div=document.createElement('div');div.className='event';let link=document.createElement('a');link.href=x.url;link.target='_blank';link.rel='noopener noreferrer';link.textContent=x.title||'Haber';div.appendChild(link);let s=document.createElement('div');s.className='smallline';s.textContent=(x.domain||'GDELT')+' · '+(x.time||'');div.appendChild(s);news.appendChild(div)}}else news.textContent=b.reason.message;
}
async function runBacktest(){let bt=$('runTest');bt.disabled=true;bt.textContent='Hesaplanıyor...';$('btInfo').textContent='Kapanmış mumlarla maliyetli strateji testi...';try{let q=new URLSearchParams({symbol,tf,strategy:$('strategy').value,fee_bps:$('fee').value,slippage_bps:$('slip').value});let j=await getJSON('/api/backtest?'+q);lastBT=j;renderBT(j)}catch(e){$('btInfo').textContent='Backtest çalışmadı: '+e.message}finally{bt.disabled=false;bt.textContent='Backtest çalıştır'}}
function renderBT(x){if(x.error){$('btInfo').textContent=x.error;return}
 $('btMetrics').innerHTML=[['İşlem',x.trades_count],['Başarı oranı',pct(x.win_rate_pct)],['Profit Factor',fmt(x.profit_factor,2)],['Net PnL (1 ref)',fmt(x.net_pnl_usd_ref,2)],['Max Drawdown',pct(x.max_drawdown_pct)],['Test mumu',x.sample_candles]].map(([k,v])=>`<div class="metric"><small>${k}</small><b>${v??'—'}</b></div>`).join('');
 $('btTrades').innerHTML=(x.trades||[]).slice(-80).reverse().map(t=>`<tr><td>${date(t.t)}</td><td class="${clsDecision(t.side)}">${t.side}</td><td>${fmt(t.entry)}</td><td>${fmt(t.exit)}</td><td class="${t.pnl_usd_ref>=0?'green':'red'}">${fmt(t.pnl_usd_ref,3)}</td></tr>`).join('');
 $('btInfo').textContent=x.note;
 $('performanceCards').innerHTML=$('btMetrics').innerHTML;
 paintEquity(x.equity_curve||[]);
}
function paintEquity(points){let canvas=$('equity');let rect=canvas.getBoundingClientRect(),dpi=devicePixelRatio||1;canvas.width=Math.max(240,rect.width)*dpi;canvas.height=Math.max(160,rect.height)*dpi;let g=canvas.getContext('2d');g.setTransform(dpi,0,0,dpi,0,0);let w=canvas.width/dpi,h=canvas.height/dpi;g.clearRect(0,0,w,h);
 if(points.length<2){g.fillStyle='#8aa6bc';g.fillText('Henüz tamamlanan işlem yok',12,22);return}
 let ys=points.map(x=>x.equity);let lo=Math.min(...ys),hi=Math.max(...ys),pad=Math.max(1,(hi-lo)*.18);lo-=pad;hi+=pad;
 g.strokeStyle='#21334e';for(let i=0;i<5;i++){let y=12+i*(h-26)/4;g.beginPath();g.moveTo(0,y);g.lineTo(w,y);g.stroke()}
 g.beginPath();points.forEach((pt,i)=>{let x=12+i/(points.length-1)*(w-24),y=h-16-(pt.equity-lo)/(hi-lo)*(h-32);if(!i)g.moveTo(x,y);else g.lineTo(x,y)});g.strokeStyle=ys.at(-1)>=ys[0]?'#20d9ab':'#fa5f7e';g.lineWidth=2.2;g.stroke();
 g.fillStyle='#a6d2e9';g.font='11px system-ui';g.fillText(fmt(ys.at(-1),2),12,14)
}
function startSocket(){if(clientWs)try{clientWs.close()}catch{};let url=(location.protocol==='https:'?'wss://':'ws://')+location.host+'/ws/stream';let ws=new WebSocket(url);clientWs=ws;
 ws.onopen=()=>{retryMs=1200};ws.onmessage=e=>{try{let j=JSON.parse(e.data);if(j.type==='snapshot')updateSnap(j.payload)}catch(err){console.warn('stream',err)}};
 ws.onclose=()=>{if(clientWs!==ws)return;$('conn').textContent='BAĞLANTI KOPTU';$('led').className='dot bad';setTimeout(startSocket,retryMs);retryMs=Math.min(30000,retryMs*1.7)};
 ws.onerror=()=>{ws.close()};}

let aqInFlight=0;
const aqFamiliesLabels={regime:'Piyasa rejimi',structure:'SMC / Yapı',mtf:'MTF hiyerarşi',flow:'Order Flow',derivatives:'Vadeli / OI',macro:'Makro',statistics:'İstatistik',setup:'Giriş / Maliyet'};
async function loadAltinQuant(){
 const seq=++aqInFlight;
 $('aqStamp').textContent='Veri kontrol ediliyor…';
 try {
   const d=await getJSON('/api/altin-quant/analysis?symbol='+encodeURIComponent(symbol)+'&tf='+encodeURIComponent(tf));
   if(seq!==aqInFlight||page!=='altinquant')return;
   const score=d.score||{},r=d.regime||{},s=d.statistics||{},flow=d.orderflow||{},set=d.setup||{},old=d.legacy||{};
   $('aqStamp').textContent=(d.mode||'')+' · '+new Date(d.sample_time_ms).toLocaleTimeString('tr-TR');
   $('aqLegacy').textContent=old.decision||'—';setClass('aqLegacy',clsDecision(old.decision));
   $('aqLegacyVeto').textContent=(old.veto?.length||0)+' eski veto';
   $('aqNew').textContent=score.final||'—';$('aqCompare').textContent='Teorik: '+(score.theoretical||'—')+' · '+(d.comparison||'—');
   $('aqRegime').textContent=r.label||'VERİ EKSİK';$('aqContext').textContent='Ana MTF: '+(d.mtf?.context||'—');
   $('aqLong').textContent=fmt(score.long_points,1);$('aqShort').textContent=fmt(score.short_points,1);
   $('aqCoverage').textContent='Ölçülebilir aile kapsamı '+(score.coverage_points??0)+'/100 · Puanlar gerçek başarı yüzdesi değil.';
   heatBox('aqLong',score.long_points,'up');heatBox('aqShort',score.short_points,'down');
   heatBox('aqLegacy',45,heatStatusTone(old.decision),false);
   heatBox('aqNew',score.coverage_points,heatStatusTone(score.final),false);
   heatBox('aqRegime',null,'neutral');

   $('aqStats').innerHTML=s.status==='ready'?
     [['Örneklem',s.samples,''],['Tarihsel VaR %95',s.historical_var95_pct,'%'],['Expected Shortfall %95',s.historical_es95_pct,'%'],['Skewness',s.skewness,''],['Excess kurtosis',s.excess_kurtosis,''],['Lag-1 oto-korelasyon',s.lag1_autocorrelation,'']]
     .map(([n,v,u])=>{const h=heatQuant(n,v);return `<div class="row heat-stat-row" ${h?.pct!==undefined?`style="${heatVars(h.pct,h.tone)}"`:''}><span class="note">${escaped(n)}</span><b>${fmt(v,3)}${u}</b>${h?.pct!==undefined?`<small>${heatP(h.pct)}% görsel</small>`:''}</div>`}).join('')+
     `<p class="note">Bootstrap ort. %95 GA: ${fmt(s.block_bootstrap_mean_ci95_pct?.[0],5)} … ${fmt(s.block_bootstrap_mean_ci95_pct?.[1],5)}</p>`:
     `<p class="note">${escaped(s.reason||'İstatistik verisi yetersiz')}</p>`;
   $('aqSetup').innerHTML=`<div class="metric"><small>Referans fiyat</small><b>${fmt(set.entry_ref)}</b></div>`+
    [['Örnek stop',set.stop],['Örnek hedef',set.take_profit],['Net R/R yaklaşımı',set.net_rr_est],['Spread (bps)',set.spread_bps],['Örnek toplam maliyet (bps)',set.roundtrip_est_bps]]
    .map(([n,v])=>`<div class="row" style="margin:7px 0"><span class="note">${escaped(n)}</span><b>${fmt(v,3)}</b></div>`).join('')+
    `<p class="note">${escaped(set.note||'')}</p>`;
   $('aqFamilies').innerHTML=Object.entries(aqFamiliesLabels).map(([k,n])=>{
     let x=score.families?.[k]||{},available=x.long!==null&&x.long!==undefined;
     let l=available?Math.min(100,100*x.long/x.max):0,sh=available?Math.min(100,100*x.short/x.max):0;
     const intensity=available?Math.max(l,sh):null;
     return `<div class="heat-family ${available?'heat-surface':'heat-empty'}" style="${heatVars(intensity,l>=sh?'up':'down')}"><div class="row"><b style="font-size:12px">${escaped(n)}</b><span class="note">${available?fmt(x.long,1)+' L / '+fmt(x.short,1)+' S':'ÖLÇÜLEMİYOR'} · ${x.max??'—'} p.</span></div>
     <div class="bar" style="margin-top:6px"><div style="width:${l}%;background:linear-gradient(90deg,#146c5f,#27d8ac)"></div></div>
     <div class="bar" style="margin-top:3px"><div style="width:${sh}%;background:linear-gradient(90deg,#723048,#ff7089)"></div></div>
     <p class="note" style="margin:5px 0 0">${escaped(x.detail||'')}</p></div>`}).join('');
   $('aqVeto').innerHTML=(score.veto||[]).map(x=>`<div class="reason negative">${escaped(x)}</div>`).join('')||'<span class="chip green">Açık veto yok (gözlem modu)</span>';
   let errors=Object.entries(d.data_errors||{}).map(([k,v])=>k+': '+v);
   $('aqMissing').textContent=[...(d.warnings||[]),...errors].join(' · ')||'Ek uyarı yok';
   $('aqMTF').innerHTML=(d.mtf?.rows||[]).map(x=>`<div class="row" style="margin:8px 0"><b>${escaped(x.tf)}</b><span class="${clsDecision(x.direction)}">${escaped(x.direction)}</span><small class="note">${x.bars} mum</small></div>`).join('');
   $('aqFlow').innerHTML=flow.valid?Object.entries(flow.windows||{}).map(([k,w])=>{const total=(heatN(w.buy_usdt)||0)+(heatN(w.sell_usdt)||0);const h=total>0?Math.abs(w.delta_usdt)/total*100:null;return `<div class="row heat-stat-row" style="${heatVars(h,w.delta_usdt>=0?'up':'down')}"><b>${k} sn</b><span class="${w.delta_usdt>=0?'green':'red'}">${fmt(w.delta_usdt,1)} USDT</span><small class="note">${w.count} işlem${h===null?'':' · '+heatP(h)+'% delta payı'}</small></div>`}).join('')+
       `<p class="note">DOM20 imbalance: ${fmt(flow.depth?.['20']?.imbalance,3)} · Spread: ${fmt(flow.spread_bps,2)} bps</p>`:
       '<p class="hint warn">Doğrulanmış canlı XAUUSDT trade ve derinlik verisi eksik.</p>';
   $('aqContextDetails').innerHTML=`<div><b>Son SMC adayları</b><p class="note">${(d.smc?.events||[]).slice(-3).map(x=>escaped(x.type)).join(', ')||'Yok'}</p></div><div class="separator"></div>`+
      `<div><b>Vadeli</b><p class="note">${escaped(d.derivatives?.note||d.derivatives?.reason||'Eksik')}</p></div><div class="separator"></div>`+
      `<div><b>Makro</b><p class="note">${escaped(d.macro_events?.reason||'Doğrulanmadı')}</p></div>`;
   $('aqStrategies').innerHTML=(d.strategies||[]).map(x=>`<div class="event"><b>${escaped(x.id)} · ${escaped(x.name)}</b><span class="chip ${x.status==='İZLE'?'green':''}">${escaped(x.status)}</span><p class="note">${escaped(x.reason)}</p></div>`).join('');
 }catch(e){if(seq!==aqInFlight)return;$('aqStamp').textContent='HATA: '+e.message;$('aqNew').textContent='VERİ YOK';$('aqVeto').textContent=e.message}
}

async function aqRiskCalc(){
 const q=new URLSearchParams({equity:$('aqEquity').value,daily_loss:$('aqDailyLoss').value,
  weekly_loss:$('aqWeeklyLoss').value,consecutive_losses:$('aqLossStreak').value,
  drawdown_pct:$('aqDrawdown').value});
 $('aqRiskResult').textContent='Risk bütçesi hesaplanıyor…';
 try{const j=await getJSON('/api/altin-quant/risk-plan?'+q.toString());
   $('aqRiskResult').innerHTML=`<div class="metricgrid" style="grid-template-columns:repeat(2,minmax(0,1fr))">`+
      [['Tek işlem bütçesi',j.risk_budget_usd],['Kalan günlük bütçe',j.daily_remaining_usd],['Kalan haftalık bütçe',j.weekly_remaining_usd]]
       .map(([k,v])=>`<div class="metric"><small>${escaped(k)}</small><b>${fmt(v)} USD</b></div>`).join('')+
      `</div>`+(j.veto||[]).map(x=>`<div class="reason negative">${escaped(x)}</div>`).join('')+
      `<p class="note">Bu hesap senaryo amaçlıdır. Günlük açık risk, gerçek hesap bakiyesi ve borsa sözleşme özellikleri doğrulanmıyor; otomatik emir imkânı yok.</p>`;
 }catch(e){$('aqRiskResult').textContent='Risk hesabı yapılamadı: '+e.message}
}


// GOLD v2.1 — Isolated optional UI. Legacy functions and chart controllers unchanged.
async function runAdvancedGoldTest(){
 const btn=$('runAdvTest'),dst=$('advTestResult');btn.disabled=true;dst.textContent='Bağımsız filtreli strateji testi çalışıyor…';
 try{
  const q=new URLSearchParams({symbol,tf,strategy:$('strategy').value,fee_bps:$('fee').value,
   slippage_bps:$('slip').value,spread_bps:$('advSpread').value});
  const result=await getJSON('/api/gold-v21/backtest?'+q.toString());
  const x=result.filtered||{},f=x.forward||{},tr=x.all||{},old=result.legacy||{};
  if(!x.ready){dst.textContent=x.error||'Veri yetersiz';return}
  dst.innerHTML=`<p><b>Eski test:</b> ${fmt(old.net_pnl_usd_ref,2)} ref · ${old.trades_count??'—'} işlem · PF ${fmt(old.profit_factor,2)}</p>`+
   `<p><b>Yeni filtreli tüm örneklem:</b> ${fmt(tr.net_pnl_ref,2)} ref · ${tr.trades_count??'—'} işlem · PF ${fmt(tr.profit_factor,2)}</p>`+
   `<p><b>Son %30 ileri dönem:</b> ${fmt(f.net_pnl_ref,2)} ref · ${f.trades_count??'—'} işlem · PF ${fmt(f.profit_factor,2)}</p>`+
   `<div class="${f.trades_count>=30&&f.net_pnl_ref>0?'reason':'reason negative'}">${f.trades_count<30?'İLERİ DÖNEM YETERSİZ: 30 işlem altı; pozitif sonuç bile kanıt değildir.':f.net_pnl_ref>0?'Pozitif ileri test gözlendi; tekrar doğrulama gerekir.':'İleri dönem negatif; stratejiyi canlı kullanım için önerme.'}</div>`+
   `<p class="note">${escaped(x.note||'')}</p>`+
   `<p class="note">Filtrelenen kurulumlar: ${escaped(JSON.stringify(x.rejected||{}))}</p>`;
 }catch(err){dst.textContent='Filtreli test hatası: '+err.message}
 finally{btn.disabled=false}
}
async function loadGoldExtra(){
 const status=$('goldExtraStatus'),grid=$('goldExtraMetrics'),veto=$('goldExtraVeto');
 status.textContent='Bitget türevleri, sözleşme ve ekonomik takvim kaynakları doğrulanıyor…';grid.innerHTML='';veto.innerHTML='';
 try{
  const data=await getJSON('/api/gold-v21/report?symbol='+encodeURIComponent(symbol)+'&tf='+encodeURIComponent(tf));
  if(data.status==='unavailable'){status.textContent=data.reason;return}
  const oi=data.derivatives||{},ins=data.instrument||{},cal=data.calendar||{},risk=data.risk_plan||{};
  status.textContent='Durum: '+data.status+' · '+new Date(data.timestamp_ms).toLocaleTimeString('tr-TR')+' · Sadece analiz';
  const pairs=[['OI son 5m değişimi',oi.oi_change_5m_pct==null?'—':fmt(oi.oi_change_5m_pct,4)+'%'],
   ['Funding',oi.funding_rate_pct==null?'—':fmt(oi.funding_rate_pct,5)+'%'],
   ['Taker komisyonu',ins.taker_fee_bps==null?'—':fmt(ins.taker_fee_bps,3)+' bps'],
   ['Minimum miktar',ins.min_order_qty==null?'—':fmt(ins.min_order_qty,6)+' '+escaped(ins.base_coin||'base')],
   ['Haber takvimi',cal.status==='ready'?'DOĞRULANDI':'ERİŞİLEMİYOR'],
   ['Örnek işlem planı',risk.status||'BLOCKED']];
  grid.innerHTML=pairs.map(([k,v])=>`<div class="metric"><small>${escaped(k)}</small><b style="font-size:14px">${escaped(v)}</b></div>`).join('');
  const reasons=data.all_veto||[];
  veto.innerHTML=reasons.length?reasons.map(x=>`<div class="reason negative">${escaped(x)}</div>`).join(''):'<div class="reason">Ek veri veto listesinde bir hata bildirilmedi; gerçek işlem yetkisi yoktur.</div>';
  const plan=data.stop_take_scenarios||{};
  if(plan.status==='illustrative'){
    veto.innerHTML+=`<p><b>5m kapalı mumdan matematiksel SENARYOLAR (emir değil)</b></p>`+
      (plan.scenarios||[]).map(x=>`<div class="metric" style="margin:5px 0"><b>${escaped(x.direction)}</b>`+
      `<span class="note">Giriş ${fmt(x.entry_ref)} · Stop ${fmt(x.stop_ref)} · Hedef ${fmt(x.target_ref)} · Net R/R ${fmt(x.net_rr_estimate,2)}</span></div>`).join('');
  }else veto.innerHTML+=`<p class="note">Stop/hedef senaryoları: ${escaped(plan.reason||'Ölçülemedi')}</p>`;
  veto.innerHTML+=`<p class="note">${escaped(data.mtf_explanation||'')}</p>`;
 }catch(err){status.textContent='Ek veri bağlantısı hatası: '+err.message}
}
$('runAdvTest').onclick=runAdvancedGoldTest;
$('goldExtraRefresh').onclick=loadGoldExtra;

// GOLD SCALP PRO · Mobile UX v2.2 (visual-only, no order endpoints)
// Uses verified /api/candles and /api/analysis already loaded by legacy system.
const UX_LIB = {
  ma:{name:'MA • Basit ortalama',short:'MA',kind:'overlay',group:'Trend',note:'Kapanışın basit ortalaması',periods:[5,10,20],multi:true},
  ema:{name:'EMA • Üssel ortalama',short:'EMA',kind:'overlay',group:'Trend',note:'Hızlı tepki veren ortalama',periods:[9,20,50],multi:true},
  boll:{name:'BOLL • Bollinger Bantları',short:'BOLL',kind:'overlay',group:'Volatilite',note:'Ortalama ve ± standart sapma',periods:[20],bands:true},
  sar:{name:'SAR • Parabolic Stop',short:'SAR',kind:'overlay',group:'Trend',note:'Dönüş ve iz süren seviye',periods:[]},
  avl:{name:'AVL • Ortalama fiyat',short:'AVL',kind:'overlay',group:'Trend',note:'(High + Low + Close) / 3 değerinin ortalaması',periods:[20]},
  resist:{name:'RESIST • Önceki bölge sınırları',short:'RESIST',kind:'overlay',group:'Yapı',note:'Geçmiş N mumun tepe/dip seviyesi; tahmini kurumsal emir değil',periods:[20]},
  super:{name:'SUPER • Supertrend',short:'SUPER',kind:'overlay',group:'Trend',note:'ATR tabanlı trend seviyesi',periods:[10],multiplier:3},
  vwap:{name:'VWAP • Hacim ağırlıklı',short:'VWAP',kind:'overlay',group:'Trend',note:'Seçili veri kaynağının hacmiyle hesaplanan 50 mum VWAP',periods:[50]},
  ichi:{name:'ICHI • Tenkan / Kijun',short:'ICHI',kind:'overlay',group:'Trend',note:'Ichimoku dönüş ve baz çizgileri; geleceğe taşınan bulut gösterilmez',periods:[9,26]},
  donchian:{name:'Donchian • Kanal',short:'DONCH',kind:'overlay',group:'Volatilite',note:'Önceki mumların üst/alt aralığı',periods:[20]},
  volume:{name:'VOL • İşlem hacmi',short:'VOL',kind:'panel',group:'Hacim',note:'Kaynağın bildirdiği bar hacmi; CFD tick hacmi farklıdır',periods:[]},
  macd:{name:'MACD',short:'MACD',kind:'panel',group:'Momentum',note:'MACD 12/26/9 histogram ve sinyal',periods:[12,26,9]},
  kdj:{name:'KDJ • Stochastic',short:'KDJ',kind:'panel',group:'Momentum',note:'%K, %D, J çizgileri',periods:[9,3,3]},
  rsi:{name:'RSI • Göreli güç',short:'RSI',kind:'panel',group:'Momentum',note:'Wilder RSI; aşırı bölge 30/70 referanstır',periods:[14]},
  roc:{name:'ROC • Fiyat değişim hızı',short:'ROC',kind:'panel',group:'Momentum',note:'N mum yüzdesel getiri',periods:[12]},
  cci:{name:'CCI • Emtia Kanal Endeksi',short:'CCI',kind:'panel',group:'Momentum',note:'Typical price sapmasının ölçekli göstergesi',periods:[20]},
  williams:{name:'WR • Williams %R',short:'WR',kind:'panel',group:'Momentum',note:'Fiyatın geçmiş yüksek/düşük aralığındaki konumu',periods:[14]},
  obv:{name:'OBV • Denge hacmi',short:'OBV',kind:'panel',group:'Hacim',note:'Mum yönüne göre kümülatif bildirilen hacim',periods:[]},
  stochrsi:{name:'Stoch RSI',short:'STOCH RSI',kind:'panel',group:'Momentum',note:'RSI değerinin stochastic normalize hali',periods:[14]},
  mfi:{name:'MFI • Para Akışı',short:'MFI',kind:'panel',group:'Hacim',note:'Fiyat × hacim bazlı akış endeksi',periods:[14]},
  dmi:{name:'DMI / ADX',short:'DMI',kind:'panel',group:'Trend',note:'+DI / −DI / ADX (Wilder)',periods:[14]},
  atr:{name:'ATR • Gerçek Aralık',short:'ATR',kind:'panel',group:'Volatilite',note:'Fiyat cinsinden ortalama gerçek aralık',periods:[14]},
  cmf:{name:'CMF • Chaikin Money Flow',short:'CMF',kind:'panel',group:'Hacim',note:'Mum aralığı ve hacimden türetilen akış',periods:[20]},
  momentum:{name:'MTM • Momentum',short:'MTM',kind:'panel',group:'Momentum',note:'N mum fiyat farkı',periods:[10]}
};
const UX_KEYS=Object.keys(UX_LIB);
const UX_PALETTE=['#ffbf54','#ff50b6','#8e6cff','#25cfff','#54dfaa','#ff8e5d','#76a7ff'];
const UX_PRESETS={
  bare:{label:'Yalnız fiyat',keys:[],desc:'Grafik üzerindeki tüm indikatörler kapalı'},
  plain:{label:'Sade',keys:['ema','volume'],desc:'EMA ve hacim'},
  scalp:{label:'Scalping',keys:['ema','vwap','rsi','macd','volume'],desc:'EMA • VWAP • RSI • MACD • VOL'},
  trend:{label:'Trend',keys:['ema','super','dmi','macd'],desc:'EMA • Supertrend • DMI • MACD'},
  revert:{label:'Ortalamaya dönüş',keys:['boll','vwap','rsi','cci'],desc:'BOLL • VWAP • RSI • CCI'},
  quant:{label:'Quant Gold',keys:['ema','boll','vwap','rsi','macd','atr','dmi'],desc:'Çoklu teknik + matematiksel takip'}
};
function uxDefault(){
 const inds={};UX_KEYS.forEach((k,idx)=>{inds[k]={enabled:UX_PRESETS.scalp.keys.includes(k),periods:[...UX_LIB[k].periods],colors:UX_PALETTE.slice(idx%UX_PALETTE.length).concat(UX_PALETTE).slice(0,Math.max(3,UX_LIB[k].periods.length)),width:2,height:148,lineEnabled:Array(Math.max(3,UX_LIB[k].periods.length)).fill(true)}});
 return {indicators:inds,chartType:'candlestick',grid:true,crosshair:true,priceLine:true,legend:true,chartHeight:365,preset:'scalp',custom:null,drawings:{},showMark:true,showIndex:false,showSpot:false,alerts:{},panelOrder:UX_KEYS.filter(k=>UX_LIB[k].kind==='panel')};
}
function uxLoad(){const p=uxDefault();try{const v=JSON.parse(localStorage.getItem('gold-ux-v22')||'{}');if(v&&typeof v==='object'){
 for(const key of UX_KEYS){const cfg=v.indicators?.[key];if(!cfg)continue;const cur=p.indicators[key];cur.enabled=!!cfg.enabled;
 cur.periods=(Array.isArray(cfg.periods)?cfg.periods:cur.periods).slice(0,7).map(x=>Math.max(1,Math.min(400,parseInt(x)||14)));
 cur.colors=(Array.isArray(cfg.colors)?cfg.colors:cur.colors).slice(0,7).map((c,i)=>/^#[a-fA-F0-9]{6}$/.test(c)?c:UX_PALETTE[i]);
 cur.lineEnabled=Array.isArray(cfg.lineEnabled)?cfg.lineEnabled.slice(0,7).map(Boolean):cur.lineEnabled;
 cur.width=Math.max(1,Math.min(4,Number(cfg.width)||2));cur.height=Math.max(100,Math.min(500,Number(cfg.height)||148));
 }
 if(['candlestick','line','area','heikin'].includes(v.chartType))p.chartType=v.chartType;
 for(let k of ['grid','crosshair','priceLine','legend'])if(typeof v[k]==='boolean')p[k]=v[k];
 p.chartHeight=Math.max(240,Math.min(750,Number(v.chartHeight)||365));p.drawings=v.drawings&&typeof v.drawings==='object'?v.drawings:{};
 p.showMark=typeof v.showMark==='boolean'?v.showMark:true;p.showIndex=typeof v.showIndex==='boolean'?v.showIndex:false;p.showSpot=typeof v.showSpot==='boolean'?v.showSpot:false;
 p.alerts=v.alerts&&typeof v.alerts==='object'?v.alerts:{};p.custom=Array.isArray(v.custom)?v.custom.filter(x=>UX_KEYS.includes(x)):null;
 p.panelOrder=Array.isArray(v.panelOrder)?[...new Set(v.panelOrder.filter(x=>UX_LIB[x]?.kind==='panel'))]:p.panelOrder;
 p.preset=typeof v.preset==='string'?v.preset:'custom';
 }}catch(e){console.warn('UX preferences reset',e)}return p;
}
let UX=uxLoad(),uxSheetName='',uxDraftKey='',uxLibraryFilter='Tümü',uxSearch='',uxDraft=null,uxCharts={},uxPriceExtras={},uxLastBarsKey='',uxCalcCache={},uxDrawTool='',uxPendingPoint=null,uxTemplateWarning=false,uxToastTimer=null;
const uxInd=k=>UX.indicators[k];
function uxSave(){try{localStorage.setItem('gold-ux-v22',JSON.stringify(UX))}catch(e){uxToast('Tarayıcı tercihleri saklayamadı')}}
const uxV=(x,d=3)=>Number.isFinite(Number(x))?Number(x).toLocaleString('tr-TR',{maximumFractionDigits:d}):'—';
function uxToast(t){let el=$('uxToast');if(!el)return;el.textContent=t;el.classList.add('show');clearTimeout(uxToastTimer);uxToastTimer=setTimeout(()=>el.classList.remove('show'),2600)}
function uxOpen(name='library',arg=''){uxSheetName=name;uxDraft=null;uxDraftKey='';const sheet=$('uxSheet'),overlay=$('uxOverlay');sheet.classList.add('open');overlay.classList.add('open');document.body.classList.add('ux-sheet-on');sheet.setAttribute('aria-hidden','false');uxRenderSheet(name,arg);$('uxCloseSheet').focus();}
function uxClose(){uxSheetName='';$('uxSheet').classList.remove('open');$('uxOverlay').classList.remove('open');document.body.classList.remove('ux-sheet-on');$('uxSheet').setAttribute('aria-hidden','true');uxDrawTip(false)}
function uxSheetRender(name,body,footer=''){$('uxSheetTitle').textContent=name;$('uxSheetBody').innerHTML=body;$('uxSheetFooter').innerHTML=footer;$('uxSheetFooter').style.display=footer?'flex':'none';}
const uxFooter=(cancel='Vazgeç',okay='Uygula')=>`<button class="ux-outline-btn" data-ux="sheet-close">${cancel}</button><button class="ux-primary-btn" data-ux="sheet-save">${okay}</button>`;
function uxRenderSheet(name,arg=''){
 if(name==='library'){
  const tabs=['Tümü','Aktif','Trend','Momentum','Volatilite','Hacim','Yapı'];let terms=uxSearch.toLocaleLowerCase('tr-TR');
  const list=UX_KEYS.filter(k=>(uxLibraryFilter==='Tümü'||(uxLibraryFilter==='Aktif'?uxInd(k).enabled:UX_LIB[k].group===uxLibraryFilter))&&(UX_LIB[k].name.toLocaleLowerCase('tr-TR').includes(terms)||UX_LIB[k].short.toLocaleLowerCase('tr-TR').includes(terms)));
  const html=`<p class="ux-sheet-sub">Grafikte çizimleri aç/kapat. Her gösterge yalnız görsel amaçlıdır; işlem motorunu değiştirmez.</p><input class="ux-search" id="uxSearch" placeholder="İndikatör ara..." aria-label="İndikatör ara" value="${escaped(uxSearch)}"><div class="ux-sheet-tabs">${tabs.map(x=>`<button class="ux-sheet-tab ${uxLibraryFilter===x?'active':''}" data-ux="cat" data-id="${x}">${x}</button>`).join('')}</div>`+
  (list.map(k=>{let i=UX_LIB[k];return `<div class="ux-library-row"><div style="flex:1;min-width:0"><strong>${i.name}</strong><p>${i.note} · ${i.kind==='panel'?'Bağımsız alt panel':'Fiyat üzeri'}</p></div><div class="ux-library-actions"><button class="ux-pill-btn ${uxInd(k).enabled?'active':''}" data-ux="toggle" data-id="${k}" aria-pressed="${uxInd(k).enabled}">${uxInd(k).enabled?'Kapat':'Ekle'}</button><button class="ux-icon-btn" aria-label="${i.short} ayarları" data-ux="edit" data-id="${k}">⚙</button></div></div>`}).join('')||'<p class="ux-note">Bu aramada gösterge bulunamadı.</p>');
  uxSheetRender('İndikatör Kütüphanesi',html);const inp=$('uxSearch');inp?.addEventListener('input',e=>{uxSearch=e.target.value;const caret=e.target.selectionStart;uxRenderSheet('library');const x=$('uxSearch');x.focus();x.setSelectionRange(caret,caret)});return;
 }
 if(name==='active'){
  let list=UX_KEYS.filter(k=>uxInd(k).enabled);
  uxSheetRender('Aktif Katmanlar',`<p class="ux-sheet-sub">Alt panellerin sırasını değiştirebilir, büyütebilir veya kaldırabilirsin.</p>`+
   (list.map(k=>`<div class="ux-library-row"><div><strong>${UX_LIB[k].name}</strong><p>${UX_LIB[k].kind==='panel'?'Alt panel · '+uxInd(k).height+'px':'Ana grafik'}</p></div><div class="ux-library-actions"><button class="ux-pill-btn" data-ux="edit" data-id="${k}">Ayar</button>${UX_LIB[k].kind==='panel'?`<button class="ux-pill-btn" data-ux="move-up" data-id="${k}" aria-label="Yukarı">↑</button>`:''}<button class="ux-pill-btn danger" data-ux="toggle" data-id="${k}">Kaldır</button></div></div>`).join('')||'<p class="ux-note">Hiç aktif gösterge yok.</p>')+
  `<button class="ux-pill-btn" style="width:100%;margin-top:15px" data-ux="open-library">+ Yeni indikatör ekle</button>`);return;
 }
 if(name==='settings'){
  const setting=(title,key,checked)=>`<div class="ux-input-row"><label for="ux-setting-${key}">${title}</label><input id="ux-setting-${key}" data-uxpref="${key}" type="checkbox" ${checked?'checked':''}></div>`;
  uxSheetRender('Grafik Ayarları',`<div class="ux-tile-grid">${[['library','▥','İndikatör'],['draw','✎','Çizim'],['templates','▦','Şablonlar'],['active','☷','Aktif Katmanlar'],['alert','◉','Fiyat Alarmı']].map(([id,ico,n])=>`<button class="ux-tile" data-ux="open-${id}">${ico} ${n}</button>`).join('')}</div><div class="ux-sheet-group">Grafik görünümü</div>`+
   `<div class="ux-input-row"><label for="uxType">Grafik türü</label><select id="uxType"><option value="candlestick">Mum</option><option value="line">Çizgi</option><option value="area">Alan</option><option value="heikin">Heikin Ashi*</option></select></div>`+
   setting('Kılavuz çizgileri','grid',UX.grid)+setting('Artı imleç','crosshair',UX.crosshair)+setting('Son fiyat çizgisi','priceLine',UX.priceLine)+setting('Gösterge etiketleri','legend',UX.legend)+
   `<div class="ux-sheet-group">Doğrulanmış piyasa fiyat çizgileri</div>`+setting('Mark fiyatını göster','showMark',UX.showMark)+setting('Index fiyatını göster','showIndex',UX.showIndex)+setting('Spot karşılaştırma fiyatı','showSpot',UX.showSpot)+
   `<div class="ux-input-row"><label for="uxHeight">Ana grafik yüksekliği</label><input id="uxHeight" type="range" min="240" max="650" value="${UX.chartHeight}"><output id="uxHeightLabel">${UX.chartHeight}px</output></div>`+
   `<p class="ux-note">* Heikin Ashi dönüştürülmüş mumdur; gerçek işlem fiyatı değildir. Konum/pozisyon emri çizimi bu read-only uygulamada bulunmaz.</p>`,uxFooter('Kapat','Kaydet'));
  $('uxType').value=UX.chartType;return;
 }
 if(name==='edit'){
  const i=UX_LIB[arg];if(!i)return uxRenderSheet('library');const cfg=uxDraftKey===arg&&uxDraft?uxDraft:uxInd(arg);
  if(uxDraftKey!==arg||!uxDraft){uxDraft={...cfg,periods:[...cfg.periods],colors:[...cfg.colors],lineEnabled:[...(cfg.lineEnabled||[])]};uxDraftKey=arg}
  const rows=cfg.periods.map((p,idx)=>`<div class="ux-form-row"><input type="checkbox" data-uxline="${idx}" aria-label="Çizgi ${idx+1} görünür" ${cfg.lineEnabled?.[idx]!==false?'checked':''}><div class="ux-form-label">${i.short} ${cfg.periods.length>1?' '+(idx+1):''}</div><input class="ux-number" type="number" inputmode="numeric" min="1" max="400" data-uxperiod="${idx}" value="${p}"><input type="color" data-uxcolor="${idx}" value="${cfg.colors[idx]||UX_PALETTE[idx%UX_PALETTE.length]}"><button class="ux-width" data-ux="width" aria-label="Çizgi kalınlığı">${cfg.width}px</button></div>`).join('');
  const one=!i.periods.length?`<div class="ux-input-row"><label>Çizgi rengi</label><input aria-label="Renk" type="color" data-uxcolor="0" value="${cfg.colors[0]||UX_PALETTE[0]}"></div>`:'';
  uxSheetRender(i.name,`<p class="ux-sheet-sub">${i.note}</p><div class="ux-input-row"><label for="uxEnabled">Grafikte göster</label><input type="checkbox" id="uxEnabled" ${cfg.enabled?'checked':''}></div><div class="ux-sheet-group">${i.kind==='overlay'?'Ana grafik çizgileri':'Alt panel hesaplaması'}</div>${rows}${one}`+
   (i.multi?`<div class="ux-input-row"><button class="ux-pill-btn" data-ux="add-line" data-id="${arg}">+ MA/EMA çizgisi ekle</button><button class="ux-pill-btn danger" data-ux="remove-line" data-id="${arg}">Son çizgiyi çıkar</button></div>`:'')+
   (i.kind==='panel'?`<div class="ux-input-row"><label for="uxPanelHeight">Alt panel yüksekliği</label><input id="uxPanelHeight" type="range" min="100" max="440" value="${cfg.height}"><output id="uxPanelHeightValue">${cfg.height}px</output></div>`:'')+
   `<p class="ux-note">Yalnız grafik çizim ayarıdır. Karar skoru, backtest ve Gateway hesaplamaları değişmez.</p>`,`<button class="ux-outline-btn" data-ux="reset-ind" data-id="${arg}">Sıfırla</button><button class="ux-primary-btn" data-ux="save-ind" data-id="${arg}">Uygula</button>`);return;
 }
 if(name==='templates'){
  const entries=Object.entries(UX_PRESETS).map(([k,v])=>`<div class="ux-template-card"><strong>${v.label}</strong><p>${v.desc}</p><button class="ux-pill-btn ${UX.preset===k?'active':''}" data-ux="preset" data-id="${k}">${UX.preset===k?'Etkin':'Uygula'}</button></div>`).join('');
  uxSheetRender('Grafik Şablonları',`<p class="ux-sheet-sub">Tek dokunuşla görünüm değiştir. Renk ve periyot ayarların korunur.</p>${entries}<div class="ux-sheet-group">Kişisel şablon</div><button class="ux-pill-btn" data-ux="save-template">Mevcut görünümü kaydet</button>`+
  (UX.custom?`<button class="ux-pill-btn" style="margin-left:8px" data-ux="restore-template">Kişisel şablonu yükle</button>`:'')+
  `<p class="ux-note">Kaydedilen şablon sadece bu tarayıcıda saklanır.</p>`);return;
 }
 if(name==='alert'){
  const conf=UX.alerts[symbol]||{direction:'above',price:'',active:false};
  uxSheetRender('Fiyat Alarmı',`<p class="ux-sheet-sub">Alarm sadece uygulama açıkken, seçili enstrümanın doğrulanmış canlı fiyatı eşiğe ulaşırsa bu ekranda uyarı gösterir. Arka planda bildirim gönderilmez.</p>`+
   `<div class="ux-input-row"><label for="uxAlertDirection">Koşul</label><select id="uxAlertDirection"><option value="above">Fiyat yükselirse ≥</option><option value="below">Fiyat düşerse ≤</option></select></div>`+
   `<div class="ux-input-row"><label for="uxAlertPrice">Eşik fiyat</label><input class="ux-number" id="uxAlertPrice" type="number" step="0.01" min="0.01" value="${conf.price||''}"></div>`+
   `<div class="ux-input-row"><label for="uxAlertEnabled">Alarm aktif</label><input type="checkbox" id="uxAlertEnabled" ${conf.active?'checked':''}></div>`,uxFooter('Kapat','Alarmı kaydet'));
   $('uxAlertDirection').value=conf.direction;return;
 }
 if(name==='draw'){
  uxSheetRender('Çizim Araçları',`<p class="ux-sheet-sub">Grafik üzerine fiyat seviyesi veya iki dokunuşla trend çizgisi ekle. Bunlar analiz notudur, emir değildir.</p>`+
  `<div class="ux-tile-grid"><button class="ux-tile ${uxDrawTool==='horizontal'?'active':''}" data-ux="tool" data-id="horizontal">━ Yatay fiyat çizgisi</button><button class="ux-tile ${uxDrawTool==='trend'?'active':''}" data-ux="tool" data-id="trend">╱ İki nokta trend çizgisi</button><button class="ux-tile" data-ux="draw-undo">↶ Son çizimi geri al</button><button class="ux-tile" data-ux="draw-clear">⌫ Tüm çizimleri temizle</button></div><p class="ux-note">Çizim sırasında grafiğe dokun. Tam görünür alana göre konumlar güncellenir.</p>`);return;
 }
 if(name==='analysis-menu'||name==='more-menu'){
  const menus=name==='analysis-menu'?[['technical','▧','Teknik Göstergeler'],['smc','◇','SMC / ICT'],['flow','⇄','Order Flow'],['depth','▥','Emir Defteri DOM'],['quant','Σ','Quant İstatistik'],['altinquant','✦','ALTIN QUANT v2'],['quanthub','◈','7 Quant + Konsensüs'],['decision','◎','Karar Motoru']]:[['derivatives','◉','Vadeli / OI / Funding'],['macro','☼','Makro ve Haber'],['performance','▤','Performans'],['health','●','Veri Sağlığı'],['settings','⚙','Ayarlar']];
  if(name==='analysis-menu'){
   const groups=[['Hızlı analiz',['technical','flow','smc']],['Matematik & Quant',['quant','altinquant','quanthub']],['Doğrulama ve derinlik',['decision','depth']]];
   uxSheetRender('Analiz merkezi',`<p class="ux-sheet-sub">Aynı kategoriye ait bilgiler aynı bölümde. Günlük karar için Özet, ayrıntı için ilgili analiz ekranını aç.</p>`+
    groups.map(([title,ids])=>`<div class="g32-menu-group"><h3>${title}</h3><div class="ux-tile-grid">${ids.map(id=>{const m=menus.find(x=>x[0]===id);return `<button class="ux-tile" data-go="${id}">${m[1]} ${m[2]}</button>`}).join('')}</div></div>`).join(''));return;
  }
  uxSheetRender('Diğer Bölümler',`<p class="ux-sheet-sub">Vadeli, haberler, performans ve sistem ayarları.</p><div class="ux-tile-grid">${menus.map(([k,icon,label])=>`<button class="ux-tile" data-go="${k}">${icon} ${label}</button>`).join('')}</div>`);return;
 }
}
function uxUpdateDock(k){document.body.dataset.uxPage=k;const group=k==='dashboard'?'dashboard':k==='chart'?'chart':k==='strategies'?'strategies':['technical','smc','flow','depth','quant','altinquant','quanthub','decision'].includes(k)?'analysis':'more';document.querySelectorAll('[data-uxnav]').forEach(x=>{let active=x.dataset.uxnav===group;x.classList.toggle('active',active);if(active)x.setAttribute('aria-current','page');else x.removeAttribute('aria-current')});}
function uxSetTf(v){if(!tfs.includes(v))return;tf=v;$('tfbar').querySelectorAll('[data-tf]').forEach(x=>x.classList.toggle('active',x.dataset.tf===v));document.querySelectorAll('[data-uxtf]').forEach(x=>x.classList.toggle('active',x.dataset.uxtf===v));uxToast(v+' zaman dilimi');uxLastBarsKey='';reloadAll()}
function uxApplyPreset(k){if(!UX_PRESETS[k])return;UX_KEYS.forEach(id=>{UX.indicators[id].enabled=UX_PRESETS[k].keys.includes(id)});UX.preset=k;uxSave();uxUpdateIndicators();uxRenderSheet('templates');uxToast(UX_PRESETS[k].label+' şablonu uygulandı')}
function uxToggle(k,open){if(!UX_LIB[k])return;UX.indicators[k].enabled=typeof open==='boolean'?open:!UX.indicators[k].enabled;UX.preset='custom';uxSave();uxUpdateIndicators();if(uxSheetName==='library'||uxSheetName==='active')uxRenderSheet(uxSheetName);uxToast(`${UX_LIB[k].short} ${UX.indicators[k].enabled?'açıldı':'kapatıldı'}`)}
function uxUpdateIndicators(){uxRenderQuick();uxUpdateActiveTags();uxRenderDetail()}
function uxRenderQuick(){let root=$('uxQuick');if(!root)return;const items=['ma','ema','boll','sar','avl','resist','super','vwap','ichi','rsi','macd','cci','atr'];root.innerHTML=items.map(k=>`<button class="ux-quick ${uxInd(k).enabled?'active':''}" aria-pressed="${uxInd(k).enabled}" data-uxquick="${k}" title="${UX_LIB[k].name} — uzun bas: ayar">${UX_LIB[k].short}</button>`).join('')+'<button class="ux-quick ux-add" data-ux="open-library" aria-label="Gösterge ekle">＋</button>'}
function uxUpdateActiveTags(){let root=$('uxActiveTags');if(!root)return;root.innerHTML=UX.legend?UX_KEYS.filter(k=>uxInd(k).enabled).map(k=>`<span class="ux-tag">${UX_LIB[k].short} <button aria-label="${UX_LIB[k].short} kaldır" data-ux="toggle" data-id="${k}">×</button></span>`).join(''):' '}
function uxSetPanelSize(k,delta){const cfg=uxInd(k);cfg.height=Math.max(100,Math.min(440,cfg.height+delta));uxSave();const root=$(`ux-panel-${k}`);if(root){root.querySelector('.ux-osc-canvas').style.height=cfg.height+'px';root.querySelector('small').textContent=cfg.height+'px';uxCharts[k]?.chart?.applyOptions({autoSize:true})}}
function uxPanelOrder(k){let ids=UX.panelOrder.filter(x=>x!==k),old=UX.panelOrder.indexOf(k);ids.splice(Math.max(0,old-1),0,k);UX.panelOrder=ids;uxSave();uxRenderDetail()}
function uxDrawingKey(){return symbol+'|'+tf}
function uxDrawings(){let d=UX.drawings[uxDrawingKey()];return Array.isArray(d)?d:[]}
function uxSaveDrawing(d){UX.drawings[uxDrawingKey()]=d.slice(-40);uxSave()}
function uxDrawTip(on,text){let el=$('uxDrawTip');el.classList.toggle('show',!!on);el.textContent=text||''}
function uxDrawingAction(action){let items=[...uxDrawings()];if(action==='undo')items.pop();else if(action==='clear')items=[];uxSaveDrawing(items);uxRedrawDrawings();uxToast(action==='clear'?'Çizimler temizlendi':'Son çizim kaldırıldı')}
function uxAttachDraw(chartWrap){if(!chartWrap||chartWrap._uxDrawListener)return;chartWrap._uxDrawListener=true;chartWrap.chart.subscribeClick(param=>{
 if(!uxDrawTool||!param?.point)return;const price=chartWrap.main.coordinateToPrice(param.point.y),t=chartWrap.chart.timeScale().coordinateToTime(param.point.x);
 if(!Number.isFinite(price)||typeof t!=='number')return;
 if(uxDrawTool==='horizontal'){uxSaveDrawing([...uxDrawings(),{type:'horizontal',price,time:t}]);uxDrawTool='';uxDrawTip(false);uxToast('Yatay seviye eklendi')}
 else if(uxDrawTool==='trend'){if(!uxPendingPoint){uxPendingPoint={time:t,price};uxDrawTip(true,'Trend çizgisi: ikinci noktaya dokun')}else{uxSaveDrawing([...uxDrawings(),{type:'trend',a:uxPendingPoint,b:{time:t,price}}]);uxPendingPoint=null;uxDrawTool='';uxDrawTip(false);uxToast('Trend çizgisi eklendi')}}uxRedrawDrawings();
 });chartWrap.chart.timeScale().subscribeVisibleLogicalRangeChange(()=>{window.__uxZoomTouched=true;uxRedrawDrawings();uxSyncPanels()});
}
function uxRedrawDrawings(){const can=$('uxDrawCanvas'),p=plots.detail;if(!can||!p)return;let rect=can.getBoundingClientRect(),ratio=Math.min(2,devicePixelRatio||1);if(rect.width<2)return;can.width=Math.floor(rect.width*ratio);can.height=Math.floor(rect.height*ratio);const c=can.getContext('2d');c.setTransform(ratio,0,0,ratio,0,0);c.clearRect(0,0,rect.width,rect.height);
 c.strokeStyle='#eac46f';c.fillStyle='#eac46f';c.lineWidth=1.5;c.setLineDash([5,4]);
 for(const item of uxDrawings()){
  if(item.type==='horizontal'){const y=p.main.priceToCoordinate(item.price);if(y===null)continue;c.beginPath();c.moveTo(0,y);c.lineTo(rect.width,y);c.stroke();c.font='11px system-ui';c.fillText(uxV(item.price,2),7,Math.max(12,y-4))}
  if(item.type==='trend'){const x1=p.chart.timeScale().timeToCoordinate(item.a.time),x2=p.chart.timeScale().timeToCoordinate(item.b.time),y1=p.main.priceToCoordinate(item.a.price),y2=p.main.priceToCoordinate(item.b.price);if([x1,x2,y1,y2].some(x=>x===null))continue;c.beginPath();c.moveTo(x1,y1);c.lineTo(x2,y2);c.stroke()}
 }
 c.setLineDash([]);
}
function uxSyncPanels(){let p=plots.detail;if(!p)return;try{const range=p.chart.timeScale().getVisibleLogicalRange();if(range){for(const x of Object.values(uxCharts))try{x.chart.timeScale().setVisibleLogicalRange(range)}catch(e){}}}catch(e){}}
// Browser indicators are VISUAL ONLY. No future bars, no data source replacement.
const uxNone=n=>Array(n).fill(null);
function uxSma(a,n){let out=uxNone(a.length),sum=0;for(let i=0;i<a.length;i++){const v=a[i];if(!Number.isFinite(v)){sum=0;continue}sum+=v;if(i>=n)sum-=Number.isFinite(a[i-n])?a[i-n]:0;if(i>=n-1)out[i]=sum/n}return out}
function uxEma(a,n){let out=uxNone(a.length),seed=[],e=null,k=2/(n+1);for(let i=0;i<a.length;i++){const v=a[i];if(!Number.isFinite(v))continue;if(e===null){seed.push(v);if(seed.length===n){e=seed.reduce((x,y)=>x+y,0)/n;out[i]=e}}else{e=k*v+(1-k)*e;out[i]=e}}return out}
function uxRsi(a,n){let out=uxNone(a.length),gain=0,loss=0,ag=0,al=0;for(let i=1;i<a.length;i++){const d=a[i]-a[i-1],g=Math.max(0,d),l=Math.max(0,-d);if(i<=n){gain+=g;loss+=l;if(i===n){ag=gain/n;al=loss/n;out[i]=al===0?100:100-100/(1+ag/al)}}else{ag=(ag*(n-1)+g)/n;al=(al*(n-1)+l)/n;out[i]=al===0?100:100-100/(1+ag/al)}}return out}
function uxTrueRange(b){return b.map((x,i)=>Math.max(x.h-x.l,Math.abs(x.h-(i?b[i-1].c:x.c)),Math.abs(x.l-(i?b[i-1].c:x.c))))}
function uxWilder(a,n){let o=uxNone(a.length),seed=0,prev=null;for(let i=0;i<a.length;i++){const x=a[i];if(!Number.isFinite(x))continue;if(i<n){seed+=x;if(i===n-1){prev=seed/n;o[i]=prev}}else if(prev!==null){prev=(prev*(n-1)+x)/n;o[i]=prev}}return o}
function uxAtr(b,n){return uxWilder(uxTrueRange(b),n)}
function uxBoll(a,n,mult=2){const mid=uxSma(a,n),up=uxNone(a.length),low=uxNone(a.length);for(let i=n-1;i<a.length;i++){if(mid[i]==null)continue;let variance=0;for(let j=i-n+1;j<=i;j++)variance+=(a[j]-mid[i])**2;const dev=Math.sqrt(variance/n)*mult;up[i]=mid[i]+dev;low[i]=mid[i]-dev}return {mid,up,low}}
function uxVWAP(b,n){let out=uxNone(b.length),num=0,den=0;for(let i=0;i<b.length;i++){const tp=(b[i].h+b[i].l+b[i].c)/3,v=Number(b[i].v||0);num+=tp*v;den+=v;if(i>=n){let old=(b[i-n].h+b[i-n].l+b[i-n].c)/3,ov=Number(b[i-n].v||0);num-=old*ov;den-=ov}if(i>=n-1&&den>0)out[i]=num/den}return out}
function uxHighLow(b,n,excludeCurrent=false){let hi=uxNone(b.length),lo=uxNone(b.length);for(let i=n-1;i<b.length;i++){let end=excludeCurrent?i:i+1,start=end-n;if(start<0)continue;let h=-Infinity,l=Infinity;for(let j=start;j<end;j++){h=Math.max(h,b[j].h);l=Math.min(l,b[j].l)}hi[i]=h;lo[i]=l}return {hi,lo}}
function uxSAR(b){let out=uxNone(b.length);if(b.length<3)return out;let up=b[1].c>=b[0].c,ep=up?Math.max(b[0].h,b[1].h):Math.min(b[0].l,b[1].l),sar=up?Math.min(b[0].l,b[1].l):Math.max(b[0].h,b[1].h),af=.02;for(let i=2;i<b.length;i++){sar=sar+af*(ep-sar);if(up){sar=Math.min(sar,b[i-1].l,b[i-2].l);if(b[i].l<sar){up=false;sar=ep;ep=b[i].l;af=.02}else if(b[i].h>ep){ep=b[i].h;af=Math.min(.2,af+.02)}}else{sar=Math.max(sar,b[i-1].h,b[i-2].h);if(b[i].h>sar){up=true;sar=ep;ep=b[i].h;af=.02}else if(b[i].l<ep){ep=b[i].l;af=Math.min(.2,af+.02)}}out[i]=sar}return out}
function uxSuper(b,n,m=3){let out=uxNone(b.length),atr=uxAtr(b,n),prevUp=null,prevDown=null,trend=1;for(let i=0;i<b.length;i++){if(atr[i]===null)continue;const mid=(b[i].h+b[i].l)/2,baseUp=mid+m*atr[i],baseDown=mid-m*atr[i];let upper=prevUp!==null&&(baseUp>=prevUp&&b[i-1].c<=prevUp)?prevUp:baseUp,lower=prevDown!==null&&(baseDown<=prevDown&&b[i-1].c>=prevDown)?prevDown:baseDown;if(i>0&&prevUp!==null){if(trend<0&&b[i].c>upper)trend=1;else if(trend>0&&b[i].c<lower)trend=-1}out[i]=trend>0?lower:upper;prevUp=upper;prevDown=lower}return out}
function uxMACD(a,f,s,sign){let first=uxEma(a,f),second=uxEma(a,s),mac=first.map((v,i)=>v!==null&&second[i]!==null?v-second[i]:null),signal=uxEma(mac,sign),hist=mac.map((v,i)=>v!==null&&signal[i]!==null?v-signal[i]:null);return{mac,signal,hist}}
function uxStoch(b,n,smooth=3,d=3){let k0=uxNone(b.length),lohi=uxHighLow(b,n);for(let i=0;i<b.length;i++){let lo=lohi.lo[i],hi=lohi.hi[i];if(lo!==null)k0[i]=hi===lo?50:100*(b[i].c-lo)/(hi-lo)};let k=uxSmaOptional(k0,smooth),dd=uxSmaOptional(k,d),j=k.map((v,i)=>v!==null&&dd[i]!==null?3*v-2*dd[i]:null);return{k,d:dd,j}}
function uxSmaOptional(a,n){let out=uxNone(a.length);for(let i=n-1;i<a.length;i++){const w=a.slice(i-n+1,i+1);if(w.every(x=>x!==null&&Number.isFinite(x)))out[i]=w.reduce((x,y)=>x+y,0)/n}return out}
function uxCCI(b,n){let tp=b.map(x=>(x.h+x.l+x.c)/3),ma=uxSma(tp,n),out=uxNone(tp.length);for(let i=n-1;i<tp.length;i++){let dev=0;for(let j=i-n+1;j<=i;j++)dev+=Math.abs(tp[j]-ma[i]);dev/=n;if(dev>0)out[i]=(tp[i]-ma[i])/(.015*dev)}return out}
function uxDMI(b,n){let plus=uxNone(b.length).map(()=>0),minus=uxNone(b.length).map(()=>0),tr=uxTrueRange(b);for(let i=1;i<b.length;i++){let up=b[i].h-b[i-1].h,down=b[i-1].l-b[i].l;plus[i]=up>down&&up>0?up:0;minus[i]=down>up&&down>0?down:0}let at=uxWilder(tr,n),p=uxWilder(plus,n),m=uxWilder(minus,n),pdi=uxNone(b.length),mdi=uxNone(b.length),dx=uxNone(b.length);for(let i=0;i<b.length;i++){if(at[i]===null||!at[i])continue;pdi[i]=100*p[i]/at[i];mdi[i]=100*m[i]/at[i];const den=pdi[i]+mdi[i];dx[i]=den?100*Math.abs(pdi[i]-mdi[i])/den:0}let adx=uxWilder(dx.map(x=>x??0),n);return{pdi,mdi,adx}}
function uxMFI(b,n){let tp=b.map(x=>(x.h+x.l+x.c)/3),out=uxNone(b.length);for(let i=n;i<b.length;i++){let pos=0,neg=0;for(let j=i-n+1;j<=i;j++){let flow=tp[j]*Math.max(0,b[j].v||0);if(tp[j]>tp[j-1])pos+=flow;else if(tp[j]<tp[j-1])neg+=flow}if(pos+neg>0)out[i]=neg===0?100:100-100/(1+pos/neg)}return out}
function uxCMF(b,n){let out=uxNone(b.length);for(let i=n-1;i<b.length;i++){let mf=0,v=0;for(let j=i-n+1;j<=i;j++){let x=b[j],vol=Math.max(0,x.v||0);v+=vol;mf+=x.h===x.l?0:((x.c-x.l)-(x.h-x.c))/(x.h-x.l)*vol}if(v>0)out[i]=mf/v}return out}
function uxStochRSI(a,n){let r=uxRsi(a,n),o=uxNone(a.length);for(let i=2*n-1;i<a.length;i++){const w=r.slice(i-n+1,i+1);if(w.some(x=>x===null))continue;let high=Math.max(...w),low=Math.min(...w);o[i]=high===low?50:100*(r[i]-low)/(high-low)}return o}
function uxCompute(b,k){const cfg=uxInd(k),n=cfg.periods[0]||14,c=b.map(x=>x.c),res=[];const add=(id,values,colorIndex=0,hist=false)=>{res.push({id,values,hist,color:cfg.colors[colorIndex]||UX_PALETTE[colorIndex%UX_PALETTE.length],width:cfg.width})};
 switch(k){
  case 'ma':cfg.periods.forEach((p,i)=>{if(cfg.lineEnabled?.[i]!==false)add('MA'+p,uxSma(c,p),i)});break;
  case 'ema':cfg.periods.forEach((p,i)=>{if(cfg.lineEnabled?.[i]!==false)add('EMA'+p,uxEma(c,p),i)});break;
  case 'boll':{let x=uxBoll(c,n);add('Üst bant',x.up,0);add('Orta',x.mid,1);add('Alt bant',x.low,2);break}
  case 'vwap':add('VWAP'+n,uxVWAP(b,n));break;
  case 'avl':add('AVL'+n,uxSma(b.map(x=>(x.h+x.l+x.c)/3),n));break;
  case 'resist':{let x=uxHighLow(b,n,true);add('Direnç',x.hi,0);add('Destek',x.lo,1);break}
  case 'donchian':{let x=uxHighLow(b,n,true);add('Donchian üst',x.hi,0);add('Donchian alt',x.lo,1);break}
  case 'sar':add('SAR',uxSAR(b));break;
  case 'super':add('Supertrend',uxSuper(b,n));break;
  case 'ichi':{let a=uxHighLow(b,cfg.periods[0]||9),d=uxHighLow(b,cfg.periods[1]||26);add('Tenkan',a.hi.map((v,i)=>v!==null?(v+a.lo[i])/2:null),0);add('Kijun',d.hi.map((v,i)=>v!==null?(v+d.lo[i])/2:null),1);break}
  case 'volume':add('Hacim',b.map(x=>x.v||0),0,true);break;
  case 'macd':{let x=uxMACD(c,...cfg.periods.slice(0,3));add('MACD',x.mac,0);add('Sinyal',x.signal,1);add('Histogram',x.hist,2,true);break}
  case 'kdj':{let x=uxStoch(b,...cfg.periods.slice(0,3));add('%K',x.k,0);add('%D',x.d,1);add('J',x.j,2);break}
  case 'rsi':add('RSI'+n,uxRsi(c,n));break;
  case 'roc':add('ROC'+n,c.map((x,i)=>i>=n&&c[i-n]!==0?100*(x/c[i-n]-1):null));break;
  case 'cci':add('CCI',uxCCI(b,n));break;
  case 'williams':{const hl=uxHighLow(b,n);add('Williams R',c.map((v,i)=>hl.hi[i]!==null&&hl.hi[i]!==hl.lo[i]?-100*(hl.hi[i]-v)/(hl.hi[i]-hl.lo[i]):null));break}
  case 'obv':{let acc=0;add('OBV',c.map((v,i)=>{if(i)acc+=(v>c[i-1]?1:v<c[i-1]?-1:0)*(b[i].v||0);return acc}));break}
  case 'stochrsi':add('Stoch RSI',uxStochRSI(c,n));break;
  case 'mfi':add('MFI',uxMFI(b,n));break;
  case 'dmi':{let x=uxDMI(b,n);add('+DI',x.pdi,0);add('−DI',x.mdi,1);add('ADX',x.adx,2);break}
  case 'atr':add('ATR'+n,uxAtr(b,n));break;
  case 'cmf':add('CMF'+n,uxCMF(b,n));break;
  case 'momentum':add('Momentum',c.map((x,i)=>i>=n?x-c[i-n]:null));break;
 }
 return res;
}
function uxBars(){return candleData.filter(x=>Number.isFinite(x.t)&&Number.isFinite(x.c)&&x.c>0).map(x=>({t:x.t,o:Number(x.o),h:Number(x.h),l:Number(x.l),c:Number(x.c),v:Number(x.v||0)}))}
function uxDataKey(b){if(!b.length)return '';let last=b[b.length-1];return symbol+'|'+tf+'|'+b.length+'|'+last.t+'|'+last.c+'|'+last.v}
function uxGetCalculations(b){let key=uxDataKey(b);if(uxLastBarsKey!==key){uxLastBarsKey=key;uxCalcCache={}};return uxCalcCache}
function uxGetLines(b,k){const cache=uxGetCalculations(b),cfg=uxInd(k),signature=JSON.stringify([k,cfg.periods,cfg.colors,cfg.width,cfg.lineEnabled]);if(!cache[signature])cache[signature]=uxCompute(b,k);return cache[signature]}
function uxPlotSeries(chart,owner,b,keys){const L=window.LightweightCharts;if(!L||!chart)return;const desired=new Set();for(const k of keys){if(!uxInd(k).enabled)continue;const lines=uxGetLines(b,k);for(const d of lines){const sk=k+':'+d.id;desired.add(sk);let entry=owner[sk];if(!entry){const src=chart.addSeries(d.hist?L.HistogramSeries:L.LineSeries,{color:d.color,lineWidth:d.width,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});owner[sk]={series:src,hist:d.hist};entry=owner[sk]}
 const data=d.values.map((v,i)=>v===null||!Number.isFinite(v)?null:{time:b[i].t,value:v,...(d.hist?{color:k==='volume'?(b[i].c>=b[i].o?'#43d8ad':'#fa718a'):(v>=0?'#4bd4b8':'#f0748c')}:{} )}).filter(Boolean);
 try{entry.series.applyOptions({visible:true,color:d.color,lineWidth:d.width});entry.series.setData(data)}catch(e){console.warn('UX indicator plot',sk,e)}
 }}for(const [id,obj] of Object.entries(owner))if(!desired.has(id)){try{chart.removeSeries(obj.series)}catch(e){}delete owner[id]}
}
function uxHeikin(b){let out=[],prevOpen=b[0]?.o||0,prevClose=b[0]?.c||0;for(const x of b){let close=(x.o+x.h+x.l+x.c)/4,open=out.length?(prevOpen+prevClose)/2:(x.o+x.c)/2;out.push({time:x.t,open,close,high:Math.max(x.h,open,close),low:Math.min(x.l,open,close)});prevOpen=open;prevClose=close}return out}
function uxCreateTypeSeries(p,b){const L=window.LightweightCharts;if(!L)return;const map={line:L.LineSeries,area:L.AreaSeries,heikin:L.CandlestickSeries};for(const [k,typ] of Object.entries(map)){if(!uxPriceExtras[k])uxPriceExtras[k]=p.chart.addSeries(typ,k==='area'?{lineColor:'#54cfff',topColor:'#165b80a8',bottomColor:'#0c244000'}:k==='heikin'?{upColor:'#64e0ad',downColor:'#ed728d',wickUpColor:'#64e0ad',wickDownColor:'#ed728d'}:{color:'#52d5ff',lineWidth:2});let active=UX.chartType===k;uxPriceExtras[k].applyOptions({visible:active,priceLineVisible:UX.priceLine});if(active)uxPriceExtras[k].setData(k==='heikin'?uxHeikin(b):b.map(x=>({time:x.t,value:x.c})))}
 p.main.applyOptions({visible:UX.chartType==='candlestick',priceLineVisible:UX.priceLine});
}
function uxEnsurePanels(b){const root=$('uxPanelList'),L=window.LightweightCharts;if(!root||!L)return;const enabled=UX.panelOrder.filter(k=>UX_LIB[k]?.kind==='panel'&&uxInd(k).enabled);
 for(const k of Object.keys(uxCharts)){if(!enabled.includes(k)){try{uxCharts[k].chart.remove()}catch(e){}delete uxCharts[k]}}
 for(const k of enabled){let container=$(`ux-panel-${k}`);if(!container){container=document.createElement('article');container.className='ux-osc-card';container.id='ux-panel-'+k;container.innerHTML=`<div class="ux-osc-head"><div><strong>${UX_LIB[k].name}</strong> <small>${uxInd(k).height}px</small></div><div class="ux-osc-actions"><button class="ux-panel-action" aria-label="Yukarı taşı" data-ux="move-up" data-id="${k}">↑</button><button class="ux-panel-action" aria-label="Küçült" data-ux="resize" data-id="${k}" data-value="-40">−</button><button class="ux-panel-action" aria-label="Büyüt" data-ux="resize" data-id="${k}" data-value="60">＋</button><button class="ux-panel-action" aria-label="Ayarla" data-ux="edit" data-id="${k}">⚙</button><button class="ux-panel-action" aria-label="Kapat" data-ux="toggle" data-id="${k}">×</button></div></div><div class="ux-osc-canvas" id="ux-osc-${k}" style="height:${uxInd(k).height}px"></div><div class="ux-osc-note">Bağımsız yakınlaştırma ve yükseklik · Kapanmış mum</div>`;root.append(container)}else root.append(container);
 if(!uxCharts[k]){const chart=L.createChart($(`ux-osc-${k}`),{...chartOptions(),rightPriceScale:{borderColor:'#2a4058',scaleMargins:{top:.12,bottom:.1}},timeScale:{visible:false},handleScroll:true,handleScale:true,localization:{priceFormatter:p=>Number(p).toLocaleString('tr-TR',{maximumFractionDigits:3})}});uxCharts[k]={chart,series:{}}}
 uxPlotSeries(uxCharts[k].chart,uxCharts[k].series,b,[k]);
 }
}
let uxRenderedOnce=false;
function uxRenderDetail(){if(page!=='chart'||!window.LightweightCharts||!plots.detail||!candleData?.length)return;const b=uxBars(),p=plots.detail;if(!b.length)return;
 uxAttachDraw(p);
 const priceRoot=$('uxPriceWrap');if(priceRoot){const isFull=!!priceRoot.closest('.ux-chart-fullscreen');priceRoot.style.height=isFull?'':UX.chartHeight+'px'}
 for(const line of Object.values(p.lines))try{line.applyOptions({visible:false})}catch(e){}
 p.chart.applyOptions({grid:{vertLines:{visible:UX.grid,color:'#1d2c42'},horzLines:{visible:UX.grid,color:'#1d2c42'}},crosshair:{mode:UX.crosshair?0:2}});
 uxCreateTypeSeries(p,b);uxUpdatePriceGuides();
 uxPlotSeries(p.chart,(p.uxOverlays||(p.uxOverlays={})),b,UX_KEYS.filter(k=>UX_LIB[k].kind==='overlay'));
 uxEnsurePanels(b);
 $('uxChartSymbol').textContent=symbol;$('uxChartPrice').textContent=uxV(b[b.length-1].c,2);$('uxChartSource').textContent=symbol==='XAUUSDT'?'Bitget UTA v3 · Perpetual':'OANDA Spot · ayrı kaynak';$('uxChartTf').textContent=tf;
 document.querySelectorAll('[data-uxtf]').forEach(x=>x.classList.toggle('active',x.dataset.uxtf===tf));uxUpdateActiveTags();
 if(!uxRenderedOnce){uxRenderedOnce=true;setTimeout(()=>{uxSyncPanels();uxRedrawDrawings()},180)}else setTimeout(uxRedrawDrawings,50);
}
function uxAfterGo(k){uxUpdateDock(k);uxClose();if(k==='chart'){uxRenderedOnce=false;setTimeout(()=>{uxRenderQuick();ensureCharts();renderPlots();uxRenderDetail()},125)}}
let uxPriceGuides={};
function uxUpdatePriceGuides(){const p=plots.detail;if(!p||symbol!=='XAUUSDT'||!snap?.valid?.ticker)return;
 const levels={mark:UX.showMark?Number(snap.price?.mark):NaN,index:UX.showIndex?Number(snap.price?.index):NaN,
  spot:UX.showSpot&&Number(snap.spot_age_s)<60?Number(snap.spot?.last):NaN};
 const colors={mark:'#ffd078',index:'#9b8cf8',spot:'#60c6ff'};
 for(const [key,price] of Object.entries(levels)){
  const old=uxPriceGuides[key];if(!Number.isFinite(price)||price<=0){if(old){try{old.parent.removePriceLine(old.line)}catch(e){}delete uxPriceGuides[key]}continue}
  if(!old){try{uxPriceGuides[key]={parent:p.main,line:p.main.createPriceLine({price,color:colors[key],lineWidth:1,lineStyle:2,axisLabelVisible:true,title:key.toUpperCase()})}}catch(e){}}
  else try{old.line.applyOptions({price})}catch(e){}
 }
}
function uxCheckAlert(){const a=UX.alerts[symbol];if(!a?.active||a.triggered||!snap)return;
 const fresh=symbol==='XAUUSDT'?!!snap.valid?.ticker:!!snap.spot&&Number(snap.spot_age_s)<20;
 const value=symbol==='XAUUSDT'?Number(snap.price?.last):Number(snap.spot?.last);
 if(!fresh||!Number.isFinite(value))return;
 if(a.direction==='above'?value>=a.price:value<=a.price){a.triggered=true;a.active=false;uxSave();uxToast('FİYAT ALARMI: '+symbol+' '+uxV(value,2));}
}
function uxUpdateTop(){uxUpdatePriceGuides();uxCheckAlert();let el=$('uxTopPrice');if(!el)return;const p=symbol==='XAUUSDT'?snap?.price?.last:snap?.spot?.last;el.textContent=Number.isFinite(Number(p))?uxV(p,2):'—';const price=$('uxChartPrice');if(price)price.textContent=el.textContent;const name=$('uxTopSymbol');if(name)name.textContent=symbol;const status=$('uxFeedStatus');if(status)status.textContent=snap?.valid?.ticker?(snap?.ws_connected?'CANLI':'GECİKMELİ'):'VERİ EKSİK'}
function uxInit(){
 uxUpdateDock(page);uxRenderQuick();uxUpdateActiveTags();$('uxTfrow').innerHTML=tfs.map(x=>`<button class="ux-time ${x===tf?'active':''}" data-uxtf="${x}">${x}</button>`).join('');
 $('uxMobileNav').addEventListener('click',e=>{const b=e.target.closest('[data-uxnav]');if(!b)return;const k=b.dataset.uxnav;if(k==='analysis'||k==='more')uxOpen(k==='analysis'?'analysis-menu':'more-menu');else go(k==='strategies'?'strategies':k)});
 $('uxOverlay').addEventListener('click',uxClose);$('uxCloseSheet').addEventListener('click',uxClose);
 document.addEventListener('keydown',e=>{if(e.key==='Escape'&&uxSheetName)uxClose()});
 let held=false,quickTimer=null;const quick=$('uxQuick');quick.addEventListener('pointerdown',e=>{const el=e.target.closest('[data-uxquick]');if(!el)return;held=false;quickTimer=setTimeout(()=>{held=true;uxOpen('edit',el.dataset.uxquick)},520)});
 for(const ev of ['pointerup','pointercancel','pointerleave'])quick.addEventListener(ev,()=>clearTimeout(quickTimer));
 quick.addEventListener('click',e=>{const el=e.target.closest('[data-uxquick]');if(!el)return;if(held){held=false;return}uxToggle(el.dataset.uxquick)});
 $('uxTfrow').addEventListener('click',e=>{const b=e.target.closest('[data-uxtf]');if(b)uxSetTf(b.dataset.uxtf)});
 document.addEventListener('click',e=>{const el=e.target.closest('[data-ux]');if(!el)return;const action=el.dataset.ux,k=el.dataset.id||'';
  if(action.startsWith('open-')){uxOpen(action.slice(5));return}
  if(action==='sheet-close'){uxClose();return}
  if(action==='cat'){uxLibraryFilter=k;uxRenderSheet('library');return}
  if(action==='toggle'){uxToggle(k);return}
  if(action==='edit'){uxOpen('edit',k);return}
  if(action==='move-up'){uxPanelOrder(k);if(uxSheetName==='active')uxRenderSheet('active');return}
  if(action==='resize'){uxSetPanelSize(k,Number(el.dataset.value));return}
  if(action==='reset-ind'){const d=uxDefault().indicators[k];UX.indicators[k]=d;uxSave();uxUpdateIndicators();uxOpen('edit',k);return}
  if(action==='add-line'&&uxDraft){if(uxDraft.periods.length>=7)return uxToast('En fazla 7 çizgi');const last=uxDraft.periods.at(-1)||9;uxDraft.periods.push(Math.min(400,last+10));uxDraft.colors.push(UX_PALETTE[uxDraft.colors.length%UX_PALETTE.length]);uxDraft.lineEnabled.push(true);uxRenderSheet('edit',k);return}
  if(action==='remove-line'&&uxDraft){if(uxDraft.periods.length<=1)return uxToast('En az bir çizgi kalmalı');uxDraft.periods.pop();uxDraft.colors.pop();uxDraft.lineEnabled.pop();uxRenderSheet('edit',k);return}
  if(action==='width'&&uxDraft){uxDraft.width=uxDraft.width%4+1;document.querySelectorAll('.ux-width').forEach(b=>b.textContent=uxDraft.width+'px');return}
  if(action==='save-ind'&&uxDraft){UX.indicators[k]=uxDraft;UX.preset='custom';uxSave();uxUpdateIndicators();uxClose();uxToast(UX_LIB[k].short+' ayarları kaydedildi');return}
  if(action==='sheet-save'&&uxSheetName==='settings'){UX.chartType=$('uxType').value;for(let x of ['grid','crosshair','priceLine','legend','showMark','showIndex','showSpot'])UX[x]=$('ux-setting-'+x).checked;UX.chartHeight=Number($('uxHeight').value);uxSave();uxUpdateIndicators();uxClose();uxToast('Grafik ayarları kaydedildi');return}
  if(action==='sheet-save'&&uxSheetName==='alert'){const price=Number($('uxAlertPrice').value);if(!Number.isFinite(price)||price<=0)return uxToast('Geçerli pozitif fiyat gir');UX.alerts[symbol]={price,direction:$('uxAlertDirection').value,active:$('uxAlertEnabled').checked,triggered:false};uxSave();uxClose();uxToast('Alarm kaydedildi (yalnız uygulama açıkken)');return}
  if(action==='preset'){uxApplyPreset(k);return}
  if(action==='save-template'){UX.custom=UX_KEYS.filter(x=>UX.indicators[x].enabled);uxSave();uxToast('Kişisel şablon saklandı');return}
  if(action==='restore-template'){if(UX.custom){UX_KEYS.forEach(x=>UX.indicators[x].enabled=UX.custom.includes(x));UX.preset='custom';uxSave();uxUpdateIndicators();uxClose()}return}
  if(action==='tool'){uxDrawTool=k;uxPendingPoint=null;uxClose();uxDrawTip(true,k==='horizontal'?'Grafiğe dokun: yatay çizgi': 'Grafiğe dokun: birinci nokta');return}
  if(action==='draw-undo'){uxDrawingAction('undo');uxRenderSheet('draw');return}
  if(action==='draw-clear'){uxDrawingAction('clear');uxRenderSheet('draw');return}
  if(action==='fullscreen'){let wrap=$('uxWorkSurface');wrap.classList.toggle('ux-chart-fullscreen');el.setAttribute('aria-pressed',String(wrap.classList.contains('ux-chart-fullscreen')));setTimeout(()=>{renderPlots();uxRedrawDrawings()},120);return}
 });
 $('uxSheetBody').addEventListener('input',e=>{if(!uxDraft)return;const el=e.target;if(el.dataset.uxline!==undefined)uxDraft.lineEnabled[Number(el.dataset.uxline)]=el.checked;if(el.dataset.uxperiod!==undefined)uxDraft.periods[Number(el.dataset.uxperiod)]=Math.max(1,Math.min(400,parseInt(el.value)||1));if(el.dataset.uxcolor!==undefined)uxDraft.colors[Number(el.dataset.uxcolor)]=el.value;if(el.id==='uxEnabled')uxDraft.enabled=el.checked;if(el.id==='uxPanelHeight'){uxDraft.height=Number(el.value);$('uxPanelHeightValue').textContent=el.value+'px'}});
 $('uxSheetBody').addEventListener('input',e=>{if(e.target.id==='uxHeight')$('uxHeightLabel').textContent=e.target.value+'px'});
 $('uxOnlyPrice').addEventListener('click',()=>{UX_KEYS.forEach(k=>UX.indicators[k].enabled=false);UX.preset='bare';uxSave();uxUpdateIndicators();uxToast('Yalnız fiyat grafiği')});
 $('uxResetZoom').addEventListener('click',()=>{window.__uxZoomTouched=false;plots.detail?.chart?.timeScale()?.fitContent();uxSyncPanels()});
 const oldGo=go;go=function(k){oldGo(k);uxAfterGo(k)};
 const oldRender=renderPlots;renderPlots=function(){oldRender();if(page==='chart')uxRenderDetail()};
 const oldSnap=updateSnap;updateSnap=function(s){oldSnap(s);uxUpdateTop()};
 window.addEventListener('resize',()=>{if(page==='chart')setTimeout(uxRedrawDrawings,100)});
}

/* GOLD v3.2 — Display-only, explainable scoring and navigation.
   Never mutates ana, snap, backtest, risk veto, or underlying signals. */
const G32_WEIGHTS = Object.freeze([
  ['Fiyat/EMA20',1.3,'ema20'],['Fiyat/EMA50',1.1,'ema50'],
  ['EMA20/EMA50',1.1,'ema_pair'],['RSI14',1,'rsi14'],
  ['MACD histogram',1.1,'macd_hist'],['+DI/−DI',0.9,'di'],
  ['ROC12',0.7,'roc12'],['Stochastic K/D',0.6,'stoch'],
  ['Supertrend yönü',1,'supertrend_dir']
]);
const G32_TOP_IND = new Set(['close','ema9','ema20','ema50','ema200','rsi14','rsi7','macd_hist','adx14','plus_di','minus_di','atr14','bb_width_pct','zscore20','supertrend_dir']);
const G32_GROUPS={
 trend:new Set(['close','ema9','ema20','ema50','ema200','plus_di','minus_di','adx14','supertrend','supertrend_dir','vwap50','donchian_high','donchian_low','bb_mid']),
 momentum:new Set(['rsi14','rsi7','stoch_k','stoch_d','macd','macd_signal','macd_hist','roc12','williams14','cci20','mfi14','zscore20']),
 risk:new Set(['atr14','atr_pct','bb_up','bb_low','bb_width_pct','realized_vol_ann_pct']),
 volume:new Set(['obv','cmf20','volume_sma20','last_volume'])
};
let g32TechFilter='featured';
const g32Val=x=>x!==null&&x!==undefined&&x!==''&&Number.isFinite(Number(x))?Number(x):null;
const g32Clamp=(x,lo,hi)=>Math.max(lo,Math.min(hi,x));
const g32Pct=x=>Number.isFinite(x)?Math.round(g32Clamp(x,0,100)):null;
const g32Signed=x=>g32Clamp(x,-1,1);
function g32Entry(title,value,tone='neutral',sub=''){
 const n=g32Pct(value);const rgb=HEAT_TONES[tone]||HEAT_TONES.neutral;
 const alpha=n===null?0.04:(.06+.34*n/100).toFixed(3);
 return `<div class="g32-stat" style="--g32-rgb:${rgb};--g32-alpha:${alpha};--g32-w:${n??0}%" aria-label="${escaped(title)}: ${n===null?'Veri yok':n+' yüzde yoğunluk'}"><div class="g32-stat-top"><span>${escaped(title)}</span></div><strong>${n===null?'—':n+'%'}</strong><div class="g32-meter"><i></i></div><small>${escaped(sub)}</small></div>`;
}
function g32RenderSummary(id,title,tiles,details,valid=true){
 const el=$(id);if(!el)return;
 el.innerHTML=`<div class="g32-summary-head"><h3>${escaped(title)}</h3><span class="g32-summary-state ${valid?'is-ok':'is-warn'}">${valid?'HESAPLANDI':'VERİ / KAPSAM KONTROLÜ'}</span></div><div class="g32-cards">${tiles.join('')}</div><p class="g32-score-explain">${escaped(details)} <b>Skorlar işlem kazanma ihtimali değildir.</b></p>`;
}
function g32TechnicalScore(ind,quality){
 const c=g32Val(ind.close),atr=g32Val(ind.atr14),e20=g32Val(ind.ema20),e50=g32Val(ind.ema50);
 const centered=(x,denom)=>x!==null&&denom>0?g32Signed(x/denom):null;
 const dif=(a,b,denom)=>a!==null&&b!==null?centered(a-b,denom):null;
 const signal={
  ema20:dif(c,e20,atr>0?2*atr:0), ema50:dif(c,e50,atr>0?2*atr:0),
  ema_pair:dif(e20,e50,atr>0?2*atr:0),
  rsi14:g32Val(ind.rsi14)!==null?centered(g32Val(ind.rsi14)-50,25):null,
  macd_hist:centered(g32Val(ind.macd_hist),atr>0?atr:0),
  di:dif(g32Val(ind.plus_di),g32Val(ind.minus_di),25),
  roc12:centered(g32Val(ind.roc12),1),
  stoch:dif(g32Val(ind.stoch_k),g32Val(ind.stoch_d),25),
  supertrend_dir:[-1,1].includes(g32Val(ind.supertrend_dir))?g32Val(ind.supertrend_dir):null
 };
 let got=0,sum=0,total=0,count=0;
 for(const [,w,id] of G32_WEIGHTS){total+=w;const v=signal[id];if(v===null)continue;got+=w;sum+=w*v;count++}
 const coverage=total?100*got/total:0;
 const available=Boolean(quality?.candles_valid)&&got>0&&coverage>=55;
 const long=available?g32Pct(50+50*sum/got):null;
 const short=long===null?null:100-long;
 return {long,short,coverage:g32Pct(coverage),count,total:G32_WEIGHTS.length,valid:available};
}
function g32Cat(key){return Object.entries(G32_GROUPS).find(([,set])=>set.has(key))?.[0]||'other'}
function g32ApplyTechFilter(){
 const body=$('techTable');if(!body)return;
 const rows=[...body.querySelectorAll('tr')];let shown=0;
 rows.forEach(row=>{const key=row.dataset.g32Key||'';let visible=g32TechFilter==='all'||g32TechFilter==='featured'&&G32_TOP_IND.has(key)||g32TechFilter===g32Cat(key);
 row.hidden=!visible;if(visible)shown++});
 $('g32-tech-showing').textContent=`${shown} / ${rows.length} gösterge · ${g32TechFilter==='featured'?'Öne çıkanlar':{trend:'Trend',momentum:'Momentum',risk:'Volatilite',volume:'Hacim',all:'Tümü'}[g32TechFilter]}`;
 $('g32-tech-filters')?.querySelectorAll('[data-g32-filter]').forEach(b=>{const on=b.dataset.g32Filter===g32TechFilter;b.setAttribute('aria-pressed',String(on));b.classList.toggle('active',on)});
}
function g32AnalysisUpdate(a){
 const ind=a?.indicators?.latest||{};const q=a?.quant||{};
 const tech=g32TechnicalScore(ind,a?.data||{});
 const title=tech.valid&&tech.long!==null?(Math.abs(tech.long-tech.short)<12?'KARIŞIK':tech.long>tech.short?'YUKARI AĞIRLIKLI':'AŞAĞI AĞIRLIKLI'):'DOĞRULAMA BEKLENİYOR';
 g32RenderSummary('g32-tech-summary','TEKNİK · YÖN YOĞUNLUĞU',[
  g32Entry('Yükseliş göstergeleri',tech.long,'up','Ağırlıklı yönsel normalizasyon'),
  g32Entry('Düşüş göstergeleri',tech.short,'down','Karşı yöndeki yoğunluk'),
  g32Entry('Göstergelerin kapsamı',tech.coverage,'neutral',`${tech.count}/${tech.total} yönsel bileşen`),
  `<div class="g32-context"><span>Teknik görünüm</span><strong>${escaped(title)}</strong><small>Kapanmış mum • ${escaped(tf)} • mevcut karar motorunu değiştirmez</small></div>`
 ],'EMA/ATR uzaklığı, RSI, MACD, DI, ROC, Stochastic ve Supertrend ayrı ağırlıklarla ölçeklenir. ATR, hacim ve volatilite tek başına LONG/SHORT oyu sayılmaz.',tech.valid);
 const rows=$('techTable')?.querySelectorAll('tr')||[];
 Object.keys(ind).forEach((k,i)=>{if(rows[i])rows[i].dataset.g32Key=k});
 g32ApplyTechFilter();

 const riskParts=[
  ['1 mum VaR %95',g32Val(q.var95_1bar_pct),0.30],
  ['ATR / fiyat %',g32Val(ind.atr_pct),1.00],
  ['Yıllık volatilite %',g32Val(q.vol_annualized_pct),60],
  ['En büyük fiyat düşüşü %',g32Val(q.max_price_drawdown_pct),3]
 ];
 const riskAvailable=riskParts.filter(([,v])=>v!==null);
 const isCurrent=Boolean(a?.data?.candles_valid);
 const riskScore=isCurrent&&riskAvailable.length>=2?g32Pct(riskAvailable.reduce((s,[,v,ref])=>s+g32Clamp(Math.abs(v)/ref*100,0,100),0)/riskAvailable.length):null;
 const momentum=g32Val(q.momentum20_pct),z=g32Val(ind.zscore20);
 const momentumScore=isCurrent&&momentum!==null?g32Pct(Math.abs(momentum)/1*100):null;
 const zScore=isCurrent&&z!==null?g32Pct(Math.abs(z)/3*100):null;
 const momentumTone=momentum===null?'neutral':momentum>=0?'up':'down',zTone=z===null?'neutral':z>=0?'up':'down';
 g32RenderSummary('g32-quant-summary','QUANT · RİSK VE SAPMA SKORLARI',[
  g32Entry('Risk yoğunluğu',riskScore,'caution','Yüksek yüzde = daha yüksek gözlenen risk'),
  g32Entry('20 mum momentum',momentumScore,momentumTone,momentum===null?'Veri yok':`${momentum>=0?'Pozitif':'Negatif'} · |getiri| / %1`),
  g32Entry('Z-skor sapması',zScore,zTone,z===null?'Veri yok':`${z>=0?'Ort. üstünde':'Ort. altında'} · |Z| / 3`),
  g32Entry('Risk veri kapsamı',g32Pct(riskAvailable.length/riskParts.length*100),'neutral',`${riskAvailable.length}/${riskParts.length} risk bileşeni`)
 ],'VaR için %0,30; ATR için %1; yıllık volatilite için %60; düşüş için %3 görsel referans kullanılır. Risk, yön skoru veya işlem olasılığı değildir.',riskScore!==null);
}
let g32FlowLast=0;
function g32FlowUpdate(s){
 const now=Date.now();if(now-g32FlowLast<800)return;g32FlowLast=now;
 const f=s?.flow||{};const v=s?.valid||{};
 const buy=g32Val(f.buy_notional60),sell=g32Val(f.sell_notional60),bid=g32Val(f.bid_notional20),ask=g32Val(f.ask_notional20);
 const haveTrades=Boolean(v.trades)&&buy!==null&&sell!==null&&buy+sell>0;
 const haveBook=Boolean(v.book)&&bid!==null&&ask!==null&&bid+ask>0;
 const tradeBuy=haveTrades?buy/(buy+sell)*100:null;
 const bookBuy=haveBook?bid/(bid+ask)*100:null;
 const w=(haveTrades?.7:0)+(haveBook?.3:0);
 const long=w>0?( (tradeBuy??0)*(haveTrades?.7:0)+(bookBuy??0)*(haveBook?.3:0) )/w:null;
 const directionOk=haveTrades&&haveBook; // if one independent source fails, withhold the combined score
 const up=directionOk?g32Pct(long):null;
 const down=up===null?null:100-up;
 const sample=g32Val(f.trades60);const spread=g32Val(f.spread_pct);
 const sampleQ=haveTrades&&sample!==null?g32Pct(sample/120*100):null;
 const spreadQ=spread!==null?g32Pct(100-g32Clamp(spread/0.12*100,0,100)):null;
 const qualityInputs=[haveTrades?100:0,haveBook?100:0,sampleQ,spreadQ].filter(x=>x!==null);
 const quality=directionOk&&qualityInputs.length===4?g32Pct(qualityInputs[0]*.35+qualityInputs[1]*.3+qualityInputs[2]*.2+qualityInputs[3]*.15):null;
 const title=directionOk?(up>56?'ALIŞ AĞIRLIKLI':down>56?'SATIŞ AĞIRLIKLI':'KARŞILIKLI / NÖTR'):'VERİ EKSİK / GECİKMELİ';
 g32RenderSummary('g32-flow-summary','ORDER FLOW · İŞLEM & EMİR DENGESİ',[
  g32Entry('Alış baskısı',up,'up','%70 taker + %30 DOM20'),
  g32Entry('Satış baskısı',down,'down','Aynı kaynakların karşı yönü'),
  g32Entry('Veri kalite endeksi',quality,'neutral','Tazelik, işlem sayısı, spread'),
  `<div class="g32-context"><span>Akış görünümü</span><strong>${title}</strong><small>60 sn işlemler: ${haveTrades?'güncel':'eksik'} · DOM20: ${haveBook?'güncel':'eksik'}</small></div>`
 ],'İşlem alış/satış payı %70, emir defteri alış/satış payı %30. Kaynakların biri bayatsa ortak skor gösterilmez. Emir defteri bekleyen emirlerdir; gerçekleşmiş hacim değildir.',directionOk);
}
function g32Highlight(k){
 document.querySelectorAll('.g32-subnav button').forEach(b=>{const selected=b.dataset.go===k;b.classList.toggle('active',selected);b.setAttribute('aria-current',selected?'page':'false')});
}
function g32InitFilters(){
 const filterBar=$('g32-tech-filters');if(filterBar){filterBar.addEventListener('click',e=>{const b=e.target.closest('[data-g32-filter]');if(!b)return;g32TechFilter=b.dataset.g32Filter;g32ApplyTechFilter()})}
 g32Highlight(page);
}


// GOLD v2.2.2: isolated startup; never let optional chart or UX stop live feed.
const __bootStatus={};
function __goldStartPart(name,fn){
 try{fn();__bootStatus[name]=true;return true}
 catch(error){__bootStatus[name]=false;console.error('GOLD '+name+' başlatılamadı:',error);
  const el=document.getElementById('err');if(el){el.style.display='block';el.textContent=name+' modülü açılamadı: '+(error?.message||String(error))}
  return false;}
}
__goldStartPart('Gezinti',initNav);
__goldStartPart('Mobil arayüz',uxInit);
__goldStartPart('Yüzdelik renk gösterimi',heatSetupToggle);
__goldStartPart('Skor filtreleri',g32InitFilters);
// The boot watchdog confirms that the complete application script executed.
window.__GOLD_APP_READY__=true;window.__GOLD_BUILD__='3.2.0';
__goldStartPart('Grafik',ensureCharts);
__goldStartPart('Canlı bağlantı',startSocket);
__goldStartPart('İlk veri yükleme',reloadAll);
setInterval(()=>{const clock=document.getElementById('clock');if(clock)clock.textContent=new Date().toLocaleTimeString('tr-TR',{hour12:false})},1000);
setInterval(()=>{if(document.visibilityState==='visible')__goldStartPart('Yenileme',reloadAll)},45000);
window.addEventListener('resize',()=>{if(lastBT&&page==='strategies')paintEquity(lastBT.equity_curve||[])});
window.addEventListener('gold-chart-library-ready',()=>{__goldStartPart('Grafik kütüphanesi',()=>{ensureCharts();renderPlots()})});
console.info('GOLD SCALP PRO',window.__GOLD_BUILD__,'uygulama yüklendi',__bootStatus);
