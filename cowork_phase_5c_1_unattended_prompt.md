# Claude Code Session: BFA-Scout Phase 5c-1 — Evaluation Form (UNATTENDED-SAFE)

**THIS SESSION RUNS WITHOUT ALI PRESENT. EVERY DECISION IS LOCKED IN THIS PROMPT.
DO NOT WAIT FOR USER INPUT AT ANY POINT. IF UNCERTAIN, PICK THE SIMPLEST PATH AND
DOCUMENT IT IN THE RESULT FILE.**

## Critical: unattended-session protocol

Throughout this session:

1. **Always write progress to `D:\BFA-Scout\PHASE_5C1_RESULT.md`** at every significant step. This file is Ali's only window into what happened. If the session crashes, the partial file is the diagnostic.

2. **Decision-making under uncertainty:** if a UX detail isn't specified in this prompt, pick the simplest path and add the decision to the "Review-later" section of the result file. Do NOT pause or ask.

3. **Pre-flight failure:** if any pre-flight gate fails, immediately stop, write `D:\BFA-Scout\PHASE_5C1_ABORTED.md` with the failure reason, and exit. Do NOT attempt to fix unknown state.

4. **Audit-gate failure inside migration:** the transaction ROLLBACKs automatically; write `D:\BFA-Scout\PHASE_5C1_AUDIT_FAILED.md` with full mismatch details, then exit.

5. **No git commits.** Ali commits manually after reviewing the result file.

6. **No git initialization, no destructive git operations.** Treat git as read-only.

## Context

Phase 5b is committed (matches table + Wyscout auto-link + 33 matches backfilled).
Phase 5a is committed (55-item criteria taxonomy, 303 mappings, NT readiness columns
on evaluations).

**Phase 5c-1 builds the evaluation form itself** — the heart of the BFA-Scout
product. The form Cowork builds in this session is what scouts will use pitchside.

**Working folder:** `D:\BFA-Scout`. NEVER touch `D:\BFA-Analytics` or
`D:\BFA-Analytics-AWS`.

**Local environment:**
- PostgreSQL 15 native, database `bfa_scout`, user `bfa`, password `bfa2025`
- Python venv at `D:\BFA-Scout\.venv`
- Flask via `flask --app wsgi run --debug`
- Phase 5a + 5b committed; verify in pre-flight

## What's in scope vs. out of scope

### IN scope (Phase 5c-1)
1. Schema additions: 3 columns on `players`, real FK on `evaluations.match_id`
2. Match selection in form (dropdown of all matches, most-recent-first)
3. Inline "Add new match" modal (creates `matches` row on the fly)
4. Position-aware criteria form (24–42 sliders rendered from `position_group_criteria`)
5. NT Readiness section (5 fields per evaluation)
6. Draft + submit workflow with manual save-draft button
7. Per-evaluation `evaluation_scores` rows for each criterion the scout interacted with (NULL stays NULL — partial submissions allowed)
8. Admin/TD-only UI on player edit form for setting eligibility (3 new player columns)
9. New route: `/players/<id>/evaluate` → form
10. New route: `/evaluations/<id>` → view/edit submitted evaluation

### OUT of scope (deferred to 5c-2 or later)
- Lock workflow (admin/TD locking submitted evaluations)
- Per-player evaluations history section on profile
- Eligibility status display card on profile
- Mobile responsiveness polish (basic mobile-friendly OK, holistic pass later)
- Editing a submitted evaluation (only drafts editable in 5c-1)
- Bulk operations
- Evaluation deletion (defer)

## Locked decisions — do not deviate

