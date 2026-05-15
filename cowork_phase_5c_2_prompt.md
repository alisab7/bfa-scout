# Cowork/Claude Code Session: BFA-Scout Phase 5c-2 — Final Form Story

## Context

Phase 5c-1.1 is committed. The evaluation form has tri-state sliders (untouched / rated / N/A `غير متخصص`), reversible reset, reversible N/A toggle, and verified end-to-end. Three submitted evaluations exist on Arthur Rezende and Saifaldeen Bouhra for testing.

**5c-2 closes the form story.** This is the phase that makes the platform usable end-to-end by a real BFA committee — submitted evaluations finally appear on the player profile, lock/unlock workflow protects records, eligibility status is visible, mobile UX is polished, and Arabic labels are baked in.

After 5c-2, project status hits ~85%: true MVP. After Phase 6 (PDF Player Passport) it hits demo-ready for BFA leadership.

**Working folder:** `D:\BFA-Scout`. Do NOT touch `D:\BFA-Analytics` or `D:\BFA-Analytics-AWS`.

**Local environment:**
- PostgreSQL 15 native, database `bfa_scout`, user `bfa`, password `bfa2025`
- Python venv at `.venv`
- Flask via `flask --app wsgi run --debug`

## Eleven items, locked scope

1. **Evaluations history cards on profile** — replaces the "Coming in Phase 5c-2" placeholder
2. **Lock workflow** — admin/TD locks submitted evaluations
3. **Reversible unlock** — admin/TD unlocks with required reason text
4. **Admin direct-edit on submitted evaluations** with visible "edited by admin" badge
5. **Eligibility status card on profile** (status + date + countdown)
6. **`bahrain_residency_start_date` + `bahrain_residency_notes` columns** on players
7. **Eligibility admin block extended** with residency-start-date input + 5-year suggested-date UX
8. **Latest-3 NT-readiness summary line** on eligibility card
9. **Mobile polish on form** — sticky save bar, slider thumb size, accordion behavior
10. **Soft warning if scout submits with <5 criteria rated**
11. **Arabic translations** on NT Readiness section, eligibility options, major form actions

Plus housekeeping: **orphaned-scores cleanup when admin changes player position**.

## Locked decisions (do not deviate)

