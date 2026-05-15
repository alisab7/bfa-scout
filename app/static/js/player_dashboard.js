/**
 * player_dashboard.js
 * Initializes Chart.js radar + 3 trend line charts on the player profile page.
 *
 * Inputs:
 *   <canvas id="radarChart" data-radar-seasons='[{season_label, scores:{label:0-100, ...}}, ...]'>
 *     — most-recent first; current season drawn solid, prior season(s) dashed
 *   window.BFA.trendsUrl — endpoint URL for /wyscout/trends/<player_id>
 */

(function () {
  'use strict';

  // ── Color tokens matching CSS vars ──────────────────────────────────────
  const BRAND   = '#C8102E';
  const ACCENT  = '#B5924C';
  const TEXT    = '#F2F2F2';
  const MUTED   = '#9CA3AF';
  const SURFACE = '#1A1F26';
  const BORDER  = '#2A2F36';
  const GREEN   = '#22C55E';
  const BLUE    = '#60A5FA';

  // ── Chart.js global defaults ─────────────────────────────────────────────
  Chart.defaults.color = MUTED;
  Chart.defaults.borderColor = BORDER;
  Chart.defaults.font.family = "'Cairo', system-ui, sans-serif";

  // ── Radar chart ──────────────────────────────────────────────────────────
  function initRadar() {
    const canvas = document.getElementById('radarChart');
    if (!canvas) return;

    let seasons = [];
    try {
      seasons = JSON.parse(canvas.dataset.radarSeasons || '[]');
    } catch (e) {
      console.warn('BFA: radar data parse failed', e);
      return;
    }
    if (!seasons.length) return;

    // Use the axis labels from the first season's scores dict so the JS
    // stays in sync with whatever RADAR_AXES the backend defines.
    const labels = Object.keys(seasons[0].scores);

    const datasets = seasons.map((s, i) => ({
      label: s.season_label,
      data:  labels.map(l => s.scores[l] ?? 0),
      backgroundColor: i === 0 ? 'rgba(200, 16, 46, 0.20)'  // BFA red, current
                                : 'rgba(181, 146, 76, 0.15)', // BFA gold, prior
      borderColor:     i === 0 ? BRAND  : ACCENT,
      borderWidth:     2,
      borderDash:      i === 0 ? []     : [6, 4],
      pointBackgroundColor: i === 0 ? BRAND  : ACCENT,
      pointBorderColor: '#fff',
      pointRadius:     i === 0 ? 4 : 3,
    }));

    new Chart(canvas, {
      type: 'radar',
      data: { labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: true,
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
            pointLabels: {
              color: TEXT,
              font:  { size: 12, weight: '600' },
            }
          }
        },
        plugins: {
          legend: {
            display: datasets.length > 1,
            position: 'bottom',
            labels: { color: MUTED, font: { size: 11 } },
          },
          tooltip: {
            callbacks: {
              label: ctx => ` ${ctx.dataset.label}: ${ctx.parsed.r.toFixed(1)} / 100`
            }
          }
        }
      }
    });
  }

  // ── Line chart factory ───────────────────────────────────────────────────
  function makeLineChart(canvasId, label, color, labels, data) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    new Chart(canvas, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [{
          label: label,
          data: data,
          borderColor: color,
          backgroundColor: color + '22',
          borderWidth: 2,
          pointRadius: 3,
          pointBackgroundColor: color,
          tension: 0.35,
          fill: true,
          spanGaps: true,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        scales: {
          x: {
            grid: { color: BORDER },
            ticks: { color: MUTED, font: { size: 10 }, maxTicksLimit: 8 },
          },
          y: {
            grid: { color: BORDER },
            ticks: { color: MUTED, font: { size: 10 } },
            beginAtZero: true,
          }
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: SURFACE,
            borderColor: BORDER,
            borderWidth: 1,
            titleColor: TEXT,
            bodyColor: MUTED,
          }
        }
      }
    });
  }

  // ── Trend charts via fetch ───────────────────────────────────────────────
  function initTrends(trendsUrl) {
    if (!trendsUrl) return;

    fetch(trendsUrl)
      .then(r => r.json())
      .then(data => {
        const labels = data.labels || [];
        makeLineChart('trendGoals',    'G+A per match',     BRAND,  labels, data.goals_assists || []);
        makeLineChart('trendPassing',  'Pass accuracy %',   GREEN,  labels, data.pass_accuracy || []);
        makeLineChart('trendDuels',    'Duel win rate %',   BLUE,   labels, data.duel_win_rate || []);
      })
      .catch(err => {
        console.warn('BFA: trends fetch failed', err);
      });
  }

  // ── Boot ─────────────────────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', function () {
    const bfa = window.BFA || {};

    initRadar();

    if (bfa.trendsUrl) {
      initTrends(bfa.trendsUrl);
    }
  });

})();