| Decision | Choice |
|---|---|
| Slider component | Native HTML `<input type="range">`, styled with Tailwind/CSS, value display next to slider via Alpine |
| Slider scale | 1 to 10, step = 0.5 |
| Untouched-slider behavior | Slider DOM defaults to 5 visually; submission stores NULL unless scout interacted with it. Track interaction via Alpine `dirty` flag per slider. |
| Form layout | Accordion: 5 sections (Tech / Tact / Phys / Ment / NT Readiness), all visible, expand to fill. First section expanded by default. |
| Save-draft | Manual button only. NO auto-save. Posts the entire form as draft (status='draft'). |
| Draft retrieval | If a scout opens evaluate-form for a player+match they already have a draft for, that draft loads. One draft per (player, match, scout). |
| Submit confirmation | Simple modal: "Submit this evaluation? You can edit until an admin locks it." Cancel + Confirm buttons. |
| Match dropdown sort | match_date DESC, no filtering by club |
| Match dropdown limit | 50 most recent matches; if more exist, show "Use Add New Match for older fixtures" |
| Inline "Add new match" — required fields | match_date, home_team, away_team, age_group, match_type |
| Inline "Add new match" — optional fields | home_score, away_score, competition, notes |
| NT Readiness Level | Required to submit (radio: senior/u23/u20/u17/not_ready) |
| Recommendation | Required to submit (radio: call_up/shortlist/monitor/not_at_level/release) |
| Eligibility status (per-evaluation) | Optional |
| Eligibility notes (per-evaluation) | Optional |
| Comparable player (per-evaluation) | Optional |
| Player-level eligibility status | New column `nationality_status` (admin sets) |
| Player-level eligible-from date | New column `eligible_from_date` (admin sets manually, no FIFA logic) |
| Player-level eligibility notes | New column `eligibility_notes_admin` (TEXT, admin set; named with `_admin` to disambiguate from per-evaluation `eligibility_notes` field on evaluations) |
| Auto-compute eligibility | NO. Admin manually sets `eligible_from_date`. UI just displays it. |

## Pre-flight gates (run BEFORE any changes)

Write the results to `PHASE_5C1_RESULT.md` as the FIRST thing you do.
If any gate fails, abort per protocol above.

```powershell
# Gate 1: Phase 5b committed
git log --oneline | Select-String "5b"
# expect: a commit with "Phase 5b" in the message

# Gate 2: matches table exists
psql -U bfa -d bfa_scout -c "SELECT COUNT(*) FROM matches;"
# expect: 33 (or near; if it errors, abort)

# Gate 3: 55 criteria, 303 mappings (Phase 5a state)
psql -U bfa -d bfa_scout -c "SELECT COUNT(*) FROM criteria;"
# expect: 55
psql -U bfa -d bfa_scout -c "SELECT COUNT(*) FROM position_group_criteria;"
# expect: 303

# Gate 4: evaluations table has Phase 5a columns
psql -U bfa -d bfa_scout -c "\d evaluations" | Select-String "nt_readiness_level"
# expect: column exists

# Gate 5: working tree clean
git status
# expect: nothing to commit
```

## Files to create / modify

```
migrations/
├── _generate_phase_5c1.py        [NEW] Source-of-truth generator
├── phase_5c1_form_schema.sql     [NEW] Migration artifact (3 cols on players, FK on evaluations.match_id)
├── _dryrun_5c1.py                [NEW] Savepoint+rollback verify-without-apply
└── _verify_throwaway_5c1.py      [NEW] Schema.sql convergence test

schema.sql                         [MODIFY] Add 3 cols on players CREATE in-place; add FK on evaluations.match_id

app/
├── evaluations/
│   ├── __init__.py                [REPLACE STUB] Routes for create/view/save-draft/submit
│   ├── helpers.py                 [NEW] Form rendering helpers, criterion-by-position-group resolver
│   └── forms.py                   [NEW] Form validation logic
├── players/
│   └── __init__.py                [MODIFY] Add eligibility fields to /players/<id>/edit (admin/TD only block)
└── templates/
    ├── evaluations/
    │   ├── form.html              [NEW] The main evaluation form
    │   ├── _slider.html           [NEW] Reusable slider component (one criterion)
    │   ├── _section.html          [NEW] Reusable accordion section (one category)
    │   ├── _match_picker.html     [NEW] Match dropdown + Add-new-match modal
    │   ├── _nt_readiness.html     [NEW] NT readiness section (5 fields)
    │   ├── _submit_modal.html     [NEW] Submit confirmation modal
    │   └── view.html              [NEW] Read-only / editable view of an evaluation
    └── players/
        ├── edit.html              [MODIFY] Add admin/TD eligibility block at bottom
        └── profile.html           [MODIFY] Add "New Evaluation" button (visible to scout role and above)

CHANGELOG.md                       [APPEND] v0.5.0c1 entry
PROJECT.md                         [UPDATE] Mark 5c-1 complete, queue 5c-2
PHASE_5C1_RESULT.md                [NEW] Final result document — see protocol above
```

