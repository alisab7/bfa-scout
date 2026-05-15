# Cowork/Claude Code Session: BFA-Scout Phase 5d-1 — Scout Radars on Comparison Page

## Context

Phase 5d is committed (`75ad2f7`). Comparison page now has scout-derived data —
category averages, NT level, recommendation badges, per-criterion drill-down with
Latest/Averaged toggle. The deferred radar from the original 5d spec is what
this session lands.

**Phase 5d-1 adds two radar visualizations to the comparison page:**
- **A — Category-level scout radar** (4 axes: Tech / Tact / Phys / Ment), one per
  player polygon, overlaid. Paired alongside the existing Wyscout 6-axis radar.
- **C — Per-category drill-down radars** — when user expands a category sub-collapse
  in the detailed criteria comparison, a radar appears above the criteria table
  showing all players' scores on that category's criteria as overlapping polygons.

**Working folder:** `D:\BFA-Scout`. Do NOT touch `D:\BFA-Analytics` or `D:\BFA-Analytics-AWS`.

## Locked decisions

| Decision | Choice |
|---|---|
| Chart library | Chart.js (already in use for Wyscout radar in Phase 4.1) |
| Radar type | `'radar'` chart type, multiple datasets (one per player) |
| Color palette | Player 1 = `var(--brand)` red, Player 2 = `var(--accent)` gold/blue, Player 3 = third theme color |
| Scale | 0–10 fixed (criterion scale_max). Not auto-scaled. |
| Untouched criterion | No row in evaluation_scores → axis value = 0 (with tooltip note "Not rated") |
| N/A criterion | is_not_applicable=TRUE → axis value = 0 (with tooltip note "N/A") |
| Player with NO evaluations | Polygon NOT rendered for that player; legend shows "(no data)" |
| Player with all-untouched/N/A in a category | Polygon renders as flat 0-radius for that category |
| HTMX-aware | Radars re-init on `htmx:afterSwap` event so Latest/Averaged toggle re-renders them |
| Layout (Item A) | Side-by-side with Wyscout radar on desktop; stacked on mobile (<768px) |
| Layout (Item C) | Inside each `<details>` block, above the criteria table |
| Mode toggle interaction | Same toggle that swaps the textual section also re-renders both radars |

## Pre-flight gates

```powershell
# Gate 1: 5d committed, working tree clean
git log --oneline | Select-Object -First 1   # expect: top is 5d
git status                                    # expect: nothing to commit

# Gate 2: Verify Chart.js is loaded in base.html
Get-Content D:\BFA-Scout\app\templates\base.html | Select-String "chart"
# expect: a <script> tag for chart.js or chart.umd.js

# Gate 3: Existing Wyscout radar still works (regression baseline)
# Open browser: /players/compare/view?ids=2&ids=6 — Wyscout radar should render
```

## Files to create / modify

```
app/players/__init__.py            [MODIFY] compare_view + compare_scout_section enrichment:
                                              - Add per-category criteria-and-scores arrays per player
                                              - Add stable axis-label arrays for the radars
                                              - Pass to template as new context vars

app/evaluations/helpers.py         [MODIFY] Add helper:
                                              - get_radar_data_for_categories(players, all_criteria)
                                                 returns the player×category radar dataset structure

app/templates/players/
├── _compare_scout_section.html    [MODIFY] Add Item A radar at top of the section
└── _compare_scout_drilldown.html  [MODIFY] Add Item C per-category radar inside each <details>

app/static/js/
└── compare_radars.js              [NEW] Chart.js init + HTMX re-init logic

app/templates/players/compare_view.html  [MODIFY] Include the new JS file

CHANGELOG.md                       [APPEND] v0.5.0d-1 entry
PROJECT.md                         [UPDATE] Mark 5d-1 complete; queue Phase 6
```

**No schema changes.** Pure UI on data 5d already aggregates.

## Item A — 4-axis category scout radar

### Data shape needed in template context

For each player in `data.players`:

```python
p['radar_categories'] = {
    'labels': ['Technical', 'Tactical', 'Physical', 'Mentality'],  # display order
    'values': [7.4, 6.9, 7.8, 8.0],  # category averages from p['scout_data']
}
```

Already computable from existing `p['scout_data']['category_averages']`. Just shape it for Chart.js.

