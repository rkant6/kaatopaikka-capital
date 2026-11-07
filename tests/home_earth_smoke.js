/* Browser-independent smoke test for the visible homepage Earth. Run with node. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
let scheduled=null,rects=0,draws=0,stars=0;
const gradient={addColorStop(){}};
const ctx={
  createRadialGradient(){return gradient},createImageData(w,h){return{data:new Uint8ClampedArray(w*h*4)}},
  putImageData(){},drawImage(){draws++},fillRect(){rects++},beginPath(){},arc(){},fill(){},stroke(){},
  moveTo(){},lineTo(){},fillText(){}
};
const listeners={};
const canvas={width:0,height:0,isConnected:true,
  getContext(){return ctx},getBoundingClientRect(){return{width:800,height:540}},
  addEventListener(type,cb){listeners[type]=cb},
  setPointerCapture(){},parentElement:{classList:{add(x){if(x==='has-renderer')stars++}}}};
global.document={readyState:'complete',
  getElementById(id){return id==='home-earth-canvas'?canvas:null},
  createElement(){return {width:0,height:0,getContext(){return ctx}}}};
global.window=global;global.devicePixelRatio=1;global.matchMedia=()=>({matches:false});
global.ResizeObserver=class{observe(){}};
global.requestAnimationFrame=(cb)=>{scheduled=cb};
global.fetch=async()=>({ok:false});
global.atob=s=>Buffer.from(s,'base64').toString('binary');
vm.runInThisContext(fs.readFileSync('assets/home-earth.js','utf8'),{filename:'assets/home-earth.js'});
assert.ok(scheduled,'Earth renderer must start an animation loop');
scheduled(1000);
assert.ok(draws>0,'Earth must draw a spherical disk');
assert.ok(rects>1000,'Earth must render genuine continent/land pixels, not just background stars');
assert.ok(stars>0,'The page must expose the healthy Earth state');
const sun=global.KCHomeEarth.solar(new Date('2024-06-21T12:00:00Z'));
assert.ok(Math.abs(Math.hypot(...sun)-1)<1e-7,'Sun direction is a unit vector');
global.KCHomeEarth.setSnapshot({date:'2024-01-01',mode:'unverified',companies:null});
scheduled(1100);
assert.ok(draws>1,'Historical slider date must render');
assert.ok(listeners.pointermove&&listeners.wheel,'Earth must support drag and zoom');
console.log('  Standalone home Earth renders, loads landmask, scrubs 2024, and responds to pointer controls');
