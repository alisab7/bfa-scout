# Cowork/Claude Code Session: BFA-Scout Phase 5c-2.1 — Patch (Eligibility, Score Sections, Players List)

## Context

Phase 5c-2 landed in 17 minutes (genuinely fast — built on top of the
disciplined infrastructure from 5a/5b/5c-1/5c-1.1). Browser spot-check by Ali
surfaced four real issues. This is the patch session.

**Working folder:** `D:\BFA-Scout`. Do NOT touch `D:\BFA-Analytics` or `D:\BFA-Analytics-AWS`.

**Pre-flight:** Phase 5c-2 must be committed before this patch starts.

```powershell
cd D:\BFA-Scout
git log --oneline | Select-Object -First 3   # expect 5c-2 at top
git status                                    # expect: clean
```

## Four items in this patch

| # | Item | Effort |
|---|---|---|
| 1 | Move eligibility card up in profile UI (above Wyscout dashboard) | 5 min |
| 2 | Fix `compute_eligibility_status` priority order (nationality_status → date → residency-derived) + clean up redundant template line | 30 min |
| 3 | Section-grouped expanded scores in evaluation history cards, with per-category averages, each section collapsible | 45 min |
| 4 | Eligibility column on `/players/` list (icon + label + date) + filter dropdown | 30 min |

Total: ~2 hr attended.

## Item 1 — Move eligibility card up

In `app/templates/players/profile.html`, find the include for `_eligibility_card.html`. It currently renders below the Wyscout dashboard panel. Move it to render **immediately after the player header strip** (photo + name + position + club), before the Wyscout dashboard panel.

The eligibility card is the most committee-relevant info on the page — it should be the first thing visible after identifying who the player is.

No new code, just a template reorder.

## Item 2 — Fix eligibility logic + clean up redundant template line

### The bug

`compute_eligibility_status()` returns "Status unknown" when `eligible_from_date IS NULL`, regardless of `nationality_status`. This produces confusing output like:

```
?  Status unknown
Status: Foreign Residency · مؤهل (إقامة)
Bahrain residency from 2022-08-15 — eligible at 2027-08-15
```

The icon-line says "unknown" while the rest of the card shows the status is actually known. Both are technically correct given the existing function logic, but together they look broken.

### Fix — replace `compute_eligibility_status` in `app/players/eligibility.py`

Replace the existing function with this corrected priority-ordered version:

