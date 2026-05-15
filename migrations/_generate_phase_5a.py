"""
Generator for migrations/phase_5a_reseed.sql

Builds the migration mechanically from the v2-LOCKED taxonomy so the SQL
matches the spec exactly — no eyeballed mapping resolution.

Run from repo root:
    python migrations/_generate_phase_5a.py

Writes:
    migrations/phase_5a_reseed.sql

Also asserts the per-position counts match the spec's expected table BEFORE
emitting any SQL. If counts disagree, the script aborts with the diff.
"""
from __future__ import annotations
from pathlib import Path

ALL = ["GK", "CB", "FB", "DM", "CM", "AM", "W", "ST"]
OUT = [g for g in ALL if g != "GK"]   # All except GK

# (code, name_en, name_ar, applies_to: list[str], sort_order)
TECH = [
    ("tech_first_touch",          "First touch quality (under pressure & in space)",  "جودة استلام الكرة",                       ALL,                                              101),
    ("tech_passing_short",        "Short passing — accuracy & weight",                "التمرير القصير",                          ALL,                                              102),
    ("tech_passing_long",         "Long passing — range & accuracy",                  "التمرير الطويل",                          ["GK","CB","FB","DM","CM","AM"],                  103),
    ("tech_passing_press",        "Passing under defensive pressure",                 "التمرير تحت الضغط",                       ALL,                                              104),
    ("tech_passing_progressive",  "Vertical / progressive passing selection",         "التمرير التقدمي",                         ["DM","CM","AM","FB"],                            105),
    ("tech_crossing",             "Crossing — quality & consistency",                 "جودة العرضيات",                           ["FB","W","AM"],                                  106),
    ("tech_finishing",            "Finishing — both feet, composure in box",          "التهديف",                                 ["DM","CM","AM","W","ST"],                        107),
    ("tech_finishing_chances",    "Conversion of half-chances vs. clear-cut",         "استغلال الفرص",                           ["AM","W","ST"],                                  108),
    ("tech_dribbling_1v1",        "1v1 dribbling — functional (not just attempted)",  "المراوغة الفعالة",                        ["FB","DM","CM","AM","W","ST"],                   109),
    ("tech_dribbling_press",      "Carrying ball under pressure",                     "التحكم تحت الضغط أثناء التقدم",           ["CM","AM","W"],                                  110),
    ("tech_set_pieces_taking",    "Set-piece delivery quality (corners/free-kicks)",  "تنفيذ الكرات الثابتة",                    ["CB","FB","CM","AM"],                            111),
    ("tech_set_pieces_attacking", "Attacking set-pieces (heading/finishing in box)",  "الكرات الثابتة الهجومية",                 ["CB","AM","ST"],                                 112),
    ("tech_heading_offensive",    "Aerial — offensive (attacking corners, crosses)",  "الضربات الرأسية الهجومية",                ["CB","AM","ST"],                                 113),
    ("tech_heading_defensive",    "Aerial — defensive (clearing crosses, set-piece defending)", "الضربات الرأسية الدفاعية",      ["GK","CB","FB","DM"],                            114),
    ("tech_ball_striking",        "Ball striking — distance shooting, free-kicks",    "جودة التسديد",                            OUT,                                              115),
    ("tech_gk_shot_stopping",     "Shot stopping — reactions, positioning, handling", "التصدي",                                  ["GK"],                                           116),
    ("tech_gk_handling",          "Handling under pressure (catches, parries, drops)","الإمساك بالكرة",                          ["GK"],                                           117),
    ("tech_gk_distribution",      "Distribution — short, long, under press",          "توزيع الكرة",                             ["GK"],                                           118),
    ("tech_gk_crosses",           "Cross claiming — command of area",                 "التعامل مع العرضيات",                     ["GK"],                                           119),
    ("tech_gk_sweeper",           "Sweeping behind defensive line",                   "اللعب كالليبيرو",                         ["GK"],                                           120),
]

