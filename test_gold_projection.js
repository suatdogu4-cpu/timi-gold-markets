'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {derive,statusFor,historicalCandles,escape}=require('./gold_projection.js');
const base=Date.now();
function fixture(){return {symbol:'XAUUSDT',source:'XAUUSDT Bitget UTA v3',price:3620.72,price_fresh:true,
  computed_at_utc:new Date(base).toISOString(),window:{full_30d:true},
  horizons:[{horizon_minutes:30,status:'RESEARCH',data_current:true,data_30d_complete:true,valid_count:150,
   price_q10:3613.49,price_q50:3620.4,price_q90:3627.25,upper_barrier:3627.61,lower_barrier:3613.83,
   p_up_first:30.9,p_down_first:35.6,p_timeout:33.5,condition:'trend',observed_days:29.5}]};}
test('known quantitative example: price, dollar and percent are coherent',()=>{
 const x=derive(fixture(),base),p=x.points.find(x=>x.minutes===30);
 assert.equal(x.fresh,true);assert.equal(x.symbol,'XAUUSDT');assert.equal(p.usable,true);
 assert.equal(p.q50,3620.4);assert.equal(p.upper,3627.61);assert.equal(p.down_first,35.6);
 assert.ok(Math.abs(p.delta-(-0.32))<1e-7);
 assert.ok(Math.abs(p.change_pct-(-0.008838))<0.00001);
 assert.equal(statusFor(p,x.price).label,'YATAY / BELİRSİZ');
});
test('no future value in a missing horizon, even when other horizons exist',()=>{
 const x=derive(fixture(),base);for(const p of x.points.filter(x=>x.minutes!==30)){
  assert.equal(p.usable,false);assert.equal(p.q50,null);
 }
});
test('stale report or invalid quote must hide all projections',()=>{
 let d=fixture();assert.equal(derive(d,base+180000).fresh,false);
 assert.equal(derive(d,base+180000).points[2].q50,null);
 d.price_fresh=false;assert.equal(derive(d,base).points[2].q50,null);
});
test('insufficient sample and inconsistent bands fail closed',()=>{
 let d=fixture();d.horizons[0].valid_count=15;assert.equal(derive(d,base).points[2].q50,null);
 d=fixture();d.horizons[0].price_q10=3640;assert.equal(derive(d,base).points[2].q50,null);
 d=fixture();d.horizons[0].data_current=false;assert.equal(derive(d,base).points[2].q50,null);
});
test('only source-validated closed five-minute candles are charted',()=>{
 const t=Math.floor(base/300000)*300;
 let b={fresh:true,bars:[{t:t-600,c:3612},{t:t-300,c:3618},{t:t,c:3620}]};
 assert.equal(historicalCandles(b,base).length,2);
 b.fresh=false;assert.equal(historicalCandles(b,base).length,0);
});
test('escape markup in any externally-derived text',()=>assert.equal(escape('<img src=x onerror=1>'),'&lt;img src=x onerror=1&gt;'));
