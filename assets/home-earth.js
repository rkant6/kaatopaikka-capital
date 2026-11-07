/* Kaatopaikka Capital | Blue Marble Earth
   Self-hosted NASA-derived Earth imagery (see assets/EARTH_CREDITS.md).
   GPU WebGL (smooth) + dependable 2D canvas fallback; no third-party scripts.
   Astronomical UTC Sun, historic date replay, interactive rotation + zoom.
*/
(() => {
  'use strict';
  const PI=Math.PI, TAU=2*PI, RAD=PI/180, DAY=86400000;
  const BASE='assets/';
  const PATHS=[
    BASE+'earth-blue-marble-day.jpg',
    BASE+'earth-city-lights.jpg',
    BASE+'earth-cloud-cover.png'
  ];
  const PALETTE={LONG:'#54e5ae',WATCH:'#ffc970',SHORT:'#ff797e',NEUTRAL:'#bdc8d4',LOCATION:'#b2cbd6'};
  const to2D=(a,b)=>Math.hypot(a,b);
  const clamp=(v,lo,hi)=>Math.max(lo,Math.min(hi,v));
  let app=null,packet={date:new Date().toISOString().slice(0,10),mode:'current',companies:null,event:null};

  function solar(date) {
    const n=date.getTime()/DAY+2440587.5-2451545;
    const g=(357.528+.9856003*n)*RAD;
    const ecl=(280.460+.9856474*n)*RAD+(1.915*Math.sin(g)+.020*Math.sin(2*g))*RAD;
    const obliquity=(23.439-.0000004*n)*RAD;
    const ra=Math.atan2(Math.cos(obliquity)*Math.sin(ecl),Math.cos(ecl));
    const dec=Math.asin(Math.sin(obliquity)*Math.sin(ecl));
    const lon=ra-(280.46061837+360.98564736629*n)*RAD;
    const c=Math.cos(dec);
    return [c*Math.sin(lon),Math.sin(dec),c*Math.cos(lon)];
  }
  function project(lat,lon,state) {
    const a=lat*RAD,b=lon*RAD;
    const y=Math.sin(a),co=Math.cos(a),x=co*Math.sin(b),z=co*Math.cos(b);
    const sl=Math.sin(state.lat),cl=Math.cos(state.lat),so=Math.sin(state.lon),ca=Math.cos(state.lon);
    const right=x*ca-z*so, forward=x*so+z*ca;
    return {x:state.cx+right*state.radius,y:state.cy-(y*cl-forward*sl)*state.radius,
      visible:y*sl+forward*cl>0.03};
  }
  function createState(canvas,overlay){
    const reduce=window.matchMedia && matchMedia('(prefers-reduced-motion:reduce)').matches;
    return {canvas,overlay,overlayCtx:overlay.getContext('2d'),mode:null,
      lon:18*RAD,lat:56*RAD,zoom:1,drag:false,autoSpin:!reduce,reduced:reduce,
      previous:null,velocity:0,hover:null,companies:[],textures:[],
      started:performance.now(),last:performance.now(),lastDraw:0,meteorAt:0,
      w:0,h:0,cx:0,cy:0,radius:0,dpr:1,destroyed:false};
  }
  function geometry(s){
    const r=s.canvas.getBoundingClientRect(),d=Math.min(1.75,window.devicePixelRatio||1);
    const w=Math.max(1,Math.round(r.width*d)),h=Math.max(1,Math.round(r.height*d));
    if(s.w===w&&s.h===h)return;
    s.w=w;s.h=h;s.dpr=d;
    s.canvas.width=w;s.canvas.height=h;
    s.overlay.width=w;s.overlay.height=h;
    s.cx=w*.46;s.cy=h*.52;s.radius=Math.min(w*.40,h*.44)*s.zoom;
    if(s.gpu)s.gpu.gl.viewport(0,0,w,h);
    if(s.cpu)s.cpu.resize();
  }
  function loadImage(path) {
    return new Promise(resolve=>{
      const image=new Image();image.decoding='async';
      image.onload=()=>resolve(image);
      image.onerror=()=>resolve(null);
      image.src=path;
    });
  }
  function createGpu(s) {
    let gl=null;
    try {gl=s.canvas.getContext('webgl',{alpha:true,antialias:false,depth:false,stencil:false,
      premultipliedAlpha:false,powerPreference:'high-performance',preserveDrawingBuffer:false}) ||
      s.canvas.getContext('experimental-webgl',{alpha:true,antialias:false,depth:false,stencil:false});}
    catch(e){return null;}
    if(!gl)return null;
    const vs='attribute vec2 aPos;void main(){gl_Position=vec4(aPos,0.0,1.0);}';
    const fs=[
      'precision highp float;',
      'uniform vec2 uRes,uCenter;',
      'uniform float uRadius,uSinLat,uCosLat,uSinLon,uCosLon,uCloudShift,uReady;',
      'uniform vec3 uSun;',
      'uniform sampler2D uDay,uNight,uCloud;',
      'const float PI=3.141592653589793;',
      'void main(){',
      '  vec2 p=(gl_FragCoord.xy-uCenter)/uRadius;',
      '  float rr=dot(p,p); float r=sqrt(rr);',
      // Atmosphere is drawn only around the circle; do not output opaque square pixels.
      '  if(rr>1.0){',
      '    if(r>1.17)discard;',
      '    float halo=pow(clamp((1.17-r)/.17,0.0,1.0),2.7);',
      '    gl_FragColor=vec4(0.05,0.26,0.52,halo*0.14);return;',
      '  }',
      '  float f=sqrt(max(0.0,1.0-rr));',
      '  float y=p.y*uCosLat+f*uSinLat;',
      '  float z=-p.y*uSinLat+f*uCosLat;',
      '  vec3 world=normalize(vec3(p.x*uCosLon+z*uSinLon,y,z*uCosLon-p.x*uSinLon));',
      '  float lon=atan(world.x,world.z);',
      '  vec2 uv=vec2(fract(lon/(2.0*PI)+0.5),0.5+asin(clamp(world.y,-1.0,1.0))/PI);',
      '  float sunDot=dot(world,normalize(uSun));',
      '  float light=smoothstep(-.16,.16,sunDot);',
      '  float diffuse=0.32+0.79*max(0.0,sunDot);',
      '  vec3 day=texture2D(uDay,uv).rgb;',
      '  vec3 night=texture2D(uNight,uv).rgb;',
      '  vec3 color=mix(night*1.50+day*.035,day*diffuse,light);',
      '  float ocean=min(1.0,max(0.0,day.b-day.r)*2.0);',
      '  float shine=pow(max(0.0,sunDot),18.0)*0.09*ocean;',
      '  color+=vec3(0.16,0.29,0.32)*shine;',
      '  float clouds=texture2D(uCloud,vec2(fract(uv.x+uCloudShift),uv.y)).r;',
      '  clouds=smoothstep(0.26,0.88,clouds)*.55;',
      '  vec3 cloudWhite=vec3(.82,.87,.95)*(.20+.80*max(0.0,sunDot));',
      '  color=mix(color,cloudWhite,clouds*(.13+.87*light));',
      '  float limb=pow(1.0-f,3.8);',
      '  color=mix(color,vec3(.15,.48,.76),limb*(.17+.23*light));',
      '  color=color*(.80+.20*pow(f,.35));',
      '  float edge=clamp((1.0-r)*uRadius,0.0,1.0);',
      '  gl_FragColor=vec4(pow(max(color,vec3(0.0)),vec3(.94)),edge);',
      '}'
    ].join('\n');
    function shader(type,source){
      const sh=gl.createShader(type);gl.shaderSource(sh,source);gl.compileShader(sh);
      if(!gl.getShaderParameter(sh,gl.COMPILE_STATUS)){console.warn('Earth shader error',gl.getShaderInfoLog(sh));gl.deleteShader(sh);return null;}
      return sh;
    }
    const a=shader(gl.VERTEX_SHADER,vs),b=shader(gl.FRAGMENT_SHADER,fs);
    if(!a||!b)return null;
    const program=gl.createProgram();gl.attachShader(program,a);gl.attachShader(program,b);gl.linkProgram(program);
    if(!gl.getProgramParameter(program,gl.LINK_STATUS)){console.warn('Earth program failed:',gl.getProgramInfoLog(program));return null;}
    gl.deleteShader(a);gl.deleteShader(b);gl.useProgram(program);
    const buff=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buff);
    gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,1,1]),gl.STATIC_DRAW);
    const pos=gl.getAttribLocation(program,'aPos');gl.vertexAttribPointer(pos,2,gl.FLOAT,false,0,0);gl.enableVertexAttribArray(pos);
    const location=(name)=>gl.getUniformLocation(program,name);
    const uniforms={res:location('uRes'),center:location('uCenter'),radius:location('uRadius'),
      sinLat:location('uSinLat'),cosLat:location('uCosLat'),sinLon:location('uSinLon'),
      cosLon:location('uCosLon'),sun:location('uSun'),cloudShift:location('uCloudShift'),
      ready:location('uReady')};
    const textures=[0,1,2].map((k)=>{
      const t=gl.createTexture();gl.activeTexture(gl.TEXTURE0+k);gl.bindTexture(gl.TEXTURE_2D,t);
      gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.REPEAT);
      gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
      gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,1,1,0,gl.RGBA,gl.UNSIGNED_BYTE,new Uint8Array(k===0?[32,69,95,255]:[0,0,0,255]));
      gl.uniform1i(location(['uDay','uNight','uCloud'][k]),k);
      return t;
    });
    gl.clearColor(0,0,0,0);
    gl.enable(gl.BLEND);gl.blendFunc(gl.SRC_ALPHA,gl.ONE_MINUS_SRC_ALPHA);
    const upload=(images)=>{
      gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,true);
      images.forEach((image,k)=>{
        if(!image)return;
        gl.activeTexture(gl.TEXTURE0+k);gl.bindTexture(gl.TEXTURE_2D,textures[k]);
        try {
          gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,image);
          gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);
        } catch(e){console.warn('Earth texture upload failed:',e);}
      });
      gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,false);
    };
    return {gl,upload,draw:(sun,now)=>{
      gl.viewport(0,0,s.w,s.h);gl.clear(gl.COLOR_BUFFER_BIT);gl.useProgram(program);
      gl.uniform2f(uniforms.res,s.w,s.h);
      gl.uniform2f(uniforms.center,s.cx,s.h-s.cy);
      gl.uniform1f(uniforms.radius,s.radius);
      gl.uniform1f(uniforms.sinLat,Math.sin(s.lat));
      gl.uniform1f(uniforms.cosLat,Math.cos(s.lat));
      gl.uniform1f(uniforms.sinLon,Math.sin(s.lon));
      gl.uniform1f(uniforms.cosLon,Math.cos(s.lon));
      gl.uniform3fv(uniforms.sun,new Float32Array(sun));
      gl.uniform1f(uniforms.cloudShift,s.reduced?0:((now-s.started)*0.000000016)%1);
      gl.drawArrays(gl.TRIANGLE_STRIP,0,4);
    }};
  }

  function prepareCpuTexture(image,w,h){
    if(!image)return null;
    const c=document.createElement('canvas');c.width=w;c.height=h;const x=c.getContext('2d',{willReadFrequently:true});
    if(!x)return null;
    try{x.drawImage(image,0,0,w,h);return {data:x.getImageData(0,0,w,h).data,w,h};}
    catch(e){console.warn('Earth fallback texture is unreadable:',e);return null;}
  }
  function sample(tex,lon,latitude){
    if(!tex)return null;
    const u=((lon/TAU+0.5)%1+1)%1;
    const v=clamp(0.5-Math.asin(clamp(latitude,-1,1))/PI,0,.99999);
    const x=Math.floor(u*tex.w),y=Math.floor(v*tex.h);
    const i=(y*tex.w+x)*4,d=tex.data;
    return [d[i],d[i+1],d[i+2],d[i+3]];
  }
  function createCpu(s) {
    let ctx=s.canvas.getContext('2d',{alpha:true});
    if(!ctx)return null;
    const back=document.createElement('canvas'),bc=back.getContext('2d');
    if(!bc)return null;
    const cpu={ctx,back,bc,images:null,day:null,night:null,cloud:null,step:0,
      resize(){
        // Quarter-million pixels at most, redraw 18–22fps for weak devices.
        const ideal=Math.round(Math.min(s.radius*1.4,Math.min(s.w,s.h)*0.85));
        const n=clamp(ideal,190,520);
        if(back.width!==n){back.width=back.height=n;}
      },
      upload(images){
        cpu.images=images;
        cpu.day=prepareCpuTexture(images[0],1536,768);
        cpu.night=prepareCpuTexture(images[1],1024,512);
        cpu.cloud=prepareCpuTexture(images[2],768,384);
      },
      draw(sun,now){
        const n=back.width;if(!n)return;
        const pixels=bc.createImageData(n,n),d=pixels.data;
        const sl=Math.sin(s.lat),cl=Math.cos(s.lat),so=Math.sin(s.lon),co=Math.cos(s.lon);
        const cloudShift=s.reduced?0:((now-s.started)*0.000000016);
        const cloudAngle=cloudShift*TAU;
        for(let yy=0;yy<n;yy++){
          const py=1-2*(yy+.5)/n,y2=py*py;
          for(let xx=0;xx<n;xx++){
            const px=2*(xx+.5)/n,rr=px*px+y2,o=(yy*n+xx)*4;
            if(rr>1)continue;
            const front=Math.sqrt(1-rr);
            const north=py*cl+front*sl;
            const fw=-py*sl+front*cl;
            const wx=px*co+fw*so,wz=fw*co-px*so;
            const ln=Math.atan2(wx,wz),dot=wx*sun[0]+north*sun[1]+wz*sun[2];
            const lit=clamp((dot+.16)/.32,0,1);
            const diffuse=.32+.79*Math.max(0,dot);
            const day=sample(cpu.day,ln,north),night=sample(cpu.night,ln,north),cloud=sample(cpu.cloud,ln+cloudAngle,north);
            const rim=Math.pow(1-front,3.8);
            const white=cloud?clamp((cloud[0]/255-.26)/.62,0,1)*.55*(.13+.87*lit):0;
            const ambient=.80+.20*Math.pow(front,.35);
            for(let k=0;k<3;k++){
              const base=day?day[k]:[16,54,86][k];
              const dusk=night?night[k]*1.5+base*.035:base*.08;
              let color=(dusk*(1-lit)+base*diffuse*lit)*ambient;
              color=color*(1-white)+[209,222,243][k]*(.20+.80*Math.max(0,dot))*white;
              color=color*(1-rim*.25)+[38,122,195][k]*rim*.25;
              d[o+k]=clamp(Math.round(color),0,255);
            }
            d[o+3]=clamp(Math.round((1-Math.max(0,(Math.sqrt(rr)-.993)/.007))*255),0,255);
          }
        }
        bc.putImageData(pixels,0,0);
        ctx.clearRect(0,0,s.w,s.h);
        ctx.imageSmoothingEnabled=true;
        ctx.drawImage(back,s.cx-s.radius,s.cy-s.radius,s.radius*2,s.radius*2);
      }};
    return cpu;
  }
  function renderOverlay(s,now) {
    const ctx=s.overlayCtx,w=s.w,h=s.h;
    ctx.clearRect(0,0,w,h);
    const radius=s.radius;
    // Subtle atmosphere outside the sphere; no rectangular glow texture.
    const atm=ctx.createRadialGradient(s.cx,s.cy,radius*.95,s.cx,s.cy,radius*1.22);
    atm.addColorStop(0,'rgba(68,174,238,.21)');
    atm.addColorStop(.38,'rgba(45,149,230,.14)');
    atm.addColorStop(1,'rgba(45,149,230,0)');
    ctx.strokeStyle='rgba(91,193,237,.14)';
    ctx.fillStyle=atm;ctx.beginPath();ctx.arc(s.cx,s.cy,radius*1.22,0,TAU);ctx.fill();
    if(!s.companies.length)return;
    const verified=packet.mode==='verified'&&Array.isArray(packet.companies);
    const records=verified?new Map(packet.companies.map(c=>[c.id,c])):null;
    let nearest=null,dist=Infinity;
    for(const c of s.companies) {
      if(!Number.isFinite(c.lat)||!Number.isFinite(c.lon))continue;
      const p=project(c.lat,c.lon,s);if(!p.visible)continue;
      const sig=packet.mode==='unverified'?'LOCATION':
        verified?(records.get(c.id)?.signal||'LOCATION').split(' ')[0]:(c.signal||'LOCATION').split(' ')[0];
      const color=PALETTE[sig]||PALETTE.LOCATION;
      ctx.fillStyle=color;ctx.shadowColor=color;ctx.shadowBlur=8*s.dpr;
      ctx.beginPath();ctx.arc(p.x,p.y,2.6*s.dpr,0,TAU);ctx.fill();
      ctx.shadowBlur=0;
      if(s.hover){const z=to2D(p.x-s.hover.x,p.y-s.hover.y);if(z<dist){nearest={c,p,color};dist=z;}}
    }
    if(nearest&&dist<20*s.dpr) {
      const name=nearest.c.name||nearest.c.ticker||'Company';
      ctx.font='600 '+12*s.dpr+'px IBM Plex Mono,monospace';
      const width=ctx.measureText(name).width+20*s.dpr;
      const tx=clamp(nearest.p.x+12*s.dpr,10*s.dpr,w-width-8*s.dpr);
      const ty=clamp(nearest.p.y-30*s.dpr,24*s.dpr,h-18*s.dpr);
      ctx.fillStyle='rgba(8,15,23,.93)';ctx.fillRect(tx,ty,width,25*s.dpr);
      ctx.strokeStyle='rgba(255,186,83,.65)';ctx.strokeRect(tx,ty,width,25*s.dpr);
      ctx.fillStyle='#e8edf5';ctx.fillText(name,tx+10*s.dpr,ty+17*s.dpr);
    }
    if(s.meteorAt&&packet.mode==='verified') {
      const k=(now-s.meteorAt)/1000;
      if(k>1)s.meteorAt=0;
      else {
        ctx.strokeStyle='rgba(255,165,72,'+(1-k)+')';ctx.lineWidth=3*s.dpr;
        const x=s.cx+radius*(1.1-1.05*k),y=s.cy-radius*(.95-.55*k);
        ctx.beginPath();ctx.moveTo(x+70*s.dpr,y-45*s.dpr);ctx.lineTo(x,y);ctx.stroke();
        ctx.fillStyle='#fff0ba';ctx.beginPath();ctx.arc(x,y,5*s.dpr,0,TAU);ctx.fill();
      }
    }
  }
  function updateSnapshot(p){
    if(!p||!/^\\d{4}-\\d{2}-\\d{2}$/.test(String(p.date||'')))return;
    packet={...packet,...p};
    if(!app)return;
    if(p.event?.type==='observed_drawdown'&&packet.mode==='verified')app.meteorAt=performance.now();
    app.dirty=true;
  }
  function bindControls(s){
    const c=s.canvas,info=s.overlay;
    const start=(e)=>{s.drag=true;s.autoSpin=false;s.hover=null;
      s.previous={x:e.clientX,y:e.clientY};s.velocity=0;
      try{c.setPointerCapture(e.pointerId);}catch(_){}};
    c.addEventListener('pointerdown',start);
    c.addEventListener('pointermove',(e)=>{
      if(!s.drag){const a=c.getBoundingClientRect();
        s.hover={x:(e.clientX-a.left)*s.dpr,y:(e.clientY-a.top)*s.dpr};return;}
      const dx=e.clientX-s.previous.x,dy=e.clientY-s.previous.y;
      s.lon-=dx*.0076;s.lat=clamp(s.lat+dy*.0065,-1.43,1.43);
      s.velocity=dx*.0005;s.previous={x:e.clientX,y:e.clientY};s.dirty=true;
    });
    for(const type of ['pointerup','pointercancel'])
      c.addEventListener(type,()=>{s.drag=false;s.previous=null;});
    c.addEventListener('pointerleave',()=>{s.hover=null;});
    c.addEventListener('wheel',e=>{e.preventDefault();s.zoom=clamp(s.zoom*(e.deltaY>0?.93:1.07),.7,1.48);
      s.radius=Math.min(s.w*.40,s.h*.44)*s.zoom;s.dirty=true;},{passive:false});
  }
  function init(){
    const canvas=document.getElementById('home-earth-canvas');
    const overlay=document.getElementById('home-earth-overlay');
    if(!canvas||!overlay)return;
    const s=createState(canvas,overlay);app=s;
    s.gpu=createGpu(s);
    if(s.gpu)s.mode='gpu';
    else {s.cpu=createCpu(s);s.mode=s.cpu?'cpu':'none';}
    geometry(s);
    bindControls(s);
    if(typeof ResizeObserver!=='undefined')new ResizeObserver(()=>geometry(s)).observe(canvas);
    else window.addEventListener('resize',()=>geometry(s),{passive:true});
    // Always self-host the imagery, so the site does not depend on Google, NASA
    // or an external JavaScript library being available at render time.
    Promise.all(PATHS.map(loadImage)).then(images=>{
      s.textures=images;
      if(s.gpu)s.gpu.upload(images);
      if(s.cpu)s.cpu.upload(images);
      s.dirty=true;
      if(images[0])canvas.parentElement.classList.add('earth-textured');
      else canvas.parentElement.classList.add('earth-texture-missing');
    }).catch(()=>{canvas.parentElement.classList.add('earth-texture-missing');});
    fetch('data.json',{cache:'no-store'}).then(r=>r.ok?r.json():null)
      .then(data=>{if(data?.companies)s.companies=data.companies;})
      .catch(()=>{});
    let last=performance.now(),lastDraw=0;
    function frame(now){
      if(!canvas.isConnected||s.destroyed)return;
      const dt=clamp((now-last)/1000,0,.06);last=now;
      if(!document.hidden){
        if(!s.drag&&!s.reduced){
          if(s.autoSpin)s.lon+=dt*.033;
          if(Math.abs(s.velocity)>0.00003){s.lon-=s.velocity;s.velocity*=.94;}
        }
        const fps=s.mode==='gpu'?60:22;
        if(now-lastDraw>1000/fps||s.dirty){
          geometry(s);
          const noon=Date.parse(packet.date+'T12:00:00Z');
          const time=new Date((Number.isFinite(noon)?noon:Date.now())+
            (s.reduced?0:(now-s.started)*DAY/120000));
          const sun=solar(time);
          if(s.gpu)s.gpu.draw(sun,now);
          else if(s.cpu)s.cpu.draw(sun,now);
          renderOverlay(s,now);
          lastDraw=now;s.dirty=false;
          canvas.parentElement.classList.add('has-renderer');
        }
      }
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }
  window.KCHomeEarth=Object.freeze({setSnapshot:updateSnapshot,solar});
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});
  else init();
})();
