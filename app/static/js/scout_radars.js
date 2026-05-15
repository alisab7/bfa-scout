/**
 * scout_radars.js  (Phase 5d-1)
 *
 * Renders Chart.js radars for the Scout-Assessment section on /compare/view:
 *   1) one "category averages" radar (4 axes: Technical/Tactical/Physical/Mentality)
 *   2) one per-category drill-down radar inside each <details> block
 *      (axes = criterion names for that category — Tech 10, Tact 16-20,
 *       Phys 9, Ment 6 for the AM∪DM union)
 *
 * Each canvas is `<canvas data-scout-radar='<JSON>'>` where the JSON has shape:
 *   { axes: [str, ...], datasets: [{label, values, annotations}, ...] }
 *
 * `annotations[i]` is one of 'rated' | 'na' | 'absent' and drives tooltip text:
 *   - 'rated':  values[i] is the real score; tooltip "Player: 4.2 / 5"
 *   - 'na':     values[i] = 0 for plotting; tooltip "Player: N/A"
 *   - 'absent': values[i] = 0 for plotting; tooltip "Player: — (not in profile)"
 *
 * Why plot 0 for N/A/absent rather than null? Chart.js radar treats nulls as
 * gaps that break the polygon — visually messy when one player has 12/16
 * axes filled and another 9/16. Plotted-zero + annotation tooltip keeps the
 * polygons closed; the truth is in the hover.
 *
 * ── Init contract ─────────────────────────────────────────────────────────
 *   - DOMContentLoaded → initScoutRadars() inits all canvases on page load
 *     (all 5 are visible from first render — Phase 5d's <details open>
 *     decision means lazy-init would only delay rendering the user already
 *     wants to see, with zero saving).
 *   - htmx:afterSwap on #scout-section → initScoutRadars() re-inits all 5
 *     after a Latest ↔ Averaged swap. Existing Chart instances are
 *     destroyed first (Chart.getChart(canvas)?.destroy()) to avoid leaks.
 *
 * Chart.js v4.4.2 is loaded globally in base.html.
 */
(function () {
  'use strict';

  // BFA palette — matches compare.js so overlapping radars feel cohesive.
  const PALETTE = [
    { fill: 'rgba(200, 16, 46, 0.20)', border: '#C8102E' },  // BFA red
    { fill: 'rgba(181, 146, 76, 0.20)', border: '#B5924C' }, // BFA gold
    { fill: 'rgba(96, 165, 250, 0.20)', border: '#60A5FA' }, // blue
  ];

  const TEXT   = '#F2F2F2';
  const MUTED  = '#9CA3AF';
  const BORDER = '#2A2F36';

  function initScoutRadars() {
    if (typeof Chart === 'undefined') {
      // Chart.js not loaded — fail soft. Nothing else on the page depends
      // on these radars, so just log and bail.
      console.warn('BFA: Chart.js not available; scout radars not initialized');
      return 0;
    }

    const canvases = document.querySelectorAll('canvas[data-scout-radar]');
    let inited = 0;

    canvases.forEach((canvas) => {
      let cfg;
      try {
        cfg = JSON.parse(canvas.dataset.scoutRadar || '{}');
      } catch (e) {
        console.warn('BFA: scout-radar config parse failed', e, canvas);
        return;
      }
      const axes     = cfg.axes     || [];
      const datasets = cfg.datasets || [];
      // No axes (empty category) or no datasets (no players) → skip render.
      if (!axes.length || !datasets.length) return;

      // Re-init safety: destroy any prior Chart bound to this canvas
      // before constructing a new one. Critical for HTMX swaps and for
      // accidental double-DOMContentLoaded (some test runners fire it twice).
      const prior = Chart.getChart(canvas);
      if (prior) prior.destroy();

      const chartDatasets = datasets.map((d, i) => {
        const c = PALETTE[i % PALETTE.length];
        return {
          label:                d.label || `#${i + 1}`,
          data:                 (d.values || []).map(v => (v == null ? 0 : v)),
          // Stash annotations on the dataset itself so the tooltip
          // callback can look them up by data index. Chart.js ignores
          // unknown keys on datasets, so this is safe.
          _annotations:         d.annotations || [],
          backgroundColor:      c.fill,
          borderColor:          c.border,
          borderWidth:          2,
          pointBackgroundColor: c.border,
          pointBorderColor:     '#fff',
          pointRadius:          3,
        };
      });

      // Set Chart defaults globally (cheap; idempotent).
      Chart.defaults.color       = MUTED;
      Chart.defaults.borderColor = BORDER;
      Chart.defaults.font.family = "'Cairo', system-ui, sans-serif";

      new Chart(canvas, {
        type: 'radar',
        data: { labels: axes, datasets: chartDatasets },
        options: {
          responsive:          true,
          maintainAspectRatio: false,
          scales: {
            r: {
              min: 0,
              max: 10,                      // BFA scoring scale 1-10 (criteria.scale_max=10)
              ticks: {
                stepSize:      2,           // gridlines at 0/2/4/6/8/10 — readable
                color:         MUTED,
                backdropColor: 'transparent',
                font:          { size: 10 },
              },
              grid:        { color: BORDER },
              angleLines:  { color: BORDER },
              pointLabels: { color: TEXT, font: { size: 11, weight: '600' } },
            }
          },
          plugins: {
            legend: {
              display:  true,
              position: 'bottom',
              labels:   { color: MUTED, font: { size: 12 } },
            },
            tooltip: {
              callbacks: {
                label: (ctx) => {
                  const ds  = ctx.dataset;
                  const ann = (ds._annotations && ds._annotations[ctx.dataIndex]) || 'rated';
                  if (ann === 'na') {
                    return ` ${ds.label}: N/A`;
                  }
                  if (ann === 'absent') {
                    return ` ${ds.label}: — (not in player profile)`;
                  }
                  return ` ${ds.label}: ${ctx.parsed.r.toFixed(1)} / 10`;
                }
              }
            }
          }
        }
      });
      inited += 1;
    });

    return inited;
  }

  // ── Eager init on first page load ────────────────────────────────────
  document.addEventListener('DOMContentLoaded', initScoutRadars);

  // ── HTMX re-init after Latest ↔ Averaged swap ────────────────────────
  document.addEventListener('htmx:afterSwap', (event) => {
    // Only re-init when our section was the swap target. Other HTMX
    // swaps on the page (search, etc.) aren't our concern.
    const tgt = event && event.detail && event.detail.target;
    if (tgt && tgt.id === 'scout-section') {
      initScoutRadars();
    }
  });

  // Expose for ad-hoc debugging from the console.
  window.initScoutRadars = initScoutRadars;
})();