```python
def compute_eligibility_status(player) -> dict:
    """
    Returns a dict for the eligibility card template:
        {'icon':  '✅' | '⏳' | '❌' | '?',
         'label': str,
         'note':  str | None}

    Priority order (first match wins):
      1. nationality_status == 'not_eligible'        → ❌ Not eligible
      2. nationality_status in (bahraini, foreign_ancestry) → ✅ Eligible now
                                                              (birthright; date irrelevant)
      3. eligible_from_date set                      → ✅/⏳ based on date
      4. nationality_status == 'foreign_residency'   → use bahrain_residency_start_date
                                                       to derive suggested eligibility
                                                       OR ⏳ Pending if residency_start
                                                       is not set
      5. nationality_status == 'foreign_other'       → ? Foreign-eligible (admin to set date)
      6. otherwise                                    → ? Status unknown
    """
    def get(field):
        if hasattr(player, "get"):
            return player.get(field)
        return getattr(player, field, None)

    nat = get("nationality_status")

    # Priority 1: explicitly not eligible
    if nat == "not_eligible":
        return {"icon": "❌", "label": "Not eligible", "note": None}

    # Priority 2: birthright eligibility — eligible regardless of date
    if nat == "bahraini":
        return {"icon": "✅", "label": "Eligible now", "note": "Bahraini citizen"}
    if nat == "foreign_ancestry":
        return {"icon": "✅", "label": "Eligible now",
                "note": "Foreign-eligible (ancestry)"}

    # Priority 3: explicit eligible_from_date present
    edate = get("eligible_from_date")
    if isinstance(edate, str):
        try:
            edate = date.fromisoformat(edate)
        except ValueError:
            edate = None

    if edate:
        today = date.today()
        if edate <= today:
            return {"icon": "✅", "label": "Eligible now",
                    "note": f"From {edate.strftime('%Y-%m-%d')}"}
        delta_days = (edate - today).days
        diff_years = delta_days // 365
        diff_months = (delta_days % 365) // 30
        return {"icon": "⏳",
                "label": f"Eligible in {diff_years}y {diff_months}m",
                "note": f"From {edate.strftime('%Y-%m-%d')}"}

    # Priority 4: residency-route with start date but no eligible_from_date
    if nat == "foreign_residency":
        rstart = get("bahrain_residency_start_date")
        if isinstance(rstart, str):
            try:
                rstart = date.fromisoformat(rstart)
            except ValueError:
                rstart = None
        if rstart:
            suggested = compute_suggested_eligibility(rstart)
            if suggested:
                today = date.today()
                if suggested <= today:
                    return {
                        "icon": "✅",
                        "label": "Eligible now",
                        "note": (f"5-year residency complete "
                                 f"(suggested {suggested.strftime('%Y-%m-%d')}; "
                                 f"admin to confirm)")
                    }
                delta_days = (suggested - today).days
                diff_years = delta_days // 365
                diff_months = (delta_days % 365) // 30
                return {
                    "icon": "⏳",
                    "label": f"Eligible in {diff_years}y {diff_months}m",
                    "note": (f"Suggested {suggested.strftime('%Y-%m-%d')} "
                            f"(Article 5; admin to confirm)")
                }
        return {"icon": "⏳", "label": "Pending — residency start not set",
                "note": "Admin to set Bahrain residency start date"}

    # Priority 5: foreign-eligible by 'other' route — admin must set date
    if nat == "foreign_other":
        return {"icon": "?", "label": "Foreign-eligible (other route)",
                "note": "Admin to set eligible-from date"}

    # Priority 6: truly unknown
    return {"icon": "?", "label": "Status unknown", "note": None}
```

### Template cleanup — `_eligibility_card.html`

After the fix, the redundant `Status: ...` line should be removed because the icon-line now correctly reflects status. Replace:

```html
{% if player.nationality_status %}
  <p class="text-xs mt-3" style="color:var(--text-muted);">
    Status:
    <span style="color:var(--text);">
      {{ player.nationality_status | replace('_', ' ') | title }}
    </span>
    ...
```

with a smaller route-info line that's still useful but doesn't duplicate the eligibility status:

```html
{% if player.nationality_status and player.nationality_status not in ('unknown', None) %}
  <p class="text-xs mt-3" style="color:var(--text-muted);">
    Route:
    <span style="color:var(--text);">
      {{ NATIONALITY_ROUTE_LABEL_EN.get(player.nationality_status, player.nationality_status | replace('_', ' ') | title) }}
    </span>
    {% set ar_label = ELIGIBILITY_STATUS_LABEL_AR.get(player.nationality_status) %}
    {% if ar_label %}
      · <span style="direction:rtl;">{{ ar_label }}</span>
    {% endif %}
  </p>
{% endif %}
```

Add to the existing dictionary in helpers (or wherever ELIGIBILITY_STATUS_LABEL_AR lives):

```python
NATIONALITY_ROUTE_LABEL_EN = {
    'bahraini': 'Bahraini citizen',
    'foreign_residency': 'Foreign — residency',
    'foreign_ancestry': 'Foreign — ancestry',
    'foreign_other': 'Foreign — other route',
    'not_eligible': 'Not eligible',
    'unknown': 'Unknown',
}
```

This way the eligibility card has one clear status answer (icon line) and one supplementary route label, with no contradictions.

## Item 3 — Section-grouped expanded scores

### Current state

When user clicks "Show all scores" on a history card (`_history_card.html`), all criteria scores render in a flat list. For an AM player with 42 sliders, that's a long wall of items.

### Desired state

