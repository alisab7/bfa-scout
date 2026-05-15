# BFA-Scout — Phase 5 Criteria Taxonomy (v2 — LOCKED FOR RESEED)

**Status:** Final after Mentality trim. Counts verified by Python script, not eyeballed. Ready for Phase 5a reseed once Phase 4.1 is committed and constraint name is verified.

**Total items: 55**
- Technical: 20
- Tactical: 20
- Physical: 9
- Mentality: 6 (trimmed from 12 — see "What was dropped" below)

**Total `position_group_criteria` mappings: 303**

**Form sizes (verified):**

| Position | Tech | Tact | Phys | Ment | Total |
|---|---|---|---|---|---|
| GK | 10 | 5 | 3 | 6 | **24** |
| CB | 9 | 18 | 9 | 6 | **42** |
| FB | 10 | 18 | 8 | 6 | **42** |
| DM | 9 | 18 | 7 | 6 | **40** |
| CM | 10 | 16 | 5 | 6 | **37** |
| AM | 14 | 16 | 6 | 6 | **42** |
| W | 9 | 16 | 7 | 6 | **38** |
| ST | 9 | 15 | 8 | 6 | **38** |

These are the audit-query expected values for Phase 5a step 6.

---

## Category: TECHNICAL (20 items)

| Code | Item (EN) | Item (AR — placeholder) | Applies to |
|---|---|---|---|
| `tech_first_touch` | First touch quality (under pressure & in space) | جودة استلام الكرة | All |
| `tech_passing_short` | Short passing — accuracy & weight | التمرير القصير | All |
| `tech_passing_long` | Long passing — range & accuracy | التمرير الطويل | GK, CB, FB, DM, CM, AM |
| `tech_passing_press` | Passing under defensive pressure | التمرير تحت الضغط | All |
| `tech_passing_progressive` | Vertical / progressive passing selection | التمرير التقدمي | DM, CM, AM, FB |
| `tech_crossing` | Crossing — quality & consistency | جودة العرضيات | FB, W, AM |
| `tech_finishing` | Finishing — both feet, composure in box | التهديف | DM, CM, AM, W, ST |
| `tech_finishing_chances` | Conversion of half-chances vs. clear-cut | استغلال الفرص | AM, W, ST |
| `tech_dribbling_1v1` | 1v1 dribbling — *functional* (not just attempted) | المراوغة الفعالة | FB, DM, CM, AM, W, ST |
| `tech_dribbling_press` | Carrying ball under pressure | التحكم تحت الضغط أثناء التقدم | CM, AM, W |
| `tech_set_pieces_taking` | Set-piece delivery quality (corners/free-kicks) | تنفيذ الكرات الثابتة | CB, FB, CM, AM |
| `tech_set_pieces_attacking` | Attacking set-pieces (heading/finishing in box) | الكرات الثابتة الهجومية | CB, AM, ST |
| `tech_heading_offensive` | Aerial — offensive (attacking corners, crosses) | الضربات الرأسية الهجومية | CB, AM, ST |
| `tech_heading_defensive` | Aerial — defensive (clearing crosses, set-piece defending) | الضربات الرأسية الدفاعية | GK, CB, FB, DM |
| `tech_ball_striking` | Ball striking — distance shooting, free-kicks | جودة التسديد | All except GK |
| `tech_gk_shot_stopping` | Shot stopping — reactions, positioning, handling | التصدي | GK |
| `tech_gk_handling` | Handling under pressure (catches, parries, drops) | الإمساك بالكرة | GK |
| `tech_gk_distribution` | Distribution — short, long, under press | توزيع الكرة | GK |
| `tech_gk_crosses` | Cross claiming — command of area | التعامل مع العرضيات | GK |
| `tech_gk_sweeper` | Sweeping behind defensive line | اللعب كالليبيرو | GK |

---

## Category: TACTICAL (20 items)

