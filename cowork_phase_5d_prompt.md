# Cowork/Claude Code Session: BFA-Scout Phase 5d — Scout Dimension on Comparison Page

## Context

Phase 5c-3 + follow-up are committed. Eleven phases on master. Real evaluation
data exists (5+ submitted evaluations across 3 players) — finally enough to
design 5d against actual data shape, not speculation.

**Phase 5d adds scout-derived data to the comparison page.** Currently the
comparison view shows only Wyscout career stats + radar. After 5d, scouts can
compare players on scout judgment too: category averages, per-criterion drill-down,
divergence between Wyscout and scout signals.

This is **Phase 5d**, parked since Phase 4.1 specifically because it depended
on real evaluation data. Now unblocked.

**Working folder:** `D:\BFA-Scout`. Do NOT touch `D:\BFA-Analytics` or `D:\BFA-Analytics-AWS`.

**Local environment:**
- PostgreSQL 15 native, database `bfa_scout`, user `bfa`, password `bfa2025`
- Python venv at `.venv`
- Flask via `flask --app wsgi run --debug`

## Goal

Comparison page (`/players/compare/view`) currently shows:
1. Bio header per player (photo, name, position, club, age)
2. Career stats table (Matches, Minutes, Goals, Assists, Shots, Pass%, Duels%, etc.)
3. 6-axis Wyscout radar overlay

After 5d, add a third section below the radar:
4. **Scout evaluation summary** — same N players, scout-derived data:
   - **Headline:** Category averages (Tech / Tact / Phys / Ment) + recommendation badge + NT readiness level + evaluator count
   - **Per-criterion drill-down** (expandable): full criteria union across selected players' position groups, with NULL cells marked "—"
   - **Mode toggle:** Latest (default) vs Averaged-across-all-evaluations
   - **Scout-vs-Wyscout overlay** (the "do the numbers and the eye agree?" view) — secondary radar with scout categories alongside the existing Wyscout radar

## Locked decisions

| Decision | Choice |
|---|---|
| Cross-position rule | Allow any combination. Criteria union shown. NULL cells = "—" |
| Multi-evaluator aggregation | Latest by default; toggle to averaged-across-all |
| Scout section position | Below Wyscout section, visually distinct (separate card with "Scout Assessment" header) |
| Headline scout data | Category averages (Tech/Tact/Phys/Ment), NT readiness level, recommendation, evaluator count |
| N/A handling | Excluded from averages. Per-criterion cells show "N/A · غير متخصص" badge instead of value |
| Untouched handling | No row exists in evaluation_scores → cell shows "—" (same as cross-position NULL) |
| Soft-deleted evaluations | EXCLUDED from all aggregation (deleted_at IS NULL filter — Phase 5c-3 invariant) |
| Locked evaluations | INCLUDED (locked is a workflow state, not data hiding) |
| Per-criterion expand | Native `<details>` collapsible, grouped by category, sub-collapse per category |
| Scout-vs-Wyscout radar | Render alongside (not on top of) existing Wyscout radar. Two side-by-side radars. |
| Number of players | 2-3 (same as Wyscout comparison) |
| GK rule | Existing GK-vs-outfield block STILL applies for the entire compare page (not just Wyscout) |
| Player without evaluations | Scout section shows "No evaluations yet" placeholder for that player's column |
| All players without evaluations | Scout section shown but reads "No scout data available for any selected player" |

## Data shape

For each selected player, scout section needs:

```python
{
    'player_id': int,
    'evaluation_count': int,                        # active (non-deleted), submitted-or-locked
    'latest_eval': {
        'id', 'submitted_at', 'evaluator_name',
        'nt_readiness_level',                       # senior/u23/u20/u17/not_ready
        'recommendation',                           # call_up/shortlist/monitor/not_at_level/release
        'summary',                                  # scout's free text (truncated to 200 chars)
        'category_averages': {                      # only categories with at least 1 rated criterion
            'tech': 7.4,
            'tact': 6.9,
            'phys': 7.8,
            'ment': 8.0,
        },
        'scores': [
            {'criterion_id', 'criterion_code', 'name_en', 'name_ar',
             'category_code', 'score', 'is_not_applicable'},
            ...
        ]
    } | None,
    'averaged_eval': {
        # Same shape as latest_eval but averaged across all submitted+locked, non-deleted
        # 'scores' shows averages per criterion across the N evaluations that rated it
        # NT level: most-frequent value (mode) across evaluations; ties: most recent wins
        # Recommendation: same — most-frequent (mode), ties broken by most recent
    } | None,
}
```

