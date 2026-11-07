/* Kaatopaikka Solar Globe: real UTC Sun geometry, quiet GPU shader overlay,
   optional audited event effects, and accessible non-WebGL fallback.
   No dependency beyond THREE r128 already used by classic.html. */
(function () {
  'use strict';
  const DAY=86400000, RAD=Math.PI/180;
  let runtime=null, fallback=null, pendingPacket=null, currentDate=new Date().toISOString().slice(0,10);
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
    fallback.querySelectorAll('[data-company]').forEach(el=>{
      const c=map?.get(el.dataset.company);
      const sig=mode==='unverified'?'unverified':c?.signal||el.dataset.originalSignal;
      const pal={LONG:'#52dbac',WATCH:'#ffbd55',NEUTRAL:'#a4afbd',SHORT:'#ff777c',EXCLUDED:'#738293',unverified:'#75899a'};
      el.setAttribute('fill',pal[String(sig).split(' ')[0]]||pal.NEUTRAL);
    });
    if(packet.event){fallback.classList.remove('impact');void fallback.offsetWidth;fallback.classList.add('impact');}
  }

  async function renderFallback() {
    if(runtime||fallback)return;
    const warn=document.getElementById('warn'),stage=document.getElementById('stage');
    if(!warn||!stage)return;
    let companies=[];
    try{const response=await fetch('data.json',{cache:'no-store'});if(response.ok)companies=(await response.json()).companies||[];}catch(_e){}
    const el=document.createElement('div');el.className='globe-2d-fallback';
    const clean=text=>String(text??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const W=710,H=455,x=lon=>66+(lon-5)/31*580,y=lat=>40+(72-lat)/19*375;
    const grid=[55,60,65,70].map(lat=>`<line x1="54" y1="${y(lat)}" x2="668" y2="${y(lat)}" stroke="#314251" stroke-dasharray="3 9"/><text x="12" y="${y(lat)+4}" fill="#7c98ab" font-size="10">${lat}°N</text>`).join('');
    const circles=companies.map(c=>{
      if(!Number.isFinite(c.lat)||!Number.isFinite(c.lon))return '';
      const sig=String(c.signal||'NEUTRAL').split(' ')[0];
      const pal={LONG:'#52dbac',WATCH:'#ffbd55',NEUTRAL:'#a4afbd',SHORT:'#ff777c',EXCLUDED:'#738293'};
      return `<circle data-company="${clean(c.id)}" data-original-signal="${clean(sig)}" cx="${x(c.lon).toFixed(1)}" cy="${y(c.lat).toFixed(1)}" r="5" fill="${pal[sig]||pal.NEUTRAL}" stroke="#0b1118" stroke-width="2"><title>${clean(c.name)} · ${clean(c.city)} · ${clean(sig)}</title></circle>`;
    }).join('');
    el.innerHTML=`<div class="fallback-heading">NORDIC LOCATION GRID <span class="fallback-status">CURRENT COMPANY LOCATIONS</span></div><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Two-dimensional latitude-longitude map of Nordic corporate headquarters">${grid}<text x="190" y="70" fill="#46586a" font-size="13" letter-spacing="3">NORWAY</text><text x="353" y="92" fill="#46586a" font-size="13" letter-spacing="3">SWEDEN</text><text x="516" y="110" fill="#46586a" font-size="13" letter-spacing="3">FINLAND</text><text x="173" y="393" fill="#46586a" font-size="13" letter-spacing="3">DENMARK</text>${circles}</svg><div class="fallback-footer">3D rendering is unavailable in this browser. This chart uses the published HQ coordinates. It is a location grid, not a geographic boundary map.</div>`;
    warn.style.display='none';stage.append(el);fallback=el;
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
