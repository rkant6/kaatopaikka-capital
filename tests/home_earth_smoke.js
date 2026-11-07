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
const buttons={};
for(const id of ['earth-zoom-in','earth-zoom-out','earth-zoom-reset','earth-zoom-level']){
  buttons[id]={disabled:false,textContent:'',events:{},addEventListener(type,fn){this.events[type]=fn}};
}
const overlay={width:0,height:0,getContext(){return fakeContext()}};
const canvas={width:0,height:0,isConnected:true,
 getContext(type){return type==='2d'?fakeContext():null},
 getBoundingClientRect(){return{width:800,height:540}},
 addEventListener(type,fn){listeners[type]=fn},setPointerCapture(){},
 parentElement:{classList:{add(x){if(x==='has-renderer')ready++}}}
};
global.document={readyState:'complete',hidden:false,
 getElementById(id){return id==='home-earth-canvas'?canvas:id==='home-earth-overlay'?overlay:(buttons[id]||null)},
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
const zoom=()=>global.KCHomeEarth.getViewState().zoom;
const originalRadius=global.KCHomeEarth.getViewState().radius;
let prevented=false;
listeners.wheel({deltaY:-120,deltaMode:0,preventDefault(){prevented=true}});
assert.ok(prevented,'Wheel zoom must prevent page scroll while hovering over Earth');
assert.ok(zoom()>1.2,'Wheel zoom-in must visibly enlarge Earth');
assert.ok(global.KCHomeEarth.getViewState().radius>originalRadius*1.2,'Zoom must change projected Earth radius');
buttons['earth-zoom-in'].events.click();
assert.ok(zoom()>1.5,'Zoom + control must work');
assert.ok(/%$/.test(buttons['earth-zoom-level'].textContent),'Zoom level must update');
const afterPlus=zoom();
buttons['earth-zoom-out'].events.click();
assert.ok(zoom()<afterPlus,'Zoom − control must work');
buttons['earth-zoom-reset'].events.click();
assert.ok(Math.abs(zoom()-1)<.00001,'Reset control must restore original view');
for(let i=0;i<12;i++)buttons['earth-zoom-in'].events.click();
assert.ok(zoom()>7.9,'Deep zoom must reach approximately 800 percent');
buttons['earth-zoom-reset'].events.click();
assert.ok(Math.abs(zoom()-1)<.00001,'Deep zoom reset must restore globe');
listeners.pointerdown({pointerId:1,clientX:100,clientY:100});
listeners.pointerdown({pointerId:2,clientX:200,clientY:100});
listeners.pointermove({pointerId:2,clientX:250,clientY:100});
assert.ok(zoom()>1.45,'Two-finger pinch must enlarge Earth');
listeners.pointerup({pointerId:1});
listeners.pointerup({pointerId:2});
listeners.keydown({key:'+',preventDefault(){}});
assert.ok(zoom()>1.7,'Keyboard + must zoom in');
listeners.keydown({key:'0',preventDefault(){}});
assert.ok(Math.abs(zoom()-1)<.00001,'Keyboard 0 must reset zoom');
listeners.wheel({deltaY:900,deltaMode:0,preventDefault(){}});
assert.ok(zoom()>=.4-1e-6&&zoom()<.75,'Zoom out must respect expanded 40%–800% bounds');
buttons['earth-zoom-reset'].events.click();

assert.ok(!fs.readFileSync('assets/home-earth.js','utf8').includes('LAND_BITS'),
  'Obsolete coarse point mask must not be used to draw geography');
console.log('  Blue Marble Earth: Canvas fallback, 3 local textures, 2024 replay, wheel/pinch/button/keyboard zoom and solar geometry OK');