TACT = [
    ("tact_positioning_def",        "Defensive positioning",                            "التموضع الدفاعي",                       ALL,                                              201),
    ("tact_positioning_att",        "Attacking positioning (off the ball)",             "التموضع الهجومي",                       OUT,                                              202),
    ("tact_scanning",               "Scanning frequency before receiving",              "النظر للمحيط قبل الاستلام",             ALL,                                              203),
    ("tact_body_orientation",       "Body orientation when receiving",                  "اتجاه الجسم عند الاستلام",              OUT,                                              204),
    ("tact_decision_making",        "Decision-making speed & quality",                  "اتخاذ القرار",                          ALL,                                              205),
    ("tact_off_ball_movement",      "Off-ball movement & space creation",               "الحركة بدون كرة",                       OUT,                                              206),
    ("tact_runs_in_behind",         "Runs in behind — timing & frequency",              "الجري خلف الدفاع",                      ["AM","W","ST"],                                  207),
    ("tact_pressing_trigger",       "Pressing — recognition of triggers",               "قراءة لحظات الضغط",                     OUT,                                              208),
    ("tact_pressing_intensity",     "Pressing — intensity & sustainability",            "شدة الضغط",                             OUT,                                              209),
    ("tact_def_shape",              "Maintaining defensive shape (within unit)",        "الانضباط الدفاعي",                      OUT,                                              210),
    ("tact_def_recovery",           "Recovery work after losing ball",                  "العودة الدفاعية",                       ["FB","CM","AM","W"],                             211),
    ("tact_marking",                "Marking discipline (zonal & man-to-man)",          "الرقابة",                               OUT,                                              212),
    ("tact_back_post_cover",        "Back-post coverage on diagonal balls",             "تغطية القائم البعيد",                   ["CB","FB","DM"],                                 213),
    ("tact_long_ball_cover",        "Covering depth on long balls / counter",           "التغطية في الكرات الطويلة",             ["CB","FB","DM"],                                 214),
    ("tact_one_v_one_def",          "1v1 defending — body shape, timing",               "الدفاع الفردي",                         OUT,                                              215),
    ("tact_build_up",               "Build-up contribution from back/middle third",     "بناء الهجمة",                           ["GK","CB","FB","DM"],                            216),
    ("tact_third_man_runs",         "Third-man runs / combination play",                "لعب المثلثات",                          OUT,                                              217),
    ("tact_communication",          "Tactical communication / organising teammates",    "التواصل التكتيكي",                      ["GK","CB","DM","CM"],                            218),
    ("tact_transition_def_to_att",  "Defensive → attacking transition speed",           "الانتقال من الدفاع للهجوم",             OUT,                                              219),
    ("tact_transition_att_to_def",  "Attacking → defensive transition speed",           "الانتقال من الهجوم للدفاع",             OUT,                                              220),
]

PHYS = [
    ("phys_speed_acceleration", "Acceleration over 5–10m",                                                "التسارع",                  OUT,                                  301),
    ("phys_speed_top",          "Top speed",                                                              "السرعة القصوى",            ["CB","FB","AM","W","ST"],            302),
    ("phys_strength_duels",     "Strength in ground duels (50/50s, shoulder-to-shoulder)",                "القوة في الالتحامات",      OUT,                                  303),
    ("phys_strength_aerial",    "Aerial dominance (jump + power)",                                        "القوة في الضربات الهوائية","GK,CB,ST".split(","),                304),
    ("phys_agility",            "Agility — change of direction",                                          "الرشاقة",                  ALL,                                  305),
    ("phys_stamina_90min",      "Stamina across 90+ minutes",                                             "اللياقة (90 دقيقة كاملة)", ALL,                                  306),
    ("phys_recovery_speed",     "Recovery speed (chasing back)",                                          "سرعة العودة",              ["CB","FB","DM","W"],                 307),
    ("phys_balance",            "Balance under contact",                                                  "التوازن",                  OUT,                                  308),
    ("phys_robustness",         "Physical robustness (handles contact, doesn't go down easy)",            "الصلابة البدنية",          ["CB","FB","DM","ST"],                309),
]