If a player has 0 active evaluations, both `latest_eval` and `averaged_eval` are `None`.

## Pre-flight gates

```powershell
# Gate 1: 5c-3 follow-up committed
git log --oneline | Select-String "5c-3"
# expect: at least one commit

# Gate 2: clean working tree
git status
# expect: nothing to commit

# Gate 3: at least 5 submitted-or-locked, non-deleted evaluations exist
psql -U bfa -d bfa_scout -c "SELECT COUNT(*) FROM evaluations WHERE status IN ('submitted','locked') AND deleted_at IS NULL;"
# expect: 5 or more (depends on Ali's testing)

# Gate 4: comparison route exists and renders 200
curl http://localhost:5000/players/compare -o NUL -w "%{http_code}"
# expect: 200 or 302 (auth redirect — fine)

# Gate 5: existing Wyscout comparison logic works
curl http://localhost:5000/players/compare/view?ids=2&ids=6 -o NUL -w "%{http_code}"
# expect: 200 or 302
```

## Files to create / modify

```
app/players/
└── __init__.py                          [MODIFY] compare_view() route enriches each player with scout data

app/evaluations/
└── helpers.py                           [MODIFY] Add three functions:
                                                    - get_player_evaluation_aggregate(player_id, mode='latest')
                                                    - compute_category_averages(scores)
                                                    - get_evaluation_count_active(player_id)

app/templates/players/
└── compare_view.html                    [MODIFY] Add scout section below the existing Wyscout section

app/templates/players/_compare_scout_section.html  [NEW] The scout section partial
app/templates/players/_compare_scout_card.html     [NEW] Per-player scout card (one column)
app/templates/players/_compare_scout_drilldown.html [NEW] Per-criterion table (expandable)

app/static/js/                           [NEW IF NOT EXISTS] compare_radar.js (extracted radar logic if needed)

CHANGELOG.md                             [APPEND] v0.5.0d entry
PROJECT.md                               [UPDATE] Mark 5d complete; queue Phase 6
```

**No schema changes.** All data already in `evaluations` + `evaluation_scores`.

## Implementation

### Helpers — `app/evaluations/helpers.py`

```python
def compute_category_averages(scores: list[dict]) -> dict:
    """
    Returns {category_code: avg_score, ...}
    Only includes categories with at least 1 rated (not N/A, not None) score.
    N/A and None are excluded entirely.
    """
    by_cat = {}
    for s in scores:
        if s.get('is_not_applicable') or s.get('score') is None:
            continue
        cat = s.get('category_code')
        if cat not in by_cat:
            by_cat[cat] = {'sum': 0.0, 'count': 0}
        by_cat[cat]['sum'] += float(s['score'])
        by_cat[cat]['count'] += 1

    return {
        cat: round(data['sum'] / data['count'], 1)
        for cat, data in by_cat.items()
        if data['count'] > 0
    }


def get_evaluation_count_active(player_id: int) -> int:
    """Count submitted+locked, non-deleted evaluations."""
    sql = """
        SELECT COUNT(*) AS n
        FROM evaluations
        WHERE player_id = %s
          AND status IN ('submitted', 'locked')
          AND deleted_at IS NULL
    """
    # ...


def get_player_evaluation_aggregate(player_id: int, mode: str = 'latest') -> dict | None:
    """
    Returns the player's evaluation summary for the comparison page.
    mode='latest': returns the most recently submitted+locked, non-deleted eval
    mode='averaged': averages all submitted+locked, non-deleted evals

    Returns None if no evaluations match.
    Always filters: status IN ('submitted','locked') AND deleted_at IS NULL.
    """
    if mode not in ('latest', 'averaged'):
        raise ValueError(f"mode must be 'latest' or 'averaged', got {mode!r}")

    if mode == 'latest':
        # Get most recent non-deleted eval
        eval_sql = """
            SELECT e.id, e.submitted_at, e.locked_at,
                   e.nt_readiness_level, e.recommendation, e.summary,
                   u.full_name AS evaluator_name
            FROM evaluations e
            LEFT JOIN users u ON u.id = e.evaluator_id
            WHERE e.player_id = %s
              AND e.status IN ('submitted', 'locked')
              AND e.deleted_at IS NULL
            ORDER BY e.submitted_at DESC NULLS LAST
            LIMIT 1
        """
        # Fetch eval row
        # If None, return None
        # Fetch scores for this eval (with category JOIN)
        # Compute category_averages
        # Return shape per spec

    else:  # 'averaged'
        # Get all non-deleted evals for this player
        # Fetch all scores across all those evals
        # For each criterion: average across evals where it was rated
        # For NT level + recommendation: mode (most frequent), ties → most recent
        # Compute category_averages from the averaged scores
        # Return shape per spec — evaluator_name is "N evaluations averaged"
```