## Schema changes

### `players` — 3 new columns

```sql
ALTER TABLE players
    ADD COLUMN nationality_status     VARCHAR(32)
        CHECK (nationality_status IN ('bahraini','foreign_ancestry','foreign_residency','not_eligible','unknown') OR nationality_status IS NULL),
    ADD COLUMN eligible_from_date     DATE,
    ADD COLUMN eligibility_notes_admin TEXT;
```

All nullable. No data backfill needed.

### `evaluations` — promote `match_id` to a real FK

The existing `match_id` column is INTEGER, currently no FK. Make it a real FK to
matches with `ON DELETE SET NULL` (preserves evaluation if a match is deleted).

```sql
ALTER TABLE evaluations
    ADD CONSTRAINT evaluations_match_id_fkey
    FOREIGN KEY (match_id) REFERENCES matches(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_evaluations_match_id ON evaluations (match_id);
```

**Important:** before adding the FK, check that no existing `evaluations.match_id` values violate the FK (the column is currently a free integer, possibly with stale values). If any exist, set them to NULL first:

```sql
UPDATE evaluations
SET match_id = NULL
WHERE match_id IS NOT NULL
  AND match_id NOT IN (SELECT id FROM matches);
```

Audit gate inside transaction: confirm 0 evaluations rows where `match_id IS NOT NULL AND match_id NOT IN (SELECT id FROM matches)`.

## Routes

| Method | Path | Decorator | Purpose |
|---|---|---|---|
| GET  | `/players/<int:player_id>/evaluate` | `@scout_or_above` | Render new-evaluation form (or load existing draft) |
| POST | `/players/<int:player_id>/evaluate` | `@scout_or_above` | Save draft OR submit (button-name disambiguates) |
| GET  | `/evaluations/<int:eval_id>` | `@any_authenticated` | View evaluation (read-only if submitted; editable if draft and same scout) |
| POST | `/evaluations/<int:eval_id>` | `@scout_or_above` | Update draft (only own drafts editable) |
| POST | `/evaluations/<int:eval_id>/submit` | `@scout_or_above` | Transition draft → submitted |
| POST | `/matches/new-inline` | `@scout_or_above` | Create a match inline from the modal, return JSON `{id, label}` |

## Form rendering — helpers.py

