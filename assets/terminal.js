/* Kaatopaikka Capital Investment Terminal
   Static GitHub Pages frontend. The daily Python model is the source of truth.
   No browser-side model outputs are written back to the portfolio. */
(() => {
  'use strict';
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const pct = (n, digits = 1, sign = false) => Number.isFinite(Number(n)) && n !== null ? `${sign && n > 0 ? '+' : ''}${(n * 100).toFixed(digits)}%` : '—';
  const pp = (n, digits = 1) => Number.isFinite(Number(n)) && n !== null ? `${n > 0 ? '+' : ''}${(n * 100).toFixed(digits)} pp` : '—';
  const eur = n => Number.isFinite(Number(n)) && n !== null ? new Intl.NumberFormat('en-IE',{style:'currency',currency:'EUR',maximumFractionDigits:0}).format(n) : '—';
  const dec = (n, digits = 2) => Number.isFinite(Number(n)) && n !== null ? Number(n).toFixed(digits) : '—';
  const fmtDate = value => { const d = new Date(value && value.length === 10 ? `${value}T12:00:00Z` : value); return Number.isNaN(d.getTime()) ? String(value || 'Unknown') : d.toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric',timeZone:'UTC'}); };
  const shortDate = value => {const d=new Date(`${value}T12:00:00Z`);return Number.isNaN(d.getTime())?value:d.toLocaleDateString('en-GB',{day:'numeric',month:'short',timeZone:'UTC'});};
  const clamp = (n,min,max)=>Math.max(min,Math.min(max,n));
  const signal = s => /^(LONG|WATCH|NEUTRAL|SHORT|EXCLUDED)/.exec(s || '')?.[1] || 'NEUTRAL';
  const tag = s => {const k=signal(s);return `<span class="tag tag-${k.toLowerCase()}">${k === 'SHORT' ? 'AVOID' : k}</span>`;};
  const colorOf = s => ({LONG:'#4bd6a7',WATCH:'#ffbd54',NEUTRAL:'#95a2b6',SHORT:'#ff777c',EXCLUDED:'#747e8b'})[signal(s)];
  const signedClass = v => v > 0 ? 'positive' : v < 0 ? 'negative' : '';
  const pageNames = {overview:'OVERVIEW',research:'RESEARCH',portfolio:'PORTFOLIO',decisions:'DECISION JOURNAL',lab:'VALUATION LAB',globe:'NORDIC GLOBE',methodology:'METHODOLOGY',backtest:'2024 STRATEGY REPLAY'};
  const state = {data:null,port:null,sim:null,history:null,sort:'rank',desc:false,lab:null,opened:null,lastFocus:null,
    replayDay:null,playRaf:null,playDayFloat:null,playLastFrame:null};
  const find = id => state.data?.companies.find(c=>c.id === id);

  const stat = (label,value,note,klass='')=>`<div class="stat"><div class="stat-label">${esc(label)}</div><div class="stat-value ${klass}">${esc(value)}</div><div class="stat-note">${esc(note)}</div></div>`;
  function dates() { const today=new Date();$('#top-date').textContent=today.toLocaleDateString('en-GB',{weekday:'short',day:'numeric',month:'short',year:'numeric'}).toUpperCase(); }
  function navigate(page, updateHash=true) {
    if(!pageNames[page])page='overview';
    $$('.page').forEach(el=>el.classList.toggle('is-active',el.id===`page-${page}`));
    $$('.nav-item').forEach(b=>b.classList.toggle('is-active',b.dataset.page===page));
    $('#breadcrumb-name').textContent=pageNames[page];
    if(page==='globe') { const f=$('#classic-frame'); if(!f.src && f.dataset.src) f.src=f.dataset.src; }
    if(page!=='overview')stopTime();
    $('#sidebar').classList.remove('is-open');$('#menu-toggle').setAttribute('aria-expanded','false');
    if(updateHash && location.hash!==`#${page}`)history.replaceState(null,'',`#${page}`);
    window.scrollTo({top:0,behavior:'instant'});
  }
  function openCompany(c) {
    if(!c)return;
    state.lastFocus=document.activeElement;
    state.opened=c.id;
    $('#drawer-content').innerHTML=renderMemo(c);
    $('#company-drawer').hidden=false;$('#drawer-backdrop').hidden=false;
    document.body.style.overflow='hidden';$('#drawer-close').focus();
    $$('[data-open]',$('#drawer-content')).forEach(b=>b.addEventListener('click',()=>openCompany(find(b.dataset.open))));
    $('#drawer-lab')?.addEventListener('click',()=>{closeDrawer();navigate('lab');$('#lab-company').value=c.id;resetLab(c);});
    $('#drawer-copy')?.addEventListener('click',async()=>{
      const url=`${location.origin}${location.pathname}#company/${encodeURIComponent(c.id)}`;
      try {await navigator.clipboard.writeText(url);$('#drawer-copy').textContent='Copied ✓';}
      catch {_download('kaatopaikka-link.txt',url,'text/plain');}
    });
    history.replaceState(null,'',`#company/${encodeURIComponent(c.id)}`);
  }
  function closeDrawer() {
    $('#company-drawer').hidden=true;$('#drawer-backdrop').hidden=true;document.body.style.overflow='';state.opened=null;
    if(location.hash.startsWith('#company/'))history.replaceState(null,'','#research');
    state.lastFocus?.focus?.();
  }
  function _download(name,text,type) { const blob=new Blob([text],{type});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000); }
  function getHeld(c) { return (state.port?.holdings || []).find(h=>h.id===c.id); }
  function getTarget(c) { return (state.port?.targets || []).find(h=>h.id===c.id); }
  function modelRationale(c) {
    const held=getHeld(c),target=getTarget(c),gap=c.norm-c.cur;
    const reasons=[],risks=[];
    if(gap>0.0005)reasons.push(`Operating margin ${pct(c.cur)} is below the model's ${pct(c.norm)} normalized estimate (${pp(gap)} gap).`);
    else if(gap<-.0005)risks.push(`Operating margin ${pct(c.cur)} is above its ${pct(c.norm)} normalized estimate; mean reversion could reduce earnings.`);
    else reasons.push('Current profitability is close to the model’s normalized estimate.');
    if(c.revUp>0)reasons.push(`The model estimates ${pct(c.revUp,0,true)} margin-reversion upside against its status-quo valuation scenario.`);
    else risks.push(`The margin-reversion scenario is ${pct(c.revUp,0,true)} relative to the status-quo valuation.`);
    if(c.trap==='YES'||signal(c.signal)==='WATCH')risks.push('The value-trap screen flags a depressed, deteriorating margin trend; it does not establish that recovery is underway.');
    if(c.flag==='Y')risks.push('The data is marked for a structural break or comparability issue.');
    if(c.nObs<8)risks.push(`Only ${c.nObs} years enter the current normalization window; estimates may be unstable.`);
    let decision='';
    if(held)decision=`HELD — ${pct(held.weight)} of the paper portfolio. The position reflects the model's latest eligible ranking and sizing rules.`;
    else if(target)decision=`CURRENT TARGET — ${pct(target.weight)} model weight; the holding may differ until the next monthly rebalance.`;
    else if(signal(c.signal)==='EXCLUDED')decision='NOT ELIGIBLE — data quality or observation requirements are not met.';
    else if(signal(c.signal)==='SHORT')decision='NOT SELECTED — the composite score is in the bottom quintile (AVOID). This is not an actual short position.';
    else if(c.revUp<=0)decision='NOT SELECTED — the model requires positive margin-reversion upside for a portfolio candidate.';
    else decision='NOT SELECTED — the current strategy has only five slots, filled using composite rank and its position-sizing rules.';
    return {reasons,risks,decision};
  }

  function svgLine(series, labels, opts={}) {
    const W=760,H=260,pad={l:55,r:19,t:19,b:43};
    const n=Math.max(...series.map(s=>s.values.length),2);
    const vals=series.flatMap(s=>s.values).filter(Number.isFinite);
    if(!vals.length)return `<div class="empty-chart"><strong>No chart data available</strong><span>Historical points will appear after updates.</span></div>`;
    let min=opts.min??Math.min(...vals), max=opts.max??Math.max(...vals);
    if(min===max){min-=Math.max(1,Math.abs(min)*.05);max+=Math.max(1,Math.abs(max)*.05);}
    const range=max-min;min-=range*.11;max+=range*.11;
    const X=i=>pad.l+i*(W-pad.l-pad.r)/(n-1),Y=v=>pad.t+(max-v)/(max-min)*(H-pad.t-pad.b);
    let out=`<svg class="chart-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(opts.label||'Time series chart')}">`;
    for(let j=0;j<5;j++){const y=pad.t+j*(H-pad.t-pad.b)/4,v=max-j*(max-min)/4;out+=`<line x1="${pad.l}" x2="${W-pad.r}" y1="${y}" y2="${y}" stroke="#29313e" stroke-dasharray="3 5"/><text x="${pad.l-11}" y="${y+4}" fill="#8e98aa" font-family="IBM Plex Mono" font-size="10" text-anchor="end">${opts.money?`€${(v/1000).toFixed(1)}k`:v.toFixed(opts.digits??1)+(opts.suffix||'')}</text>`;}
    series.forEach((s,idx)=>{
      let started=false;
      const path=s.values.map((v,i)=>{
        if(!Number.isFinite(v)){started=false;return '';}
        const command=started?'L':'M';started=true;
        return `${command}${X(i).toFixed(1)} ${Y(v).toFixed(1)}`;
      }).join(' ');
      out+=`<path d="${path}" fill="none" stroke="${s.color||['#ffad32','#4bd6a7'][idx%2]}" stroke-width="${idx?2:3}" stroke-linejoin="round" stroke-linecap="round" ${s.dash?'stroke-dasharray="5 6"':''}/>`;
      const last=s.values.at(-1);if(Number.isFinite(last))out+=`<circle cx="${X(s.values.length-1)}" cy="${Y(last)}" r="4" stroke="#10151d" stroke-width="2" fill="${s.color||'#ffad32'}"/>`;
    });
    const indices=[...new Set([0,Math.floor((n-1)/2),n-1])];indices.forEach(i=>{out+=`<text x="${X(i)}" y="${H-12}" fill="#8e98aa" font-family="IBM Plex Mono" font-size="10" text-anchor="middle">${esc(labels[i]||'')}</text>`;});
    return out+'</svg>'+`<div class="chart-legend">${series.map(s=>`<span><i class="legend-line" style="background:${s.color}"></i>${esc(s.name)}</span>`).join('')}</div>`;
  }

  function renderOverview() {
    const D=state.data,M=D.meta,P=state.port,companies=D.companies,positions=P?.holdings||[];
    const candidates=companies.filter(c=>c.revUp>0&& !['SHORT','EXCLUDED'].includes(signal(c.signal)));
    const value=P?.value??10000,ret=P?P.value/P.start_capital-1:0,bench=P?P.bench_value/P.start_capital-1:0;
    $('#overview-stats').classList.remove('skeleton-grid');
    $('#overview-stats').innerHTML=[
      stat('Portfolio value',eur(value),P?.status==='live'?`Since ${fmtDate(P.inception)}`:'Awaiting paper trading'),
      stat('Net return',pct(ret,2,true),`Benchmark ${pct(bench,2,true)}`,signedClass(ret)),
      stat('Covered companies',String(companies.length),'Sweden · Finland · Norway · Denmark'),
      stat('Positive-upside candidates',String(candidates.length),'Eligible under model screening')
    ].join('');
    $('#overview-portfolio').innerHTML=`<div><div class="big-number">${eur(value)}</div><div class="number-caption">Starting capital ${eur(P?.start_capital||10000)} · simulated portfolio</div></div><div class="performance-badge ${ret<0?'loss':''}">${pct(ret,2,true)} TOTAL RETURN</div>`;
    const hist=P?.history||[];
    $('#overview-chart').innerHTML=hist.length>1?svgLine([{name:'Kaatopaikka',values:hist.map(h=>h.value),color:'#ffad32'},{name:'Equal-weight 30',values:hist.map(h=>h.bench),color:'#7c9ab6',dash:true}],hist.map(h=>shortDate(h.date)),{money:true,label:'Paper portfolio value vs equal-weight universe'}):`<div class="empty-chart"><strong>Track record just started</strong><span>The performance chart appears after the second daily observation.<br>Current value includes estimated execution costs.</span></div>`;
    $('#overview-picks').innerHTML=companies.filter(c=>!['SHORT','EXCLUDED'].includes(signal(c.signal))).sort((a,b)=>a.rank-b.rank).slice(0,5).map(c=>`<button class="opportunity-row" data-open="${esc(c.id)}"><span class="rank-index">${String(c.rank).padStart(2,'0')}</span><span class="company-main">${esc(c.name)}<small>${esc(c.group)} · ${esc(c.country)}</small></span><span class="opportunity-numbers"><strong class="${signedClass(c.revUp)}">${pct(c.revUp,0,true)}</strong><small>${signal(c.signal)==='WATCH'?'WATCH / CAUTION':signal(c.signal)}</small></span></button>`).join('');
    const chosen=positions.length?find(positions[0].id):companies.find(c=>c.rank===1);
    const memo=chosen?modelRationale(chosen):null;
    $('#overview-thesis').innerHTML=chosen?`<div class="thesis-summary"><div class="thesis-name"><span>${esc(chosen.name)}</span>${tag(chosen.signal)}</div><p>${esc(memo.reasons[0]||memo.risks[0]||'A model-selected company.')}</p><p><strong class="warning-text">Key caveat:</strong> ${esc(memo.risks[0]||'Expected margin normalization is uncertain and may already be priced in.')}</p><button class="text-link" data-open="${esc(chosen.id)}">Read the full model memo ↗</button></div>`:'<div class="subtle-note">No candidates available.</div>';
    const labels=['LONG','WATCH','NEUTRAL','SHORT','EXCLUDED'],counts=Object.fromEntries(labels.map(x=>[x,companies.filter(c=>signal(c.signal)===x).length]));
    $('#overview-signals').innerHTML=`<div class="signal-bar">${labels.map(k=>`<span title="${k}" style="width:${counts[k]/companies.length*100}%;background:${colorOf(k)}"></span>`).join('')}</div><div class="signal-list">${labels.map(k=>`<div class="signal-item"><span class="swatch" style="background:${colorOf(k)}"></span>${k==='SHORT'?'AVOID':k}<b>${counts[k]}</b></div>`).join('')}</div>`;
    const oldest=[...companies].sort((a,b)=>a.priceDate.localeCompare(b.priceDate))[0];
    const flagged=companies.filter(c=>c.flag==='Y').length;
    const stale=companies.filter(c=>daysAgo(c.priceDate)>5).length;
    $('#overview-health').innerHTML=`<div class="health-list"><div class="health-item"><span class="health-icon">✓</span><span><strong>Last model update</strong><small>${esc(M.updated||'Not available')}</small></span></div><div class="health-item"><span class="health-icon ${stale?'warn':''}">${stale?'!':'✓'}</span><span><strong>${stale} potentially stale quote${stale===1?'':'s'}</strong><small>Price older than five calendar days</small></span></div><div class="health-item"><span class="health-icon ${flagged?'warn':''}">${flagged?'!':'✓'}</span><span><strong>${flagged} accounting data flag${flagged===1?'':'s'}</strong><small>Structural breaks require extra review</small></span></div><div class="health-item"><span class="health-icon">i</span><span><strong>Oldest quote: ${esc(oldest?.name||'—')}</strong><small>${esc(oldest?.priceDate||'')}</small></span></div></div>`;
  }
  function daysAgo(date) { const d=new Date(`${date}T23:59:59Z`);return Number.isNaN(d.getTime())?999:Math.max(0,Math.floor((Date.now()-d.getTime())/86400000)); }
  const TIMELINE_START=Date.UTC(2024,0,1);
  const DAY_MS=86400000;
  const isoForDay=n=>new Date(TIMELINE_START+n*DAY_MS).toISOString().slice(0,10);
  function lastReplaySnapshot(iso) {
    const snaps=state.history?.snapshots||[];
    for(let i=snaps.length-1;i>=0;i--)if(snaps[i].date<=iso)return snaps[i];
    return null;
  }
  function sendGlobeTime(iso,meteor=null,replayEvents=[]) {
    const current=iso>=state.data?.meta?.priceTo;
    const verified=state.history?.validated_inputs===true && Array.isArray(state.history.history);
    const snap=verified&&!current?lastReplaySnapshot(iso):null;
    const packet={type:'KC_GLOBE_TIME',date:iso,mode:current?'current':snap?'verified':'unverified',
      companies:current?null:snap?.companies||null,event:meteor,events:replayEvents};
    // Home canvas is the primary renderer: it remains visible even when
    // third-party Three.js or WebGL are unavailable.
    window.KCHomeEarth?.setSnapshot(packet);
    const frame=$('#home-frame'); // optional legacy iframe, not required
    if(frame?.contentWindow)frame.contentWindow.postMessage(packet,location.origin);
  }
  function setTimelineDay(day,opts={}) {
    const slider=$('#time-date-range');if(!slider)return;
    const max=Number(slider.max);
    day=clamp(Math.round(day),0,max);slider.value=day;
    const iso=isoForDay(day),prev=state.replayDay;
    if(iso===prev&&opts.playing)return; // Avoid expensive DOM/plot updates every animation frame.
    state.replayDay=iso;
    $('#time-date-label').textContent=fmtDate(iso);
    const current=iso>=state.data?.meta?.priceTo;
    const verified=state.history?.validated_inputs===true && Array.isArray(state.history.history);
    const snap=verified&&!current?lastReplaySnapshot(iso):null;
    const status=$('#planet-data-state'),mode=$('#time-mode');
    status.classList.toggle('verified',Boolean(current||snap));
    status.textContent=current?'● CURRENT MODEL SNAPSHOT':snap?'● SOURCE-DATED REPLAY':'● HISTORICAL DATA AWAITED';
    mode.textContent=current?'LATEST MARKET DATA':snap?'BACKTEST / FIXED UNIVERSE':'SOLAR GEOMETRY ONLY';
    const title=$('#time-summary-title'),detail=$('#time-summary');
    if(current){
      title.textContent='Latest published model snapshot';
      detail.textContent=`Company locations and signals as of ${state.data.meta.priceTo}. The live paper portfolio began in 2026, not in 2024.`;
    }else if(snap){
      const points=state.history.history.filter(x=>x.date<=iso);
      const last=points.at(-1);
      title.textContent=last?`${eur(last.nav)} · ${pct(last.return,1,true)} since 2024`:'Backtest has not traded yet';
      detail.textContent=`Monthly positions based on reports public before ${snap.signal_asof}. Retrospective fixed universe: survivorship bias remains.`;
    }else{
      title.textContent='Historical equity results not verified';
      detail.textContent='The original Q1–Q4 publication dates and complete prices are not yet provided. No future report values or invented backtest returns are displayed.';
    }
    const activeEvents=verified?(state.history.events||[]).filter(e=>Math.abs((Date.parse(e.date+'T00:00:00Z')-Date.parse(iso+'T00:00:00Z'))/DAY_MS)<=7):[];
    $('#time-events').innerHTML=activeEvents.length?activeEvents.slice(-2).map(e=>`<div class="time-event"><span class="meteor-symbol">☄</span><span>${esc(e.date)} · ${esc(e.description)} (${pct(e.severity,1)})</span></div>`).join(''):'<span>No verified adverse event near this date.</span>';
    let meteor=null;
    if(opts.playing&&verified&&prev&&iso>prev){
      meteor=(state.history.events||[]).find(e=>e.date>prev&&e.date<=iso&&e.type==='observed_drawdown')||null;
    }
    // Highlight only events actually present in the audited historical file.
    // Trades/earnings are never inferred from the latest (2026) snapshot.
    const replayEvents=opts.playing&&verified&&prev&&iso>prev
      ?(state.history.events||[]).filter(e=>e.date>prev&&e.date<=iso).slice(-10):[];
    sendGlobeTime(iso,meteor,replayEvents);
    window.dispatchEvent(new CustomEvent('kc:timeline',{detail:{iso,playing:Boolean(opts.playing),from:prev,
      events:replayEvents}}));
  }
  function stopTime(){
    if(state.playRaf!==null)cancelAnimationFrame(state.playRaf);
    state.playRaf=null;state.playLastFrame=null;
    const btn=$('#time-play');if(btn){btn.textContent='▶ Play 2024 → today';btn.setAttribute('aria-pressed','false');}
  }
  function playTime(now){
    if(state.playRaf===null)return;
    const dt=state.playLastFrame===null?0:Math.min((now-state.playLastFrame)/1000,.2);
    state.playLastFrame=now;
    state.playDayFloat+=dt*clamp(Number($('#replay-speed')?.value)||14,1,70); // Playback clock; real market facts require source-dated inputs.
    const max=Number($('#time-date-range').max);
    setTimelineDay(state.playDayFloat,{playing:true});
    if(state.playDayFloat>=max){stopTime();return;}
    state.playRaf=requestAnimationFrame(playTime);
  }
  function setupTimeMachine(){
    const range=$('#time-date-range');
    const max=Math.max(0,Math.floor((Date.now()-TIMELINE_START)/DAY_MS));
    range.max=max;range.value=max;
    $('#time-end-date').textContent=isoForDay(max).slice(0,7).replace('-',' / ');
    range.addEventListener('input',()=>{stopTime();setTimelineDay(Number(range.value));});
    $('#time-today').addEventListener('click',()=>{stopTime();setTimelineDay(max);});
    $('#time-play').addEventListener('click',()=>{
      if(state.playRaf!==null){stopTime();return;}
      if(Number(range.value)>=max-1)setTimelineDay(0);
      state.playDayFloat=Number(range.value);state.playLastFrame=null;state.playRaf=requestAnimationFrame(playTime);
      $('#time-play').textContent='Ⅱ Pause replay';$('#time-play').setAttribute('aria-pressed','true');
    });
    $('#home-frame')?.addEventListener('load',()=>{if(state.replayDay)sendGlobeTime(state.replayDay);});
    window.addEventListener('message',event=>{
      if(event.origin===location.origin&&event.source===$('#home-frame')?.contentWindow&&event.data?.type==='KC_GLOBE_READY'){
        if(state.replayDay)sendGlobeTime(state.replayDay);
      }
    });
    setTimelineDay(max);
  }
  function renderResearch() {
    const query=$('#research-query').value.trim().toLowerCase(),country=$('#research-country').value,sig=$('#research-signal').value;
    let rows=state.data.companies.filter(c=>(country==='all'||c.country===country)&&(sig==='all'||signal(c.signal)===sig)&&(`${c.name} ${c.ticker} ${c.group} ${c.country}`.toLowerCase().includes(query)));
    const col=state.sort;rows.sort((a,b)=>{let av=a[col],bv=b[col];if(!Number.isFinite(av))av=-Infinity;if(!Number.isFinite(bv))bv=-Infinity;return (state.desc?-1:1)*(av-bv);});
    $('#research-count').textContent=`${rows.length} / ${state.data.companies.length} COMPANIES`;
    $('#research-rows').innerHTML=rows.map(c=>`<tr><td class="mono">${c.rank}</td><td class="name-cell">${esc(c.name)}<small>${esc(c.ticker)} · ${esc(c.group)}</small></td><td>${esc(c.country)}</td><td>${tag(c.signal)}</td><td class="mono ${signedClass(c.revUp)}">${pct(c.revUp,1,true)}</td><td class="mono ${signedClass(c.gap)}">${pp(c.gap)}</td><td class="mono">${dec(c.score)}</td><td><button class="table-link" data-open="${esc(c.id)}">Analyze ↗</button></td></tr>`).join('')||'<tr><td colspan="8">No companies match your filters.</td></tr>';
    $('#research-bottom').textContent=`Prices from ${state.data.meta.priceFrom} to ${state.data.meta.priceTo}. Scores are relative within the current 30-stock universe; not investment advice.`;
  }
  function renderPortfolio() {
    const P=state.port,hold=P?.holdings||[],D=state.data;
    if(!P){$('#portfolio-stats').innerHTML=stat('Portfolio','Unavailable','No portfolio.json loaded');return;}
    const ret=P.value/P.start_capital-1,br=P.bench_value/P.start_capital-1;
    $('#portfolio-stats').innerHTML=[stat('Net asset value',eur(P.value),`Started ${fmtDate(P.inception)}`),stat('Total return',pct(ret,2,true),'Excluding dividends',signedClass(ret)),stat('Relative to benchmark',pp(ret-br,2),'Equal-weight universe',signedClass(ret-br)),stat('Trading costs',eur(P.costs_paid||0),`${hold.length} positions · ${P.history.length} observations`)].join('');
    $('#portfolio-history').innerHTML=P.history.length>1?svgLine([{name:'Strategy',values:P.history.map(h=>h.value),color:'#ffad32'},{name:'Equal-weight universe',values:P.history.map(h=>h.bench),color:'#7c9ab6',dash:true}],P.history.map(h=>shortDate(h.date)),{money:true,label:'Portfolio performance history'}):'<div class="empty-chart"><strong>More observations required</strong><span>A performance chart cannot be inferred from one trading day.</span></div>';
    const country={};const sector={};hold.forEach(h=>{const c=find(h.id);if(!c)return;country[c.country]=(country[c.country]||0)+h.weight;sector[c.group]=(sector[c.group]||0)+h.weight;});
    const exposure=(title,map)=>`<div class="exposure-section"><div class="eyebrow" style="margin-bottom:14px">${title}</div>${Object.entries(map).sort((a,b)=>b[1]-a[1]).map(([k,w])=>`<div style="margin-bottom:12px"><div class="exposure-top"><span>${esc(k)}</span><span>${pct(w)}</span></div><div class="exposure-bar"><i style="width:${clamp(w*100,0,100)}%"></i></div></div>`).join('')}</div>`;
    $('#portfolio-exposure').innerHTML=`<div class="exposure">${exposure('BY COUNTRY',country)}${exposure('BY SECTOR',sector)}<div class="exposure-hint">Concentration is based on portfolio weights, not a covariance or factor-risk model. Five holdings can have correlated exposures despite operating in different industries.</div></div>`;
    $('#portfolio-holdings').innerHTML=hold.map(h=>{const c=find(h.id),note=c?modelRationale(c).reasons[0]||'Model-selected':'Model position';return `<tr><td class="name-cell">${esc(h.name)}<small>${esc(c?.ticker||'')}</small></td><td>${tag(h.signal||c?.signal)}</td><td class="mono">${pct(h.weight)}</td><td class="mono">${eur(h.value)}</td><td class="mono ${signedClass(h.ret)}">${pct(h.ret,1,true)}</td><td><button class="table-link" data-open="${esc(h.id)}">See memo ↗</button></td></tr>`;}).join('')||'<tr><td colspan="6">No simulated holdings yet.</td></tr>';
  }
  function renderDecisions() {
    const P=state.port,decisions=P?.decisions||[];
    $('#journal-feed').innerHTML=decisions.slice().reverse().map(d=>`<div class="journal-entry"><span class="journal-date">DECISION #${esc(d.n)} · ${fmtDate(d.date)}</span><h3>${esc(d.type==='initial buy'?'Initial portfolio construction':'Monthly model rebalance')}</h3>${(d.orders||[]).map(o=>`<div class="journal-action"><div><strong>${esc(o.name)}</strong><small>${esc(o.reason||'Executed under the systematic weighting and rebalance rules; individual rationale not stored for this historical decision.')}</small></div><div style="text-align:right"><span class="tag ${o.side==='SELL'?'tag-short':'tag-long'}">${o.side==='SELL'?'SELL':'BUY'}</span><span class="mono" style="display:block;margin-top:5px">${eur(o.eur)}</span></div></div>`).join('')||'<p class="small-text">No trades recorded at this rebalance.</p>'}</div>`).join('')||'<div class="subtle-note">Decisions are created by the daily model after trading starts.</div>';
    const notHeld=state.data.companies.filter(c=>!getHeld(c)).sort((a,b)=>a.rank-b.rank);
    $('#journal-rejected').innerHTML=notHeld.map(c=>{const explanation=modelRationale(c).decision;return `<button class="rejected-row" data-open="${esc(c.id)}"><span><strong>${esc(c.name)}</strong><small>${esc(explanation)}</small></span>${tag(c.signal)}</button>`;}).join('');
  }
  function renderMemo(c) {
    const memo=modelRationale(c),held=getHeld(c),target=getTarget(c);
    const date=c.priceDate||state.data.meta.priceTo;
    const years=state.data.meta.years||[];
    const margins=(c.margins||[]).map(v=>v===null?NaN:v*100);
    const chart=svgLine([{name:'Reported EBIT margin',values:margins,color:'#ffad32'},{name:'Current normalized estimate',values:margins.map(()=>c.norm*100),color:'#4bd6a7',dash:true}],years.map(String),{label:`${c.name} operating margin history`,suffix:'%',digits:1});
    return `<div class="drawer-body"><div class="eyebrow">RANK ${c.rank} / ${state.data.companies.length} · ${esc(c.group).toUpperCase()}</div><h2 class="drawer-title" id="drawer-title">${esc(c.name)}</h2><div class="drawer-subtitle">${tag(c.signal)}<span>${esc(c.ticker)} · ${esc(c.country)}</span><span>Quote ${fmtDate(date)}</span></div><div class="drawer-stats"><div class="drawer-metric"><small>REVERSION UPSIDE</small><strong class="${signedClass(c.revUp)}">${pct(c.revUp,1,true)}</strong></div><div class="drawer-metric"><small>NORMAL MARGIN</small><strong>${pct(c.norm)}</strong></div><div class="drawer-metric"><small>COMPOSITE SCORE</small><strong>${dec(c.score)}</strong></div><div class="drawer-metric"><small>CURRENT MARGIN</small><strong>${pct(c.cur)}</strong></div><div class="drawer-metric"><small>MARGIN GAP</small><strong class="${signedClass(c.gap)}">${pp(c.gap)}</strong></div><div class="drawer-metric"><small>EV / NORM. EBIT</small><strong>${dec(c.evNorm,1)}×</strong></div></div><div class="drawer-section"><h3>Investment decision</h3><div class="memo-callout">${esc(memo.decision)}</div>${held?`<p style="margin-top:14px">Current paper position: ${pct(held.weight)} · ${eur(held.value)} · return ${pct(held.ret,1,true)} excluding dividends.</p>`:target?`<p>Target allocation: ${pct(target.weight)}</p>`:''}</div><div class="drawer-section"><h3>Why the model is interested</h3><div class="memo-list">${memo.reasons.map(r=>`<div class="memo-item"><i>✓</i><span>${esc(r)}</span></div>`).join('')||'<p>No positive model factors at the selected thresholds.</p>'}</div></div><div class="drawer-section"><h3>Risks and alternative explanations</h3><div class="memo-list">${(memo.risks.length?memo.risks:['A depressed margin can reflect permanent competitive deterioration; recovering profitability is not assured.']).map(r=>`<div class="memo-item risk"><i>!</i><span>${esc(r)}</span></div>`).join('')}<div class="memo-item risk"><i>!</i><span>Stock returns depend on future expectations and valuation, not margin recovery alone.</span></div></div></div><div class="drawer-section"><h3>Historical operating margin</h3>${chart}</div><div class="drawer-section"><h3>What would change our view?</h3><p>Reassess when new reported margins materially shift the normalization estimate, when evidence points to a structural break, or when the price moves enough to change the valuation and rank. This is a testable monitoring rule, not a company-specific catalyst claim.</p>${c.note?`<div class="source-note">Data context: ${esc(c.note)}</div>`:''}<p class="small-text">Historical observations: ${c.nObs}; persistence φ = ${dec(c.phi)}; illustrative margin half-life ${dec(c.hl,1)} years. Market-cap figure: €${dec(c.mcapEur,1)}bn.</p></div><div class="drawer-section"><div class="drawer-actions"><button class="button button-primary" id="drawer-lab">Explore in margin lab ↗</button><button class="button button-ghost" id="drawer-copy">Copy research link ↗</button></div></div><div class="source-note">Auto-generated explanation from the currently published model fields. No AI-generated company claims, verified fundamental news, human investment committee approval or personalized investment advice is implied. Source financial statements are not refreshed with every price update.</div></div>`;
  }
  function renderLabOptions() {
    $('#lab-company').innerHTML=[...state.data.companies].sort((a,b)=>a.rank-b.rank).map(c=>`<option value="${esc(c.id)}">${esc(c.name)} · #${c.rank}</option>`).join('');
    resetLab(state.data.companies.find(c=>c.rank===1)||state.data.companies[0]);
  }
  function resetLab(c){
    if(!c)return;
    $('#lab-company').value=c.id;
    const v=c.valuation;
    state.lab={cur:c.cur*100,norm:c.norm*100,phi:c.phi,
      wacc:(v?.discountRate??c.disc??.09)*100,
      growth:(v?.growthExplicit??.03)*100,
      terminal:(v?.growthTerminal??.02)*100,
      ronic:(v?.ronic??.15)*100};
    drawLab();
  }
  function drawLab() {
    const c=find($('#lab-company').value),L=state.lab;if(!L||!c)return;
    const ids=['cur','norm','phi','wacc','growth','terminal','ronic'];
    for(const k of ids){
      const el=$(`#lab-${k}`);el.value=clamp(L[k],Number(el.min),Number(el.max));
      $(`#lab-${k}-out`).value=k==='phi'?L[k].toFixed(2):`${L[k].toFixed(2)}%`;
    }
    const years=Array.from({length:11},(_,i)=>`Y${i}`),path=years.map((_,t)=>L.norm+Math.pow(L.phi,t)*(L.cur-L.norm));
    $('#lab-result-title').textContent=`${c.name}: live DCF scenario`;
    $('#lab-chart').innerHTML=svgLine([{name:'Modeled operating margin',values:path,color:'#ffad32'},{name:'Normalized target',values:years.map(()=>L.norm),color:'#4bd6a7',dash:true}],years,{suffix:'%',digits:1,label:'Ten-year operating margin path'});
    $('#lab-table').innerHTML=`<div class="lab-table"><table><thead><tr>${years.filter((_,i)=>i%2===0).map(y=>`<th>${y}</th>`).join('')}</tr></thead><tbody><tr>${path.filter((_,i)=>i%2===0).map(v=>`<td>${v.toFixed(1)}%</td>`).join('')}</tr></tbody></table></div>`;
    const metric=(label,value,klass='')=>`<div class="lab-key-box"><small>${esc(label)}</small><strong class="${klass}">${esc(value)}</strong></div>`;
    const assumptions={currentMargin:L.cur/100,normalizedMargin:L.norm/100,persistence:L.phi,
      discountRate:L.wacc/100,growthExplicit:L.growth/100,growthTerminal:L.terminal/100,ronic:L.ronic/100};
    if(!c.valuation||!window.KCValuation){
      $('#lab-key-metrics').innerHTML=`<div class="lab-key">${metric('CURRENT MARGIN',`${L.cur.toFixed(1)}%`)}${metric('YEAR 5',`${path[5].toFixed(1)}%`)}${metric('NORMALIZED',`${L.norm.toFixed(1)}%`)}</div>`;
      $('#lab-validation').textContent='Awaiting a daily model refresh to publish revenue, capital structure and tax inputs. DCF outputs are withheld until their source data is available.';
      $('#lab-validation').className='lab-validation warn';
      $('#lab-sensitivity').innerHTML='<div class="sensitivity-note">The sensitivity grid will activate as soon as the model publishes the valuation inputs. No implied values are invented.</div>';
      return;
    }
    const result=window.KCValuation.calculate(c.valuation,assumptions);
    if(!result.valid){
      $('#lab-key-metrics').innerHTML=`<div class="lab-key">${metric('CURRENT MARGIN',`${L.cur.toFixed(1)}%`)}${metric('YEAR 5',`${path[5].toFixed(1)}%`)}${metric('NORMALIZED',`${L.norm.toFixed(1)}%`)}</div>`;
      $('#lab-validation').textContent=result.error;
      $('#lab-validation').className='lab-validation warn';
    } else {
      const curr=c.ccy||'LOCAL';
      const amount=n=>`${curr} ${new Intl.NumberFormat('en-US',{maximumFractionDigits:0}).format(n)}m`;
      const share=result.terminalShare;
      $('#lab-key-metrics').innerHTML=`<div class="lab-key">${metric('DCF EQUITY UPSIDE',pct(result.upside,1,true),signedClass(result.upside))}${metric('FAIR EQUITY VALUE',amount(result.fairEquity))}${metric('PRESENT VALUE / TERMINAL',share===null?'—':pct(share,1))}${metric('YEAR 5 MARGIN',`${path[5].toFixed(1)}%`)}</div>`;
      const isBase=Object.entries(assumptions).every(([k,v])=>Math.abs(v-c.valuation[k])<1e-9);
      const delta=result.upside-c.fairUp;
      $('#lab-validation').textContent=isBase
        ?(Math.abs(delta)<1e-7?`✓ Baseline reconciles with published DCF: ${pct(c.fairUp,1,true)} fair-value upside.`:`⚠ Published-model mismatch: ${pp(delta,3)}. Verify the financial snapshot.`)
        :`SCENARIO / NOT A FORECAST · Published DCF baseline: ${pct(c.fairUp,1,true)}. Current scenario: ${pct(result.upside,1,true)}.`;
      $('#lab-validation').className=`lab-validation ${isBase&&Math.abs(delta)<1e-7?'good':isBase?'warn':''}`;
    }
    const offsets=[-2,-1,0,1,2],marginOffsets=[-3,-1.5,0,1.5,3];
    const cells=offsets.map((rateDelta,row)=>{
      const rate=L.wacc+rateDelta;
      return `<tr><th scope="row">${rate.toFixed(2)}%</th>${marginOffsets.map((marginDelta,col)=>{
        const norm=L.norm+marginDelta;
        const value=window.KCValuation.calculate(c.valuation,{...assumptions,discountRate:rate/100,normalizedMargin:norm/100});
        const k=!value.valid?'invalid':value.upside>=.5?'deep-positive':value.upside>=0?'positive-cell':value.upside<=-.5?'deep-negative':'negative-cell';
        return `<td class="${k} ${row===2&&col===2?'current-cell':''}" title="Discount rate ${rate.toFixed(2)}%; normalized margin ${norm.toFixed(2)}%" aria-label="WACC ${rate.toFixed(2)} percent, normalized margin ${norm.toFixed(2)} percent: ${value.valid?pct(value.upside,1,true):'invalid assumptions'}">${value.valid?pct(value.upside,0,true):'N/A'}</td>`;
      }).join('')}</tr>`;
    }).join('');
    $('#lab-sensitivity').innerHTML=`<div class="sensitivity-wrap"><table class="sensitivity-table"><thead><tr><th scope="col">WACC ↓ / MARGIN →</th>${marginOffsets.map(d=>`<th scope="col">${(L.norm+d).toFixed(2)}%</th>`).join('')}</tr></thead><tbody>${cells}</tbody></table></div><div class="sensitivity-note">Rows: discount rate ±2 percentage points in 1 pp steps. Columns: normalized margin ±3 percentage points in 1.5 pp steps. Terminal growth and other assumptions are held at the scenario values. Green indicates positive equity fair-value upside; red indicates negative. A result is not a probability-weighted forecast.</div>`;
  }
  function renderMethod() {
    const M=state.data.meta;
    $('#method-params').innerHTML=[['Universe',`${state.data.companies.length} Nordic companies`],['Lookback','10 fiscal years'],['Current margin','Trailing 12 months'],['Own / peer / universe','60% / 25% / 15%'],['Prior persistence','0.60'],['DCF horizon','10 years'],['Portfolio positions','5'],['Maximum weight','30%'],['Rebalance','Monthly'],['Estimated trade cost','0.15%']].map(([k,v])=>`<div class="param-row"><span>${esc(k)}</span><strong>${esc(v)}</strong></div>`).join('');
    $('#method-data').innerHTML=`<div class="param-row"><span>Accounting years</span><strong>${esc(M.years?.[0])}–${esc(M.years?.at(-1))}</strong></div><div class="param-row"><span>Market quotes</span><strong>${esc(M.priceFrom)} to ${esc(M.priceTo)}</strong></div><div class="param-row"><span>Last pipeline run</span><strong>${esc(M.updated)}</strong></div>`;
  }
  function hookEvents() {
    $$('[data-page]').forEach(b=>b.addEventListener('click',()=>navigate(b.dataset.page)));
    $$('[data-page-go]').forEach(b=>b.addEventListener('click',()=>navigate(b.dataset.pageGo)));
    $('#menu-toggle').addEventListener('click',()=>{let open=$('#sidebar').classList.toggle('is-open');$('#menu-toggle').setAttribute('aria-expanded',String(open));});
    $('#drawer-close').addEventListener('click',closeDrawer);$('#drawer-backdrop').addEventListener('click',closeDrawer);
    document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('#company-drawer').hidden)closeDrawer();});
    document.addEventListener('click',e=>{const b=e.target.closest('[data-open]');if(b&&state.data){const c=find(b.dataset.open);if(c)openCompany(c);}});
    ['research-query','research-country','research-signal'].forEach(id=>$( `#${id}`).addEventListener(id==='research-query'?'input':'change',()=>state.data&&renderResearch()));
    $$('[data-sort]').forEach(b=>b.addEventListener('click',()=>{const s=b.dataset.sort;state.desc=state.sort===s?!state.desc:s!=='rank';state.sort=s;renderResearch();}));
    $('#lab-company').addEventListener('change',e=>resetLab(find(e.target.value)));
    ['cur','norm','phi','wacc','growth','terminal','ronic'].forEach(k=>$(`#lab-${k}`).addEventListener('input',e=>{state.lab[k]=Number(e.target.value);drawLab();}));
    $('#lab-reset').addEventListener('click',()=>resetLab(find($('#lab-company').value)));
    window.addEventListener('hashchange',readHash);
  }
  function readHash() {
    const raw=decodeURIComponent(location.hash.slice(1));
    if(raw.startsWith('company/')){const c=find(raw.slice(8));if(c){navigate('research',false);openCompany(c);}return;}
    if(!$('#company-drawer').hidden){$('#company-drawer').hidden=true;$('#drawer-backdrop').hidden=true;document.body.style.overflow='';}
    navigate(pageNames[raw]?raw:'overview',false);
  }
  function exports() {
    const btn=document.createElement('button');btn.className='button button-ghost';btn.textContent='Export screener CSV ↧';$('#research-count').before(btn);
    btn.addEventListener('click',()=>{
      const header=['Rank','Company','Ticker','Country','Sector','Signal','PriceDate','CurrentMargin','NormalizedMargin','ReversionUpside','Score'];
      const csv=[header.join(','),...state.data.companies.map(c=>[c.rank,c.name,c.ticker,c.country,c.group,c.signal,c.priceDate,c.cur,c.norm,c.revUp,c.score].map(v=>`"${String(v??'').replaceAll('"','""')}"`).join(','))].join('\r\n');
      _download(`kaatopaikka-screener-${state.data.meta.priceTo}.csv`,csv,'text/csv;charset=utf-8');
    });
    const letter=document.createElement('button');letter.className='button button-ghost';letter.textContent='Export model letter ↧';$('#decision-title').closest('.page-heading').append(letter);
    letter.addEventListener('click',()=>{
      const P=state.port;let lines=[`# Kaatopaikka Capital — model activity report`,`Report generated ${new Date().toISOString().slice(0,10)}`,`Market data through ${state.data.meta.priceTo}`,'',`Paper portfolio value: ${eur(P.value)}`,`Net return since inception: ${pct(P.value/P.start_capital-1,2,true)}`,`Equal-weight benchmark: ${pct(P.bench_value/P.start_capital-1,2,true)}`,'',`## Current holdings`,...P.holdings.map(h=>`- ${h.name}: ${pct(h.weight)}, ${eur(h.value)}; ${modelRationale(find(h.id)).decision}`),'',`## Latest model decision`,...((P.decisions||[]).slice(-1).flatMap(d=>[`Decision ${d.n}, ${d.date}: ${d.type}`,...(d.orders||[]).map(o=>`- ${o.name}: ${o.side||'BUY'} ${eur(o.eur)}. ${o.reason||''}`)])),'',`## Material limitations`,`Quotes may be delayed. Fundamental data are not updated with every quote. Simulated portfolio excludes dividends and uses fractional shares. No human investment approval is implied. Not investment advice.`];
      _download(`kaatopaikka-model-letter-${state.data.meta.priceTo}.md`,lines.join('\n'),'text/markdown;charset=utf-8');
    });
  }
  async function loadJSON(path) {const res=await fetch(`${path}?v=${Date.now()}`,{cache:'no-store'});if(!res.ok)throw new Error(`${path} HTTP ${res.status}`);return res.json();}
  async function refreshLatestPublishedData() {
    if(document.hidden||!state.data)return;
    try{
      const [data,port,sim,historical]=await Promise.all([
        loadJSON('data.json'),loadJSON('portfolio.json'),loadJSON('simulation.json'),
        loadJSON('historical-backtest.json').catch(()=>null)
      ]);
      if(!Array.isArray(data?.companies)||!port?.start_capital)return;
      const hasChanged=data?.meta?.updated!==state.data?.meta?.updated ||
        port?.history?.length!==state.port?.history?.length ||
        historical?.last_rebuilt_utc!==state.history?.last_rebuilt_utc;
      if(!hasChanged)return;
      Object.assign(state,{data,port,sim,
        history:historical?.validated_inputs===true?historical:null});
      const stale=data.companies.filter(c=>daysAgo(c.priceDate)>5).length;
      $('#data-status').textContent=stale?'● '+stale+' STALE QUOTES':'● EOD DATA · AUTO-SYNC';
      $('#data-status').classList.toggle('warning',stale>0);
      $('#side-status').textContent='Updated '+(data.meta.priceTo||'—');
      renderOverview();renderResearch();renderPortfolio();renderDecisions();
      renderMethod();
      if(state.replayDay){
        const offset=Math.round((Date.parse(state.replayDay+'T00:00:00Z')-TIMELINE_START)/DAY_MS);
        setTimelineDay(offset);
      }
      window.dispatchEvent(new CustomEvent('kc:data-refreshed',{
        detail:{priceTo:data.meta.priceTo}
      }));
    }catch(e){
      // Never replace valid EOD data with a transient network failure.
      console.warn('EOD update check failed',e);
    }
  }
  async function init() {
    dates();hookEvents();
    try {
      const [data,port,sim,historical]=await Promise.all([loadJSON('data.json'),loadJSON('portfolio.json'),loadJSON('simulation.json'),
        loadJSON('historical-backtest.json').catch(()=>null)]);
      if(!Array.isArray(data?.companies)||!data?.meta||!port?.start_capital)throw new Error('Unexpected JSON schema');
      Object.assign(state,{data,port,sim,history:historical?.validated_inputs===true?historical:null});
      const stale=data.companies.filter(c=>daysAgo(c.priceDate)>5).length;
      $('#data-status').textContent=stale?`● ${stale} STALE QUOTES`:'● END-OF-DAY DATA';
      $('#data-status').classList.toggle('warning',stale>0);
      $('#side-status').textContent=`Updated ${data.meta.priceTo||'—'}`;
      renderOverview();renderResearch();renderPortfolio();renderDecisions();renderLabOptions();renderMethod();setupTimeMachine();exports();readHash();
      setInterval(refreshLatestPublishedData,90000); // Poll published snapshots; not a live exchange feed.
    } catch(e) {
      console.error('Investment terminal load failed',e);
      $('#load-error').hidden=false;$('#data-status').textContent='● DATA UNAVAILABLE';$('#data-status').classList.add('warning');
      $('#side-status').textContent='Check the data pipeline';
      $('#overview-stats').classList.remove('skeleton-grid');$('#overview-stats').innerHTML=stat('Data unavailable','—','Please reload after GitHub Actions completes');
    }
  }
  init();
})();