| Code | Item (EN) | Item (AR — placeholder) | Applies to |
|---|---|---|---|
| `tact_positioning_def` | Defensive positioning | التموضع الدفاعي | All |
| `tact_positioning_att` | Attacking positioning (off the ball) | التموضع الهجومي | All except GK |
| `tact_scanning` | Scanning frequency before receiving | النظر للمحيط قبل الاستلام | All |
| `tact_body_orientation` | Body orientation when receiving | اتجاه الجسم عند الاستلام | All except GK |
| `tact_decision_making` | Decision-making speed & quality | اتخاذ القرار | All |
| `tact_off_ball_movement` | Off-ball movement & space creation | الحركة بدون كرة | All except GK |
| `tact_runs_in_behind` | Runs in behind — timing & frequency | الجري خلف الدفاع | AM, W, ST |
| `tact_pressing_trigger` | Pressing — recognition of triggers | قراءة لحظات الضغط | All except GK |
| `tact_pressing_intensity` | Pressing — intensity & sustainability | شدة الضغط | All except GK |
| `tact_def_shape` | Maintaining defensive shape (within unit) | الانضباط الدفاعي | All except GK |
| `tact_def_recovery` | Recovery work after losing ball | العودة الدفاعية | FB, CM, AM, W |
| `tact_marking` | Marking discipline (zonal & man-to-man) | الرقابة | All except GK |
| `tact_back_post_cover` | Back-post coverage on diagonal balls | تغطية القائم البعيد | CB, FB, DM |
| `tact_long_ball_cover` | Covering depth on long balls / counter | التغطية في الكرات الطويلة | CB, FB, DM |
| `tact_one_v_one_def` | 1v1 defending — body shape, timing | الدفاع الفردي | All except GK |
| `tact_build_up` | Build-up contribution from back/middle third | بناء الهجمة | GK, CB, FB, DM |
| `tact_third_man_runs` | Third-man runs / combination play | لعب المثلثات | All except GK |
| `tact_communication` | Tactical communication / organising teammates | التواصل التكتيكي | GK, CB, DM, CM |
| `tact_transition_def_to_att` | Defensive→attacking transition speed | الانتقال من الدفاع للهجوم | All except GK |
| `tact_transition_att_to_def` | Attacking→defensive transition speed | الانتقال من الهجوم للدفاع | All except GK |

---

## Category: PHYSICAL (9 items)