```python
def get_form_criteria(position_group_id: int) -> list[dict]:
    """
    Returns ALL criteria for a position group, joined to category info.
    Ordered by (category sort_order, criterion sort_order).

    Each row dict:
      - criterion_id, criterion_code, name_en, name_ar
      - category_id, category_code, category_name_en, category_name_ar
      - scale_min, scale_max, allow_half
      - sort_order

    Used by form.html to render sliders grouped by category.
    """
    sql = """
    SELECT c.id AS criterion_id, c.code AS criterion_code,
           c.name_en, c.name_ar,
           cc.id AS category_id, cc.code AS category_code,
           cc.name_en AS category_name_en, cc.name_ar AS category_name_ar,
           c.scale_min, c.scale_max, c.allow_half,
           c.sort_order
    FROM position_group_criteria pgc
    JOIN criteria c ON c.id = pgc.criterion_id
    JOIN criteria_categories cc ON cc.id = c.category_id
    WHERE pgc.position_group_id = %s
      AND c.is_active = TRUE
    ORDER BY cc.sort_order, c.sort_order
    """

def get_or_create_draft(player_id: int, match_id: int, scout_id: int) -> dict:
    """
    Returns the existing draft for (player, match, scout) if one exists,
    else creates a new draft row in 'evaluations' (status='draft') and returns it.
    Returns dict with: id, player_id, match_id, evaluator_id, status, etc.
    """

def save_evaluation_scores(eval_id: int, scores: dict) -> int:
    """
    UPSERT evaluation_scores rows. scores is {criterion_id: value} where value
    is a number 1-10 in 0.5 steps, or None for untouched.
    Skips None values entirely. Returns count of rows written.
    """

def submit_draft(eval_id: int, scout_id: int) -> tuple[bool, str]:
    """
    Validates required fields filled (nt_readiness_level + recommendation),
    then transitions status from 'draft' to 'submitted'. Sets submitted_at.
    Returns (ok, message). Only the original scout can submit their own draft.
    """
```

## Templates

### `form.html` — the main form

Layout:

1. **Header strip** — player photo + name + position badge + age. Re-uses get_player_photo, get_player_pos.
2. **Match selector** — dropdown of recent 50 matches (date desc), formatted as "2026-04-16 · Muharraq vs Khalidiya". Below dropdown: "Match not listed? [Add new match]" — opens modal.
3. **Save Draft button + Submit button** at top right (sticky on scroll for mobile).
4. **Accordion sections** — 5 of them:
   - Technical (expanded by default)
   - Tactical
   - Physical
   - Mentality
   - NT Readiness (different content — radios + text fields, not sliders)
