/* Kaatopaikka Solar Globe: real UTC Sun geometry, quiet GPU shader overlay,
   optional audited event effects, and accessible non-WebGL fallback.
   No dependency beyond THREE r128 already used by classic.html. */
(function () {
  'use strict';
  const DAY=86400000, RAD=Math.PI/180;
  let runtime=null, fallback=null, fallbackView=null, pendingPacket=null, currentDate=new Date().toISOString().slice(0,10);
  let mode='current', activeMeteor=null, meteorLast=0;

  // Approximate apparent solar coordinates (Meeus/NOAA low-order terms),
  // including Greenwich sidereal time. This is astronomical geometry, not
  // a stock-data animation and not a weather/atmospheric model.
  function solarDirection(date) {
    const jd=date.getTime()/DAY+2440587.5, n=jd-2451545;
    const L=(280.460+0.9856474*n)*RAD;
    const g=(357.528+0.9856003*n)*RAD;
    const lambda=L+(1.915*Math.sin(g)+.020*Math.sin(2*g))*RAD;
    const obliquity=(23.439-.0000004*n)*RAD;
    const rightAscension=Math.atan2(Math.cos(obliquity)*Math.sin(lambda),Math.cos(lambda));
    const declination=Math.asin(Math.sin(obliquity)*Math.sin(lambda));
    const gmst=(280.46061837+360.98564736629*n)*RAD;
    const lon=rightAscension-gmst;
    const cos=Math.cos(declination);
    return [cos*Math.sin(lon),Math.sin(declination),cos*Math.cos(lon)];
  }

  function createGlow(THREE) {
    const canvas=document.createElement('canvas');canvas.width=canvas.height=128;
    const g=canvas.getContext('2d'),r=g.createRadialGradient(64,64,2,64,64,64);
    r.addColorStop(0,'rgba(255,249,212,1)');r.addColorStop(.14,'rgba(255,206,95,.98)');
    r.addColorStop(.36,'rgba(255,164,55,.36)');r.addColorStop(1,'rgba(255,142,25,0)');
    g.fillStyle=r;g.fillRect(0,0,128,128);
    const texture=new THREE.CanvasTexture(canvas);texture.needsUpdate=true;return texture;
  }

  function meteor(runtime,ev) {
    if(!ev || ev.type!=='observed_drawdown')return;
    const now=performance.now();if(now-meteorLast<1200)return;meteorLast=now;
    const {THREE,scene,globe}=runtime;
    const from=new THREE.Vector3(-1.55,1.48,1.0);
    const to=new THREE.Vector3(.3,.67,.75).normalize().multiplyScalar(1.06);
    to.applyQuaternion(globe.quaternion);
    const streak=new THREE.Line(new THREE.BufferGeometry().setFromPoints([from,from]),
      new THREE.LineBasicMaterial({color:0xff9c4a,transparent:true,opacity:.95,depthWrite:false}));
    const dot=new THREE.Sprite(new THREE.SpriteMaterial({map:runtime.glow,color:0xffbc6a,
      transparent:true,depthWrite:false,blending:THREE.AdditiveBlending}));
    dot.scale.set(.24,.24,1);dot.position.copy(from);scene.add(dot,streak);
    activeMeteor={from,to,start:now,streak,dot,duration:1150};
  }

  function resetMarker(m,base,version,THREE) {
    if(version==='unverified'){
      m.pillar.visible=false;m.cap.visible=false;m.base.visible=true;
      m.color.set('#748693');m.base.material.color.set('#748693');m.base.material.opacity=.4;
    } else {
      m.pillar.visible=true;m.cap.visible=true;m.base.visible=true;
      const key=String(m.c.signal||'').split(' ')[0];
      const palette={LONG:'#4bd6a7',WATCH:'#ffbd54',NEUTRAL:'#a0afbd',SHORT:'#ff777c',EXCLUDED:'#677584'};
      m.color.set(palette[key]||'#a0afbd');
      m.base.material.color.copy(m.color);m.cap.material.color.copy(m.color);
      m.base.material.opacity=.8;
    }
  }

  function setSnapshot(packet) {
    const day=String(packet.date||'');
    if(!/^\d{4}-\d{2}-\d{2}$/.test(day) || !Number.isFinite(Date.parse(day+'T12:00:00Z')))return;
    pendingPacket=packet;
    currentDate=day;mode=packet.mode==='verified'?'verified':packet.mode==='current'?'current':'unverified';
    document.documentElement.classList.toggle('historical-unverified',mode==='unverified');
    document.documentElement.dataset.timelineMode=mode;
    if(runtime){
      const data=Array.isArray(packet.companies)?new Map(packet.companies.map(c=>[c.id,c])):null;
      runtime.markers.forEach((m,i)=>{
        const original=runtime.original[i];const next=mode==='verified'?data?.get(m.c.id):original;
        if(next){
          for(const key of ['signal','rank','revUp','gap','cur','norm','score'])if(next[key]!==undefined)m.c[key]=next[key];
        }
        resetMarker(m,original,mode,runtime.THREE);
      });
      runtime.status.textContent=mode==='unverified'?'HISTORICAL EQUITY SIGNALS: NOT YET VERIFIED':
        mode==='verified'?'SOURCE-DATED HISTORICAL SIGNALS':'LATEST PUBLISHED MODEL';
      if(packet.event)meteor(runtime,packet.event);
    }
    if(fallback)updateFallback(packet);
  }

  function attach({THREE,scene,globe,camera,renderer,markers,sun}) {
    if(runtime)return;
    // A thin alpha shell darkens ocean + land dots on the night hemisphere.
    // It sits outside the ocean surface, but below tall HQ pillars.
    const light=new THREE.Vector3(1,0,0);
    const material=new THREE.ShaderMaterial({transparent:true,depthWrite:false,side:THREE.FrontSide,
      uniforms:{sunDirection:{value:light}},
      vertexShader:'varying vec3 vWorldNormal;void main(){vWorldNormal=normalize(mat3(modelMatrix)*normal);gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}',
      fragmentShader:'uniform vec3 sunDirection;varying vec3 vWorldNormal;void main(){float d=dot(normalize(vWorldNormal),normalize(sunDirection));float night=1.0-smoothstep(-0.12,0.18,d);gl_FragColor=vec4(0.012,0.022,0.041,night*0.86);}'
    });
    const shell=new THREE.Mesh(new THREE.SphereGeometry(1.012,96,64),material);globe.add(shell);
    if(sun.parent)sun.parent.remove(sun);scene.add(sun);sun.intensity=1.1;
    const glow=createGlow(THREE);
    const sunSprite=new THREE.Sprite(new THREE.SpriteMaterial({map:glow,color:0xffdfad,
      transparent:true,depthWrite:false,depthTest:true,blending:THREE.AdditiveBlending}));
    sunSprite.scale.set(.72,.72,1);scene.add(sunSprite);
    const status=document.createElement('div');status.className='globe-solar-status';status.textContent='SOLAR LIGHTING · UTC';
    document.getElementById('stage').append(status);
    runtime={THREE,scene,globe,camera,renderer,markers,sun,material,glow,sunSprite,status,
      original:markers.map(m=>Object.fromEntries(['signal','rank','revUp','gap','cur','norm','score'].map(k=>[k,m.c[k]]))),
      started:performance.now(),tmpVector:new THREE.Vector3(),earthVector:new THREE.Vector3(),worldQuaternion:new THREE.Quaternion()};
    if(pendingPacket)setSnapshot(pendingPacket);
    tick(performance.now());
  }

  function tick(now) {
    if(!runtime)return;
    const r=runtime;
    // The date slider determines the season/year. The solar hour advances
    // smoothly at 24 h / 120 seconds, so fast financial scrubs do not strobe.
    const noon=Date.parse(currentDate+'T12:00:00Z');
    const simulatedTime=new Date(noon+(now-r.started)*DAY/120000);
    r.earthVector.fromArray(solarDirection(simulatedTime));
    r.globe.getWorldQuaternion(r.worldQuaternion);
    r.tmpVector.copy(r.earthVector).applyQuaternion(r.worldQuaternion).normalize();
    r.material.uniforms.sunDirection.value.copy(r.tmpVector);
    r.sun.position.copy(r.tmpVector).multiplyScalar(6);
    r.sunSprite.position.copy(r.tmpVector).multiplyScalar(3.8);
    if(activeMeteor){
      const m=activeMeteor,t=Math.min(1,(now-m.start)/m.duration);
      m.dot.position.copy(m.from).lerp(m.to,t);
      const tail=m.from.clone().lerp(m.to,Math.max(0,t-.17));
      m.streak.geometry.setFromPoints([tail,m.dot.position]);
      m.streak.material.opacity=Math.max(0,1-t);
      m.dot.material.opacity=Math.max(0,1-t);
      if(t>=1){r.scene.remove(m.dot,m.streak);m.dot.material.dispose();m.streak.material.dispose();m.streak.geometry.dispose();activeMeteor=null;}
    }
  }

  function updateFallback(packet) {
    if(!fallback)return;
    fallback.dataset.mode=mode;
    fallback.querySelector('.fallback-status').textContent=mode==='unverified'
      ?'HISTORICAL SIGNALS NOT YET VERIFIED · LOCATION VIEW ONLY'
      :mode==='verified'?'POINT-IN-TIME COMPANY SIGNALS':'CURRENT COMPANY LOCATIONS';
    const map=packet.companies?new Map(packet.companies.map(x=>[x.id,x])):null;
    if(fallbackView)fallbackView.companies.forEach(c=>{
      const historical=map?.get(c.id);
      c.activeSignal=mode==='unverified'?'unverified':mode==='verified'
        ?historical?.signal||'NEUTRAL':c.signal;
    });
    if(packet.event){fallback.classList.remove('impact');void fallback.offsetWidth;fallback.classList.add('impact');}
  }

  // CPU-only orthographic renderer. It uses the same embedded Natural Earth
  // coast geometry as the WebGL globe, and therefore needs no third-party
  // service, static image, or network request for the shape of the continents.
  // It is deliberately lightweight: a low-resolution sunlight texture and
  // geographic coast outlines are drawn at 25 fps at most.
  function drawFallback(view,now) {
    const {canvas,ctx,companies,coasts,shade,shadeCtx}=view;
    const {width:w,height:h}=canvas;
    if(!w||!h)return;
    const t=(now-view.started);
    const auto=view.reducedMotion?0:t*.0011;
    const lon0=(view.lon+auto)*RAD,lat0=view.lat*RAD;
    const sin0=Math.sin(lat0),cos0=Math.cos(lat0);
    const radius=Math.max(40,Math.min(w*.38,h*.44))*view.zoom;
    const cx=w*.50,cy=h*.51;
    const project=(lon,lat)=>{
      const a=lon*RAD-lon0,b=lat*RAD;
      const sa=Math.sin(a),ca=Math.cos(a),sb=Math.sin(b),cb=Math.cos(b);
      const z=sin0*sb+cos0*cb*ca;
      return [cx+radius*cb*sa,cy-radius*(cos0*sb-sin0*cb*ca),z];
    };
    ctx.clearRect(0,0,w,h);
    // Subtle starfield: no random values are sampled during animation.
    for(let i=0;i<65;i++){
      const px=(Math.sin(i*127.1)*43758.5453%1+1)%1*w;
      const py=(Math.sin(i*71.6+4)*15631.23%1+1)%1*h;
      ctx.fillStyle=i%5===0?'#263e50':'#162937';ctx.fillRect(px,py,1,1);
    }
    const solarTime=new Date(Date.parse(currentDate+'T12:00:00Z')+t*DAY/120000);
    const sun=solarDirection(solarTime);
    const sunLon=Math.atan2(sun[0],sun[2]);
    const lit=project(sunLon/RAD,Math.asin(sun[1])/RAD);
    const halo=ctx.createRadialGradient(lit[0],lit[1],radius*.07,lit[0],lit[1],radius*1.1);
    halo.addColorStop(0,'#f5b44b26');halo.addColorStop(.3,'#da882010');halo.addColorStop(1,'#d98a1400');
    ctx.fillStyle=halo;ctx.fillRect(cx-radius*2,cy-radius*2,radius*4,radius*4);
    const atmosphere=ctx.createRadialGradient(cx,cy,radius*.79,cx,cy,radius*1.12);
    atmosphere.addColorStop(0,'#0a172800');atmosphere.addColorStop(.78,'#1b7da811');
    atmosphere.addColorStop(.88,'#47c5e929');atmosphere.addColorStop(1,'#47c5e900');
    ctx.fillStyle=atmosphere;ctx.beginPath();ctx.arc(cx,cy,radius*1.13,0,Math.PI*2);ctx.fill();
    // Shade the ocean sphere per visible surface normal. Land boundaries are
    // rendered as accurate outlines below, never as guessed filled polygons:
    // even a correctly closed global coastline may straddle the map seam.
    // This avoids false patches near the horizon and international date line.
    if(now-view.lastShadow>50||view.lastShadow<0){
      view.lastShadow=now;
      const n=shade.width,img=shadeCtx.createImageData(n,n),d=img.data;
      for(let y=0;y<n;y++)for(let x=0;x<n;x++){
        const sx=(x+.5)*2/n-1,sy=1-(y+.5)*2/n,rr=sx*sx+sy*sy;
        if(rr>=1)continue;
        const front=Math.sqrt(1-rr),yn=sy*cos0+front*sin0;
        const forward=-sy*sin0+front*cos0;
        const worldLon=lon0+Math.atan2(sx,forward);
        const latCos=Math.sqrt(Math.max(0,1-yn*yn));
        const sunlight=latCos*Math.sin(worldLon)*sun[0]+yn*sun[1]+latCos*Math.cos(worldLon)*sun[2];
        const daylight=Math.min(1,Math.max(0,(sunlight+.10)/.33));
        const brightness=(.20+daylight*.8)*(.76+.24*front);
        const col=[18,55,74];
        const o=(y*n+x)*4;
        d[o]=col[0]*brightness;d[o+1]=col[1]*brightness;d[o+2]=col[2]*brightness;
        d[o+3]=255;
      }
      shadeCtx.putImageData(img,0,0);
    }
    ctx.drawImage(shade,cx-radius,cy-radius,radius*2,radius*2);
    ctx.save();ctx.beginPath();ctx.arc(cx,cy,radius-.6,0,2*Math.PI);ctx.clip();
    // Longitude and latitude are actual sphere great/small circles, clipped
    // against the visible hemisphere instead of being painted as a flat grid.
    ctx.strokeStyle='#42677864';ctx.lineWidth=.7;
    const curve=points=>{
      ctx.beginPath();let open=false;
      for(const [lo,la] of points){const p=project(lo,la);
        if(p[2]<.01){open=false;continue;}
        if(open)ctx.lineTo(p[0],p[1]);else ctx.moveTo(p[0],p[1]);open=true;
      }
      ctx.stroke();
    };
    for(let lat=-75;lat<=75;lat+=15){const pts=[];for(let lon=-180;lon<=180;lon+=3)pts.push([lon,lat]);curve(pts);}
    for(let lon=-180;lon<180;lon+=15){const pts=[];for(let lat=-90;lat<=90;lat+=3)pts.push([lon,lat]);curve(pts);}
    // Built-in country/coastline source of the primary globe, simplified by
    // skipping every other point (no inaccurate hand-drawn continents).
    ctx.strokeStyle='#a4c9aeaa';ctx.lineWidth=.86;
    for(const poly of coasts){
      if(poly.length<8)continue;
      ctx.beginPath();let visible=0,open=false;
      for(let j=0;j<poly.length;j+=4){
        const p=project(poly[j],poly[j+1]);
        if(p[2]<.015){open=false;continue;}
        if(!open){ctx.moveTo(p[0],p[1]);open=true;}else ctx.lineTo(p[0],p[1]);
        visible++;
      }
      if(visible>1)ctx.stroke();
    }
    ctx.restore();
    const pal={LONG:'#52dbac',WATCH:'#ffbd55',NEUTRAL:'#a4afbd',SHORT:'#ff777c',EXCLUDED:'#738293',unverified:'#75899a'};
    for(const c of companies){
      if(!Number.isFinite(c.lat)||!Number.isFinite(c.lon))continue;
      const p=project(c.lon,c.lat);if(p[2]<0)continue;
      const signal=String(c.activeSignal||c.signal||'NEUTRAL').split(' ')[0];
      const color=pal[signal]||pal.NEUTRAL;
      ctx.fillStyle=color;ctx.shadowColor=color;ctx.shadowBlur=7;
      ctx.beginPath();ctx.arc(p[0],p[1],Math.max(2.5,w*.004),0,2*Math.PI);ctx.fill();
      ctx.shadowBlur=0;ctx.lineWidth=1.25;ctx.strokeStyle='#071219';ctx.stroke();
    }
    ctx.strokeStyle='#81b7c455';ctx.lineWidth=1.3;ctx.beginPath();ctx.arc(cx,cy,radius,0,2*Math.PI);ctx.stroke();
  }

  function startFallbackAnimation(view) {
    let previous=0;
    const frame=now=>{
      if(!view.canvas.isConnected)return;
      if(!document.hidden&&(now-previous>38||!previous)){
        previous=now;drawFallback(view,now);
      }
      requestAnimationFrame(frame);
    };
    requestAnimationFrame(frame);
  }

  async function renderFallback() {
    if(runtime||fallback)return;
    const warn=document.getElementById('warn'),stage=document.getElementById('stage');
    if(!warn||!stage)return;
    let companies=[];
    try{const response=await fetch('data.json',{cache:'no-store'});if(response.ok)companies=(await response.json()).companies||[];}catch(_e){}
    const el=document.createElement('div');el.className='globe-2d-fallback';
    el.innerHTML='<div class="fallback-heading">EARTH / LIVE SOLAR POSITION <span class="fallback-status">CURRENT COMPANY LOCATIONS</span></div><canvas class="fallback-earth" role="img" aria-label="Rotating orthographic globe with actual coastlines, solar day-night shading and Nordic company headquarters"></canvas><div class="fallback-footer">Canvas mode · drag to rotate · scroll to zoom · UTC solar terminator · published company headquarters. 3D hardware graphics unavailable.</div>';
    warn.style.display='none';stage.append(el);fallback=el;
    const canvas=el.querySelector('canvas'),ctx=canvas.getContext('2d',{alpha:true});
    const shade=document.createElement('canvas');shade.width=shade.height=240;
    const shadeCtx=shade.getContext('2d');
    if(!ctx||!shadeCtx)return;
    const coasts=typeof GEO!=='undefined'&&Array.isArray(GEO.land)?GEO.land:[];
    const view={canvas,ctx,shade,shadeCtx,companies,coasts,lon:17,lat:59,zoom:1,started:performance.now(),lastShadow:-1,reducedMotion:matchMedia('(prefers-reduced-motion: reduce)').matches};
    const resize=()=>{const r=canvas.getBoundingClientRect(),dpr=Math.min(1.5,window.devicePixelRatio||1);canvas.width=Math.max(1,Math.round(r.width*dpr));canvas.height=Math.max(1,Math.round(r.height*dpr));};
    resize();new ResizeObserver(resize).observe(canvas);
    let dragging=false,lastX=0,lastY=0;
    canvas.addEventListener('pointerdown',e=>{dragging=true;lastX=e.clientX;lastY=e.clientY;canvas.setPointerCapture(e.pointerId);});
    canvas.addEventListener('pointermove',e=>{if(!dragging)return;view.lon-=(e.clientX-lastX)*.32;view.lat=Math.max(-80,Math.min(80,view.lat+(e.clientY-lastY)*.25));lastX=e.clientX;lastY=e.clientY;view.lastShadow=-1;});
    canvas.addEventListener('pointerup',()=>{dragging=false;});
    canvas.addEventListener('pointercancel',()=>{dragging=false;});
    canvas.addEventListener('wheel',e=>{e.preventDefault();view.zoom=Math.min(1.5,Math.max(.67,view.zoom*(e.deltaY>0?.94:1.06)));},{passive:false});
    fallbackView=view;startFallbackAnimation(view);
    updateFallback({date:currentDate,mode,companies:null});
  }

  // The astronomy routine can also be unit-tested without a browser or GPU.
  if(typeof window==='undefined'){
    if(typeof module==='object'&&module.exports)module.exports={solarDirection};
    return;
  }
  window.addEventListener('message',event=>{
    if(event.origin!==location.origin || event.source!==window.parent)return;
    if(event.data?.type==='KC_GLOBE_TIME')setSnapshot(event.data);
  });
  document.addEventListener('DOMContentLoaded',()=>{
    const warn=document.getElementById('warn');if(!warn)return;
    const observer=new MutationObserver(()=>{if(warn.style.display==='flex'){
      observer.disconnect();renderFallback();
    }});
    observer.observe(warn,{attributes:true,attributeFilter:['style']});
    if(warn.style.display==='flex'){observer.disconnect();renderFallback();}
  });
  window.addEventListener('load',()=>{
    if(window.parent!==window)window.parent.postMessage({type:'KC_GLOBE_READY'},location.origin);
  });
  window.KCSolar=Object.freeze({attach,tick,solarDirection});
  if(typeof module==='object'&&module.exports)module.exports={solarDirection};
})();
