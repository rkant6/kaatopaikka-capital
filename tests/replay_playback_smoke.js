/* Verify 2024 playback does not show future model returns or forged events. */
'use strict';
const assert=require('node:assert/strict');
const vm=require('node:vm'),fs=require('node:fs');
global.window=global;
global.document={readyState:'loading',addEventListener(){}};
vm.runInThisContext(fs.readFileSync('assets/replay-desk.js','utf8'),{filename:'replay-desk.js'});
const tools=global.KCReplayResearch;
assert.ok(tools,'Replay test adapter missing');
const days=['2024-01-02','2024-02-01','2025-01-02'];
const history=days.map((date,i)=>({
 date,nav:[9900,10000,19000][i],
 bench_nav:[9950,10100,15000][i],
 return:[-.01,0,.9][i],
 bench_return:[-.005,.01,.5][i]
}));
const valid={
 validated_inputs:true,is_investable_track_record:false,
 from:'2024-01-02',through:'2025-01-02',history,
 events:[],decisions:[{date:'2024-01-02',orders:[]}]
};
assert.ok(tools.validData(valid),'Valid source-dated research is accepted');
assert.ok(!tools.validData({...valid,validated_inputs:false}),'Unverified research must be rejected');
assert.ok(!tools.validData({...valid,is_investable_track_record:true}),'Do not present a live brokerage account as retrospective research');
assert.equal(tools.visibleCount(history,'2023-12-30'),0);
assert.equal(tools.visibleCount(history,'2024-01-31'),1);
assert.equal(tools.visibleCount(history,'2024-02-02'),2);
const jan=tools.drawChart(history,'2024-01-31',false);
const feb=tools.drawChart(history,'2024-02-02',false);
const future=tools.drawChart(history,'2026-11-08',false);
assert.ok(jan.includes('through 2024-01-02'),'Chart date must only include historical frames');
assert.ok(!jan.includes('19000'),'2025 strategy NAV must never appear on 2024 playback');
assert.ok(!feb.includes('through 2025-01-02'),'February 2024 frame must not imply 2025 coverage');
assert.ok(future.includes('through 2025-01-02'),'Last frame may show full verified history');
const pathCount=(s)=>(s.match(/L\d+\.\d+,\d+\.\d+/g)||[]).length;
assert.ok(pathCount(jan)<pathCount(future),'Earlier frame must actually have fewer plotted line segments');
console.log('  2024 research replay: no-lookahead NAV chart, source gates and date cursor OK');
