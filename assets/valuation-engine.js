/* Kaatopaikka Capital: deterministic, side-effect-free DCF valuation engine.
   Mirrors the ten-period margin fade model in nordic_margin_reversion.py.
   Returns the equity value in the SAME monetary units as the source snapshot. */
(function (root, factory) {
  'use strict';
  const engine = factory();
  if (typeof module === 'object' && module.exports) module.exports = engine;
  if (root) root.KCValuation = engine;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const PARAMS = ['currentMargin','normalizedMargin','persistence','discountRate','growthExplicit','growthTerminal','ronic'];

  function calculate(snapshot, overrides = {}) {
    if (!snapshot || typeof snapshot !== 'object') return {valid:false,error:'DCF input snapshot is unavailable.'};
    const p = Object.assign({}, snapshot, overrides);
    const numeric = PARAMS.concat(['revenueTtm','marketCap','netClaims','taxRate']);
    if (!numeric.every(k => typeof p[k] === 'number' && Number.isFinite(p[k]))) {
      return {valid:false,error:'A required financial input is missing or non-numeric.'};
    }
    if (p.revenueTtm <= 0 || p.marketCap <= 0 || p.ronic <= 0 ||
        p.discountRate <= p.growthTerminal || p.discountRate <= -1 ||
        p.growthExplicit <= -1 || p.growthTerminal <= -1 ||
        p.persistence < 0 || p.persistence >= 1 ||
        p.taxRate < 0 || p.taxRate >= 1) {
      return {valid:false,error:'Invalid assumptions: discount rate must exceed terminal growth; revenue, equity value and RONIC must be positive.'};
    }
    const fcfYears = [];
    let pvExplicit = 0;
    let lastRevenue = p.revenueTtm;
    for (let year = 1; year <= 10; year++) {
      const revenue = p.revenueTtm * (1 + p.growthExplicit) ** year;
      const margin = p.normalizedMargin + p.persistence ** year * (p.currentMargin - p.normalizedMargin);
      const fcf = revenue * margin * (1 - p.taxRate) * (1 - p.growthExplicit / p.ronic);
      const pv = fcf / (1 + p.discountRate) ** year;
      pvExplicit += pv;
      lastRevenue = revenue;
      fcfYears.push({year,revenue,margin,fcf,pv});
    }
    const terminalFcf = lastRevenue * (1 + p.growthTerminal) * p.normalizedMargin *
      (1 - p.taxRate) * (1 - p.growthTerminal / p.ronic);
    const terminalValue = terminalFcf / (p.discountRate - p.growthTerminal);
    const pvTerminal = terminalValue / (1 + p.discountRate) ** 10;
    const fairEV = pvExplicit + pvTerminal;
    const fairEquity = fairEV - p.netClaims;
    const upside = fairEquity / p.marketCap - 1;
    if (![pvExplicit,pvTerminal,fairEV,fairEquity,upside].every(Number.isFinite)) {
      return {valid:false,error:'The scenario produced a non-finite valuation.'};
    }
    return {valid:true,assumptions:p,fcfYears,pvExplicit,terminalFcf,terminalValue,pvTerminal,fairEV,fairEquity,upside,
      terminalShare:fairEV !== 0 ? pvTerminal / fairEV : null};
  }

  return Object.freeze({calculate});
});