The `averaged` mode is the trickier path. Pseudocode for the per-criterion averaging:

```python
# For each criterion, collect all rated scores (excluding N/A and untouched)
crit_scores = {}  # criterion_id -> [list of values]
for ev in active_evaluations:
    for s in ev.scores:
        if s['score'] is None or s['is_not_applicable']:
            continue
        crit_scores.setdefault(s['criterion_id'], []).append(float(s['score']))

# Compute averages
averaged_scores = []
for cid, values in crit_scores.items():
    if values:
        averaged_scores.append({
            'criterion_id': cid,
            ...,
            'score': round(sum(values) / len(values), 1),
            'is_not_applicable': False,
            'eval_count': len(values),  # NEW field — for "averaged from N reports" tooltip
        })
```

For NT level mode-finding:

```python
from collections import Counter
nt_levels = [ev['nt_readiness_level'] for ev in active_evals if ev['nt_readiness_level']]
if nt_levels:
    counts = Counter(nt_levels)
    max_count = max(counts.values())
    # Resolve ties by most recent
    candidates = [lvl for lvl, c in counts.items() if c == max_count]
    if len(candidates) == 1:
        nt_level = candidates[0]
    else:
        # Find most recent eval with one of the tied levels
        for ev in sorted(active_evals, key=lambda e: e['submitted_at'], reverse=True):
            if ev['nt_readiness_level'] in candidates:
                nt_level = ev['nt_readiness_level']
                break
```

### Route enrichment — `app/players/__init__.py compare_view()`

Existing route fetches `players` and `wyscout_aggregate` per id. After that:

```python
mode = request.args.get('scout_mode', 'latest')
if mode not in ('latest', 'averaged'):
    mode = 'latest'

for p in players:
    p['eval_count'] = get_evaluation_count_active(p['id'])
    p['scout_data'] = get_player_evaluation_aggregate(p['id'], mode=mode) if p['eval_count'] > 0 else None

# Build the union of criteria across all selected players' position groups
all_criteria = []
seen = set()
for p in players:
    pg = p.get('position_group_id')
    if not pg:
        continue
    pg_criteria = get_form_criteria(pg)  # already exists in helpers
    for c in pg_criteria:
        if c['criterion_id'] not in seen:
            all_criteria.append(c)
            seen.add(c['criterion_id'])

# Sort by category sort_order, then criterion sort_order
all_criteria.sort(key=lambda c: (c['category_sort_order'], c['sort_order']))

return render_template('players/compare_view.html',
                       players=players,
                       wyscout=wyscout_data,
                       scout_mode=mode,
                       all_criteria=all_criteria,
                       ...)
```

### Template — `compare_view.html` (additions)

After existing Wyscout section, add:

```html
{# Scout Assessment Section — Phase 5d #}
<section class="rounded-xl p-6 mb-6"
         style="background:var(--surface);border:1px solid var(--border);">
  <div class="flex items-center justify-between mb-4">
    <h2 class="text-lg font-semibold" style="color:var(--accent);">Scout Assessment</h2>

    {# Mode toggle #}
    <div class="flex gap-1 text-xs">
      <a href="?{{ urlencode_with('scout_mode', 'latest') }}"
         class="px-3 py-1 rounded {% if scout_mode == 'latest' %}font-semibold{% endif %}"
         style="background:{% if scout_mode == 'latest' %}var(--brand);color:white{% else %}var(--bg);color:var(--text-muted);border:1px solid var(--border){% endif %};">
        Latest
      </a>
      <a href="?{{ urlencode_with('scout_mode', 'averaged') }}"
         class="px-3 py-1 rounded {% if scout_mode == 'averaged' %}font-semibold{% endif %}"
         style="background:{% if scout_mode == 'averaged' %}var(--brand);color:white{% else %}var(--bg);color:var(--text-muted);border:1px solid var(--border){% endif %};">
        Averaged
      </a>
    </div>
  </div>

  {% include 'players/_compare_scout_section.html' %}
</section>
```