MENT = [
    ("ment_composure",          "Composure under pressure",                                  "الهدوء تحت الضغط",            ALL, 401),
    ("ment_leadership",         "Leadership — vocal & by example",                           "القيادة",                     ALL, 402),
    ("ment_concentration",      "Concentration over full match",                             "التركيز",                     ALL, 403),
    ("ment_resilience",         "Resilience after mistakes (visible in body language)",      "تحمل الأخطاء",                ALL, 404),
    ("ment_work_rate",          "Work rate without the ball",                                "الجهد بدون كرة",              ALL, 405),
    ("ment_winning_mentality",  "Visible winning mentality / hunger / will to win duels",    "عقلية الفوز",                 ALL, 406),
]

CATEGORIES = [
    ("TECH", TECH),
    ("TACT", TACT),
    ("PHYS", PHYS),
    ("MENT", MENT),
]

# Spec's expected per-position counts (from v2-LOCKED doc)
EXPECTED = {
    "GK": {"tech":10, "tact": 5, "phys": 3, "ment": 6, "total": 24},
    "CB": {"tech": 9, "tact":18, "phys": 9, "ment": 6, "total": 42},
    "FB": {"tech":10, "tact":18, "phys": 8, "ment": 6, "total": 42},
    "DM": {"tech": 9, "tact":18, "phys": 7, "ment": 6, "total": 40},
    "CM": {"tech":10, "tact":16, "phys": 5, "ment": 6, "total": 37},
    "AM": {"tech":14, "tact":16, "phys": 6, "ment": 6, "total": 42},
    "W":  {"tech": 9, "tact":16, "phys": 7, "ment": 6, "total": 38},
    "ST": {"tech": 9, "tact":15, "phys": 8, "ment": 6, "total": 38},
}


def verify_counts() -> dict[str, dict[str, int]]:
    """Compute per-position counts from the taxonomy and assert vs EXPECTED."""
    actual = {g: {"tech": 0, "tact": 0, "phys": 0, "ment": 0, "total": 0} for g in ALL}
    for cat_code, items in CATEGORIES:
        cat_key = cat_code.lower()  # TECH → tech
        for code, _en, _ar, applies, _so in items:
            for g in applies:
                if g not in ALL:
                    raise SystemExit(f"BUG: code {code!r} maps to unknown group {g!r}")
                actual[g][cat_key] += 1
                actual[g]["total"] += 1
    diffs = []
    for g in ALL:
        for k in ("tech", "tact", "phys", "ment", "total"):
            if actual[g][k] != EXPECTED[g][k]:
                diffs.append(f"  {g}.{k}: actual={actual[g][k]} expected={EXPECTED[g][k]}")
    if diffs:
        raise SystemExit("Per-position counts disagree with v2-LOCKED spec:\n" + "\n".join(diffs))
    return actual


def sql_str(s: str) -> str:
    """Single-quote escape for a SQL literal. (No backslash-escapes in standard SQL.)"""
    return "'" + s.replace("'", "''") + "'"


def render_criteria_values(items: list[tuple], cat_code: str) -> list[str]:
    out = []
    for code, en, ar, _applies, sort_order in items:
        out.append(f"    ({sql_str(cat_code)}, {sql_str(code):<32}, {sql_str(en):<70}, {sql_str(ar):<46}, {sort_order:>4})")
    return out


def render_mapping_values(items: list[tuple]) -> list[str]:
    out = []
    for code, _en, _ar, applies, _so in items:
        codes_arr = "ARRAY[" + ",".join(sql_str(g) for g in applies) + "]"
        out.append(f"    ({sql_str(code):<34}, {codes_arr})")
    return out


