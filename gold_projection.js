/* GOLD SCALP PRO — price/time projection. Read-only, uncalibrated retrospective research. */
'use strict';
(function(root){
  const HORIZONS=[5,15,30,60,120];
  const num=v=>typeof v==='number'&&Number.isFinite(v)?v:null;
  const escape=s=>String(s??'—').replace(/[&<>"']/g,x=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x]));
  const fmt=(v,dec=2)=>num(v)===null?'—':v.toLocaleString('tr-TR',{minimumFractionDigits:dec,maximumFractionDigits:dec});
  const pct=v=>num(v)===null?'—':(v>0?'+':'')+fmt(v,2)+'%';
  const delta=v=>num(v)===null?'—':(v>0?'+':'')+fmt(v,2)+' $';
  const safePrice=v=>num(v)!==null&&v>0?v:null;
  function derive(report,asof=Date.now()){
    if(!report||typeof report!=='object')throw Error('Kantitatif veri raporu bulunamadı.');
    const price=safePrice(report.price),created=Date.parse(report.computed_at_utc||'');
    const recent=Number.isFinite(created)&&asof-created>=-30000&&asof-created<=120000;
    const fresh=Boolean(price&&report.price_fresh&&recent);
    const window=report.window||{};
    const horizonRows=Array.isArray(report.horizons)?report.horizons:[];
    const points=HORIZONS.map(minutes=>{
      const row=horizonRows.find(x=>x&&x.horizon_minutes===minutes)||{};
      const q10=safePrice(row.price_q10),q50=safePrice(row.price_q50),q90=safePrice(row.price_q90);
      const count=Number.isInteger(row.valid_count)?row.valid_count:0;
      const usable=Boolean(fresh&&row.status==='RESEARCH'&&row.data_current&&count>=40&&q10&&q50&&q90&&q10<=q50&&q50<=q90
        &&Math.abs(q50-price)/price<0.15&&Math.abs(q90-price)/price<0.20&&Math.abs(q10-price)/price<0.20);
      const upper=safePrice(row.upper_barrier),lower=safePrice(row.lower_barrier);
      const upFreq=num(row.p_up_first),downFreq=num(row.p_down_first),timeoutFreq=num(row.p_timeout);
      return {minutes,status:usable?'GÖSTERİLEBİLİR':!fresh?'GÜNCEL DEĞİL':row.status||'YETERSİZ',usable,
        sample_count:count,history_days:num(row.observed_days),condition:row.condition||'none',full_30d:!!row.data_30d_complete,
        q10:usable?q10:null,q50:usable?q50:null,q90:usable?q90:null,
        delta:usable?q50-price:null,change_pct:usable?(q50/price-1)*100:null,
        upper:usable?upper:null,lower:usable?lower:null,
        up_first:usable&&upFreq!==null&&upFreq>=0&&upFreq<=100?upFreq:null,
        down_first:usable&&downFreq!==null&&downFreq>=0&&downFreq<=100?downFreq:null,
        timeout:usable&&timeoutFreq!==null&&timeoutFreq>=0&&timeoutFreq<=100?timeoutFreq:null,
        median_touch:usable?num(row.median_first_touch_minutes):null};
    });
    return {symbol:['XAUUSDT','XAUUSD'].includes(report.symbol)?report.symbol:'—',price:fresh?price:null,
      source:report.source||'—',fresh,points,window_complete:!!window.full_30d,
      errors:report.data_quality?.errors||{},created:report.computed_at_utc||null,
      notice:!recent?'Raporun hesaplama zamanı güncel değil.':!fresh?'Canlı fiyat doğrulanmadı.':null};
  }
  function statusFor(point,price){
    if(!point||!point.usable||!price)return {label:'BEKLE · veri yok',tone:'neutral',explain:'Kapanmış, güncel ve yeterli örnek gerekiyor.'};
    const d=point.change_pct;
    if(Math.abs(d)<0.05)return {label:'YATAY / BELİRSİZ',tone:'neutral',explain:'Geçmiş medyan farkı %0,05 altında: yön avantajı göstermez.'};
    return {label:d>0?'YUKARI MEDYAN':'AŞAĞI MEDYAN',tone:d>0?'up':'down',explain:'Bu, geçmiş koşullardaki medyan kapanışın yönüdür; LONG/SHORT sinyali değildir.'};
  }
  function historicalCandles(payload,now=Date.now()){
    if(!payload||payload.fresh!==true||!Array.isArray(payload.bars))return [];
    return payload.bars.filter(b=>{
      if(!b||!Number.isFinite(b.t)||!Number.isFinite(b.c)||b.c<=0)return false;
      return (b.t+300)*1000<=now&&b.t*1000<=now;
    }).sort((a,b)=>a.t-b.t);
  }
  const API={derive,statusFor,historicalCandles,escape,fmt,pct,delta};
  if(typeof module!=='undefined'&&module.exports)module.exports=API;
  if(typeof document==='undefined')return;

  const get=id=>document.getElementById(id);
  let selected=30,historyHours=2,inflight=false,needsRefresh=false,last=null,history=[],poll=null;
  function metric(name,value,tone='',note=''){
    return `<div class="metric"><div class="muted">${escape(name)}</div><strong class="${tone}">${escape(value)}</strong><small class="muted">${escape(note)}</small></div>`;
  }
  function panelStatus(message,error=false){get('status').textContent=message;get('status').className='notice'+(error?' bad':'');}
  function tableRows(view){
    return view.points.map(p=>{
      if(!p.usable)return `<tr><td>${p.minutes} dk</td><td colspan="6" class="muted">${escape(p.status)} · ${p.sample_count} örnek · veri yoksa hedef verilmez</td></tr>`;
      const tone=p.delta>=0?'up':'down';
      return `<tr class="selectrow ${selected===p.minutes?'selected':''}" data-horizon="${p.minutes}"><td>${p.minutes} dk</td><td class="${tone}">${fmt(p.q50)} $</td><td class="${tone}">${delta(p.delta)}</td><td class="${tone}">${pct(p.change_pct)}</td><td>${fmt(p.q10)}–${fmt(p.q90)}</td><td>${fmt(p.up_first,1)} / ${fmt(p.down_first,1)}</td><td>${p.sample_count}</td></tr>`;
    }).join('');
  }
  function spark(view,barSeries){
    const vals=barSeries.map(b=>b.c);
    const usable=view.points.filter(p=>p.usable);
    const price=view.price;
    if(!price)return `<div class="empty">Canlı fiyat doğrulanmadığından fiyat projeksiyonu çizilmiyor.</div>`;
    if(!usable.length)return `<div class="empty">Güncel ve yeterli tarihsel örnek olmadan geleceğe çizgi çizilmiyor.</div>`;
    const W=1100,H=405,l=65,r=105,top=28,bottom=55,axis=490,hi=H-bottom;
    const take=Math.min(barSeries.length,Math.max(12,historyHours*12));
    const sampled=barSeries.slice(-take);
    const pp=[price,...sampled.map(x=>x.c),...usable.flatMap(p=>[p.q10,p.q50,p.q90])];
    const active=usable.find(p=>p.minutes===selected)||usable[0];
    if(active.upper)pp.push(active.upper);
    if(active.lower)pp.push(active.lower);
    const lo=Math.min(...pp),high=Math.max(...pp),padding=Math.max((high-lo)*0.15,price*0.0004);
    const vmin=lo-padding,vmax=high+padding;
    const y=p=>top+(vmax-p)/(vmax-vmin)*(hi-top);
    const xFor=m=>axis+(m/120)*(W-r-axis);
    const hist=sampled.map((b,i)=>[l+i/Math.max(1,sampled.length-1)*(axis-l),y(b.c)]);
    hist.push([axis,y(price)]);
    const future=usable.map(p=>[xFor(p.minutes),y(p.q50)]);
    const line=arr=>arr.map(([x,y],i)=>(i?'L':'M')+x.toFixed(1)+' '+y.toFixed(1)).join(' ');
    const middle=[[axis,y(price)],...future];
    const lower=[[axis,y(price)],...usable.map(p=>[xFor(p.minutes),y(p.q10)])];
    const upper=[[axis,y(price)],...usable.map(p=>[xFor(p.minutes),y(p.q90)])];
    const fullBand=[...upper,...lower.slice().reverse()];
    const area=fullBand.map(([x,y],i)=>(i?'L':'M')+x.toFixed(1)+' '+y.toFixed(1)).join(' ')+' Z';
    let svg=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Son kapanmış 5 dakika fiyatları ve geleceğe yönelik koşullu medyan fiyat projeksiyonu, yüzde 10–90 tarihsel aralıklar">
      <defs><linearGradient id="projection-band" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#42b6f5" stop-opacity=".28"/><stop offset="1" stop-color="#42b6f5" stop-opacity=".07"/></linearGradient></defs>`;
    for(let i=0;i<=4;i++){
      const p=vmax-(vmax-vmin)*i/4,gy=y(p);
      svg+=`<line x1="${l}" y1="${gy}" x2="${W-r+20}" y2="${gy}" stroke="#304154" stroke-width="1" stroke-dasharray="3 6"/><text x="${l-9}" y="${gy+4}" fill="#95a9c4" text-anchor="end" font-size="13">${fmt(p,1)}</text>`;
    }
    svg+=`<rect x="${axis}" y="${top}" width="${W-r-axis+20}" height="${hi-top}" fill="#0f2338" opacity=".42"/><line x1="${axis}" y1="${top-6}" x2="${axis}" y2="${hi+5}" stroke="#b3c7dd" stroke-dasharray="4 4"/><text x="${axis}" y="${H-9}" fill="#dbe8f7" text-anchor="middle" font-size="14">ŞİMDİ</text>`;
    if(sampled.length>2){
      svg+=`<path d="${line(hist)}" fill="none" stroke="#e8effa" stroke-width="2.5" stroke-linecap="round"/>`;
      svg+=`<text x="${l+12}" y="${H-9}" fill="#9bb5d3" font-size="13">Son ${historyHours} saat · 5dk kapanış</text>`;
    }
    svg+=`<path d="${area}" fill="url(#projection-band)"/><path d="${line(lower)}" stroke="#d47e8c" fill="none" stroke-width="1.4" stroke-dasharray="4 6"/><path d="${line(upper)}" stroke="#59d9bc" fill="none" stroke-width="1.4" stroke-dasharray="4 6"/><path d="${line(middle)}" stroke="#ffc76e" fill="none" stroke-width="3" stroke-dasharray="7 5"/>`;
    for(const p of usable){const x=xFor(p.minutes),mY=y(p.q50);svg+=`<circle cx="${x}" cy="${mY}" r="${p.minutes===selected?7:4}" fill="#ffc76e" stroke="#091422" stroke-width="2"/><text x="${x}" y="${H-9}" text-anchor="middle" fill="#b7cde5" font-size="14">+${p.minutes} dk</text>`;}
    if(active&&active.usable){
      const x=xFor(active.minutes),cy=y(active.q50);
      svg+=`<line x1="${x}" y1="${top}" x2="${x}" y2="${hi}" stroke="#ffc76e" stroke-opacity=".5" stroke-dasharray="3 7"/>`;
      svg+=`<text x="${Math.min(W-r-25,x+6)}" y="${Math.max(26,cy-13)}" fill="#ffda9c" font-size="17" font-weight="700" text-anchor="end">${fmt(active.q50)} $</text>`;
    }
    svg+=`<circle cx="${axis}" cy="${y(price)}" r="6" fill="#fff"/><text x="${axis+7}" y="${y(price)-12}" font-size="15" fill="#fff">${fmt(price)} $</text></svg>`;
    return svg;
  }
  function render(){if(!last)return;const p=last.points.find(x=>x.minutes===selected)||last.points[2];
    const dir=statusFor(p,last.price);
    get('horizonTabs').innerHTML=HORIZONS.map(m=>`<button type="button" data-horizon="${m}" class="tab ${m===selected?'active':''}">${m} dk</button>`).join('');
    get('historyTabs').innerHTML=[1,2,4].map(h=>`<button type="button" data-history="${h}" class="tab ${h===historyHours?'active':''}">${h} saat</button>`).join('');
    get('symbolLabel').textContent=last.symbol+' · '+last.source;
    get('cards').innerHTML=metric('Canlı fiyat',last.price?fmt(last.price)+' $':'—','sky',last.fresh?'Kaynak güncel':'Veri yok')+
      metric('Seçilen ufuk · Medyan hedef',p.usable?fmt(p.q50)+' $':'—',p.usable?(p.delta>=0?'up':'down'):'','Gelecekte garanti değil')+
      metric('Medyan hareket',p.usable?delta(p.delta):'—',p.usable?(p.delta>=0?'up':'down'):'',p.usable?pct(p.change_pct):'Veri yetersiz')+
      metric('Tarihsel kapanış %10–90',p.usable?fmt(p.q10)+' – '+fmt(p.q90)+' $':'—','sky','Model aralığı, güven aralığı değil');
    get('chart').innerHTML=spark(last,history);
    get('summaryTitle').textContent=dir.label;get('summaryTitle').className=dir.tone;
    get('summaryExplain').textContent=dir.explain;
    get('barriers').innerHTML=p.usable?
      metric('↑ üst bariyer',fmt(p.upper)+' $','up',delta(p.upper-last.price)+' · '+pct((p.upper/last.price-1)*100))+
      metric('↓ alt bariyer',fmt(p.lower)+' $','down',delta(p.lower-last.price)+' · '+pct((p.lower/last.price-1)*100))+
      metric('↑ önce temas geçmiş sıklığı',fmt(p.up_first,1)+'%','up','İşlem kazanma olasılığı değil')+
      metric('↓ önce temas geçmiş sıklığı',fmt(p.down_first,1)+'%','down','İşlem kazanma olasılığı değil'):
      '<div class="empty">Bu zaman ufku için doğrulanmış hedef bulunmuyor.</div>';
    get('quantTable').innerHTML=tableRows(last);
    get('quality').textContent='Kaynak: '+last.source+' • 30 günlük günlük seri: '+(last.window_complete?'tam':'eksik')+' • '+
      (p?.usable?'Ufuk örneği: '+p.sample_count+' • Gözlenen '+fmt(p.history_days,1)+' gün • Koşul: '+p.condition+' • '+(p.full_30d?'30 gün kapsanmış':'kısa tarihçe'):'Ufuk yetersiz/güncel değil')+
      ' • Tarihsel ilk-temas frekansları kalibre edilmiş gelecek olasılığı değildir. Gerçek emir yok.';
    panelStatus((last.fresh?'Kaynak güncel':'Fiyat güncel değil')+' · '+new Date(last.created||Date.now()).toLocaleTimeString('tr-TR')+' · '+(history.length?'Gerçek 5dk kapanışları doğrulandı':'Tarihsel çizgi yok')+
      ' · Bu ekran koşullu araştırma projeksiyonudur.',!last.fresh);
  }
  async function update(){if(inflight)return;inflight=true;get('refresh').disabled=true;
    panelStatus('Güncel Bitget/OANDA verileri ve geçmiş örnekler alınıyor…');
    const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),55000);
    try{
      const symbol=get('symbol').value;
      const calls=await Promise.allSettled([
        fetch('/api/gold30?symbol='+encodeURIComponent(symbol),{cache:'no-store',signal:controller.signal}),
        fetch('/api/candles?symbol='+encodeURIComponent(symbol)+'&tf=5m&limit=350',{cache:'no-store',signal:controller.signal})
      ]);
      if(calls[0].status!=='fulfilled'||!calls[0].value.ok)throw Error('30G Quant API erişimi başarısız.');
      const data=await calls[0].value.json();
      if(symbol!==get('symbol').value)return;
      if(data.symbol!==symbol)throw Error('Sembol uyuşmazlığı: kaynak verisi reddedildi.');
      last=derive(data);
      // Historical chart only when both source and updated, closed 5m candle data are verified.
      if(calls[1].status==='fulfilled'&&calls[1].value.ok){
        const candles=await calls[1].value.json();
        history=candles.symbol===symbol&&candles.tf==='5m'?historicalCandles(candles):[];
      }else history=[];
      render();
    }catch(e){last=null;history=[];get('cards').innerHTML='';get('chart').innerHTML='<div class="empty">Güncel veri yok; projeksiyon gösterilmedi.</div>';
      get('quantTable').innerHTML='';get('barriers').innerHTML='';get('summaryTitle').textContent='BEKLE';
      panelStatus('Analiz alınamadı: '+e.message+' • Render/Bitget bağlantısını kontrol edin.',true);
    }finally{clearTimeout(timer);inflight=false;get('refresh').disabled=false;
      if(needsRefresh){needsRefresh=false;update();}}
  }
  function init(){
    get('horizonTabs').addEventListener('click',e=>{const b=e.target.closest('[data-horizon]');if(!b)return;selected=Number(b.dataset.horizon);render()});
    get('quantTable').addEventListener('click',e=>{const b=e.target.closest('[data-horizon]');if(!b)return;selected=Number(b.dataset.horizon);render();window.scrollTo({top:0,behavior:'smooth'})});
    get('historyTabs').addEventListener('click',e=>{const b=e.target.closest('[data-history]');if(!b)return;historyHours=Number(b.dataset.history);render()});
    get('symbol').addEventListener('change',()=>{last=null;history=[];if(inflight){needsRefresh=true;panelStatus('Yeni piyasa için veri isteniyor…');}else update()});
    get('refresh').addEventListener('click',update);
    document.addEventListener('visibilitychange',()=>{if(!document.hidden)update()});
    poll=setInterval(()=>{if(!document.hidden)update()},45000);
    update();
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})(typeof window!=='undefined'?window:undefined);