5. **Summary text area** at the bottom (free text — anything that doesn't fit a slider).

Every slider:
- Label: criterion `name_en` (and `name_ar` smaller below)
- Slider input with current value displayed numerically (e.g. "7.5") to the right
- Slider DOM attribute: `data-criterion-id="123"`, `data-dirty="false"`
- On user interaction (Alpine `@input`): set `data-dirty="true"`, update display
- Submission form-data: only sliders with `data-dirty="true"` get included

Save Draft posts to same URL with `name="action" value="save_draft"`.
Submit posts with `name="action" value="submit"` AND triggers the confirm modal first.

### `_match_picker.html`

```html
<div x-data="{ showModal: false }">
  <select name="match_id" required class="w-full ...">
    <option value="">— Select a match —</option>
    {% for m in recent_matches %}
      <option value="{{ m.id }}" {% if m.id == selected_match_id %}selected{% endif %}>
        {{ m.match_date.strftime('%Y-%m-%d') }} · {{ m.home_team }} vs {{ m.away_team }}
      </option>
    {% endfor %}
  </select>
  <p class="text-xs mt-1" style="color:var(--text-muted);">
    Match not listed?
    <button type="button" @click="showModal = true" class="underline">Add new match</button>
  </p>

  <!-- Modal -->
  <div x-show="showModal" x-cloak class="fixed inset-0 z-50 flex items-center justify-center bg-black/70">
    <div class="rounded-xl p-6 max-w-md w-full" style="background:var(--surface);border:1px solid var(--border);">
      <h3 class="font-bold mb-4">Add a new match</h3>
      <!-- Required: date, home_team, away_team, age_group, match_type -->
      <!-- Optional: home_score, away_score, competition, notes -->
      <!-- On submit, fetch POST /matches/new-inline, then update select dropdown -->
    </div>
  </div>
</div>
```

The inline-create POSTs to `/matches/new-inline`, server returns JSON `{id, label}`,
JS prepends a new `<option>` to the select and selects it. Modal closes.

### `_section.html` — accordion section

```html
<details {% if expanded %}open{% endif %}
         class="rounded-lg mb-3"
         style="background:var(--surface);border:1px solid var(--border);">
  <summary class="px-4 py-3 cursor-pointer font-semibold flex justify-between items-center">
    {{ category.name_en }}
    <span class="text-xs" style="color:var(--text-muted);">
      {{ filled_count }} / {{ total_count }} rated
    </span>
  </summary>
  <div class="px-4 pb-4 space-y-4">
    {% for crit in criteria %}
      {% include 'evaluations/_slider.html' %}
    {% endfor %}
  </div>
</details>
```

Use native `<details>` element — accessible, keyboard-friendly, no JS needed for
expand/collapse. Alpine x-data only inside slider for the dirty-tracking.

### `_slider.html`

```html
<div x-data="{ value: 5, dirty: false }" class="border-b pb-3">
  <div class="flex justify-between items-center mb-1">
    <label class="text-sm font-medium">
      {{ crit.name_en }}
      <span class="block text-xs" style="color:var(--text-muted);">{{ crit.name_ar }}</span>
    </label>
    <span class="font-mono text-sm" style="color:var(--brand);"
          x-text="dirty ? value : '—'"></span>
  </div>
  <input type="range"
         min="{{ crit.scale_min }}"
         max="{{ crit.scale_max }}"
         step="{% if crit.allow_half %}0.5{% else %}1{% endif %}"
         x-model="value"
         @input="dirty = true"
         :name="dirty ? 'score_' + {{ crit.criterion_id }} : ''"
         class="w-full">
</div>
```

The `:name="dirty ? '...' : ''"` pattern is critical: untouched sliders have empty
`name` attribute, so the browser doesn't include them in form submission. Touched
sliders have `name="score_<criterion_id>"`.

Server-side: parse all keys starting with `score_`, extract the criterion_id from
the suffix. Build a `{criterion_id: value}` dict. UPSERT into `evaluation_scores`.
Skip any criterion_ids not present (i.e. NULL stays NULL — exactly the behavior
locked in decisions).

### NT Readiness section

5 fields, NOT sliders:

```html
<div class="space-y-4">
  <!-- nt_readiness_level: required radio -->
  <div>
    <label class="block text-sm font-semibold mb-2">NT Readiness Level *</label>
    <div class="space-y-1">
      <label><input type="radio" name="nt_readiness_level" value="senior" required> Senior NT</label>
      <label><input type="radio" name="nt_readiness_level" value="u23"> U23</label>
      <label><input type="radio" name="nt_readiness_level" value="u20"> U20</label>
      <label><input type="radio" name="nt_readiness_level" value="u17"> U17</label>
      <label><input type="radio" name="nt_readiness_level" value="not_ready"> Not yet ready</label>
    </div>
  </div>
  <!-- recommendation: required radio -->
  <!-- eligibility_status: optional radio (6 options) -->
  <!-- eligibility_notes: optional textarea -->
  <!-- comparable_player: optional text input -->
</div>
```

Pre-fill from existing draft if loading.

## Player edit form — eligibility block (admin/TD only)

In `templates/players/edit.html`, near the bottom, add:

```html
{% if current_user.has_role('admin', 'technical_director') %}
  <fieldset class="rounded-lg p-4 mt-6"
            style="background:var(--surface);border:1px solid var(--border);">
    <legend class="px-2 font-semibold">National-Team Eligibility (admin)</legend>

    <label>Status</label>
    <select name="nationality_status">
      <option value="">— Unknown —</option>
      <option value="bahraini">Bahraini citizen</option>
      <option value="foreign_ancestry">Foreign-eligible (ancestry)</option>
      <option value="foreign_residency">Foreign-eligible (residency)</option>
      <option value="not_eligible">Not eligible</option>
      <option value="unknown">Unknown</option>
    </select>

    <label>Eligible from (date)</label>
    <input type="date" name="eligible_from_date">
    <p class="text-xs">When the player becomes eligible for national-team selection. For Bahraini citizens, today's date or earlier. Leave blank if unknown.</p>

    <label>Notes</label>
    <textarea name="eligibility_notes_admin" rows="3"></textarea>
  </fieldset>
{% endif %}
```

Modify the `/players/<id>/edit` POST handler to read these 3 fields and UPDATE
`players` accordingly. Only allow update if current_user has admin or TD role
(decorator-level enforcement existing routes already have).

## "New Evaluation" entry point on player profile

Modify `templates/players/profile.html` to add a button visible to scouts and above:

```html
{% if current_user.has_role('admin', 'technical_director', 'scout') %}
  <a href="{{ url_for('evaluations.new', player_id=player.id) }}"
     class="btn-primary">New Evaluation</a>
{% endif %}
```

Place near the "Edit / Deactivate" buttons.

## Verification protocol — RUN AFTER CODE IS WRITTEN

After all code changes, run the full unattended verification sequence. Write
results to `PHASE_5C1_RESULT.md` as you go.

### Sequence:

1. **Run migration:**
   ```powershell
   psql -U bfa -d bfa_scout -f migrations\phase_5c1_form_schema.sql
   ```
   Verify the audit DO-block prints "AUDIT PASS".

2. **Update schema.sql:** Add the 3 new columns to `players` CREATE in-place; add the FK on `evaluations.match_id` in-place. No ALTER statements.

3. **Throwaway-namespace verify:** Run `_verify_throwaway_5c1.py`. Confirm schema.sql produces the same final state as the migration on the live DB.

4. **Restart Flask in the background:**
   ```powershell
   .\.venv\Scripts\Activate.ps1
   Start-Process -NoNewWindow -FilePath flask -ArgumentList "--app","wsgi","run","--debug","--port","5057" -RedirectStandardOutput flask.log
   Start-Sleep -Seconds 4
   ```

5. **Run a synthetic end-to-end test using Python's stdlib HTTP** (no curl chains; one Python script):

   - Create or use existing admin session (cookied)
   - GET `/players/2/evaluate` (Arthur Rezende) → 200, form HTML present, all 4 category sections present, ~42 sliders for AM position
   - POST `/players/2/evaluate` with `action=save_draft`, match_id=11 (the shared fixture), scores dict for ~5 sliders, nt_readiness_level=u23, recommendation=monitor
   - Verify DB: `SELECT id, player_id, match_id, status, nt_readiness_level FROM evaluations WHERE evaluator_id = <admin_id> ORDER BY id DESC LIMIT 1` → row exists with status='draft', match_id=11
   - Verify DB: `SELECT criterion_id, score FROM evaluation_scores WHERE evaluation_id = <id>` → 5 rows, no NULLs
   - GET `/players/2/evaluate` again → form should LOAD the draft (re-using the (player, match, scout) tuple), sliders should pre-fill the 5 saved values
   - POST again with `action=submit`, all required fields filled (nt_readiness_level, recommendation already set)
   - Verify DB: status='submitted', submitted_at NOT NULL

6. **Stop Flask** when done with synthetic test.

7. **Verify all artifacts written:**
   - `migrations/phase_5c1_form_schema.sql` exists
   - `migrations/_generate_phase_5c1.py` exists
   - `migrations/_dryrun_5c1.py` exists
   - `migrations/_verify_throwaway_5c1.py` exists
   - `app/evaluations/__init__.py`, `helpers.py`, `forms.py`
   - All 7 templates in `app/templates/evaluations/`
   - `players/edit.html` modified
   - `players/profile.html` modified
   - `CHANGELOG.md` has v0.5.0c1 entry
   - `PROJECT.md` marked 5c-1 complete

## Acceptance criteria — write to PHASE_5C1_RESULT.md as ✅/❌

| # | Check | How verified |
|---|---|---|
| 1 | Pre-flight gates pass | psql + git output |
| 2 | Migration runs cleanly, AUDIT PASS | psql output |
| 3 | 3 new columns on players | `\d players` shows them |
| 4 | FK on evaluations.match_id | `\d evaluations` shows constraint |
| 5 | schema.sql throwaway-namespace verify | Python script outputs PASS |
| 6 | Flask restarts without errors | flask.log shows "Running on" |
| 7 | GET /players/2/evaluate returns 200 | HTTP test |
| 8 | Form has correct number of sliders for player's position | DOM count matches `position_group_criteria` count |
| 9 | Save draft POST creates evaluation row + scores | DB query |
| 10 | Reopening form loads the draft | Form pre-fills with saved values |
| 11 | Submit POST transitions to submitted, validates required | DB query + status check |
| 12 | Untouched sliders → NULL in DB (not stored) | Score count = touched-slider count, not total |
| 13 | Inline match modal creates a matches row | DB query after POST to /matches/new-inline |
| 14 | Player edit form shows eligibility block to admin | GET as admin shows fieldset |
| 15 | Same form does NOT show eligibility block to scout | GET as scout test (use existing scout user) |

## Hard rules

- ❌ Do NOT modify auth, players (CRUD logic), criteria, wyscout/parser, wyscout/ingest
- ❌ Do NOT modify schema.sql with ALTER statements — declarative only (in-place CREATE edits)
- ❌ Do NOT initialize git, do not commit
- ❌ Do NOT touch `D:\BFA-Analytics` or `D:\BFA-Analytics-AWS`
- ❌ Do NOT use `flask.test_client()` for verification — restart real Flask + cookied stdlib HTTP
- ❌ Do NOT add lock workflow (5c-2)
- ❌ Do NOT add evaluations history view on profile (5c-2)
- ❌ Do NOT modify nationality_status auto-fill logic — admin sets manually
- ❌ Do NOT change criteria scale or allow_half settings
- ✅ Wrap migration in transaction with audit gate
- ✅ Pre-flight gate that aborts on unexpected state
- ✅ Generator script as source of truth (mirror Phase 5b pattern)
- ✅ Throwaway-namespace verification before declaring done
- ✅ Append v0.5.0c1 entry to CHANGELOG.md
- ✅ Update PROJECT.md
- ✅ Write PHASE_5C1_RESULT.md throughout the session

## Out of scope (DO NOT BUILD — Phase 5c-2 or 5e)

- Lock workflow (5c-2)
- Evaluations history section on player profile (5c-2)
- Eligibility status display card on profile (5c-2)
- Holistic mobile responsiveness pass (5c-2)
- Editing submitted (non-draft) evaluations (deferred entirely; admin must unlock)
- Aggregating scout readiness across evaluations (5e)
- Divergence flagging (5e)
- Evaluation deletion (deferred)

## Session discipline

- Target: complete in one continuous unattended session
- Write progress to PHASE_5C1_RESULT.md at every significant step (pre-flight, schema migration, schema.sql update, each new file written, each verification step)
- If anything aborts, write a clear reason to PHASE_5C1_ABORTED.md or PHASE_5C1_AUDIT_FAILED.md
- The result file is Ali's only diagnostic — be verbose, include actual SQL output and HTTP response snippets

## Final-status requirements

When the session ends (success or failure), `PHASE_5C1_RESULT.md` MUST contain:

1. Pre-flight gate results (5 entries, ✅/❌)
2. Migration results (audit DO-block output, 1 row of pass/fail)
3. Schema.sql throwaway-namespace verify results
4. Each acceptance criterion 1-15 with ✅/❌ status and evidence (SQL output, HTTP snippet, or reason for failure)
5. Files modified/created list
6. "Review-later" section: any UX defaults Cowork picked that weren't fully specified in this prompt
7. "Next-session" recommendation: what Phase 5c-2 should pick up
8. Final pass/fail summary at top: "PHASE 5C-1 COMPLETE ✅" or "PHASE 5C-1 INCOMPLETE — see details below ❌"

If ANY acceptance criterion is ❌, the session is INCOMPLETE. Don't claim COMPLETE.

After the session, Ali commits manually:
```powershell
cd D:\BFA-Scout
git add -A
git commit -m "Phase 5c-1: Evaluation form (matches selection, dynamic criteria, draft/submit, eligibility admin)"
```
