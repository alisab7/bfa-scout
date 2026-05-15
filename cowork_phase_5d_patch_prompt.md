# Cowork/Claude Code Session: BFA-Scout Phase 5d Patch — Match Label, HTMX Toggle, Drilldown Diagnosis

## Context

Phase 5d landed but Ali surfaced 3 real issues during browser spot-check.
**Phase 5d is NOT yet committed.** Patches land in the same uncommitted working
state, then commit as one clean unit.

**Working folder:** `D:\BFA-Scout`. Do NOT touch `D:\BFA-Analytics` or `D:\BFA-Analytics-AWS`.

## Three items in this patch

| # | Item | Effort estimate |
|---|---|---|
| 1 | Match label visible in Latest-mode header card | 10 min |
| 2 | HTMX swap for Latest/Averaged toggle (no full reload, no scroll jump) | 30 min |
| 3 | Detailed criteria comparison shows no data — diagnose and fix | 20 min |

Total: ~1 hr attended.

**Item 4 (multi-season Career stats) is OUT of scope** — scheduled as Phase 4.2 after Phase 6.

## Pre-flight gates

```powershell
# Gate 1: Phase 5d work is in working tree, NOT yet committed
git log --oneline | Select-Object -First 1   # expect: top is 5c-3 (NOT 5d)
git status                                    # expect: dirty (5d files modified/created)

# Gate 2: Verify scout aggregation works at the data layer (helpers were unit-verified at session end of 5d)
psql -U bfa -d bfa_scout -c "SELECT pl.id, pl.full_name, pl.primary_position_id, p.position_group_id, pg.code FROM players pl LEFT JOIN positions p ON p.id = pl.primary_position_id LEFT JOIN position_groups pg ON pg.id = p.position_group_id WHERE pl.id IN (2, 6);"
# expect: Arthur AM/6, Bouhra DM/4

# Gate 3: Confirm position_group_criteria mappings exist for both groups
psql -U bfa -d bfa_scout -c "SELECT pg.code, COUNT(*) FROM position_groups pg JOIN position_group_criteria pgc ON pgc.position_group_id = pg.id WHERE pg.code IN ('AM', 'DM') GROUP BY pg.code;"
# expect: AM = 42, DM = 40 (the Phase 5a locked numbers)
```

## Item 1 — Match label in Latest-mode header

### What's missing

Latest-mode header card currently shows: "Latest by {evaluator_name} · {submitted_at}"
Should also show: which match was evaluated.

### Implementation

In `app/evaluations/helpers.py`, modify `get_player_evaluation_aggregate(player_id, mode='latest')`:

The function currently SELECTs from evaluations + users. Add a LEFT JOIN to matches:

```sql
SELECT e.id, e.submitted_at, e.locked_at,
       e.nt_readiness_level, e.recommendation, e.summary,
       u.full_name AS evaluator_name,
       m.match_date, m.home_team, m.away_team, m.competition,
       m.id AS match_id
FROM evaluations e
LEFT JOIN users u ON u.id = e.evaluator_id
LEFT JOIN matches m ON m.id = e.match_id          -- NEW
WHERE e.player_id = %s
  AND e.status IN ('submitted', 'locked')
  AND e.deleted_at IS NULL
ORDER BY e.submitted_at DESC NULLS LAST
LIMIT 1
```

Build a `match_label` string in Python (cleaner than format-in-template):

```python
def _format_match_label(row):
    """Returns 'Home vs Away' or 'Freestanding (no match linked)'."""
    if not row.get('match_id'):
        return 'Freestanding (no match linked)'
    home = row.get('home_team') or '?'
    away = row.get('away_team') or '?'
    return f"{home} vs {away}"
```

Add `match_label` and `match_date` to the returned dict:

```python
return {
    'evaluator_name': row['evaluator_name'],
    'submitted_at': row['submitted_at'],
    'locked_at': row['locked_at'],
    'nt_readiness_level': row['nt_readiness_level'],
    'recommendation': row['recommendation'],
    'summary': row['summary'],
    'match_label': _format_match_label(row),     # NEW
    'match_date': row['match_date'],              # NEW (may be None)
    'category_averages': {...},
    'scores': [...],
    ...
}
```

For **averaged** mode, the match_label doesn't apply (multiple evaluations). Either omit the field entirely OR set it to `'Averaged across {N} evaluations'` — whichever fits cleanest. Spec recommendation: omit for averaged, template handles missing field gracefully.