### `_compare_scout_section.html` (new)

Headline cards (one per player) showing category averages + key labels:

```html
<div class="grid gap-4" style="grid-template-columns: repeat({{ players|length }}, 1fr);">
  {% for p in players %}
    <div class="rounded-lg p-4" style="background:var(--bg);border:1px solid var(--border);">
      <h3 class="font-semibold text-sm mb-2">{{ p.full_name }}</h3>

      {% if p.scout_data %}
        <div class="text-xs mb-3" style="color:var(--text-muted);">
          {% if scout_mode == 'latest' %}
            Latest by {{ p.scout_data.evaluator_name }}
            · {{ p.scout_data.submitted_at.strftime('%Y-%m-%d') }}
          {% else %}
            Averaged across {{ p.eval_count }} evaluation{{ '' if p.eval_count == 1 else 's' }}
          {% endif %}
        </div>

        {# Category averages #}
        <div class="space-y-1 mb-3">
          {% for cat_code in ['tech','tact','phys','ment'] %}
            {% set avg = p.scout_data.category_averages.get(cat_code) %}
            <div class="flex justify-between text-xs">
              <span>{{ CATEGORY_LABEL_EN.get(cat_code, cat_code) }}</span>
              <span class="font-mono"
                    style="color:{% if avg %}var(--brand){% else %}var(--text-muted){% endif %};">
                {{ avg if avg else '—' }}
              </span>
            </div>
          {% endfor %}
        </div>

        {# NT level + recommendation badges #}
        <div class="flex gap-2 flex-wrap">
          <span class="px-2 py-1 rounded text-xs font-semibold"
                style="background:var(--accent);color:var(--bg);">
            {{ NT_LEVEL_LABEL_EN.get(p.scout_data.nt_readiness_level) or '—' }}
          </span>
          <span class="px-2 py-1 rounded text-xs font-semibold"
                style="background:var(--brand);color:white;">
            {{ RECOMMENDATION_LABEL_EN.get(p.scout_data.recommendation) or '—' }}
          </span>
        </div>
      {% else %}
        <p class="text-xs" style="color:var(--text-muted);">No evaluations yet</p>
      {% endif %}
    </div>
  {% endfor %}
</div>

{# Per-criterion expandable drill-down #}
{% if any_player_has_scout_data %}
  <details class="mt-4 rounded-lg" style="background:var(--bg);border:1px solid var(--border);">
    <summary class="px-4 py-3 cursor-pointer font-semibold">
      Detailed criteria comparison ({{ all_criteria|length }} criteria across {{ players|length }} players)
    </summary>
    <div class="px-4 pb-4">
      {% include 'players/_compare_scout_drilldown.html' %}
    </div>
  </details>
{% endif %}
```

### `_compare_scout_drilldown.html` (new)

Per-criterion table grouped by category. Each category is a sub-collapse:

```html
{% set grouped_criteria = group_criteria_by_category(all_criteria) %}
{% for cat in grouped_criteria %}
  <details class="rounded mb-2" style="background:var(--surface);border:1px solid var(--border);">
    <summary class="px-3 py-2 cursor-pointer flex justify-between">
      <span class="font-semibold text-sm">
        {{ cat.name_en }}
        <span class="text-xs ml-2" style="color:var(--text-muted);">{{ cat.name_ar }}</span>
      </span>
    </summary>
    <table class="w-full text-xs">
      <thead>
        <tr>
          <th class="text-left p-2">Criterion</th>
          {% for p in players %}
            <th class="text-right p-2">{{ p.full_name|truncate(15, True) }}</th>
          {% endfor %}
        </tr>
      </thead>
      <tbody>
        {% for crit in cat['items'] %}
          <tr>
            <td class="p-2">
              {{ crit.name_en }}
              <span class="text-xs ml-1" style="color:var(--text-muted);">{{ crit.name_ar }}</span>
            </td>
            {% for p in players %}
              {% set s = (p.scout_data and p.scout_data.scores | selectattr('criterion_id', 'equalto', crit.criterion_id) | list | first) %}
              <td class="p-2 text-right font-mono">
                {% if s and s.is_not_applicable %}
                  <span class="px-1.5 py-0.5 rounded text-xs"
                        style="background:var(--surface);color:var(--text-muted);">N/A</span>
                {% elif s and s.score is not none %}
                  <span style="color:var(--brand);">{{ '%.1f'|format(s.score) }}</span>
                  {% if scout_mode == 'averaged' and s.eval_count %}
                    <span class="text-xs" style="color:var(--text-muted);">({{ s.eval_count }})</span>
                  {% endif %}
                {% else %}
                  <span style="color:var(--text-muted);">—</span>
                {% endif %}
              </td>
            {% endfor %}
          </tr>
        {% endfor %}
      </tbody>
    </table>
  </details>
{% endfor %}
```

### Scout-vs-Wyscout radar (nice-to-have, conditional)

Phase 4.1 already has a Wyscout radar. To add a scout radar alongside it:

In `compare_view.html`, after the existing radar div, conditionally render:

```html
{% if any_player_has_scout_data %}
  <div class="rounded-xl p-6 mb-6"
       style="background:var(--surface);border:1px solid var(--border);">
    <h2 class="text-lg font-semibold mb-4" style="color:var(--accent);">Scout Radar</h2>

    {# 4-axis: Tech / Tact / Phys / Ment #}
    <div id="scout-radar"></div>
    <script>
      // Same Chart.js / d3 pattern as the Wyscout radar
      // Axes: tech, tact, phys, ment
      // Each player's polygon = their category_averages
      // Render alongside (not on top of) Wyscout radar — separate canvas/svg
    </script>
  </div>
{% endif %}
```

If implementing the radar adds significant complexity, **defer it** to a follow-up patch. The category-average cards in `_compare_scout_section.html` already convey the information textually. Document the deferral in the result file.

### Helper to register as Jinja global

Already-registered globals: `compute_eligibility_status`, `nt_readiness_summary`, `group_scores_by_category`, `flag_emoji`, `NATIONALITY_CHOICES`, `NT_LEVEL_LABEL_AR`, `RECOMMENDATION_LABEL_AR`, `ELIGIBILITY_STATUS_LABEL_AR`, `NATIONALITY_ROUTE_LABEL_EN`.

New globals needed:
- `CATEGORY_LABEL_EN = {'tech': 'Technical', 'tact': 'Tactical', 'phys': 'Physical', 'ment': 'Mentality'}`
- `NT_LEVEL_LABEL_EN = {'senior': 'Senior NT', 'u23': 'U23', ...}`
- `RECOMMENDATION_LABEL_EN = {'call_up': 'Call up', 'shortlist': 'Shortlist', ...}`
- `urlencode_with(key, value)` — helper for the mode-toggle links that preserves other query params

If these don't exist, add to `app/__init__.py`.

## Verification protocol

1. **Restart Flask**
2. **Test scenarios:**

| # | Test | Expected |
|---|---|---|
| 1 | Compare Arthur (id=2) vs Bouhra (id=6) | Both have evaluations; both columns show category averages, NT level, recommendation, latest evaluator name + date |
| 2 | Same comparison, toggle to "Averaged" mode | URL changes to `?scout_mode=averaged`; both columns now show "Averaged across N evaluations"; category averages may differ slightly from Latest |
| 3 | Click "Detailed criteria comparison" → expand Tech category | Table shows criteria from both players' position groups (AM ∪ DM); cells show scores, NULL = "—", N/A = badge |
| 4 | Confirm cross-position NULLs render | At least one criterion in the union should not apply to one of the players (e.g. `tech_set_pieces_taking` applies to AM but maybe not DM in this taxonomy); cell shows "—" |
| 5 | Compare Arthur vs Sayed (no evaluations) | Sayed's column shows "No evaluations yet" placeholder; Arthur's normal |
| 6 | Comparison includes a player whose all evaluations are deleted | Treated as no evaluations |
| 7 | Soft-delete one of Arthur's evaluations, then refresh | Latest mode picks the next-most-recent eval; Averaged mode now averages 1 fewer eval |
| 8 | DB sanity: `SELECT id, status, deleted_at FROM evaluations WHERE player_id = 2;` shows correct state |
| 9 | Restore deleted eval; refresh comparison; numbers return to prior |
| 10 | GK-vs-outfield comparison | Existing block still applies (Phase 4.1 logic untouched); compare page rejects with friendly error |