def main():
    actual = verify_counts()
    total_items = sum(len(items) for _, items in CATEGORIES)
    total_mappings = sum(actual[g]["total"] for g in ALL)
    print(f"Counts verified vs spec — {total_items} items, {total_mappings} mappings.")
    print("Per-position totals: " + ", ".join(f"{g}={actual[g]['total']}" for g in ALL))

    # ───────────── render SQL ─────────────
    body = []
    body.append("-- =============================================================")
    body.append("-- BFA-Scout — Phase 5a reseed migration")
    body.append("-- Generated by migrations/_generate_phase_5a.py from v2-LOCKED")
    body.append("-- taxonomy. Do not edit by hand: re-run the generator instead.")
    body.append("-- =============================================================")
    body.append("-- Effects:")
    body.append("--   1. Pre-flight: aborts if evaluation_scores has rows or any")
    body.append("--      evaluation uses the legacy recommendation = 'not_ready'.")
    body.append(f"--   2. Reseeds criteria ({total_items} items) and")
    body.append(f"--      position_group_criteria ({total_mappings} mappings).")
    body.append("--   3. Adds 4 columns to evaluations (NT readiness section).")
    body.append("--   4. Drops + re-adds evaluations_recommendation_check with")
    body.append("--      the new value set (loses 'not_ready', gains 'not_at_level').")
    body.append("--   5. Audit assertions enforce per-position counts before COMMIT.")
    body.append("-- =============================================================")
    body.append("")
    body.append("\\set ON_ERROR_STOP on")
    body.append("\\timing on")
    body.append("")
    body.append("-- ─── Pre-flight (no transaction yet — fail fast before locking rows) ───")
    body.append("DO $$")
    body.append("DECLARE")
    body.append("  s_count INT;")
    body.append("  bad_recs INT;")
    body.append("BEGIN")
    body.append("  SELECT COUNT(*) INTO s_count FROM evaluation_scores;")
    body.append("  IF s_count > 0 THEN")
    body.append("    RAISE EXCEPTION 'ABORT: evaluation_scores has % row(s); reseed would orphan or violate FKs', s_count;")
    body.append("  END IF;")
    body.append("  SELECT COUNT(*) INTO bad_recs FROM evaluations WHERE recommendation = 'not_ready';")
    body.append("  IF bad_recs > 0 THEN")
    body.append("    RAISE EXCEPTION 'ABORT: % evaluation row(s) use legacy recommendation = not_ready; migrate them before re-running', bad_recs;")
    body.append("  END IF;")
    body.append("END $$;")
    body.append("")
    body.append("BEGIN;")
    body.append("")
    body.append("-- ─── Drop old criteria + their mappings ───")
    body.append("DELETE FROM position_group_criteria;")
    body.append("DELETE FROM criteria;")
    body.append("")
    body.append("-- ─── Insert 55 criteria (codes use category prefix; sort_order grouped per category) ───")
    body.append("INSERT INTO criteria (category_id, code, name_en, name_ar, sort_order)")
    body.append("SELECT cc.id, v.code, v.name_en, v.name_ar, v.sort_order")
    body.append("FROM (VALUES")
    blocks = []
    for cat_code, items in CATEGORIES:
        block_rows = render_criteria_values(items, cat_code)
        blocks.append(f"    -- {cat_code}\n" + ",\n".join(block_rows))
    body.append(",\n".join(blocks))
    body.append(") AS v(cat_code, code, name_en, name_ar, sort_order)")
    body.append("JOIN criteria_categories cc ON cc.code = v.cat_code;")
    body.append("")
    body.append(f"-- ─── Insert {total_mappings} position-group mappings ───")
    body.append("INSERT INTO position_group_criteria (position_group_id, criterion_id, sort_order)")
    body.append("SELECT pg.id, c.id, c.sort_order")
    body.append("FROM criteria c")
    body.append("JOIN (VALUES")
    blocks = []
    for cat_code, items in CATEGORIES:
        block_rows = render_mapping_values(items)
        blocks.append(f"    -- {cat_code}\n" + ",\n".join(block_rows))
    body.append(",\n".join(blocks))
    body.append(") AS m(criterion_code, group_codes) ON c.code = m.criterion_code")
    body.append("JOIN position_groups pg ON pg.code = ANY(m.group_codes);")
    body.append("")
    body.append("-- ─── NT-readiness columns + recommendation CHECK swap ───")
    body.append("ALTER TABLE evaluations")
    body.append("  ADD COLUMN nt_readiness_level VARCHAR(16)")
    body.append("    CHECK (nt_readiness_level IN ('senior','u23','u20','u17','not_ready') OR nt_readiness_level IS NULL),")
    body.append("  ADD COLUMN eligibility_status VARCHAR(32)")
    body.append("    CHECK (eligibility_status IN ('bahraini','foreign_residency','foreign_ancestry','foreign_other','not_eligible','unknown') OR eligibility_status IS NULL),")
    body.append("  ADD COLUMN eligibility_notes  TEXT,")
    body.append("  ADD COLUMN comparable_player  VARCHAR(255);")
    body.append("")
    body.append("ALTER TABLE evaluations DROP CONSTRAINT evaluations_recommendation_check;")
    body.append("ALTER TABLE evaluations ADD CONSTRAINT evaluations_recommendation_check")
    body.append("  CHECK (recommendation IN ('call_up','shortlist','monitor','not_at_level','release') OR recommendation IS NULL);")
    body.append("")
    body.append("-- ─── Audit: assert each position-group's per-category counts match the v2 spec ───")
    body.append("DO $$")
    body.append("DECLARE")
    body.append("  r RECORD;")
    body.append("  expected JSONB := jsonb_build_object(")
    parts = []
    for g in ALL:
        e = EXPECTED[g]
        parts.append(f"    '{g}', jsonb_build_object('tech',{e['tech']},'tact',{e['tact']},'phys',{e['phys']},'ment',{e['ment']},'total',{e['total']})")
    body.append(",\n".join(parts))
    body.append("  );")
    body.append("BEGIN")
    body.append("  FOR r IN")
    body.append("    SELECT pg.code AS grp,")
    body.append("           COUNT(*) FILTER (WHERE c.code LIKE 'tech_%') AS tech,")
    body.append("           COUNT(*) FILTER (WHERE c.code LIKE 'tact_%') AS tact,")
    body.append("           COUNT(*) FILTER (WHERE c.code LIKE 'phys_%') AS phys,")
    body.append("           COUNT(*) FILTER (WHERE c.code LIKE 'ment_%') AS ment,")
    body.append("           COUNT(*)                                     AS total")
    body.append("    FROM position_groups pg")
    body.append("    LEFT JOIN position_group_criteria pgc ON pgc.position_group_id = pg.id")
    body.append("    LEFT JOIN criteria c                  ON c.id = pgc.criterion_id")
    body.append("    GROUP BY pg.code, pg.sort_order")
    body.append("    ORDER BY pg.sort_order")
    body.append("  LOOP")
    body.append("    IF (expected->r.grp->>'tech')::int  != r.tech")
    body.append("    OR (expected->r.grp->>'tact')::int  != r.tact")
    body.append("    OR (expected->r.grp->>'phys')::int  != r.phys")
    body.append("    OR (expected->r.grp->>'ment')::int  != r.ment")
    body.append("    OR (expected->r.grp->>'total')::int != r.total THEN")
    body.append("      RAISE EXCEPTION 'AUDIT FAIL %: got tech=% tact=% phys=% ment=% total=% (expected %)',")
    body.append("        r.grp, r.tech, r.tact, r.phys, r.ment, r.total, expected->r.grp;")
    body.append("    END IF;")
    body.append("  END LOOP;")
    body.append("  RAISE NOTICE 'AUDIT PASS — all 8 position groups match v2-LOCKED counts';")
    body.append("END $$;")
    body.append("")
    body.append("-- ─── Human-eyeball audit table (printed before COMMIT) ───")
    body.append("SELECT pg.code AS grp,")
    body.append("       COUNT(*) FILTER (WHERE c.code LIKE 'tech_%') AS tech,")
    body.append("       COUNT(*) FILTER (WHERE c.code LIKE 'tact_%') AS tact,")
    body.append("       COUNT(*) FILTER (WHERE c.code LIKE 'phys_%') AS phys,")
    body.append("       COUNT(*) FILTER (WHERE c.code LIKE 'ment_%') AS ment,")
    body.append("       COUNT(*)                                     AS total")
    body.append("FROM position_groups pg")
    body.append("LEFT JOIN position_group_criteria pgc ON pgc.position_group_id = pg.id")
    body.append("LEFT JOIN criteria c                  ON c.id = pgc.criterion_id")
    body.append("GROUP BY pg.code, pg.sort_order")
    body.append("ORDER BY pg.sort_order;")
    body.append("")
    body.append("COMMIT;")
    body.append("")

    out_path = Path(__file__).parent / "phase_5a_reseed.sql"
    out_path.write_text("\n".join(body), encoding="utf-8")
    print(f"Wrote {out_path}  ({sum(1 for _ in out_path.read_text(encoding='utf-8').splitlines())} lines)")


if __name__ == "__main__":
    main()
