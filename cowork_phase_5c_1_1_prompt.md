# Cowork/Claude Code Session: BFA-Scout Phase 5c-1.1 — Tri-State Slider (N/A + Reset)

## Context

Phase 5c-1 is committed (commits `22e603d` + `cb50d3d`). The evaluation form works
end-to-end: scout picks a match, drags sliders, fills NT readiness, saves draft,
submits. Three submitted evaluations exist for testing.

**5c-1.1 closes a UX gap before 5c-2 starts.** The current slider has only two
states (untouched OR rated), which conflates two different scout intents and has
no way to undo an accidental drag.

**Working folder:** `D:\BFA-Scout`. Do NOT touch `D:\BFA-Analytics` or `D:\BFA-Analytics-AWS`.

**Local environment:**
- PostgreSQL 15 native, database `bfa_scout`, user `bfa`, password `bfa2025`
- Python venv at `.venv`
- Flask via `flask --app wsgi run --debug`

## Goal

Replace the current two-state slider with a tri-state model:

| State | How to reach | Submission |
|---|---|---|
| Untouched | Initial state, OR clicking ✕ on a rated slider, OR clicking N/A again on an N/A slider | No row in `evaluation_scores` |
| Rated | Drag slider | Row with `score = value`, `is_not_applicable = FALSE` |
| N/A (`غير متخصص`) | Click N/A button | Row with `score = NULL`, `is_not_applicable = TRUE` |

All transitions are **fully reversible**:
- Rated → Untouched via ✕ next to the value
- N/A → Untouched via clicking N/A button again

## Locked decisions (do not deviate)

| Decision | Choice |
|---|---|
| N/A label EN | "N/A" |
| N/A label AR | "غير متخصص" |
| Reset affordance | Small ✕ button next to the value display |
| ✕ visibility | Only visible when slider is `dirty` (rated state) |
| N/A toggle | Click once to enable, click again to disable |
| When N/A is active | Slider visually greyed out, value display shows "N/A", drag input disabled |
| Schema column | `evaluation_scores.is_not_applicable BOOLEAN NOT NULL DEFAULT FALSE` |
| Score column constraint change | `evaluation_scores.score` becomes nullable (was NOT NULL) |
| CHECK constraint | enforces (score IS NOT NULL AND is_not_applicable=FALSE) OR (score IS NULL AND is_not_applicable=TRUE) |
| Submission strategy | Three keys per criterion: scout interacted? → if rated, send `score_<id>=value`; if N/A, send `na_<id>=1`; if untouched, send nothing |

## Pre-flight gates

```powershell
# Gate 1: 5c-1 committed
git log --oneline | Select-String "5c-1"
# expect: at least one commit with "5c-1"

# Gate 2: Working tree clean
git status
# expect: nothing to commit

# Gate 3: evaluation_scores table exists with 14 rows (from 3 submitted evals)
psql -U bfa -d bfa_scout -c "SELECT COUNT(*) FROM evaluation_scores;"
# expect: 14 (5 + 9 + 0 from the three submitted evals)

# Gate 4: No is_not_applicable column yet
psql -U bfa -d bfa_scout -c "\d evaluation_scores" | Select-String "is_not_applicable"
# expect: empty (column doesn't exist yet)

# Gate 5: All existing scores are non-NULL (current state)
psql -U bfa -d bfa_scout -c "SELECT COUNT(*) FROM evaluation_scores WHERE score IS NULL;"
# expect: 0
```

If any gate fails, stop and surface the failure before touching anything.

## Files to create / modify

```
migrations/
├── _generate_phase_5c1_1.py      [NEW] Source-of-truth generator
├── phase_5c1_1_na_column.sql     [NEW] Migration artifact
├── _dryrun_5c1_1.py              [NEW] Savepoint+rollback verify-without-apply
└── _verify_throwaway_5c1_1.py    [NEW] Schema.sql convergence test

schema.sql                         [MODIFY] Add `is_not_applicable` column to evaluation_scores CREATE in-place; change `score` to nullable; add CHECK constraint

app/templates/evaluations/
└── _slider.html                   [MODIFY] Tri-state with N/A button + ✕ reset

app/evaluations/
├── forms.py                       [MODIFY] Parse `na_<id>` keys alongside `score_<id>` keys
└── helpers.py                     [MODIFY] save_evaluation_scores() handles is_not_applicable column

app/templates/evaluations/
├── _section.html                  [MODIFY] Section progress text now counts (rated + N/A) as "decided", untouched as "pending"
└── view.html                      [MODIFY] Read-only view renders N/A as "غير متخصص" badge instead of a numeric value

CHANGELOG.md                       [APPEND] v0.5.0c1.1 entry
PROJECT.md                         [UPDATE] Mark 5c-1.1 complete
```

