/* Cosmic Deeku — visual-only mascot controls.
   Keeps pointer events over the globe and never touches model or historical data. */
(() => {
  'use strict';
  const start = () => {
    const stage = document.querySelector('.ape-theater');
    const toggle = document.getElementById('ape-motion-toggle');
    if (!stage || !toggle) return;
    const setPaused = paused => {
      stage.classList.toggle('is-paused', paused);
      toggle.setAttribute('aria-pressed', String(!paused));
      toggle.setAttribute('aria-label', paused ? 'Play monkey and rocket animations' : 'Pause monkey and rocket animations');
      toggle.textContent = paused ? '▶ Mascot' : 'Ⅱ Mascot';
    };
    setPaused(window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    toggle.addEventListener('click', () => setPaused(!stage.classList.contains('is-paused')));
    // For background tabs, CSS animations do not require JavaScript frames.
    // Pressing the button pauses only the mascot, never the globe or the time slider.
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once:true});
  else start();
})();
