/* Standalone photorealistic Earth smoke test.
   Runs with plain Node: intentionally forces Canvas2D fallback (no WebGL). */
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
let scheduled=null,rendered=0,pixelShades=0,ready=0;
for(const asset of ['earth-blue-marble-day.jpg','earth-city-lights.jpg','earth-cloud-cover.png']){
 const file=fs.readFileSync('assets/'+asset);
 assert.ok(file.length>100000,'Earth texture missing or too small: '+asset);
}
const grad={addColorStop(){}};
function fakeContext(){
 return {
  createRadialGradient(){return grad},
  createImageData(w,h){pixelShades+=w*h;return{data:new Uint8ClampedArray(w*h*4)}},
  getImageData(x,y,w,h){return{data:new Uint8ClampedArray(w*h*4)}},
  putImageData(){rendered++},
  drawImage(){rendered++},
  measureText(x){return{width:x.length*7}},
  clearRect(){},fillRect(){},strokeRect(){},fill(){},stroke(){},
  beginPath(){},arc(){},moveTo(){},lineTo(){},fillText(){}
 };
}
const listeners={};
const overlay={width:0,height:0,getContext(){return fakeContext()}};
const canvas={width:0,height:0,isConnected:true,
 getContext(type){return type==='2d'?fakeContext():null},
 getBoundingClientRect(){return{width:800,height:540}},
 addEventListener(type,fn){listeners[type]=fn},setPointerCapture(){},
 parentElement:{classList:{add(x){if(x==='has-renderer')ready++}}}
};
global.document={readyState:'complete',hidden:false,
 getElementById(id){return id==='home-earth-canvas'?canvas:id==='home-earth-overlay'?overlay:null},
 createElement(tag){return{width:0,height:0,getContext(){return fakeContext()}}}};
global.window=global;global.devicePixelRatio=1;global.matchMedia=()=>({matches:false});
global.ResizeObserver=class{observe(){}};
global.requestAnimationFrame=fn=>{scheduled=fn};
global.fetch=async()=>({ok:false});
global.Image=class{set src(src){this.url=src;queueMicrotask(()=>this.onload?.())}};
vm.runInThisContext(fs.readFileSync('assets/home-earth.js','utf8'),{filename:'assets/home-earth.js'});
assert.ok(scheduled,'Renderer loop must start');
scheduled(1000);
assert.ok(rendered>1,'Earth fallback must draw an actual image surface');
assert.ok(pixelShades>20000,'Earth fallback must shade a real pixel array');
assert.ok(ready>0,'Renderer must signal it successfully displayed the Earth');
const sun=global.KCHomeEarth.solar(new Date('2024-06-21T12:00:00Z'));
assert.ok(Math.abs(Math.hypot(...sun)-1)<1e-7,'Solar direction is normalized');
const decl=Math.asin(sun[1])*180/Math.PI;
assert.ok(Math.abs(decl-23.44)<1,'Sun is correctly positioned at summer solstice');
global.KCHomeEarth.setSnapshot({date:'2024-01-01',mode:'unverified',companies:null});
const before=rendered;scheduled(1100);
assert.ok(rendered>before,'Time-slider scrubbing must redraw the Earth');
assert.ok(listeners.pointerdown&&listeners.pointermove&&listeners.wheel,'Rotation and wheel zoom must work');
assert.ok(!fs.readFileSync('assets/home-earth.js','utf8').includes('LAND_BITS'),
  'Obsolete coarse point mask must not be used to draw geography');
console.log('  Blue Marble Earth: Canvas fallback, 3 local textures, 2024 replay, drag/zoom and solar geometry OK');
