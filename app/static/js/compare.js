/**
 * compare.js
 * Renders an overlapping Chart.js radar for 2-3 players on the comparison view.
 *
 * Input:
 *   <canvas id="compareRadar" data-compare='{
 *     "players": [
 *       {"id": int, "full_name": str, "radar_scores": {label: 0-100, ...}},
 *       ...
 *     ],
 *     ...
 *   }'>
 */
(function () {
  'use strict';

  const PALETTE = [
    { fill: 'rgba(200, 16, 46, 0.20)', border: '#C8102E' },  // BFA red
    { fill: 'rgba(181, 146, 76, 0.20)', border: '#B5924C' }, // BFA gold
    { fill: 'rgba(96, 165, 250, 0.20)', border: '#60A5FA' }, // blue
  ];

  const TEXT   = '#F2F2F2';
  const MUTED  = '#9CA3AF';
  const BORDER = '#2A2F36';

  document.addEventListener('DOMContentLoaded', function () {
    const canvas = document.getElementById('compareRadar');
    if (!canvas) return;

    let data;
    try {
      data = JSON.parse(canvas.dataset.compare || '{}');
    } catch (e) {
      console.warn('BFA: compare data parse failed', e);
      return;
    }
    const players = (data && data.players) || [];
    if (!players.length) return;

    // Pull axis labels from the first player's radar_scores so the JS stays
    // aligned with whatever RADAR_AXES the backend defines.
    const labels = Object.keys(players[0].radar_scores || {});
    if (!labels.length) return;

    const datasets = players.map((p, i) => {
      const c = PALETTE[i % PALETTE.length];
      return {
        label:                 p.full_name,
        data:                  labels.map(l => p.radar_scores[l] ?? 0),
        backgroundColor:       c.fill,
        borderColor:           c.border,
        borderWidth:           2,
        pointBackgroundColor:  c.border,
        pointBorderColor:      '#fff',
        pointRadius:           4,
      };
    });

    Chart.defaults.color = MUTED;
    Chart.defaults.borderColor = BORDER;
    Chart.defaults.font.family = "'Cairo', system-ui, sans-serif";

    new Chart(canvas, {
      type: 'radar',
      data: { labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          r: {
            min: 0,
            max: 100,
            ticks: {
              stepSize: 25,
              color: MUTED,
              backdropColor: 'transparent',
              font: { size: 10 },
            },
            grid:        { color: BORDER },
            angleLines:  { color: BORDER },
            pointLabels: { color: TEXT, font: { size: 12, weight: '600' } },
          }
        },
        plugins: {
          legend: {
            display: true,
            position: 'bottom',
            labels: { color: MUTED, font: { size: 12 } },
          },
          tooltip: {
            callbacks: {
              label: ctx => ` ${ctx.dataset.label}: ${ctx.parsed.r.toFixed(1)} / 100`
            }
          }
        }
      }
    });
  });
})();