3. **Synthetic E2E:** Write `migrations/_e2e_5d.py` that programmatically:
   - Calls compare_view() helper with (Arthur, Bouhra) → asserts both have scout_data populated, category_averages dict has all 4 keys, NT level + recommendation matched their latest eval
   - Calls with mode='averaged' → averages numerically computed correctly across the 2-3 evaluations Arthur has
   - Calls with (Arthur, Sayed) → Sayed has scout_data=None
   - Soft-delete Arthur's latest eval → re-call → latest_eval changes; averaged_eval differs
   - Restore the eval → assertions return to prior state

## Acceptance criteria

- ✅ Pre-flight gates pass (5)
- ✅ No schema changes (lock 5c-3 schema as v1)
- ✅ Comparison view renders scout section below Wyscout section
- ✅ Players with evaluations show category averages, NT level, recommendation, evaluator info
- ✅ Players without evaluations show "No evaluations yet" placeholder
- ✅ Latest/Averaged toggle changes URL parameter and computed values
- ✅ Latest mode shows most recent submitted+locked, non-deleted eval
- ✅ Averaged mode averages across all submitted+locked, non-deleted evals
- ✅ N/A scores excluded from averages (rated only)
- ✅ Soft-deleted evaluations excluded from both modes
- ✅ Per-criterion drill-down (collapsible) renders criteria union with category sub-collapses
- ✅ NULL cells render as "—" (criterion doesn't apply to that position group OR no row exists)
- ✅ N/A cells render as "N/A" badge
- ✅ Averaged mode shows `(N)` count next to per-criterion averaged values
- ✅ Existing Wyscout comparison + radar still work unchanged (regression check)
- ✅ GK-vs-outfield rule still applied
- ✅ Synthetic E2E PASS (count matches reality)
- ✅ schema.sql NOT modified (no schema changes)

## Hard rules

- ❌ Do NOT modify schema (verify via gate 5; no migration files needed)
- ❌ Do NOT modify Phase 4.1's Wyscout comparison logic; only ADD the scout section
- ❌ Do NOT modify auth, criteria taxonomy, eligibility, lock workflow, soft-delete logic from prior phases
- ❌ Do NOT use flask.test_client() for verification — restart real Flask
- ❌ Do NOT initialize git or commit — Ali commits manually
- ❌ Do NOT touch `D:\BFA-Analytics` or `D:\BFA-Analytics-AWS`
- ❌ Do NOT include locked-status filter (locked IS data, just protected from edit; include in aggregations)
- ❌ Do NOT include deleted_at IS NOT NULL evaluations in any aggregation (Phase 5c-3 invariant — strict)
- ✅ Use existing `get_form_criteria(position_group_id)` helper for criteria union (already in helpers)
- ✅ Reuse Phase 5c-2.1's `group_scores_by_category` helper if it fits (or create a sibling)
- ✅ Restart Flask after each significant change to verify in real browser
- ✅ Append v0.5.0d entry to CHANGELOG.md
- ✅ Mark 5d complete in PROJECT.md, queue Phase 6

## Out of scope (do NOT build)

- Schema changes (none)
- NT readiness divergence flag — that's Phase 5e
- Aggregation across evaluations from different age groups separately
- Filtering scout aggregation by date range
- Showing scout summaries from past evaluations
- Multi-page comparison
- PDF export of comparison page (Phase 6)
- Mobile pivot of comparison table

## Session discipline

- Target: 5–8 messages
- After every code change: restart Flask + browser verify
- Verify all 17 acceptance criteria explicitly
- After session, Ali commits:
  ```powershell
  cd D:\BFA-Scout
  git add -A
  git commit -m "Phase 5d: Scout dimension on comparison page (category averages, per-criterion drill-down, latest/averaged toggle)"
  ```