## Schema changes

```sql
ALTER TABLE evaluation_scores
    ADD COLUMN is_not_applicable BOOLEAN NOT NULL DEFAULT FALSE,
    ALTER COLUMN score DROP NOT NULL,
    ADD CONSTRAINT evaluation_scores_score_or_na
        CHECK (
            (is_not_applicable = TRUE  AND score IS NULL) OR
            (is_not_applicable = FALSE AND score IS NOT NULL)
        );
```

**Backfill is trivial** — all existing 14 rows are score=value with is_not_applicable=FALSE (the default). No data migration needed beyond the DEFAULT clause doing its work.

**Audit gate inside transaction:**
```sql
DO $$
DECLARE
    invalid_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO invalid_count FROM evaluation_scores
    WHERE NOT (
        (is_not_applicable = TRUE  AND score IS NULL) OR
        (is_not_applicable = FALSE AND score IS NOT NULL)
    );
    IF invalid_count > 0 THEN
        RAISE EXCEPTION 'AUDIT FAIL — % rows violate score-or-NA constraint', invalid_count;
    END IF;
    RAISE NOTICE 'AUDIT PASS — all % rows satisfy score-or-NA invariant',
        (SELECT COUNT(*) FROM evaluation_scores);
END $$;
```

## Slider template — `_slider.html`

```html
<div x-data="{
       value: 5,
       dirty: false,
       na: false,
       reset() { this.dirty = false; this.value = 5; this.na = false; },
       toggleNA() { if (this.na) { this.na = false; } else { this.na = true; this.dirty = false; } }
     }"
     class="border-b pb-3"
     :class="na ? 'opacity-60' : ''">

  <!-- Label row -->
  <div class="flex justify-between items-start mb-1 gap-2">
    <label class="text-sm font-medium flex-1">
      {{ crit.name_en }}
      <span class="block text-xs" style="color:var(--text-muted);">{{ crit.name_ar }}</span>
    </label>

    <!-- Value display + reset ✕ + N/A button -->
    <div class="flex items-center gap-2 flex-shrink-0">
      <!-- Value display -->
      <span class="font-mono text-sm min-w-[3ch] text-right"
            :style="dirty || na ? 'color:var(--brand)' : 'color:var(--text-muted)'"
            x-text="na ? 'N/A' : (dirty ? value : '—')"></span>

      <!-- Reset ✕ — only when dirty -->
      <button type="button"
              x-show="dirty && !na"
              x-cloak
              @click="reset()"
              class="text-xs leading-none px-1"
              style="color:var(--text-muted);"
              title="Reset to untouched"
              aria-label="Reset rating">✕</button>

      <!-- N/A toggle -->
      <button type="button"
              @click="toggleNA()"
              class="text-xs px-2 py-0.5 rounded border"
              :class="na ? 'font-semibold' : ''"
              :style="na
                ? 'background:var(--brand);color:white;border-color:var(--brand);'
                : 'background:transparent;color:var(--text-muted);border-color:var(--border);'"
              title="غير متخصص — Not applicable">N/A</button>
    </div>
  </div>

  <!-- The slider itself -->
  <input type="range"
         min="{{ crit.scale_min }}"
         max="{{ crit.scale_max }}"
         step="{% if crit.allow_half %}0.5{% else %}1{% endif %}"
         x-model="value"
         @input="dirty = true; na = false"
         :disabled="na"
         :name="dirty && !na ? 'score_' + {{ crit.criterion_id }} : ''"
         class="w-full">

  <!-- Hidden N/A field — only sent when na is true -->
  <input type="hidden"
         :name="na ? 'na_' + {{ crit.criterion_id }} : ''"
         value="1">
</div>
```

**Critical correctness points:**

1. The `reset()` Alpine method must reset all three (`dirty`, `value`, `na`). After reset, value goes back to centered 5 visually, dirty=false, na=false.
2. Dragging the slider after enabling N/A should not happen because `:disabled="na"` blocks input. But the Alpine `@input` also forces `na = false` to handle browsers that ignore `disabled` on touch.
3. The hidden `<input :name="na ? 'na_' + ... : ''">` only contributes to form submission when N/A is active. When N/A is off, the empty `name=""` excludes it from POST.
4. Same trick for the slider's name: `:name="dirty && !na ? 'score_' + ... : ''"` — only submits when rated AND not N/A.
5. Three states are mutually exclusive at submission time:
   - Both empty names → untouched → no DB row
   - score_X=value → rated → row with score, is_not_applicable=FALSE
   - na_X=1 → N/A → row with score=NULL, is_not_applicable=TRUE