| Code | Item (EN) | Item (AR — placeholder) | Applies to |
|---|---|---|---|
| `phys_speed_acceleration` | Acceleration over 5–10m | التسارع | All except GK |
| `phys_speed_top` | Top speed | السرعة القصوى | CB, FB, AM, W, ST |
| `phys_strength_duels` | Strength in ground duels (50/50s, shoulder-to-shoulder) | القوة في الالتحامات | All except GK |
| `phys_strength_aerial` | Aerial dominance (jump + power) | القوة في الضربات الهوائية | GK, CB, ST |
| `phys_agility` | Agility — change of direction | الرشاقة | All |
| `phys_stamina_90min` | Stamina across 90+ minutes | اللياقة (90 دقيقة كاملة) | All |
| `phys_recovery_speed` | Recovery speed (chasing back) | سرعة العودة | CB, FB, DM, W |
| `phys_balance` | Balance under contact | التوازن | All except GK |
| `phys_robustness` | Physical robustness (handles contact, doesn't go down easy) | الصلابة البدنية | CB, FB, DM, ST |

---

## Category: MENTALITY & CHARACTER (6 items — trimmed from 12)

| Code | Item (EN) | Item (AR — placeholder) |
|---|---|---|
| `ment_composure` | Composure under pressure | الهدوء تحت الضغط |
| `ment_leadership` | Leadership — vocal & by example | القيادة |
| `ment_concentration` | Concentration over full match | التركيز |
| `ment_resilience` | Resilience after mistakes (visible in body language) | تحمل الأخطاء |
| `ment_work_rate` | Work rate without the ball | الجهد بدون كرة |
| `ment_winning_mentality` | Visible winning mentality / hunger / will to win duels | عقلية الفوز |

All 6 apply to **All** position groups.

### What was dropped (and why)

- `ment_body_language` → folded into `ment_resilience` (body language IS the visible signal of resilience)
- `ment_aggression` → folded into `ment_winning_mentality` (winning mentality directed at duels = aggression)
- `ment_discipline` → cards already in Wyscout, reaction-to-officials too rare to reliably score
- `ment_coachability` → hard to observe in a single 90; depends on whether coach gives mid-match instructions
- `ment_response_to_provocation` → edge-case event, sub-set of discipline
- `ment_team_player` → better expressed in free-text summary than 1–10 slider

---

## Category: NATIONAL-TEAM READINESS (5 fields, categorical)

Dedicated section in the form. Lives in `evaluations` table directly via 4 new columns + extends `recommendation` CHECK constraint. NOT scored on 1–10 sliders.

| Field | Type | Options |
|---|---|---|
| `nt_readiness_level` | radio (required) | Senior NT • U23 • U20 • U17 • Not yet ready |
| `eligibility_status` | radio (required) | Bahraini citizen • Foreign-eligible (residency) • Foreign-eligible (ancestry) • Foreign-eligible (other) • Not eligible • Unknown |
| `eligibility_notes` | text (optional) | Free text — explain foreign-eligibility route, key facts |
| `comparable_player` | text (optional) | "Plays like X" |
| `recommendation` | radio (required, CHECK extended) | Call up immediately • Shortlist for next window • Monitor • Not at level • Release/no further interest |

---

## Schema additions for Phase 5a

**Step 1 — verify the existing CHECK constraint name** (run BEFORE Phase 5a session):

```powershell
psql -U bfa -d bfa_scout -c "SELECT conname FROM pg_constraint WHERE conrelid = 'evaluations'::regclass AND contype = 'c';"
```

Look for the constraint that checks `recommendation IN ('monitor','call_up','shortlist','release','not_ready')` (the original Phase 0 values). Note its actual name. Replace `<RECOMMENDATION_CHECK_NAME>` below with that real name.

**Step 2 — schema changes to apply:**

```sql
-- 1. Add 4 new columns to evaluations
ALTER TABLE evaluations
  ADD COLUMN nt_readiness_level VARCHAR(16)
    CHECK (nt_readiness_level IN ('senior','u23','u20','u17','not_ready') OR nt_readiness_level IS NULL),
  ADD COLUMN eligibility_status VARCHAR(32)
    CHECK (eligibility_status IN ('bahraini','foreign_residency','foreign_ancestry','foreign_other','not_eligible','unknown') OR eligibility_status IS NULL),
  ADD COLUMN eligibility_notes  TEXT,
  ADD COLUMN comparable_player  VARCHAR(255);

-- 2. Update recommendation CHECK constraint
--    Use the actual constraint name from step 1, NOT the assumed default
ALTER TABLE evaluations DROP CONSTRAINT <RECOMMENDATION_CHECK_NAME>;
ALTER TABLE evaluations ADD CONSTRAINT evaluations_recommendation_check
  CHECK (recommendation IN ('call_up','shortlist','monitor','not_at_level','release') OR recommendation IS NULL);
```

---

## Reseed plan — Phase 5a executes in this order

1. Run constraint-name discovery query (above), inject real name into ALTER
2. `BEGIN;` — wrap the entire reseed in one transaction
3. `DELETE FROM position_group_criteria;` — safe, depends on criteria
4. `DELETE FROM criteria;` — safe, evaluation_scores is empty (no scout has filled an eval yet)
5. INSERT all 55 items into `criteria` with codes from this taxonomy
6. INSERT 303 mappings into `position_group_criteria` per the "Applies to" columns
7. ALTER evaluations table per schema additions above (with verified constraint name)
8. Audit query — verify per-position counts match the table at top:
   ```sql
   SELECT pg.code,
          COUNT(*) FILTER (WHERE c.code LIKE 'tech_%') AS tech,
          COUNT(*) FILTER (WHERE c.code LIKE 'tact_%') AS tact,
          COUNT(*) FILTER (WHERE c.code LIKE 'phys_%') AS phys,
          COUNT(*) FILTER (WHERE c.code LIKE 'ment_%') AS ment,
          COUNT(*) AS total
   FROM position_groups pg
   LEFT JOIN position_group_criteria pgc ON pgc.position_group_id = pg.id
   LEFT JOIN criteria c ON c.id = pgc.criterion_id
   GROUP BY pg.code, pg.sort_order
   ORDER BY pg.sort_order;
   ```
   Expected:
   ```
    GK | 10 |  5 | 3 | 6 | 24
    CB |  9 | 18 | 9 | 6 | 42
    FB | 10 | 18 | 8 | 6 | 42
    DM |  9 | 18 | 7 | 6 | 40
    CM | 10 | 16 | 5 | 6 | 37
    AM | 14 | 16 | 6 | 6 | 42
     W |  9 | 16 | 7 | 6 | 38
    ST |  9 | 15 | 8 | 6 | 38
   ```
9. If any number is off → ROLLBACK (transaction-safe). Diagnose and re-run.
10. If all green → `COMMIT;`

---

## What's still TBD

1. **Arabic translations** — placeholders confirmed acceptable for v1
2. **Per-criterion weights** — out of scope for v1
3. **Trimming after first real evaluation** — Ali's "judge after first use" call