### Template — `_compare_scout_section.html`

Find the Latest-mode header line (currently shows evaluator + date). Modify:

```html
{% if scout_mode == 'latest' %}
  <div class="text-xs mb-3" style="color:var(--text-muted);">
    Latest by {{ p.scout_data.evaluator_name }}
    · {{ p.scout_data.submitted_at.strftime('%Y-%m-%d') if p.scout_data.submitted_at else '—' }}
    {% if p.scout_data.match_label %}
      · {{ p.scout_data.match_label }}
    {% endif %}
  </div>
{% else %}
  <div class="text-xs mb-3" style="color:var(--text-muted);">
    Averaged across {{ p.eval_count }} evaluation{{ '' if p.eval_count == 1 else 's' }}
  </div>
{% endif %}
```

## Item 2 — HTMX swap for mode toggle (no full page reload)

### Current behavior

Mode toggle is `<a href="?scout_mode=averaged">` — full page reload, browser scrolls to top.

### Target behavior

Toggle swaps just the scout section in place. No page reload, no scroll jump. Pattern matches existing HTMX usage in players list filters.

### Implementation

#### Step 1 — Add a partial-only route

In `app/players/__init__.py`, add a new route alongside `compare_view`:

```python
@bp.route('/players/compare/scout-section')
@login_required
def compare_scout_section():
    """Returns ONLY the scout section partial — used for HTMX toggle swap.

    Same parameters as compare_view (ids[], scout_mode), same enrichment logic.
    Renders only `_compare_scout_section.html` with `data` dict in scope.
    """
    ids = request.args.getlist('ids')
    if not ids:
        return ''  # gracefully empty

    mode = request.args.get('scout_mode', 'latest')
    if mode not in ('latest', 'averaged'):
        mode = 'latest'

    # Same player fetch + enrichment as compare_view
    players = []
    for player_id_str in ids[:3]:  # max 3
        try:
            pid = int(player_id_str)
        except ValueError:
            continue
        p = get_player_with_position_group(pid)
        if not p:
            continue
        p['eval_count'] = get_evaluation_count_active(pid)
        p['scout_data'] = (
            get_player_evaluation_aggregate(pid, mode=mode)
            if p['eval_count'] > 0 else None
        )
        players.append(p)

    # Build criteria union (same as compare_view)
    all_criteria = []
    seen = set()
    for p in players:
        pg = p.get('position_group_id')
        if not pg:
            continue
        for c in get_form_criteria(pg):
            if c['criterion_id'] not in seen:
                all_criteria.append(c)
                seen.add(c['criterion_id'])
    all_criteria.sort(key=lambda c: (c.get('category_sort_order', 99), c.get('sort_order', 99)))

    return render_template(
        'players/_compare_scout_section.html',
        data={'players': players},
        all_criteria=all_criteria,
        scout_mode=mode,
    )
```

The enrichment logic should be DRY-ed if compare_view's existing logic is large — extract to a helper `_enrich_compare_data(ids, scout_mode)` that both routes call.

#### Step 2 — Wrap the section in an HTMX target

In `compare_view.html`, wrap the entire scout-assessment section in a div with a stable ID:

```html
<section id="scout-section" class="rounded-xl p-6 mb-6"
         style="background:var(--surface);border:1px solid var(--border);">
  <!-- existing scout-assessment content -->
</section>
```

#### Step 3 — Convert toggle anchor to HTMX

In `_compare_scout_section.html`, find the Latest/Averaged toggle:

```html
<!-- Was:
<a href="?{{ urlencode_with('scout_mode', 'latest') }}" ...>Latest</a>
<a href="?{{ urlencode_with('scout_mode', 'averaged') }}" ...>Averaged</a>
-->

<a href="#"
   hx-get="{{ url_for('players.compare_scout_section') }}?{{ urlencode_with('scout_mode', 'latest') }}"
   hx-target="#scout-section"
   hx-swap="outerHTML"
   hx-push-url="?{{ urlencode_with('scout_mode', 'latest') }}"
   class="px-3 py-1 rounded {% if scout_mode == 'latest' %}font-semibold{% endif %}"
   style="background:{% if scout_mode == 'latest' %}var(--brand);color:white{% else %}var(--bg);color:var(--text-muted);border:1px solid var(--border){% endif %};">
  Latest
</a>
<a href="#"
   hx-get="{{ url_for('players.compare_scout_section') }}?{{ urlencode_with('scout_mode', 'averaged') }}"
   hx-target="#scout-section"
   hx-swap="outerHTML"
   hx-push-url="?{{ urlencode_with('scout_mode', 'averaged') }}"
   class="px-3 py-1 rounded {% if scout_mode == 'averaged' %}font-semibold{% endif %}"
   style="background:{% if scout_mode == 'averaged' %}var(--brand);color:white{% else %}var(--bg);color:var(--text-muted);border:1px solid var(--border){% endif %};">
  Averaged
</a>
```