## Form handler — `forms.py`

Modify `parse_evaluation_form(form_data)` (or whatever the equivalent function is named) to scan for both `score_<criterion_id>` AND `na_<criterion_id>` keys:

```python
def parse_score_inputs(form_data):
    """Returns dict {criterion_id: {'score': float|None, 'is_not_applicable': bool}}.
    Only includes criterion_ids the scout actually interacted with.
    Scout state per criterion:
      - 'score_X' present  → rated     → {score: float, is_not_applicable: False}
      - 'na_X' present     → N/A       → {score: None, is_not_applicable: True}
      - neither present    → untouched → not in dict
    Both present is a malformed POST — log warning, treat as N/A (latter wins).
    """
    parsed = {}
    for key in form_data.keys():
        if key.startswith('score_'):
            try:
                cid = int(key.split('_', 1)[1])
                value = float(form_data[key])
                if 1 <= value <= 10:  # validation
                    parsed[cid] = {'score': value, 'is_not_applicable': False}
            except (ValueError, IndexError):
                continue
        elif key.startswith('na_'):
            try:
                cid = int(key.split('_', 1)[1])
                parsed[cid] = {'score': None, 'is_not_applicable': True}
                # If we already saw a score for this cid, N/A overrides it.
                # This handles the malformed-POST case.
            except (ValueError, IndexError):
                continue
    return parsed
```

## DB write — `helpers.py`

Modify `save_evaluation_scores(eval_id, scores_dict)`:

```python
def save_evaluation_scores(eval_id, scores_dict):
    """UPSERT evaluation_scores from parse_score_inputs() output.
    scores_dict: {criterion_id: {'score': float|None, 'is_not_applicable': bool}}

    Strategy:
      1. DELETE all existing rows for this eval_id (clean slate)
      2. INSERT one row per criterion in scores_dict

    The DELETE-then-INSERT is correct because untouched criteria should
    have NO row, and updating to untouched-after-rated requires removal.
    Wrap in a transaction.
    """
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM evaluation_scores WHERE evaluation_id = %s", (eval_id,))
        for cid, payload in scores_dict.items():
            cur.execute("""
                INSERT INTO evaluation_scores (evaluation_id, criterion_id, score, is_not_applicable)
                VALUES (%s, %s, %s, %s)
            """, (eval_id, cid, payload['score'], payload['is_not_applicable']))
        conn.commit()
    return len(scores_dict)
```

DELETE-then-INSERT is the cleanest semantics — untouched-after-rated naturally results in row removal.

## Section progress display

In `_section.html`, the progress text shows e.g. "5 / 22 rated". Update to count both rated AND N/A as "decided":

```html
<summary>
  {{ category.name_en }}
  <span class="text-xs">
    <span x-text="decidedCount">0</span> / {{ total_count }} decided
  </span>
</summary>
```

Where `decidedCount` is computed across child sliders (sum of `dirty || na`). This requires the section component to coordinate with its children — easiest done with Alpine `$dispatch` events from sliders to a parent `x-data` count, OR each section reads from a shared `x-data` store.

If the parent-child coordination is too involved, simpler fallback: drop the live count, just show "{{ total_count }} criteria" with no live progress. Cleaner code, less dynamic feedback. **Cowork's call** — implement live count if straightforward, fall back to static count if it requires more than ~30 lines.

## View template — `view.html` (read-only evaluation view)

The submitted-evaluation view currently displays scores. Update to render N/A entries:

```html
{% for s in scores %}
  <li class="flex justify-between">
    <span>{{ s.name_en }}</span>
    {% if s.is_not_applicable %}
      <span class="font-mono text-sm">
        <span class="px-2 py-0.5 rounded text-xs"
              style="background:var(--surface);color:var(--text-muted);
                     border:1px solid var(--border);">
          N/A · غير متخصص
        </span>
      </span>
    {% else %}
      <span class="font-mono text-sm" style="color:var(--brand);">
        {{ '%.1f'|format(s.score) }}
      </span>
    {% endif %}
  </li>
{% endfor %}
```

## Verification protocol

After all code is written:

1. **Generate SQL** via `_generate_phase_5c1_1.py`
2. **Dry-run** via `_dryrun_5c1_1.py` — savepoint+rollback against live DB
3. **Apply** via `psql -f migrations/phase_5c1_1_na_column.sql`
4. **Update schema.sql** — declarative in-place (no ALTERs added)
5. **Throwaway-namespace verify** via `_verify_throwaway_5c1_1.py`
6. **Restart Flask**:
   ```powershell
   .\.venv\Scripts\Activate.ps1
   flask --app wsgi run --debug
   ```
7. **Browser test:**
   - Log in as admin → New Evaluation on Arthur Rezende → fresh form opens
   - Drag slider 1 to 7.5 → value display shows "7.5", ✕ button appears
   - Click ✕ → value goes back to "—", ✕ disappears, slider visually back to centered
   - Drag slider 2 to 6 → click N/A → slider greys, value shows "N/A", N/A button is highlighted
   - Click N/A again → returns to untouched (— display, no highlight)
   - Drag slider 3 to 8.5, click N/A → confirms slider drag is disabled while N/A active
   - Click N/A on slider 3 to disable → slider re-enabled, but at value 5 (centered, not previous 8.5 — by design, N/A clears prior rating)
   - Fill required NT level + recommendation
   - Save Draft
   - Reopen form → all 3 slider states should reload faithfully (slider 1 untouched, slider 2 untouched, slider 3 untouched)
   - Re-rate sliders 1+2, mark slider 3 as N/A
   - Submit → status flips to submitted
   - View the submitted evaluation → N/A renders as "N/A · غير متخصص" badge, rated criteria show numeric score
8. **DB verification:**
   ```powershell
   psql -U bfa -d bfa_scout -c "SELECT criterion_id, score, is_not_applicable FROM evaluation_scores WHERE evaluation_id = (SELECT MAX(id) FROM evaluations) ORDER BY criterion_id;"
   ```
   Should show 3 rows: 2 rated (score set, is_not_applicable=FALSE), 1 N/A (score NULL, is_not_applicable=TRUE).

## Acceptance criteria

- ✅ Pre-flight gates pass
- ✅ Migration runs cleanly, AUDIT PASS NOTICE
- ✅ schema.sql throwaway-namespace verify passes
- ✅ Flask restarts without errors
- ✅ Slider untouched → no DB row (verified by DB query)
- ✅ Slider rated → row with score=value, is_not_applicable=FALSE
- ✅ Slider N/A → row with score=NULL, is_not_applicable=TRUE
- ✅ ✕ reset on rated slider returns to untouched (visually + on submission)
- ✅ N/A toggle reversible (click again returns to untouched)
- ✅ N/A active disables slider drag
- ✅ Existing 3 submitted evaluations still display correctly (no rendering errors)
- ✅ View template renders N/A as "غير متخصص" badge
- ✅ DB CHECK constraint blocks malformed (score+NA both set) inserts
- ✅ Section progress count includes N/A as "decided" (or static fallback if too complex)

## Hard rules

- ❌ Do NOT modify auth, players, criteria taxonomy, wyscout/parser, wyscout/ingest
- ❌ Do NOT touch lock workflow (5c-2)
- ❌ Do NOT touch evaluations history view (5c-2)
- ❌ Do NOT use flask.test_client() for verification — restart real Flask
- ❌ Do NOT initialize git or commit — Ali commits manually
- ❌ Do NOT touch `D:\BFA-Analytics` or `D:\BFA-Analytics-AWS`
- ❌ Do NOT add ALTER statements to schema.sql — declarative-only
- ✅ Wrap migration in transaction with audit gate
- ✅ Pre-flight gate aborts on unexpected state
- ✅ Generator script as source of truth (mirror Phase 5b/5c-1 pattern)
- ✅ Throwaway-namespace verification before declaring done
- ✅ Append v0.5.0c1.1 entry to CHANGELOG.md
- ✅ Update PROJECT.md to mark 5c-1.1 complete

## Out of scope (do NOT build)

- Lock workflow (5c-2)
- History cards on profile (5c-2)
- Eligibility status display card (5c-2)
- Mobile polish (5c-2)
- Editing submitted evaluations beyond what already exists
- N/A in radar/aggregation logic (deferred — current radar treats missing as 0; need to revisit when 5e aggregation is built)

## Session discipline

- Target: 5–6 messages
- After every code change: restart Flask + browser-verify the slider behavior
- Verify all 13 acceptance criteria explicitly
- After session, Ali commits:
  ```powershell
  cd D:\BFA-Scout
  git add -A
  git commit -m "Phase 5c-1.1: Tri-state slider (untouched/rated/N/A) with reversible reset and N/A toggle"
  ```