Expanded view groups scores by category — Technical, Tactical, Physical, Mentality. Each category is a sub-collapse (closed by default). Each category header shows:
- Category name (EN + AR)
- Average rating across rated items in that category (e.g. "7.2 avg")
- Counts: "12 rated, 2 N/A" (untouched not shown)

N/A items don't count toward the average. Untouched items are simply absent (no row in evaluation_scores).

### Helper — add to `app/evaluations/helpers.py`

```python
def group_scores_by_category(scores: list[dict]) -> list[dict]:
    """
    Takes a flat list of score dicts (each with criterion_id, score,
    is_not_applicable, name_en, name_ar, category_code, category_name_en,
    category_name_ar) and groups them by category.

    Returns:
      [
        {
          'code': 'tech',
          'name_en': 'Technical',
          'name_ar': '...',
          'sort_order': 1,
          'rated_count': 12,
          'na_count': 2,
          'avg_score': 7.2,   # None if rated_count == 0
          'items': [...]       # the score dicts in this category
        },
        ...
      ]
    Empty categories (0 rated, 0 N/A) are omitted entirely.
    """
    by_cat = {}
    for s in scores:
        code = s.get('category_code')
        if code not in by_cat:
            by_cat[code] = {
                'code': code,
                'name_en': s.get('category_name_en'),
                'name_ar': s.get('category_name_ar'),
                'sort_order': s.get('category_sort_order', 99),
                'rated_count': 0,
                'na_count': 0,
                'avg_score': None,
                'items': [],
                '_score_sum': 0.0,
            }
        by_cat[code]['items'].append(s)
        if s.get('is_not_applicable'):
            by_cat[code]['na_count'] += 1
        elif s.get('score') is not None:
            by_cat[code]['rated_count'] += 1
            by_cat[code]['_score_sum'] += float(s['score'])

    result = []
    for cat in by_cat.values():
        if cat['rated_count'] > 0:
            cat['avg_score'] = round(cat['_score_sum'] / cat['rated_count'], 1)
        del cat['_score_sum']
        result.append(cat)

    return sorted(result, key=lambda c: c['sort_order'])
```

`get_player_evaluations()` should also return `category_code`, `category_name_en`, `category_name_ar`, and `category_sort_order` per score row (JOIN to `criteria_categories`). If it doesn't already, modify the query to include these.

### Template — `_history_card.html` expanded section

Replace the current flat-list expand body with:

```html
<div x-show="expanded" x-cloak class="mt-3 pt-3"
     style="border-top:1px solid var(--border);">

  {# Group scores by category, collapsible per-section #}
  {% set grouped = group_scores_by_category(ev.scores) %}
  {% for cat in grouped %}
    <details class="rounded-lg mb-2"
             style="background:var(--bg);border:1px solid var(--border);">
      <summary class="px-3 py-2 cursor-pointer flex justify-between items-center">
        <div>
          <span class="font-semibold text-sm">{{ cat.name_en }}</span>
          <span class="text-xs ml-2" style="color:var(--text-muted);">{{ cat.name_ar }}</span>
        </div>
        <div class="text-xs" style="color:var(--text-muted);">
          {% if cat.avg_score is not none %}
            <span style="color:var(--brand);">{{ cat.avg_score }} avg</span> ·
          {% endif %}
          {{ cat.rated_count }} rated{% if cat.na_count > 0 %},
            {{ cat.na_count }} N/A{% endif %}
        </div>
      </summary>
      <ul class="px-3 pb-2 pt-1 space-y-1 text-xs">
        {% for s in cat['items'] %}
          <li class="flex justify-between items-baseline">
            <span>
              {{ s.name_en }}
              <span style="color:var(--text-muted);">· {{ s.name_ar }}</span>
            </span>
            {% if s.is_not_applicable %}
              <span class="px-2 py-0.5 rounded text-xs"
                    style="background:var(--surface);color:var(--text-muted);
                           border:1px solid var(--border);">
                N/A · غير متخصص
              </span>
            {% else %}
              <span class="font-mono" style="color:var(--brand);">
                {{ '%.1f'|format(s.score) }}
              </span>
            {% endif %}
          </li>
        {% endfor %}
      </ul>
    </details>
  {% endfor %}

  {# Summary text + admin actions stay outside the category sections #}
  ...
</div>
```