**Critical:** the partial route returns the scout section starting from `<section id="scout-section">` (so the swap replaces the same wrapper). The `_compare_scout_section.html` template must include the wrapping section element in this case OR the partial route renders a wrapper around the section.

Cleanest pattern: have `_compare_scout_section.html` always render the `<section id="scout-section">` wrapper. Both `compare_view.html` and the partial route render the same template. compare_view.html wraps it in the rest of the page; the partial route returns just it. Same template, two contexts.

#### Step 4 — Verify HTMX is loaded

`<script src="https://unpkg.com/htmx.org@..."></script>` should already be in `base.html` from Phase 5b/5c-2.1. If not, add it.

## Item 3 — Detailed criteria comparison empty (DIAGNOSE)

### Hypothesis

`all_criteria` arrives empty at the template, so the drilldown's outer loop doesn't iterate. Three possible causes:

**A. `compare_view` route doesn't pass `all_criteria`** — route returns the variable but it's empty/missing
**B. `get_form_criteria(position_group_id)` returns empty** — the helper exists but the position_group_id is wrong or filter excludes everything
**C. Field name mismatch** — template expects `category_code`, helper returns `code`, etc.

### Diagnostic step (execute first, before any patches)

Add a debug log line to compare_view temporarily:

```python
# At end of compare_view, just before render_template:
import sys
print(f"DEBUG: players={len(players)}, all_criteria={len(all_criteria)}", file=sys.stderr, flush=True)
if all_criteria:
    print(f"DEBUG: first criterion keys={list(all_criteria[0].keys())}", file=sys.stderr, flush=True)
```

Restart Flask, hit `/players/compare/view?ids=2&ids=6`, check the terminal:

- If `len=0`: route bug. Check that `position_group_id` is on the players dict (it should be from compare_players which JOINs through positions). If missing, JOIN is broken — fix in compare_players helper.
- If `len > 0` but template shows nothing: template bug or missing field. The template uses `c.category_code`, `c.criterion_id`, `c.name_en`, `c.name_ar`, `c.category_name_en`, `c.category_name_ar`. Verify the helper returns all 6.

### Likely fix

Most-likely root cause: `compare_players()` (the helper that gets bio data for the comparison) doesn't return `position_group_id`. The 5d session noted "Extending compare_players to include position_group_id" — but it's possible the change was incomplete OR the field name returned doesn't match what the route expects.

Look at `app/wyscout/aggregations.py` (or wherever `compare_players` lives) for the SELECT — confirm `pg.id AS position_group_id` is in the column list.

If the field is there in the SQL but not in the returned dict, the bug is JOIN aliasing. Common pitfall:

```sql
SELECT pl.id, pl.full_name, p.id AS primary_position_id, pg.id AS position_group_id, ...
```

If two columns are aliased the same way (e.g. both `p.id` and `pg.id` end up as just `id` in the result), psycopg2 returns the latter. The fix is explicit aliases.

After fixing, remove the debug logging.

## Verification