When `p['scout_data']` is None (no evaluations), `radar_categories` is None and the polygon isn't drawn.

### Section layout

In `_compare_scout_section.html`, add at the top of the section (just before the per-player headline cards):

```html
{% set has_radar_data = data.players | selectattr('scout_data') | list | length > 0 %}
{% if has_radar_data %}
  <div class="grid md:grid-cols-2 gap-6 mb-6">
    {# Wyscout radar already rendered elsewhere — link to it OR move it inside this grid as you prefer #}

    {# Scout radar (4-axis) #}
    <div class="rounded-lg p-4" style="background:var(--bg);border:1px solid var(--border);">
      <h3 class="text-sm font-semibold mb-3" style="color:var(--text);">Scout Categories</h3>
      <canvas id="scout-radar-categories"
              data-radar-config='{
                "type": "category",
                "labels": {{ scout_radar_categories.labels | tojson | safe }},
                "datasets": {{ scout_radar_categories.datasets | tojson | safe }}
              }'></canvas>
    </div>
  </div>
{% endif %}
```

Where `scout_radar_categories` is built in the enrichment helper:

```python
def build_radar_categories(players):
    """Build Chart.js dataset structure for the 4-axis category radar."""
    CAT_ORDER = ['TECH', 'TACT', 'PHYS', 'MENT']
    CAT_LABELS = ['Technical', 'Tactical', 'Physical', 'Mentality']

    palette = ['#C8102E', '#B5924C', '#5B9BD5']  # match existing Wyscout radar palette

    datasets = []
    for idx, p in enumerate(players):
        if not p.get('scout_data'):
            continue  # skip players with no evaluations
        averages = p['scout_data']['category_averages']
        values = [averages.get(cat, 0) for cat in CAT_ORDER]
        color = palette[idx % len(palette)]
        datasets.append({
            'label': p['full_name'],
            'data': values,
            'backgroundColor': color + '33',  # 20% alpha
            'borderColor': color,
            'borderWidth': 2,
            'pointBackgroundColor': color,
        })

    return {'labels': CAT_LABELS, 'datasets': datasets}
```

Pass to template via `_enrich_for_scout_section` (the helper Cowork extracted in 5d patch).

### JS init in `compare_radars.js`

```javascript
function initScoutRadars() {
    const canvases = document.querySelectorAll('canvas[data-radar-config]');
    canvases.forEach(canvas => {
        // Destroy any existing chart on this canvas (re-init scenario)
        const existing = Chart.getChart(canvas);
        if (existing) existing.destroy();

        let config;
        try {
            config = JSON.parse(canvas.getAttribute('data-radar-config'));
        } catch (e) {
            console.error('Invalid radar config on', canvas, e);
            return;
        }

        new Chart(canvas, {
            type: 'radar',
            data: { labels: config.labels, datasets: config.datasets },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                scales: {
                    r: {
                        beginAtZero: true,
                        suggestedMax: 10,
                        ticks: { stepSize: 2, color: 'rgba(255,255,255,0.5)' },
                        grid:  { color: 'rgba(255,255,255,0.1)' },
                        angleLines: { color: 'rgba(255,255,255,0.2)' },
                        pointLabels: { color: 'rgba(255,255,255,0.85)', font: { size: 11 } }
                    }
                },
                plugins: {
                    legend: { position: 'top', labels: { color: 'rgba(255,255,255,0.85)' } },
                    tooltip: {
                        callbacks: {
                            // For per-category radar — show "Not rated" / "N/A" when value === 0 from absence
                            label: (ctx) => {
                                const value = ctx.parsed.r;
                                const dataset = ctx.dataset;
                                const meta = dataset.meta_per_axis && dataset.meta_per_axis[ctx.dataIndex];
                                if (meta === 'untouched') return `${dataset.label}: Not rated`;
                                if (meta === 'na')        return `${dataset.label}: N/A`;
                                return `${dataset.label}: ${value.toFixed(1)}`;
                            }
                        }
                    }
                },
                elements: { line: { borderJoinStyle: 'round' } }
            }
        });
    });
}

// Initial load
document.addEventListener('DOMContentLoaded', initScoutRadars);

// HTMX re-init: when scout section is swapped (Latest ↔ Averaged toggle), re-init radars
document.addEventListener('htmx:afterSwap', (event) => {
    if (event.detail.target.id === 'scout-section') {
        initScoutRadars();
    }
});
```

