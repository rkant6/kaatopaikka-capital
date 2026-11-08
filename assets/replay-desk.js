/* KAATOPAIKKA CAPITAL / 2024 POINT-IN-TIME RESEARCH REPLAY
   Data-driven views only. Never infer a 2024 order, margin or return from the
   current model or from placeholder CSV headers. */
(() => {
  'use strict';
  const $=s=>document.querySelector(s);
  const $$=s=>[...document.querySelectorAll(s)];
  const escapeHTML=value=>String(value??'').replace(/[&<>"']/g,c=>({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[c]));
  const money=n=>Number.isFinite(+n)&&n!==null?
    new Intl.NumberFormat('en-IE',{style:'currency',currency:'EUR',maximumFractionDigits:0}).format(+n):'—';
  const percent=n=>Number.isFinite(+n)&&n!==null?
    (+n>0?'+':'')+(100*+n).toFixed(2)+'%':'—';
  const pct=n=>Number.isFinite(+n)&&n!==null?(100*+n).toFixed(1)+'%':'—';
  const asUTC=day=>new Date(day+'T12:00:00Z');
  const formatted=d=>{
    const x=asUTC(d);
    return Number.isNaN(+x)?String(d||'—'):
      x.toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric',timeZone:'UTC'});
  };
  const ms=86400000,START=Date.UTC(2024,0,1);
  const textByType={
    trade:'MODEL TRADE',earnings:'EARNINGS RELEASE',rebalance:'REBALANCE',
    dividend:'DIVIDEND',split:'CORPORATE ACTION',observed_drawdown:'PORTFOLIO RISK'
  };
  const state={data:null,status:null,day:null,filter:'all',lastError:null,renderAt:0,
    eventFlashTimer:null,lastNarratedKey:null,playMode:false};
  const safeLink=url=>typeof url==='string'&&url.startsWith('https://')?url:null;

  function validData(data){
    return data&&data.validated_inputs===true&&
      data.is_investable_track_record===false&&
      Array.isArray(data.history)&&data.history.length>1&&
      Array.isArray(data.events)&&Array.isArray(data.decisions)&&
      data.from>='2024-01-01'&&data.from<=data.through&&
      data.history.every((p,i)=>p.date>=data.from&&p.date<=data.through&&
        Number.isFinite(Number(p.nav))&&Number(p.nav)>0&&
        (i===0||p.date>data.history[i-1].date));
  }
  function lowerBound(sorted,key){
    let lo=0,hi=sorted.length;
    while(lo<hi){const mid=(lo+hi)>>1;if(sorted[mid].date<=key)lo=mid+1;else hi=mid;}
    return lo;
  }
  function lastAt(rows,day){
    if(!rows?.length)return null;
    return rows[lowerBound(rows,day)-1]||null;
  }
  function activeData(day){
    const d=state.data;
    if(!d||day<d.from||day>d.through)return null;
    return lastAt(d.history,day);
  }
  function empty(title,detail,link){
    return '<div class="replay-empty-state">'+
      '<div class="replay-empty-mark" aria-hidden="true">◈</div>'+
      '<strong>'+escapeHTML(title)+'</strong>'+
      '<p>'+escapeHTML(detail)+'</p>'+
      (link?'<a class="replay-source-link" target="_blank" rel="noopener noreferrer" href="'+escapeHTML(link)+'">Source documentation ↗</a>':'')+
      '</div>';
  }
  function quoteDisclaimer(){
    return 'Historical trade records are a research reconstruction using a fixed 2026 universe. '
      +'They are hypothetical, subject to survivorship and strategy-selection bias, '
      +'and never evidence of actual 2024 investment activity.';
  }
  function card(label,value,foot,accent){
    return '<div class="stat"><div class="stat-label">'+escapeHTML(label)+'</div>'+
      '<div class="stat-value '+(accent||'')+'">'+escapeHTML(value)+'</div>'+
      '<div class="stat-note">'+escapeHTML(foot)+'</div></div>';
  }
  function drawChart(history,day,mini){
    if(!history?.length)return '';
    const W=920,H=mini?138:320;
    const pad={l:mini?13:64,r:mini?18:28,t:mini?13:24,b:mini?10:46};
    const x0=pad.l,x1=W-pad.r,y0=pad.t,y1=H-pad.b;
    const yvalues=history.flatMap(h=>[+h.nav,+h.bench_nav||+h.nav]).filter(Number.isFinite);
    let vmin=Math.min(...yvalues),vmax=Math.max(...yvalues);
    if(vmax===vmin){vmax*=1.025;vmin*=.975;}
    const diff=Math.max(vmax-vmin,1);vmin-=diff*.08;vmax+=diff*.08;
    const x=i=>x0+i*(x1-x0)/Math.max(1,history.length-1);
    const y=v=>y1-(+v-vmin)/(vmax-vmin)*(y1-y0);
    const curve=(field)=>history.map((p,i)=>(i?'L':'M')+x(i).toFixed(2)+','+y(p[field]??p.nav).toFixed(2)).join(' ');
    const chosen=lastAt(history,day);
    const currentIndex=chosen?history.indexOf(chosen):0;
    const currentX=x(currentIndex);
    let svg='<svg class="replay-equity-svg" viewBox="0 0 '+W+' '+H+'" role="img" aria-label="Historical model NAV and equal-weight benchmark through '+escapeHTML(history.at(-1).date)+'">';
    svg+='<defs><linearGradient id="'+(mini?'mini':'backtest')+'-replay-grad" x1="0" y1="0" x2="0" y2="1">'+
      '<stop offset="0%" stop-color="#ffa936" stop-opacity=".21"/>'+
      '<stop offset="100%" stop-color="#ffa936" stop-opacity="0"/></linearGradient></defs>';
    if(!mini){
      for(let k=0;k<5;k++){
        const level=vmin+(vmax-vmin)*k/4,yy=y(level);
        svg+='<line x1="'+x0+'" y1="'+yy+'" x2="'+x1+'" y2="'+yy+'" stroke="#293641" stroke-width="1" stroke-dasharray="3 5"/>';
        svg+='<text x="'+(x0-10)+'" y="'+(yy+4)+'" fill="#8396a5" font-size="10" font-family="IBM Plex Mono" text-anchor="end">€'+(level/1000).toFixed(1)+'k</text>';
      }
      [0,Math.floor((history.length-1)/2),history.length-1].forEach(i=>{
        svg+='<text x="'+x(i)+'" y="'+(H-12)+'" fill="#8195a4" text-anchor="middle" font-size="10" font-family="IBM Plex Mono">'+
          escapeHTML(history[i].date.slice(0,7))+'</text>';
      });
    }
    const start=x(0)+','+y1,final=x(history.length-1)+','+y1;
    svg+='<path d="M'+start+' '+curve('nav')+' L'+final+' Z" fill="url(#'+(mini?'mini':'backtest')+'-replay-grad)"/>';
    svg+='<path d="'+curve('bench_nav')+'" fill="none" stroke="#7497bb" stroke-width="'+(mini?1.8:2.5)+'" opacity=".95"/>';
    svg+='<path d="'+curve('nav')+'" fill="none" stroke="#ffad38" stroke-width="'+(mini?2.8:3.7)+'" stroke-linecap="round" stroke-linejoin="round"/>';
    svg+='<line x1="'+currentX+'" y1="'+y0+'" x2="'+currentX+'" y2="'+y1+'" stroke="#ffe5ae" opacity=".63" stroke-dasharray="5 4"/>';
    if(chosen){
      svg+='<circle cx="'+currentX+'" cy="'+y(chosen.nav)+'" r="'+(mini?4:6)+'" fill="#ffbe4c" stroke="#121921" stroke-width="2"/>';
      if(!mini)svg+='<text x="'+Math.min(currentX+10,x1-85)+'" y="'+Math.max(y(chosen.nav)-14,y0+10)+'" fill="#ffe0a1" font-size="12" font-family="IBM Plex Mono">'+
        escapeHTML(money(chosen.nav))+'</text>';
    }
    svg+='</svg>';
    if(!mini)svg+='<div class="chart-legend"><span><i class="legend-line" style="background:#ffad38"></i>Margin-reversion model</span>'+
      '<span><i class="legend-line" style="background:#7497bb"></i>Equal-weight buy-and-hold</span>'+
      '<span>Cursor: '+escapeHTML(chosen?.date||'—')+'</span></div>';
    return svg;
  }
  function annualTable(history,through){
    if(!history?.length)return empty('Annual return table pending',
      'The 2024–present model history cannot be calculated without dated Q1–Q4 original releases and prices.');
    const years=[...new Set(history.map(x=>x.date.slice(0,4)))].sort();
    const rows=[];
    let priorNav=10000,priorBench=10000;
    for(const year of years){
      const entries=history.filter(h=>h.date.startsWith(year));
      if(!entries.length)continue;
      // Annual returns use the last recorded close of the prior year,
      // or the actual EUR 10,000 notional starting capital for FY2024.
      const last=entries.at(-1);
      const ret=last.nav/priorNav-1,bench=last.bench_nav/priorBench-1;
      let peak=priorNav,maxDD=0;
      for(const p of entries){peak=Math.max(peak,p.nav);maxDD=Math.min(maxDD,p.nav/peak-1);}
      const complete=year<through.slice(0,4);
      rows.push('<tr><td><b>'+escapeHTML(year)+'</b> '+(complete?'':'<small>YTD</small>')+'</td>'+
        '<td class="'+(ret<0?'negative':'positive')+'">'+escapeHTML(percent(ret))+'</td>'+
        '<td class="'+(bench<0?'negative':'positive')+'">'+escapeHTML(percent(bench))+'</td>'+
        '<td class="'+(ret-bench<0?'negative':'positive')+'">'+escapeHTML(percent(ret-bench))+'</td>'+
        '<td class="negative">'+escapeHTML(percent(maxDD))+'</td>'+
        '<td>'+escapeHTML(money(last.nav))+'</td></tr>');
      priorNav=last.nav;priorBench=last.bench_nav;
    }
    return '<div class="table-scroll"><table class="data-table replay-annual-table">'+
      '<thead><tr><th>YEAR</th><th>STRATEGY</th><th>BENCHMARK</th><th>EXCESS</th><th>MAX DD</th><th>YEAR-END NAV</th></tr></thead>'+
      '<tbody>'+rows.join('')+'</tbody></table></div>'+
      '<div class="backtest-annual-notice">Retrospective research on a fixed, survivorship-biased universe. Returns include modeled trade costs, cash dividends and split accounting; no live investment performance is implied.</div>';
  }
  function classOfEvent(e){
    return e.type==='observed_drawdown'?'risk':
      e.type==='trade'?'trade':e.type==='earnings'?'earnings':
      e.type==='rebalance'?'rebalance':'corporate';
  }
  function iconFor(e){
    if(e.type==='observed_drawdown')return '☄';
    if(e.type==='trade')return e.side==='SELL'?'↘':'↗';
    if(e.type==='earnings')return '▤';
    if(e.type==='dividend')return '€';
    if(e.type==='split')return '≋';
    return '◎';
  }
  function eventRow(e,compact=false){
    const url=safeLink(e.source_url);
    const kind=classOfEvent(e);
    return '<article class="replay-event replay-event-'+kind+'">'+
      '<span class="replay-event-icon" aria-hidden="true">'+iconFor(e)+'</span>'+
      '<div class="replay-event-body">'+
      '<div class="replay-event-caption"><b>'+escapeHTML(textByType[e.type]||e.type.toUpperCase())+'</b> · '+escapeHTML(formatted(e.date))+'</div>'+
      '<div class="replay-event-text">'+escapeHTML(e.description||e.company||'Documented observation')+'</div>'+
      (compact?'':(url?'<a class="replay-source-link" href="'+escapeHTML(url)+'" target="_blank" rel="noopener noreferrer">Check source ↗</a>':
        '<small class="replay-source-muted">Calculated from the dated backtest</small>'))+
      '</div></article>';
  }
  // Event director: only source-dated events from an approved backtest may
  // ever appear as BUY, SELL, EARNINGS or LOSS on the moving globe.
  function updatePlayhead(day,playing){
    const track=$('#replay-progress-fill'),now=$('#replay-now-playing');
    const total=Math.max(1,Date.now()-START),progress=Math.max(0,Math.min(1,(+asUTC(day)-START)/total));
    if(track)track.style.transform='scaleX('+progress.toFixed(5)+')';
    if(!now)return;
    const eventMode=state.data&&day>=state.data.from&&day<=state.data.through;
    now.classList.toggle('is-playing',Boolean(playing));
    const caption=eventMode
      ?'RESEARCH BACKTEST · '+formatted(day)+' · SOURCE-DATED'
      :playing?'VISUAL TIME TRAVEL · NO VERIFIED 2024 MODEL ORDERS'
        :'SELECTED DATE · MODEL HISTORY AWAITING ORIGINAL REPORTS';
    const label=now.querySelector('span:last-child');
    if(label&&label.textContent!==caption)label.textContent=caption;
  }
  function narrateEvent(event,extra=0){
    if(!state.data||!event)return;
    const bubble=$('#earth-replay-event');
    if(!bubble)return;
    const key=[event.date,event.type,event.company||'',event.side||''].join('|');
    if(key===state.lastNarratedKey)return;
    state.lastNarratedKey=key;
    if(state.eventFlashTimer)clearTimeout(state.eventFlashTimer);
    const type=event.type||'event',tags={
      trade:event.side==='SELL'?'MODEL SELL':'MODEL BUY',
      earnings:'QUARTERLY REPORT',rebalance:'MONTHLY REBALANCE',
      observed_drawdown:'OBSERVED STRATEGY LOSS',
      split:'CORPORATE ACTION',dividend:'DIVIDEND RECEIVED'
    };
    const name=(event.company||event.side||'').trim();
    const heading=name||tags[type]||'Source-dated event';
    const detail=(event.description||'A documented historical observation.')
      +(extra>0?'  +'+extra+' additional event'+(extra===1?'':'s')+' on this step.':'');
    $('#earth-replay-event-type').textContent=tags[type]||'HISTORICAL EVENT';
    $('#earth-replay-event-title').textContent=heading;
    $('#earth-replay-event-detail').textContent=detail;
    $('#earth-replay-event-date').textContent=formatted(event.date);
    bubble.classList.toggle('is-negative',type==='observed_drawdown'||event.side==='SELL');
    bubble.hidden=false;
    bubble.classList.remove('is-burst');
    void bubble.offsetWidth;  // restart only on a genuine newly verified event
    bubble.classList.add('is-burst');
    state.eventFlashTimer=setTimeout(()=>{bubble.hidden=true;bubble.classList.remove('is-burst');},4800);
  }
  function timelineUpdate(detail){
    const day=detail?.iso||state.day;
    state.day=day;
    const playing=Boolean(detail?.playing);
    updatePlayhead(day,playing);
    const events=state.data?.events||[];
    if(state.data){
      const passed=playing&&detail.from&&day>detail.from
        ?events.filter(e=>e.date>detail.from&&e.date<=day)
        :events.filter(e=>e.date===day);
      if(passed.length)narrateEvent(passed.at(-1),passed.length-1);
    }
    // Repainting the entire research SVG/table every frame caused observable
    // stutter; 5fps for accounting panels while the globe runs independently
    // at 60fps is a deliberate animation budget.
    const now=performance.now();
    const significant=Boolean(detail?.events?.length);
    if(!playing||significant||now-state.renderAt>230){
      state.renderAt=now;
      showPanel(day);
    }else{
      const row=activeData(day);
      const stats=$('#replay-live-stats');
      if(stats&&row){
        stats.querySelector('span:first-child b')?.replaceChildren(document.createTextNode(money(row.nav)));
        const ret=stats.querySelector('span:nth-child(2) b');
        if(ret)ret.textContent=percent(row.return);
      }
    }
  }
  function showPanel(day){
    const row=activeData(day),d=state.data;
    const v=Boolean(row),startText=day<'2024-01-02'?'Before the first market session':'No validated trading records';
    const flag=$('#replay-validation');
    if(flag){flag.textContent=d?'SOURCE-DATED · HYPOTHETICAL':'SOURCE DATA REQUIRED';flag.classList.toggle('is-ready',!!d);}
    if($('#replay-asof')){
      const rows=state.status?.input_rows||{};
      $('#replay-asof').textContent=d?'Research replay through '+formatted(d.through)+' · Fixed-universe selection bias':
        'EVIDENCE COVERAGE · '+(rows.filings||0)+' filings / '+(rows.annual_margins||0)+' annual margins / '+(rows.prices||0)+' price rows';
    }
    const mini=$('#replay-mini-chart');
    if(mini)mini.innerHTML=d?drawChart(d.history,day,true):
      empty('2024 return series not yet verified',
        'The strategy cannot report historical buys or P&L until original Q1–Q4 releases and dated prices have been audited.',
        'https://github.com/rkant6/kaatopaikka-capital/tree/main/historical_data');
    const cards=$('#backtest-stats');
    if(cards)cards.innerHTML=[
      card('Strategy NAV',v?money(row.nav):'—',v?'Historical research through '+formatted(row.date):'2024–present evidence pending'),
      card('Strategy return',v?percent(row.return):'—',v?'Hypothetical · after modeled costs':'No invented 2024 performance',v?(row.return<0?'negative':'positive'):''),
      card('Equal-weight benchmark',v?percent(row.bench_return):'—',v?'Dividends and entry costs included':'Requires same source-dated prices'),
      card('Active positions',v?String(row.positions?.length??0):'—',v?'At '+formatted(row.date):'Trading history cannot be inferred')
    ].join('');
    if($('#backtest-status'))$('#backtest-status').textContent=d?'RESEARCH BACKTEST · NOT LIVE':'AWAITING ORIGINAL FILINGS';
    const mainChart=$('#backtest-chart');
    if(mainChart)mainChart.innerHTML=d?drawChart(d.history,day,false):
      empty('No authenticated 2024 equity curve',
        'The model will only show actual source-dated historical simulations after each Nordic filing, quote, FX series and corporate action is supplied.',
        'https://github.com/rkant6/kaatopaikka-capital/tree/main/historical_data');
    if($('#backtest-chart-caption'))$('#backtest-chart-caption').textContent=d?
      'Fixed current universe · 0.15% modeled transaction costs · retrospective research only. '+quoteDisclaimer():
      'Data-gated: 2026 paper NAV is kept separate and must not be relabeled as 2024 returns.';
    const annual=$('#backtest-annual');
    if(annual)annual.innerHTML=d?annualTable(d.history,d.through):empty(
      'No authenticated annual performance yet',
      'Year-by-year returns for 2024, 2025 and 2026 will appear after the complete source-dated research backtest is auditable.');
        const holdings=$('#backtest-holdings');
    if(holdings)holdings.innerHTML=v?(row.positions?.length?
      row.positions.slice().sort((a,b)=>b.weight-a.weight).map(p=>
        '<div class="backtest-position"><div><strong>'+escapeHTML(p.name)+'</strong><small>'+percent(p.weight)+' weight · '+money(p.value)+'</small></div>'+
        '<span class="backtest-weight-bar"><i style="width:'+Math.min(100,Math.max(0,p.weight*100))+'%"></i></span></div>').join(''):
      empty('Cash / awaiting rebalance','The first eligible common Nordic trading session has not yet produced a position.')):
      empty('Holdings not verified','No contemporary 2024 securities or weights are assumed from the 2026 model.');
    const snap=d?lastAt(d.snapshots||[],day):null;
    const holder=$('#backtest-snapshot');
    if(holder)holder.innerHTML=snap?
      '<div class="replay-audit-caption">LAST MODEL DECISION · '+escapeHTML(formatted(snap.date))+
      '<br>Signals used prior close: '+escapeHTML(snap.signal_asof)+'</div>'+
      Object.entries(snap.evidence||{}).slice(0,6).map(([name,ev])=>
        '<div class="replay-evidence"><b>'+escapeHTML(name)+'</b> <span>Filing published '+escapeHTML(ev.published_on)+'</span>'+
        (safeLink(ev.source_url)?'<a href="'+escapeHTML(ev.source_url)+'" rel="noopener noreferrer" target="_blank">↗</a>':'')+'</div>').join(''):
      '<p class="replay-audit-caption">Every eventual decision links to the report that was public before the prior-session signal. No hindsight financial updates are permitted.</p>';
    const allEvents=d?d.events.filter(x=>x.date<=day):[];
    const filter=state.filter;
    const filtered=allEvents.filter(x=>filter==='all'||(filter==='risk'?x.type==='observed_drawdown':
      filter==='trade'?x.type==='trade':x.type==='earnings'));
    const eventList=$('#backtest-events');
    if(eventList)eventList.innerHTML=filtered.length?
      filtered.slice(-26).reverse().map(x=>eventRow(x,false)).join(''):
      empty('No source-verified events at this point','Choose a later date or provide original filing and price inputs.');
    const blotter=$('#backtest-orders');
    if(blotter){
      const orders=d?d.decisions.filter(dec=>dec.date<=day).flatMap(dec=>dec.orders.map(o=>({...o,date:dec.date}))).slice(-40).reverse():[];
      blotter.innerHTML=orders.length?orders.map(o=>
        '<tr><td class="mono">'+escapeHTML(o.date)+'</td><td><span class="replay-order-side '+(o.side==='BUY'?'buy':'sell')+'">'+escapeHTML(o.side)+'</span><br>'+escapeHTML(o.company)+'</td>'+
        '<td class="mono">'+escapeHTML(money(o.eur))+'</td><td>'+
        (safeLink(o.source_url)?'<a class="replay-source-link" href="'+escapeHTML(o.source_url)+'" target="_blank" rel="noopener noreferrer">Filing '+escapeHTML(o.report_published_on)+' ↗</a>':'No source')+
        '</td></tr>').join(''):'<tr><td colspan="4" class="replay-no-orders">No authenticated historical buys or sells to display.</td></tr>';
    }
    const coverage=$('#backtest-coverage');
    if(coverage){
      const rows=state.status?.input_rows||{};
      const review=[
        ['Quarterly filings / TTM fundamentals',rows.filings||0,'Published dates, EBIT, shares, debt and original issuer links'],
        ['Annual operating-margin observations',rows.annual_margins||0,'Historical values and original release dates'],
        ['Daily close / FX / corporate actions',rows.prices||0,'Source-dated quotes, splits and dividends'],
        ['Model execution and portfolio entries',d?.decisions?.length||0,'Only generated after the complete input audit']
      ];
      coverage.innerHTML='<div class="replay-coverage-grid">'+review.map(r=>
        '<div class="replay-coverage-item"><span>'+escapeHTML(r[0])+'</span><strong>'+escapeHTML(String(r[1]))+' rows</strong><small>'+escapeHTML(r[2])+'</small></div>').join('')+'</div>'+
        '<div class="replay-coverage-notice">'+
        '<strong>'+(d?'SOURCE-DATED REPLAY AVAILABLE':'HISTORICAL RETURNS WITHHELD')+'</strong><p>'+
        escapeHTML(d?quoteDisclaimer():(state.status?.reason||
          'The original 2024–2026 filings and complete 30-name price histories are not in the repository. A 2026 snapshot cannot be reused as 2024 information.'))+'</p>'+
        '<p>Stock market data displayed on this site are end-of-day and may be delayed. The page automatically checks for newly published data but does not claim a real-time exchange feed.</p></div>';
    }
    const replayStats=$('#replay-live-stats');
    if(replayStats)replayStats.innerHTML=v?
      '<span><small>SIMULATED NAV</small><b>'+escapeHTML(money(row.nav))+'</b></span>'+
      '<span><small>SINCE 2024</small><b class="'+(row.return<0?'negative':'positive')+'">'+escapeHTML(percent(row.return))+'</b></span>'+
      '<span><small>BENCHMARK</small><b>'+escapeHTML(percent(row.bench_return))+'</b></span>':
      '<span><small>2024 NAV</small><b>—</b></span><span><small>HISTORICAL ORDERS</small><b>NOT VERIFIED</b></span>';
    const timeEvents=$('#time-events');
    if(timeEvents){
      const recent=allEvents.filter(x=>x.date>=new Date(+asUTC(day)-10*ms).toISOString().slice(0,10));
      timeEvents.innerHTML=recent.length?recent.slice(-3).reverse().map(e=>eventRow(e,true)).join(''):
        '<div class="replay-no-events">'+escapeHTML(d?'No source-dated event in the preceding 10 days.':
        'No verified 2024–2026 trades or earnings have been loaded. The Earth and timeline still animate, but historical returns cannot be inferred.')+'</div>';
    }
    const factTitle=$('#time-summary-title'),factText=$('#time-summary');
    if(factTitle&&factText){
      if(v){
        factTitle.textContent=money(row.nav)+'  ·  '+percent(row.return);
        factText.textContent='Research reconstruction as of '+formatted(row.date)+'. Last common-market rebalance followed published filings and prior close signals. Fixed 2026-selected universe.';
      }else if(d){
        factTitle.textContent=startText;
        factText.textContent='Validated backtest coverage: '+formatted(d.from)+' to '+formatted(d.through)+'. Outside that window, no returns are extrapolated.';
      }else{
        factTitle.textContent='Historical strategy performance awaits evidence';
        factText.textContent='Original source-dated reports and market history are missing. The live paper portfolio started in 2026; it cannot be backdated.';
      }
    }
    const next=$('#replay-next-event');
    if(next){
      const future=d?.events?.find(e=>e.date>day);
      next.disabled=!future;
      next.title=future?'Next source-dated event: '+future.date:'No verified future event available';
    }
  }

  async function loadJSON(path){
    try{
      const r=await fetch(path+'?replay='+Date.now(),{cache:'no-store'});
      if(!r.ok)return null;
      return await r.json();
    }catch(e){return null;}
  }
  async function sync(initial){
    const [d,status]=await Promise.all([loadJSON('historical-backtest.json'),loadJSON('historical-status.json')]);
    const next=validData(d)?d:null;
    const changed=JSON.stringify([state.data?.last_rebuilt_utc,state.status?.generated_utc])!==JSON.stringify(
      [next?.last_rebuilt_utc,status?.generated_utc]);
    state.data=next;state.status=status||null;
    if(initial||changed){
      // Keep globe events and the year-by-year performance engine in sync
      // if an end-of-day GitHub deployment publishes new historical evidence.
      window.dispatchEvent(new CustomEvent('kc:history-update',{detail:{history:next}}));
      updatePlayhead(state.day||new Date().toISOString().slice(0,10),false);
      showPanel(state.day||new Date().toISOString().slice(0,10));
    }
  }
  function setup(){
    if(!$('#replay-mini-chart'))return;
    window.addEventListener('kc:timeline',e=>timelineUpdate(e.detail));
    $$('.event-filter').forEach(button=>button.addEventListener('click',()=>{
      state.filter=button.dataset.eventKind;
      $$('.event-filter').forEach(b=>b.classList.toggle('is-active',b===button));
      showPanel(state.day||new Date().toISOString().slice(0,10));
    }));
    $('#replay-next-event')?.addEventListener('click',()=>{
      const next=state.data?.events?.find(e=>e.date>(state.day||'2024-01-01'));
      if(!next)return;
      const slider=$('#time-date-range');
      if(!slider)return;
      slider.value=Math.min(+slider.max,Math.max(0,Math.round(
        (+asUTC(next.date)-START)/ms)));
      slider.dispatchEvent(new Event('input',{bubbles:true}));
    });
    $('#backtest-jump')?.addEventListener('click',()=>{
      $('[data-page="overview"]')?.click();
      document.querySelector('.planet-desk')?.scrollIntoView({behavior:'smooth',block:'center'});
    });
    state.day=new Date().toISOString().slice(0,10);
    showPanel(state.day);
    sync(true);
    // Poll the published static files; these are END-OF-DAY facts, not a
    // streaming trade feed, and a stale date must never be labeled "live".
    setInterval(()=>{if(!document.hidden)sync(false);},90000);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',setup,{once:true});
  else setup();
})();