Per-section collapse uses native `<details>` (already proven in 5c-1's accordion).

### Important — register `group_scores_by_category` as a Jinja global

In `app/__init__.py` or wherever the Jinja env is configured, register the helper so the template can call it:

```python
from app.evaluations.helpers import group_scores_by_category
app.jinja_env.globals['group_scores_by_category'] = group_scores_by_category
```

(If `compute_eligibility_status` and `nt_readiness_summary` are already registered the same way, follow that pattern.)

## Item 4 — Eligibility column on `/players/` list + filter

### Format per locked decision

Icon + short label + date in one column. Examples:

| Display | Means |
|---|---|
| `✅ Eligible · Now` | eligible_from_date ≤ today, OR birthright |
| `⏳ Eligible · 2027-08-15 (1y 3m)` | eligible_from_date in future |
| `❌ Not eligible` | nationality_status = 'not_eligible' |
| `?  Unknown` | unknown / no data |

### Template — modify `players/list.html` (or whatever the list template is named)

Add column after "Position" and before "Club" (or wherever fits aesthetically):

```html
<th class="text-left text-xs font-semibold p-2"
    style="color:var(--text-muted);">Eligibility</th>
...
<td class="p-2 text-sm">
  {% set elig = compute_eligibility_status(p) %}
  <span class="whitespace-nowrap">
    <span>{{ elig.icon }}</span>
    <span>{{ elig.label }}</span>
    {% if elig.note and 'From' in elig.note %}
      <span class="text-xs" style="color:var(--text-muted);">
        {{ elig.note.replace('From ', '') }}
      </span>
    {% endif %}
  </span>
</td>
```

The `elig.note` parsing keeps the date when present but trims the "From " prefix to save space in a list context.

### Filter dropdown — above the table

Reuse the existing filter row if there is one; if there isn't, add a new one. Pattern:

```html
<form method="GET" action="{{ url_for('players.list_players') }}"
      class="mb-4 flex gap-2 flex-wrap">
  <input type="search" name="q" value="{{ request.args.get('q', '') }}"
         placeholder="Search by name or club…"
         class="px-3 py-2 rounded text-sm">

  <select name="elig" class="px-3 py-2 rounded text-sm">
    <option value="">All eligibility statuses</option>
    <option value="eligible_now"  {% if request.args.get('elig') == 'eligible_now'  %}selected{% endif %}>Eligible now</option>
    <option value="pending"       {% if request.args.get('elig') == 'pending'       %}selected{% endif %}>Pending (future date)</option>
    <option value="not_eligible"  {% if request.args.get('elig') == 'not_eligible'  %}selected{% endif %}>Not eligible</option>
    <option value="unknown"       {% if request.args.get('elig') == 'unknown'       %}selected{% endif %}>Unknown</option>
  </select>

  <button type="submit" class="px-4 py-2 rounded text-sm font-semibold text-white"
          style="background:var(--brand);">Filter</button>
</form>
```

### Route filter logic

In `app/players/__init__.py` (or wherever `list_players` is), add eligibility filtering. The challenge: the eligibility "computed" status doesn't live in a column, so SQL filtering needs to translate the user's choice to actual SQL conditions.

```python
elig_filter = request.args.get('elig', '').strip()

# Build extra WHERE clauses dynamically
where_clauses = ["pl.is_active = TRUE"]
params = []

if elig_filter == 'eligible_now':
    # Eligible now = (status in birthright) OR (eligible_from_date <= today)
    #                OR (foreign_residency with residency_start +5y <= today)
    where_clauses.append("""(
        pl.nationality_status IN ('bahraini', 'foreign_ancestry')
        OR (pl.eligible_from_date IS NOT NULL AND pl.eligible_from_date <= CURRENT_DATE)
        OR (pl.nationality_status = 'foreign_residency'
            AND pl.bahrain_residency_start_date IS NOT NULL
            AND pl.eligible_from_date IS NULL
            AND pl.bahrain_residency_start_date + INTERVAL '5 years' <= CURRENT_DATE)
    )""")

elif elig_filter == 'pending':
    where_clauses.append("""(
        (pl.eligible_from_date IS NOT NULL AND pl.eligible_from_date > CURRENT_DATE)
        OR (pl.nationality_status = 'foreign_residency'
            AND pl.bahrain_residency_start_date IS NOT NULL
            AND pl.eligible_from_date IS NULL
            AND pl.bahrain_residency_start_date + INTERVAL '5 years' > CURRENT_DATE)
    )""")

elif elig_filter == 'not_eligible':
    where_clauses.append("pl.nationality_status = 'not_eligible'")

elif elig_filter == 'unknown':
    where_clauses.append("""(
        pl.nationality_status IS NULL
        OR pl.nationality_status = 'unknown'
        OR (pl.nationality_status = 'foreign_other' AND pl.eligible_from_date IS NULL)
    )""")
```

The `INTERVAL '5 years'` keeps the SQL in sync with `RESIDENCY_YEARS_REQUIRED = 5`. If you ever change the constant, update both. (Fine for now — comment in `eligibility.py` already notes this.)

### Pre-flight gate: confirm `pl` alias is correct

The query in list_players uses `pl` as the alias for `players`. Confirm before changing — it might be `p` or `players` directly. **If the alias is different, use the correct one**.

## Files to modify

```
app/players/
├── eligibility.py                [MODIFY] Replace compute_eligibility_status; keep RESIDENCY_YEARS_REQUIRED + other helpers
└── __init__.py                   [MODIFY] Add eligibility filtering to list_players route

app/evaluations/
└── helpers.py                    [MODIFY] Add group_scores_by_category helper; modify get_player_evaluations to JOIN criteria_categories so each score includes category_code, category_name_en, category_name_ar, category_sort_order

app/__init__.py                   [MODIFY] Register group_scores_by_category as Jinja global (if eligibility helpers already are)

app/templates/
├── players/
│   ├── profile.html              [MODIFY] Move _eligibility_card.html include UP, above wyscout dashboard
│   └── list.html                 [MODIFY] Add Eligibility column + filter dropdown
└── evaluations/
    ├── _eligibility_card.html    [MODIFY] Remove redundant "Status:" line, replace with smaller "Route:" line
    └── _history_card.html        [MODIFY] Replace flat expand body with category-grouped sub-collapses

CHANGELOG.md                      [APPEND] v0.5.0c2.1 entry
PROJECT.md                        [UPDATE] Mark 5c-2.1 complete
```

**No schema changes in 5c-2.1.** All four items are pure-application fixes.

## Verification

1. **Restart Flask** after all changes
2. **Test Item 1** — visit `/players/2` (Arthur Rezende). Eligibility card should appear immediately after the player header strip, BEFORE the Wyscout dashboard.

3. **Test Item 2** — set test cases via psql or admin UI:
   - Player A: nationality_status='bahraini', eligible_from_date=NULL → should show ✅ "Eligible now" + note "Bahraini citizen"
   - Player B: nationality_status='foreign_ancestry', eligible_from_date=NULL → should show ✅ "Eligible now" + note "Foreign-eligible (ancestry)"
   - Player C: nationality_status='foreign_residency', eligible_from_date=NULL, bahrain_residency_start_date='2022-08-15' → should show ⏳ "Eligible in 1y Xm" + note "Suggested 2027-08-15 (Article 5; admin to confirm)"
   - Player D: nationality_status='foreign_residency', eligible_from_date='2027-08-15', residency_start_date set → should show ⏳ from explicit date (Priority 3 wins over Priority 4)
   - Player E: nationality_status='foreign_residency', eligible_from_date=NULL, residency_start=NULL → should show ⏳ "Pending — residency start not set"
   - Player F: nationality_status='not_eligible' → ❌ "Not eligible"
   - Player G: all NULL/unknown → ? "Status unknown"
   - "Status: ..." line removed; "Route: ..." line shown only when nationality_status is set

4. **Test Item 3** — open Arthur's profile, click "Show all scores" on one of his evaluation history cards. Expanded section should show Technical / Tactical / Physical / Mentality as collapsible sub-sections, each showing average rating and N/A count.

5. **Test Item 4** — visit `/players/`. Should see new Eligibility column with icon + label + date. Filter dropdown should appear above the table. Test all 5 filter options against the test players from item 2.

6. **DB check** — no schema changes, but confirm:
   ```powershell
   psql -U bfa -d bfa_scout -c "\d players" | Select-String "eligibility|residency|nationality"
   ```
   Should still show 5 columns from 5c-2 (nationality_status, eligible_from_date, eligibility_notes_admin, bahrain_residency_start_date, bahrain_residency_notes).

## Acceptance criteria

- ✅ Eligibility card appears above Wyscout dashboard on profile
- ✅ Player A (bahraini, no date) shows "Eligible now" + "Bahraini citizen" note
- ✅ Player B (ancestry, no date) shows "Eligible now" + "Foreign-eligible (ancestry)" note
- ✅ Player C (residency, no eligible_from_date, residency_start set) shows "Eligible in Xy Ym" computed from residency + 5y
- ✅ Player D (residency, eligible_from_date set) uses the explicit date (Priority 3 wins)
- ✅ Player E (residency, neither date) shows "Pending — residency start not set"
- ✅ Player F (not_eligible) shows "Not eligible"
- ✅ Player G (unknown) shows "Status unknown"
- ✅ Eligibility card no longer shows redundant "Status:" line; "Route:" line shown when applicable
- ✅ Expanded scores grouped by category, each as collapsible section, each with avg + counts
- ✅ N/A items don't count toward avg (only `score IS NOT NULL` rated rows)
- ✅ Players list shows Eligibility column with icon + label + date
- ✅ Filter dropdown applies correct SQL for each option
- ✅ "Eligible now" filter includes both birthright AND date-based AND residency-derived eligibility
- ✅ "Pending" filter includes both eligible_from_date in future AND residency-derived future date
- ✅ All 4 items work without schema changes
- ✅ Existing evaluations history still renders correctly

## Hard rules

- ❌ Do NOT modify schema (no migrations needed)
- ❌ Do NOT touch lock workflow, admin-edit logic, mobile polish — those are 5c-2 deliverables already shipped
- ❌ Do NOT use flask.test_client() — restart real Flask
- ❌ Do NOT initialize git or commit — Ali commits manually
- ❌ Do NOT touch `D:\BFA-Analytics` or `D:\BFA-Analytics-AWS`
- ❌ Do NOT change `RESIDENCY_YEARS_REQUIRED` constant
- ❌ Do NOT invent translations — use existing dicts (NATIONALITY_ROUTE_LABEL_EN to be added; ELIGIBILITY_STATUS_LABEL_AR exists from 5c-2)
- ✅ Restart Flask after each significant change to verify in browser
- ✅ Test all 7 priority cases for compute_eligibility_status (A through G above)
- ✅ Append v0.5.0c2.1 entry to CHANGELOG.md
- ✅ Mark 5c-2.1 complete in PROJECT.md

## Out of scope (do NOT build)

- Comparison page scout dimension (Phase 5d — separately scoped)
- Player Passport PDF (Phase 6)
- Schema changes (none needed)
- New translations beyond NATIONALITY_ROUTE_LABEL_EN
- Auto-aggregation logic for Phase 5e

## Session discipline

- Target: 4–6 messages
- After session, Ali commits:
  ```powershell
  cd D:\BFA-Scout
  git add -A
  git commit -m "Phase 5c-2.1 patch: eligibility card priority order, score sections, players list eligibility column + filter"
  ```