The `meta_per_axis` annotation is for Item C below, where individual criteria can be untouched / N/A / rated. For Item A (category averages), values are always real averages (or 0 if no data) — meta is empty.

### Include the JS

In `compare_view.html` (and any template that includes the scout section), add:

```html
<script src="{{ url_for('static', filename='js/compare_radars.js') }}"></script>
```

Place after Chart.js load.

## Item C — Per-category drill-down radars

### Data shape

For each category in the drilldown, build per-player datasets where each axis = one criterion in that category:

```python
def build_radar_for_category(category_code, criteria_in_cat, players):
    """Build Chart.js dataset for a single category's drill-down radar.
    Axes = criteria in this category (sorted by criterion sort_order).
    Each player polygon = their scores for those criteria.
    Untouched / N/A criterion → value = 0 with axis-meta annotation.
    """
    palette = ['#C8102E', '#B5924C', '#5B9BD5']

    labels = [c['name_en'] for c in criteria_in_cat]
    crit_ids = [c['criterion_id'] for c in criteria_in_cat]

    datasets = []
    for idx, p in enumerate(players):
        if not p.get('scout_data'):
            continue
        scores_by_id = {s['criterion_id']: s for s in p['scout_data']['scores']}
        values = []
        meta = []
        for cid in crit_ids:
            s = scores_by_id.get(cid)
            if s is None:
                values.append(0)
                meta.append('untouched')
            elif s.get('is_not_applicable'):
                values.append(0)
                meta.append('na')
            elif s.get('score') is not None:
                values.append(float(s['score']))
                meta.append('rated')
            else:
                values.append(0)
                meta.append('untouched')

        color = palette[idx % len(palette)]
        datasets.append({
            'label': p['full_name'],
            'data': values,
            'meta_per_axis': meta,
            'backgroundColor': color + '33',
            'borderColor': color,
            'borderWidth': 2,
            'pointBackgroundColor': color,
        })

    return {'labels': labels, 'datasets': datasets}
```

### Drilldown template additions

In `_compare_scout_drilldown.html`, inside each `<details>` block (before the existing criteria table):

```html
<div class="px-3 pt-3">
  <canvas id="scout-radar-cat-{{ cat_code }}"
          style="max-height: 320px;"
          data-radar-config='{
            "type": "per_category",
            "labels": {{ cat_radars[cat_code].labels | tojson | safe }},
            "datasets": {{ cat_radars[cat_code].datasets | tojson | safe }}
          }'></canvas>
</div>
```

Where `cat_radars` is built in the enrichment helper as a dict keyed by category_code.

### Performance consideration

5 simultaneous radars on one page (1 category overall + 4 per-category). On desktop fine, on mobile slower. Two mitigations:

1. Per-category radars only initialize when their `<details>` block is expanded (lazy-init via `toggle` event listener)
2. Lower point count + higher Chart.js `aspectRatio` config

The lazy-init pattern:

```javascript
function initLazyRadars() {
    document.querySelectorAll('details').forEach(d => {
        d.addEventListener('toggle', () => {
            if (d.open) {
                const canvas = d.querySelector('canvas[data-radar-config]');
                if (canvas && !Chart.getChart(canvas)) {
                    initRadarOnCanvas(canvas);
                }
            }
        });
    });
}
```

`initRadarOnCanvas` is the per-canvas init logic factored from `initScoutRadars`.

The category-level radar (Item A) is NOT lazy — it's visible immediately on page load.

## Verification

1. **Restart Flask** after JS/Python changes (templates auto-reload, JS files auto-reload via Flask debug)
2. **Browser test:**