| Decision | Choice |
|---|---|
| History layout | Card per evaluation: scout name, date, match, NT level + recommendation badges, summary snippet (first 200 chars). Click expand → full criteria scores grid (N/A-aware). Most-recent first. |
| Lock workflow | admin/TD only. Adds row to audit_log with action='evaluation.locked' |
| Unlock | admin/TD only. Required reason text (min 10 chars). Audit-logged with reason. |
| Admin direct-edit | admin/TD can edit submitted (NOT locked) evaluations. Original scout-id preserved. New `last_edited_by` column tracks who last touched it. Visible "edited by admin on YYYY-MM-DD" badge. Audit-logged. |
| Eligibility status display | ✅ "Eligible now" if eligible_from_date ≤ today / ⏳ "Eligible in Xy Ym" if future / ❌ "Not eligible" if status = 'not_eligible' / "Status unknown" otherwise |
| Latest-3 NT summary | Pulls last 3 SUBMITTED OR LOCKED evaluations. Counts NT level votes. Format: "Latest 3: Senior NT (1), U23 (2)" or similar. |
| Residency rule constant | `RESIDENCY_YEARS_REQUIRED = 5` in app/players/eligibility.py with explicit code comment |
| Suggested date UX | Read-only line below `eligible_from_date` input: "Suggested: 2027-08-15 ⓘ" with hover tooltip "Based on 5-year continuous residence (Article 5 default — confirm with eligibility advisor)" + [Use suggestion] button |
| Mobile slider thumb | Min 32×32px touch target; 44×44 preferred per iOS HIG |
| Sticky save bar | Save Draft + Submit pinned to bottom of viewport on mobile (<768px) when form is scrolled |
| Soft warning threshold | < 5 sliders rated (rated only, N/A doesn't count toward this). Warning is non-blocking confirm modal: "You've rated only X criteria. Submit anyway?" |
| Orphaned-scores handling | When admin changes primary_position_id, count orphans (criteria not in new position group). Confirm modal: "Position change will orphan N existing scores. Delete them or keep as historical record?" Two buttons. |

## Pre-flight gates

```powershell
# Gate 1: 5c-1.1 committed
git log --oneline | Select-String "5c-1.1"
# expect: at least one commit

# Gate 2: clean working tree
git status
# expect: nothing to commit

# Gate 3: tri-state schema in place
psql -U bfa -d bfa_scout -c "\d evaluation_scores" | Select-String "is_not_applicable"
# expect: column shown

# Gate 4: 14 evaluation_scores rows still exist
psql -U bfa -d bfa_scout -c "SELECT COUNT(*) FROM evaluation_scores;"
# expect: 14

# Gate 5: 3 submitted evaluations
psql -U bfa -d bfa_scout -c "SELECT COUNT(*) FROM evaluations WHERE status = 'submitted';"
# expect: 3
```

## Translation table (BAKED IN — DO NOT MODIFY)

Every label rendered in templates MUST use the Arabic value from this table when displaying both EN+AR. Do not invent translations.

| English | Arabic |
|---|---|
| **Section labels** | |
| NT Readiness | الجاهزية لتمثيل المنتخب |
| **NT readiness levels** | |
| Senior NT | المنتخب الأول |
| U23 | تحت 23 |
| U20 | تحت 20 |
| U17 | تحت 17 |
| Not yet ready | غير جاهز حالياً |
| **Recommendations** | |
| Call up immediately | استدعاء فوري |
| Shortlist for next window | اضافة الى قائمة الترشحيات للفترة القادمة |
| Monitor | متابعة |
| Not at level | لا يصل للمستوى |
| Release / no further interest | لا يوجد اهتمام |
| **Eligibility statuses** | |
| Bahraini citizen | مواطن بحريني |
| Foreign-eligible (residency) | مؤهل (إقامة) |
| Foreign-eligible (ancestry) | مؤهل (نسب) |
| Foreign-eligible (other) | مؤهل (أخرى) |
| Not eligible | غير مؤهل |
| Unknown | غير معروف |
| **Form actions / labels** | |
| Save Draft | الحفظ كـ مسودة |
| Submit | إرسال |
| New Evaluation | تقييم جديد |
| Add new match | إضافة مباراة جديدة |
| Comparable player | لاعب يمكن مقارنته به |
| Eligibility notes | ملاحظات في استحقاق تمثيل المنتخب |

## Files to create / modify

```
migrations/
├── _generate_phase_5c2.py             [NEW] Source-of-truth generator
├── phase_5c2_lock_and_eligibility.sql [NEW] Migration artifact
├── _dryrun_5c2.py                     [NEW] Savepoint+rollback verify-without-apply
└── _verify_throwaway_5c2.py           [NEW] Schema.sql convergence test

schema.sql                              [MODIFY] In-place CREATE edits — no ALTERs:
                                                  - players: add bahrain_residency_start_date, bahrain_residency_notes
                                                  - evaluations: add locked_at, locked_by, locked_reason, last_edited_by, last_edited_at
                                                  - evaluations.status CHECK: extend to include 'locked'

app/players/
├── __init__.py                         [MODIFY] Edit player route handles new residency fields, orphaned-scores confirm flow
└── eligibility.py                      [NEW] RESIDENCY_YEARS_REQUIRED constant + helper functions

app/evaluations/
├── __init__.py                         [MODIFY] Add lock/unlock routes, admin-edit route
├── helpers.py                          [MODIFY] get_player_evaluations(player_id, limit=None), nt_readiness_summary(player_id)
└── forms.py                            [MODIFY] Soft-warning logic in submit handler

app/templates/
├── players/
│   ├── profile.html                    [MODIFY] Replace placeholder with history cards + eligibility card
│   └── edit.html                       [MODIFY] Add residency-start-date + suggested-date UX + orphaned-scores confirm modal
├── evaluations/
│   ├── _history_card.html              [NEW] Card per evaluation
│   ├── _eligibility_card.html          [NEW] Status + date + countdown
│   ├── _lock_modal.html                [NEW] Lock/unlock confirmations
│   ├── _soft_warning_modal.html        [NEW] <5 ratings warning
│   ├── view.html                       [MODIFY] Add lock/unlock/admin-edit buttons (role-gated), "edited by admin" badge
│   └── form.html                       [MODIFY] Sticky save bar on mobile, soft-warning trigger, Arabic labels
│
└── _arabic.html                        [NEW] Centralized translation macro library (optional — see below)

CHANGELOG.md                            [APPEND] v0.5.0c2 entry
PROJECT.md                              [UPDATE] Mark 5c-2 complete, queue Phase 6
```

## Schema changes

```sql
-- 1. Players residency tracking (admin-set)
ALTER TABLE players
    ADD COLUMN bahrain_residency_start_date DATE,
    ADD COLUMN bahrain_residency_notes TEXT;

-- 2. Evaluations: lock + admin-edit tracking
ALTER TABLE evaluations
    ADD COLUMN locked_at TIMESTAMPTZ,
    ADD COLUMN locked_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN locked_reason TEXT,
    ADD COLUMN last_edited_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN last_edited_at TIMESTAMPTZ;

-- 3. Extend status CHECK to include 'locked'
ALTER TABLE evaluations DROP CONSTRAINT IF EXISTS evaluations_status_check;
ALTER TABLE evaluations ADD CONSTRAINT evaluations_status_check
    CHECK (status IN ('draft', 'submitted', 'locked'));
```

**Audit gate inside transaction:**
```sql
DO $$
DECLARE
    bad_status_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO bad_status_count FROM evaluations
    WHERE status NOT IN ('draft','submitted','locked');
    IF bad_status_count > 0 THEN
        RAISE EXCEPTION 'AUDIT FAIL — % evaluations with invalid status', bad_status_count;
    END IF;
    RAISE NOTICE 'AUDIT PASS — schema 5c-2 migration applied';
END $$;
```

## Routes

| Method | Path | Decorator | Purpose |
|---|---|---|---|
| GET | `/players/<id>` | existing | Profile now renders eligibility card + evaluations history |
| POST | `/evaluations/<id>/lock` | `@admin_or_td_required` | Lock a submitted eval |
| POST | `/evaluations/<id>/unlock` | `@admin_or_td_required` | Unlock with required `reason` form field (min 10 chars) |
| POST | `/evaluations/<id>/admin-edit` | `@admin_or_td_required` | Admin overwrites scout content; locks not editable; audit-logged |
| POST | `/players/<id>/edit` | existing | Now handles residency_start_date, residency_notes, eligibility fields |

All audit-logged with appropriate action codes:
- `evaluation.locked` — { eval_id, locker_id, target_status }
- `evaluation.unlocked` — { eval_id, unlocker_id, reason }
- `evaluation.admin_edited` — { eval_id, admin_id, fields_changed }
- `player.position_changed` — { player_id, old_position_id, new_position_id, orphans_deleted }

## Templates — key components

### `_eligibility_card.html` (rendered on profile)

```html
{% set elig = compute_eligibility(player) %}
<div class="rounded-lg p-4 mt-4"
     style="background:var(--surface);border:1px solid var(--border);">
  <h3 class="font-semibold text-sm mb-3">National-Team Eligibility</h3>

  <div class="flex items-baseline gap-2 mb-2">
    <span class="text-lg">{{ elig.icon }}</span>
    <span class="font-medium" style="color:var(--text);">{{ elig.label }}</span>
  </div>

  {% if elig.note %}
    <p class="text-sm" style="color:var(--text-muted);">{{ elig.note }}</p>
  {% endif %}

  {# Latest-3 summary line #}
  {% set summary = nt_readiness_summary(player.id) %}
  {% if summary.total > 0 %}
    <p class="text-xs mt-2" style="color:var(--text-muted);">
      Latest {{ summary.total }} evaluations:
      {% for level, count in summary.breakdown.items() %}
        {{ level }} ({{ count }}){% if not loop.last %}, {% endif %}
      {% endfor %}
    </p>
  {% endif %}
</div>
```

### `_history_card.html` (one per evaluation)

```html
<div class="rounded-lg p-4 mb-3"
     style="background:var(--surface);border:1px solid var(--border);"
     x-data="{ expanded: false }">

  <!-- Header -->
  <div class="flex justify-between items-start mb-2">
    <div>
      <p class="text-sm font-medium">
        {{ ev.evaluator_name }}
        {% if ev.last_edited_by and ev.last_edited_by != ev.evaluator_id %}
          <span class="ml-2 text-xs px-2 py-0.5 rounded"
                style="background:var(--brand);color:white;"
                title="Edited by {{ ev.last_edited_by_name }} on {{ ev.last_edited_at.strftime('%Y-%m-%d') }}">
            Edited by admin
          </span>
        {% endif %}
      </p>
      <p class="text-xs" style="color:var(--text-muted);">
        {{ ev.match_label or 'Freestanding' }} · {{ ev.match_date.strftime('%Y-%m-%d') }}
      </p>
    </div>
    <div class="flex gap-2">
      {# NT readiness badge #}
      <span class="px-2 py-1 rounded text-xs font-semibold"
            style="background:var(--accent);color:var(--bg);">
        {{ NT_LEVEL_LABEL_AR.get(ev.nt_readiness_level, ev.nt_readiness_level) }}
      </span>
      {# Recommendation badge #}
      <span class="px-2 py-1 rounded text-xs font-semibold"
            style="background:var(--brand);color:white;">
        {{ RECOMMENDATION_LABEL_AR.get(ev.recommendation, ev.recommendation) }}
      </span>
      {# Status badge — locked icon if applicable #}
      {% if ev.status == 'locked' %}
        <span class="text-xs" title="Locked">🔒</span>
      {% endif %}
    </div>
  </div>

  <!-- Summary snippet -->
  {% if ev.summary %}
    <p class="text-sm mb-2">
      {{ ev.summary[:200] }}{% if ev.summary|length > 200 %}…{% endif %}
    </p>
  {% endif %}

  <!-- Expand toggle -->
  <button type="button"
          @click="expanded = !expanded"
          class="text-xs underline"
          style="color:var(--text-muted);"
          x-text="expanded ? 'Hide details' : 'Show all scores'"></button>

  <!-- Expanded details -->
  <div x-show="expanded" x-cloak class="mt-3 pt-3"
       style="border-top:1px solid var(--border);">
    {# Render criteria scores grid here, organized by category #}
    {# N/A-aware: for is_not_applicable rows, show "N/A" badge instead of value #}

    {# Action buttons (role-gated) #}
    {% if current_user.has_role('admin', 'technical_director') %}
      <div class="mt-4 flex gap-2">
        {% if ev.status == 'submitted' %}
          <a href="{{ url_for('evaluations.view', eval_id=ev.id) }}#admin-edit"
             class="text-xs underline">Admin edit</a>
          <button @click="lockModal = true" class="text-xs underline">Lock</button>
        {% elif ev.status == 'locked' %}
          <button @click="unlockModal = true" class="text-xs underline">Unlock</button>
        {% endif %}
      </div>
    {% endif %}
  </div>
</div>
```

### `_lock_modal.html` and unlock modal

Confirmation modals. Lock is one-click. Unlock requires a `<textarea name="reason" minlength="10" required>` and a Confirm button.

### Sticky save bar — mobile-only, in `form.html`

```html
{# Top of form (existing) — buttons remain there for desktop #}
<div class="hidden md:flex ...">
  <button type="submit" name="action" value="save_draft">{{ T.save_draft }}</button>
  <button type="button" @click="submitConfirmModal = true">{{ T.submit }}</button>
</div>

{# Sticky bottom bar — visible only on mobile #}
<div class="md:hidden fixed bottom-0 left-0 right-0 z-40 px-4 py-3 flex gap-2 shadow-lg"
     style="background:var(--surface);border-top:1px solid var(--border);">
  <button type="submit" name="action" value="save_draft" class="flex-1 ...">{{ T.save_draft }}</button>
  <button type="button" @click="submitConfirmModal = true" class="flex-1 ...">{{ T.submit }}</button>
</div>

<!-- Reserve scrollable space for the sticky bar -->
<div class="md:hidden h-20"></div>
```

Slider thumb size mobile-friendly:
```css
input[type="range"]::-webkit-slider-thumb {
  width: 32px; height: 32px; /* desktop default ~16px */
}
@media (max-width: 768px) {
  input[type="range"]::-webkit-slider-thumb {
    width: 44px; height: 44px;
  }
}
input[type="range"]::-moz-range-thumb { /* Firefox equivalent */ }
```

### Soft warning modal in `form.html`

When user clicks Submit (the actual submit, not Save Draft), Alpine intercepts:

```javascript
function evalForm() {
  return {
    submitConfirmModal: false,
    lowRatingWarning: false,
    triggerSubmit() {
      // Count rated sliders (NOT N/A, NOT untouched)
      const ratedCount = document.querySelectorAll('input[type="range"][data-dirty="true"]:not([data-na="true"])').length;
      if (ratedCount < 5) {
        this.lowRatingWarning = true;
      } else {
        this.submitConfirmModal = true;
      }
    },
    actuallySubmit() {
      this.submitConfirmModal = false;
      this.lowRatingWarning = false;
      // Set hidden field action=submit, then form.submit()
      document.querySelector('[name="action"][value="submit"]').click();
    }
  }
}
```

### Eligibility admin block — extended

In `players/edit.html`, add:

```html
{% if current_user.has_role('admin', 'technical_director') %}
  <fieldset class="rounded-lg p-4 mt-6" ...>
    <!-- Existing nationality_status, eligible_from_date, eligibility_notes_admin -->

    <label>Bahrain residency start date (for residency-route eligibility)</label>
    <input type="date" name="bahrain_residency_start_date"
           value="{{ player.bahrain_residency_start_date|default('') }}">

    <label>Residency notes</label>
    <textarea name="bahrain_residency_notes" rows="2">{{ player.bahrain_residency_notes|default('') }}</textarea>

    {# Suggested-date display #}
    {% if player.bahrain_residency_start_date %}
      {% set suggested = compute_suggested_eligibility(player.bahrain_residency_start_date) %}
      <p class="text-xs mt-2" style="color:var(--text-muted);">
        Suggested: <span class="font-mono">{{ suggested.strftime('%Y-%m-%d') }}</span>
        <span title="Based on 5-year continuous residence (Article 5 default — confirm with eligibility advisor)" class="cursor-help">ⓘ</span>
        <button type="button"
                @click="document.querySelector('[name=eligible_from_date]').value = '{{ suggested.strftime('%Y-%m-%d') }}'"
                class="ml-2 underline">Use suggestion</button>
      </p>
    {% endif %}
  </fieldset>
{% endif %}
```

### Position-change orphaned-scores flow

In `players/edit.html` POST handler:

```python
# If primary_position_id changes, count scores that will be orphaned
if old_pos_id != new_pos_id:
    # Orphaned criteria: those in evaluation_scores for player's evaluations
    # whose criterion_id is NOT in position_group_criteria for new_pos_id
    orphan_count = count_orphan_scores(player_id, new_pos_id)
    if orphan_count > 0 and not request.form.get('orphan_decision'):
        # Render edit form again with confirm modal showing orphan_count
        # User picks: 'delete' (DELETE orphan rows) or 'keep' (leave them)
        return render_template('players/edit.html',
                               player=player,
                               orphan_confirm=True,
                               orphan_count=orphan_count)
    # User decided: act on it
    if request.form.get('orphan_decision') == 'delete':
        delete_orphan_scores(player_id, new_pos_id)
    # 'keep' = no action, position changes silently
```

Audit-logged: `player.position_changed` with `orphans_deleted` count or `orphans_kept`.

## Helpers

### `app/players/eligibility.py`

```python
from datetime import date, timedelta

# FIFA Article 5 baseline. Confirm with BFA eligibility advisor before
# relying on this for any selection decision. Override per-player via
# `eligible_from_date` admin field if a specific case differs.
RESIDENCY_YEARS_REQUIRED = 5

def compute_suggested_eligibility(residency_start: date) -> date | None:
    """Returns residency_start + RESIDENCY_YEARS_REQUIRED years, or None."""
    if not residency_start:
        return None
    return date(residency_start.year + RESIDENCY_YEARS_REQUIRED,
                residency_start.month, residency_start.day)

def compute_eligibility_status(player: dict) -> dict:
    """Returns dict for template:
       {'icon': '✅' / '⏳' / '❌' / '?',
        'label': str, 'note': str | None}
    """
    if player.get('nationality_status') == 'not_eligible':
        return {'icon': '❌', 'label': 'Not eligible', 'note': None}
    edate = player.get('eligible_from_date')
    if not edate:
        return {'icon': '?', 'label': 'Status unknown', 'note': None}
    today = date.today()
    if edate <= today:
        return {'icon': '✅', 'label': 'Eligible now', 'note': None}
    diff_years = (edate - today).days // 365
    diff_months = ((edate - today).days % 365) // 30
    return {
        'icon': '⏳',
        'label': f'Eligible in {diff_years}y {diff_months}m',
        'note': f'From {edate.strftime("%Y-%m-%d")}'
    }
```

### `app/evaluations/helpers.py` additions

```python
def get_player_evaluations(player_id: int, status_filter=None) -> list[dict]:
    """Returns list of evaluations for player, ordered by submitted_at DESC.
    Each dict includes:
      - id, status, nt_readiness_level, recommendation, summary, submitted_at, locked_at
      - match_label, match_date (joined from matches)
      - evaluator_id, evaluator_name (joined from users)
      - last_edited_by, last_edited_by_name
      - scores: list of {criterion_id, score, is_not_applicable, name_en, name_ar, category_code}
    """

def nt_readiness_summary(player_id: int, last_n: int = 3) -> dict:
    """Returns:
       {'total': int, 'breakdown': {'Senior NT': 1, 'U23': 2, ...}}
       Pulls last N submitted-or-locked evaluations.
    """
```

## Verification protocol

After all code:

1. **Generate SQL** via `_generate_phase_5c2.py`
2. **Dry-run** via `_dryrun_5c2.py`
3. **Apply** migration
4. **Update schema.sql** in-place (no ALTERs)
5. **Throwaway-namespace verify**
6. **Restart Flask**, run synthetic E2E:
   - GET `/players/2` → eligibility card visible (status: depends on Arthur's nationality_status — may be unknown)
   - GET `/players/2` → 3 history cards rendered (one per submitted eval)
   - Expand a history card → criteria scores render, N/A-aware
   - POST `/evaluations/1/lock` (as admin) → status flips to 'locked'
   - DB check: `SELECT status, locked_at, locked_by FROM evaluations WHERE id = 1` → 'locked', timestamp set, admin id set
   - POST `/evaluations/1/unlock` with reason "Test unlock" (10+ chars) → status back to 'submitted'
   - POST `/evaluations/1/unlock` with reason "Bad" (< 10 chars) → 400 or flash error
   - Edit Arthur's player record, set bahrain_residency_start_date = 2022-08-15 → verify suggested = 2027-08-15 appears in UI
   - Click "Use suggestion" → form populates eligible_from_date with 2027-08-15
   - Save → verify DB has both fields populated
   - Refresh profile → eligibility card shows "⏳ Eligible in 1y Xm" (or whatever 2027-08-15 minus today is)
   - Try to change Arthur's position from AMF (AM group) to GK → orphan-confirm modal appears showing N orphans
   - Click "Delete" → verify orphan rows gone from DB; click "Keep" → verify they remain
   - Submit a new evaluation with only 2 criteria rated → soft warning modal appears
   - Confirm anyway → submission succeeds with 2 ratings stored
7. **Mobile responsive check** — resize browser to 375px wide, scroll the form, verify sticky save bar pinned to bottom, slider thumbs ≥ 44px

## Acceptance criteria (write each ✅/❌ at session end)

- ✅ Pre-flight gates pass (5)
- ✅ Migration AUDIT PASS, throwaway-namespace verify PASS
- ✅ Profile shows eligibility card + history cards (no "Coming in Phase 5c-2" remnant)
- ✅ Lock POST flips status, audit-logged
- ✅ Unlock with valid reason flips status back, audit-logged
- ✅ Unlock with <10-char reason rejected with friendly error
- ✅ Admin edit on submitted preserves original evaluator_id, sets last_edited_by, shows badge
- ✅ Admin edit blocked on locked evaluations
- ✅ Eligibility card renders 4 states correctly (eligible / pending with countdown / not eligible / unknown)
- ✅ Latest-3 NT summary line renders when ≥1 submitted eval exists
- ✅ Residency input + suggested-date UX works end-to-end
- ✅ Position change with orphan scores → confirm modal → delete OR keep both work
- ✅ Soft warning < 5 ratings → confirm modal → submit anyway works
- ✅ Mobile: sticky save bar visible at <768px, ≥44px slider thumbs
- ✅ All Arabic translations baked in verbatim from the table (no inventions)
- ✅ View template handles 'locked' status (no edit button visible to scout)
- ✅ schema.sql declarative-only (no ALTERs added)

## Hard rules

- ❌ Do NOT modify auth, criteria taxonomy, wyscout/parser, wyscout/ingest
- ❌ Do NOT change the 5c-1.1 tri-state slider behavior
- ❌ Do NOT use flask.test_client() for verification — restart real Flask
- ❌ Do NOT initialize git or commit — Ali commits manually
- ❌ Do NOT touch `D:\BFA-Analytics` or `D:\BFA-Analytics-AWS`
- ❌ Do NOT add ALTER statements to schema.sql — declarative-only
- ❌ Do NOT invent Arabic translations — use the table verbatim
- ❌ Do NOT change RESIDENCY_YEARS_REQUIRED to anything other than 5
- ✅ Wrap migration in transaction with audit gate
- ✅ Pre-flight gate aborts on unexpected state
- ✅ Generator → migration → dry-run → apply → schema.sql → throwaway-namespace pattern
- ✅ Every state-changing route audit-logged
- ✅ Append v0.5.0c2 entry to CHANGELOG.md
- ✅ Update PROJECT.md to mark 5c-2 complete, queue Phase 6

## Out of scope (do NOT build)

- Editing locked evaluations (impossible by design — must unlock first)
- Hard-deleting evaluations
- Bulk operations
- NT readiness aggregation across all evaluations (Phase 5e)
- Comparison page scout dimension (Phase 5d)
- Player Passport PDF (Phase 6)
- Configurable RESIDENCY_YEARS_REQUIRED via UI (deferred indefinitely)
- Auto-translation of all UI strings to Arabic (only the table baked in)

## Session discipline

- Target: 8–12 messages
- After every code change: restart Flask + browser-or-curl verify
- Verify all 17 acceptance criteria explicitly with ✅/❌
- After session, Ali commits:
  ```powershell
  cd D:\BFA-Scout
  git add -A
  git commit -m "Phase 5c-2: History cards, lock workflow, admin edit, eligibility card, residency tracking, mobile polish, Arabic"
  ```