1. **Restart Flask after each change** (Jinja templates auto-reload but Python files don't)
2. **Browser test in order:**

| # | Test | Expected |
|---|---|---|
| 1 | Visit `/players/compare/view?ids=2&ids=6` | Latest-mode card shows: "Latest by {evaluator} · {date} · {match_label}" for both Arthur and Bouhra |
| 2 | Click Averaged toggle | Page DOES NOT scroll to top; URL changes to `?scout_mode=averaged`; scout section content updates in place |
| 3 | Click Latest toggle from Averaged | Reverse — back to Latest mode, no scroll, URL flips back |
| 4 | Expand "Detailed criteria comparison" | Tech / Tact / Phys / Ment sub-collapses appear; expanding any one shows criteria from AM ∪ DM with cells filled |
| 5 | Cell semantics in drilldown | Rated → numeric, N/A → badge, criterion-not-applicable → "—", no row in scores → "—" |
| 6 | Browser back button (after toggle) | URL reverts; scout section reflects the prior mode (HTMX `hx-push-url` working) |
| 7 | Existing Wyscout section + radar | Still works unchanged (regression check) |

3. **Synthetic E2E (`migrations/_e2e_5d_patch.py`):**

```python
# Test 1: latest_eval has match_label
agg = get_player_evaluation_aggregate(player_id=2, mode='latest')
assert 'match_label' in agg
assert agg['match_label'] != ''

# Test 2: partial route returns just the scout section
resp = client.get('/players/compare/scout-section?ids=2&ids=6&scout_mode=latest')
assert resp.status_code == 200
html = resp.get_data(as_text=True)
assert '<section id="scout-section"' in html
assert '<!DOCTYPE html>' not in html  # no full page

# Test 3: all_criteria is non-empty for the AM/DM combination
# Hit compare_view, parse rendered HTML, count criterion rows in drilldown
resp = client.get('/players/compare/view?ids=2&ids=6')
html = resp.get_data(as_text=True)
# Extract drilldown content
# Assert: at least 50 criterion rows total (AM=42 + DM=40 - overlap; conservative: >=40)
import re
criterion_rows = re.findall(r'<tr[^>]*>\s*<td[^>]*>\s*[\w\s\-\']+\s*<span', html)
assert len(criterion_rows) >= 40, f"only {len(criterion_rows)} criterion rows in drilldown"
```

## Acceptance criteria

- ✅ Pre-flight gates pass
- ✅ Latest-mode header shows match label (e.g. "Latest by X · 2026-04-12 · Khalidiya vs Manama")
- ✅ Averaged-mode header shows "Averaged across N evaluations"
- ✅ Mode toggle uses HTMX (no page reload, no scroll jump)
- ✅ Mode toggle URL state pushes via `hx-push-url` (browser back button works)
- ✅ Detailed criteria comparison shows criteria from both players' position groups (AM + DM union)
- ✅ Drilldown cell semantics: rated/N/A/absent all render correctly
- ✅ No regression in Wyscout comparison or radar
- ✅ Synthetic E2E PASS (count assertions match)
- ✅ Existing Phase 5d code that works (helper smoke tests, latest mode pre-fill) still works

## Hard rules

- ❌ Do NOT modify schema (no migration needed)
- ❌ Do NOT modify Phase 5d's helpers beyond the LEFT JOIN to matches
- ❌ Do NOT modify Phase 4.1's compare_view's Wyscout section
- ❌ Do NOT add ALTER statements to schema.sql (none needed)
- ❌ Do NOT use flask.test_client() for browser-equivalent verification — restart real Flask
- ❌ Do NOT initialize git or commit — Ali commits manually after this patch + 5d together
- ❌ Do NOT touch `D:\BFA-Analytics` or `D:\BFA-Analytics-AWS`
- ❌ Do NOT add multi-season Career stats logic (Phase 4.2)
- ✅ Restart Flask after each Python change
- ✅ Diagnose item 3 BEFORE patching (debug print first; remove after fix lands)
- ✅ Test all 7 browser tests + synthetic E2E
- ✅ Append v0.5.0d patch entry to CHANGELOG.md (combined with 5d entry, this is one commit)
- ✅ Update PROJECT.md to reflect 5d + patch land together

## Out of scope (do NOT build)

- Multi-season Career stats (Phase 4.2)
- Player Passport PDF (Phase 6)
- Schema changes (none)
- Mobile pivot
- Scout-vs-Wyscout dual radar (deferred from 5d)

## Session discipline

- Target: 4–6 messages
- Diagnose Item 3 first (debug print) BEFORE writing any patches for it
- Verify all 7 browser tests + E2E
- After session, Ali commits 5d + this patch as ONE commit:
  ```powershell
  cd D:\BFA-Scout
  git add -A
  git commit -m "Phase 5d: Scout dimension on comparison page (category averages, per-criterion drill-down, latest/averaged toggle, match label, HTMX swap)"
  ```

## Final-status note

If `compare_view` enrichment is found to be the issue in Item 3 and requires
extracting the logic to a helper for DRY, that's acceptable — but document
the helper's name and location in CHANGELOG.