| # | Test | Expected |
|---|---|---|
| 1 | Visit `/players/compare/view?ids=2&ids=6` | Scout section shows 4-axis category radar at top with Arthur + Bouhra polygons |
| 2 | Toggle to Averaged | Page does not scroll. Scout section swaps via HTMX. Category radar re-renders with averaged data (visibly different polygon shape) |
| 3 | Expand Tactical drill-down | A new radar appears above the criteria table with axes for the Tactical criteria union |
| 4 | Tooltip on a radar point where one player has no rating | Shows "Not rated" or "N/A" instead of 0 |
| 5 | Toggle Averaged → Latest while Tactical drilldown is open | Tactical radar re-renders with Latest data |
| 6 | Compare 3 players | All 3 polygons rendered with distinct colors |
| 7 | Player without evaluations in the comparison | That player's polygon does NOT render; legend shows their entry as "(no data)" or omitted |
| 8 | Mobile view (< 768px) | Category radar stacks below Wyscout radar; no horizontal overflow |
| 9 | Existing Wyscout radar | Still renders (regression check) |

3. **Synthetic E2E (`migrations/_e2e_5d1.py`):**

```python
# Test 1: scout_radar_categories context var present and non-empty
resp = client.get('/players/compare/view?ids=2&ids=6')
html = resp.get_data(as_text=True)
assert 'scout-radar-categories' in html
assert 'data-radar-config' in html

# Test 2: per-category radars present
for cat in ['TECH', 'TACT', 'PHYS', 'MENT']:
    assert f'scout-radar-cat-{cat}' in html

# Test 3: meta_per_axis annotations exist for per-category radars
import re
configs = re.findall(r'data-radar-config=\'(\{[^\']+\})\'', html)
per_category_configs = [json.loads(c) for c in configs if 'per_category' in c]
assert len(per_category_configs) >= 1
for c in per_category_configs:
    for ds in c['datasets']:
        assert 'meta_per_axis' in ds
        assert len(ds['meta_per_axis']) == len(ds['data'])

# Test 4: HTMX swap path returns radars
resp = client.get('/players/compare/scout-section?ids=2&ids=6&scout_mode=averaged')
html = resp.get_data(as_text=True)
assert 'scout-radar-categories' in html  # category radar present in partial
```

## Acceptance criteria

- ✅ Pre-flight gates pass
- ✅ No schema changes
- ✅ Category radar renders on initial page load with both players' polygons
- ✅ Category radar re-renders on Latest/Averaged toggle without page reload
- ✅ Per-category radars render lazily when category drill-downs are expanded
- ✅ Untouched / N/A criteria show in tooltip with appropriate label
- ✅ Player with no evaluations: polygon not drawn; legend handles gracefully
- ✅ Mobile view stacks correctly (< 768px)
- ✅ Existing Wyscout radar (Phase 4.1) still works
- ✅ Existing scout section (Phase 5d) text features still work (drill-down, mode toggle, match label)
- ✅ HTMX swap re-initializes radars (htmx:afterSwap listener)
- ✅ Synthetic E2E PASS

## Hard rules

- ❌ Do NOT modify schema (no migration needed)
- ❌ Do NOT modify the Wyscout radar (Phase 4.1) — only ADD scout radars
- ❌ Do NOT modify the textual scout section content (it's already shipped in 5d)
- ❌ Do NOT use flask.test_client() for verification — restart real Flask
- ❌ Do NOT initialize git or commit — Ali commits manually
- ❌ Do NOT touch `D:\BFA-Analytics` or `D:\BFA-Analytics-AWS`
- ❌ Do NOT add ALTER statements to schema.sql
- ❌ Do NOT replace Chart.js with another library
- ❌ Do NOT use a different palette than the existing Wyscout radar (consistency matters)
- ✅ Restart Flask after each significant change
- ✅ Test all 9 browser scenarios + E2E
- ✅ Append v0.5.0d-1 entry to CHANGELOG.md
- ✅ Mark 5d-1 complete in PROJECT.md, queue Phase 6

## Out of scope (do NOT build)

- Multi-season Career stats (Phase 4.2 — after Phase 6)
- Player Passport PDF (Phase 6)
- Per-criterion individual-axis radar (49 axes, the rejected option B)
- Schema changes
- New endpoints beyond the existing partial route
- Audit logging (no state mutation)
- Translation of axis labels to Arabic (deferred)

## Session discipline

- Target: 4–5 messages
- Build Item A first, verify in browser, then Item C
- After session, Ali commits:
  ```powershell
  cd D:\BFA-Scout
  git add -A
  git commit -m "Phase 5d-1: Scout radars on comparison page (4-axis category radar + per-category drill-down radars)"
  ```
