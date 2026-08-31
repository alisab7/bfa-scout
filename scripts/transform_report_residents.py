"""
26/27 residents intake — transform the management-provided `Report.xlsx`
into (a) a Phase-9 bulk-import CSV and (b) a GAP-LIST CSV.

This script does NOT touch the database. The generated CSV is imported
through the EXISTING Phase-9 bulk importer
(/admin/players/bulk-import: upload -> preview -> commit), which owns
validation, duplicate detection, the preview step, and the atomic
transaction. This script is only the deterministic file-level mapping.

WHOLE-ROW HIGHLIGHT EXCLUSION (the reason 88 of 112 rows import):
the source file marks players NOT wanted this season by filling the
whole row yellow (FFFFFF00) or red (FFFF0000). A value-only read misses
this, so the workbook is read WITH styles (openpyxl default, NOT
data_only) and, per data row, solid fills across the 10 columns are
counted (ignoring None/'00000000'):
  * >=7 yellow cells -> EXCLUDE (whole-row yellow)
  * >=7 red cells    -> EXCLUDE (whole-row red)
  * a single highlighted cell is a column-level note -> KEEP the player
This yields exactly 24 excluded / 88 kept, and the computed exclusion
set is cross-checked against the ratified 24-ID list below; ANY
disagreement is a hard failure — nothing is written.

Ratified mapping rules (do not deviate):
  * International First + Family name  -> full_name (English)
  * BFA ID Number                      -> national_id  ("New" = no ID yet
                                          -> left blank + flagged in gap-list)
  * Date of Birth                      -> dob (datetime cells + DD/MM/YYYY
                                          strings; blank stays blank)
  * Club Name (Arabic)                 -> current_club_name via the EXACT
                                          table below (strip trailing U+200E;
                                          NO fuzzy matching; unmapped = hard
                                          failure)
  * Tumooh Feedback == 'لديه الجواز'   -> nationality_status='bahraini'
                                          (passport holder; origin PENDING)
    anything else                      -> nationality_status='foreign_residency'
  * bahrain_residency_start_date       -> NEVER set (no invented dates)
  * origin_country                     -> NEVER set (pending for everyone)
  * position                           -> NEVER set (assigned later via
                                          /admin/assign-positions)
  * Years bucket + Tumooh feedback + Comment -> players.notes, clearly
    labelled as management-provided interim info (NOT an entry date).

Usage:
    python scripts/transform_report_residents.py [path-to-Report.xlsx]

Outputs (UTF-8, in <repo>/exports/):
    residents_2627_import.csv    — feed to /admin/players/bulk-import
    residents_2627_gap_list.csv  — who is missing what
"""
from __future__ import annotations

import csv
import sys
from datetime import datetime, date
from pathlib import Path

from openpyxl import load_workbook

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = Path(
    "/Users/AliSabah/Files From d.localized/Scout Community/Report.xlsx")
EXPORT_DIR = REPO_ROOT / "exports"

# Exact, ratified Arabic -> English club table. English names must equal
# clubs.name so the Phase-9 importer resolves club_id exactly.
CLUB_MAP = {
    "نادي المحرق الرياضي":        "Al-Muharraq",
    "نادي الرفاع الرياضي":        "Al-Riffa",
    "نادي الرفاع الشرقي الرياضي": "East Riffa",
    "نادي الحد الرياضي":          "Al-Hidd",
    "نادي الخالدية الرياضي":      "Al-Khalidiya",
    "النادي الأهلي الرياضي":      "Al-Ahli Manama",
    "نادي المنامة الرياضي":       "Manama Club",
    "نادي البحرين الرياضي":       "Al-Bahrain SC",
    "نادي سترة الرياضي":          "Sitra Club",
    "نادي عالي الرياضي":          "A'Ali FC",
    "نادي البديع الرياضي":        "Al-Budaiya",
    "نادي الاتفاق الرياضي":       "Al-Ittifaq",
    "نادي الحالة الرياضي":        "Al-Hala",
    "نادي أم الحصم الرياضي":      "Um Alhassam",
    "نادي البسيتين الرياضي":      "Busaiteen",
    "نادي مدينة عيسى الرياضي":    "Isa Town",
}

PASSPORT_FEEDBACK = "لديه الجواز"          # -> bahraini (origin pending)

# English gloss for the notes line (source value is kept verbatim too).
FEEDBACK_GLOSS = {
    "لديه الجواز": "has passport",
    "رسالة":       "letter",
    "لديه امر":    "has order",
    "بدون":        "none",
    "سحب":         "withdrawn",
}

# Whole-row highlight exclusion — see module docstring.
YELLOW = "FFFFFF00"
RED = "FFFF0000"
EXCLUDE_THRESHOLD = 7          # >=7 of 10 cells filled = whole-row highlight
N_STYLE_COLS = 10              # the sheet's 10 data columns

# Ratified exclusion list (21 yellow + 3 red: 008337M03, 007387M96,
# 008083M92). The color rule MUST reproduce this set exactly.
EXPECTED_EXCLUDED_IDS = {
    "008286M06", "008337M03", "008965M05", "009002M05", "003300M01",
    "000999M90", "002860M96", "007377M00", "008065M01", "003457M92",
    "007361M05", "007340M05", "008840M05", "008853M01", "009199M06",
    "009383M06", "007387M96", "007394M96", "008083M92", "008134M02",
    "008338M04", "000090M01", "005641M00", "005835M04",
}
EXPECTED_KEPT = 88

# Full Phase-9 ACCEPTED_COLUMNS set (incl. the new `notes`), so the
# preview shows zero unknown-column warnings.
IMPORT_COLUMNS = [
    "full_name", "dob", "national_id", "primary_position_code",
    "nationality_code", "nationality_status", "eligible_from_date",
    "bahrain_residency_start_date", "current_club_name",
    "dominant_foot", "height_cm", "weight_kg", "notes",
]


def _clean(v) -> str:
    """Trim + strip bidi/format control chars (U+200E/U+200F/U+202A-E)."""
    if v is None:
        return ""
    s = str(v).strip()
    # U+200E LRM, U+200F RLM, U+202A..U+202E embedding/override marks —
    # the source file has a trailing U+200E on one club name.
    for ch in ("\u200e", "\u200f", "\u202a", "\u202b",
               "\u202c", "\u202d", "\u202e"):
        s = s.replace(ch, "")
    return s.strip()


def _parse_dob(raw) -> date | None:
    """Excel datetime cells or DD/MM/YYYY strings. Blank/unparseable -> None
    (blanks stay blank — never invented)."""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    s = _clean(raw)
    if not s:
        return None
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unparseable DOB {raw!r}")


def _row_highlight(cells) -> str | None:
    """Return 'yellow'/'red' if the row is whole-row highlighted
    (>=EXCLUDE_THRESHOLD solid fills of that color across the data
    columns), else None. A single highlighted cell keeps the player."""
    yellow = red = 0
    for c in cells[:N_STYLE_COLS]:
        f = c.fill
        if f is None or f.patternType != "solid":
            continue
        rgb = f.fgColor.rgb
        if rgb in (None, "00000000"):
            continue
        if rgb == YELLOW:
            yellow += 1
        elif rgb == RED:
            red += 1
    if yellow >= EXCLUDE_THRESHOLD:
        return "yellow"
    if red >= EXCLUDE_THRESHOLD:
        return "red"
    return None


def transform(source: Path) -> tuple[list[dict], list[dict], dict]:
    # NOT data_only, NOT read_only: cell styles (fills) are required for
    # the whole-row highlight exclusion. The sheet holds plain values
    # (no formulas), so .value is the real value either way.
    wb = load_workbook(source)
    ws = wb["Main"]
    all_rows = list(ws.iter_rows())
    wb.close()

    header = [str(c.value).strip() if c.value is not None else ""
              for c in all_rows[0]]
    idx = {h: i for i, h in enumerate(header)}
    required = ("BFA ID Number", "International First name",
                "International Family name", "Date of Birth",
                "Main Nationality", "Club Name", "Years",
                "Tumooh Feedback", "Comment")
    missing = [c for c in required if c not in idx]
    if missing:
        raise SystemExit(f"FATAL: missing expected columns: {missing}")

    # ── Pass 1: whole-row highlight exclusion + ratified cross-check ──
    kept_cell_rows = []
    excluded: list[tuple[str, str]] = []          # (bfa_id, color)
    for cells in all_rows[1:]:
        values = [c.value for c in cells]
        if not any(v is not None and str(v).strip() for v in values):
            continue
        color = _row_highlight(cells)
        if color:
            excluded.append((_clean(values[idx["BFA ID Number"]]), color))
        else:
            kept_cell_rows.append(values)

    excluded_ids = {b for b, _ in excluded}
    if excluded_ids != EXPECTED_EXCLUDED_IDS or \
            len(excluded) != len(EXPECTED_EXCLUDED_IDS) or \
            len(kept_cell_rows) != EXPECTED_KEPT:
        raise SystemExit(
            "FATAL: highlight-exclusion cross-check FAILED — the color rule "
            "and the ratified 24-ID exclusion list disagree. NOT importing.\n"
            f"  color rule excluded {len(excluded)} rows, "
            f"kept {len(kept_cell_rows)} (expected 24/{EXPECTED_KEPT})\n"
            f"  only-in-color-rule: {sorted(excluded_ids - EXPECTED_EXCLUDED_IDS)}\n"
            f"  only-in-ratified-list: {sorted(EXPECTED_EXCLUDED_IDS - excluded_ids)}")

    import_rows: list[dict] = []
    gap_rows: list[dict] = []
    unmapped_clubs: set[str] = set()
    stats = {"total": 0, "excluded": len(excluded),
             "excluded_yellow": sum(1 for _, c in excluded if c == "yellow"),
             "excluded_red": sum(1 for _, c in excluded if c == "red"),
             "bahraini": 0, "foreign_residency": 0,
             "no_bfa_id": 0, "no_dob": 0, "blank_nationality": 0,
             "withdrawn": 0}

    for raw in kept_cell_rows:
        stats["total"] += 1

        first = _clean(raw[idx["International First name"]])
        family = _clean(raw[idx["International Family name"]])
        full_name = " ".join(p for p in (first, family) if p)

        bfa_id = _clean(raw[idx["BFA ID Number"]])
        if bfa_id.lower() == "new" or not bfa_id:
            bfa_id = ""                       # no real ID yet — never fake one
            stats["no_bfa_id"] += 1

        dob = _parse_dob(raw[idx["Date of Birth"]])
        if dob is None:
            stats["no_dob"] += 1

        club_ar = _clean(raw[idx["Club Name"]])
        club_en = CLUB_MAP.get(club_ar)
        if club_en is None:
            unmapped_clubs.add(club_ar)
            continue

        feedback = _clean(raw[idx["Tumooh Feedback"]])
        if feedback == PASSPORT_FEEDBACK:
            status = "bahraini"               # passport holder; origin PENDING
            stats["bahraini"] += 1
        else:
            status = "foreign_residency"
            stats["foreign_residency"] += 1
        if feedback == "سحب":
            stats["withdrawn"] += 1

        years = _clean(raw[idx["Years"]])
        years_norm = ""
        if years:
            yl = years.lower()
            years_norm = ("Less than 5" if yl == "less than 5" else
                          "More than 5" if yl == "more than 5" else years)

        nationality_src = _clean(raw[idx["Main Nationality"]])
        blank_nat = not nationality_src
        if blank_nat:
            stats["blank_nationality"] += 1

        comment = _clean(raw[idx["Comment"]])

        note_parts = []
        if years_norm:
            note_parts.append(
                f"Years in Bahrain (management estimate, 26/27 residents "
                f"import): {years_norm} — interim note, NOT an entry date")
        if feedback:
            gloss = FEEDBACK_GLOSS.get(feedback, "?")
            note_parts.append(f"Tumooh feedback (source file): "
                              f"{feedback} ({gloss})")
        if comment:
            note_parts.append(f"Comment (source file): {comment}")
        notes = " | ".join(note_parts)

        import_rows.append({
            "full_name":                    full_name,
            "dob":                          dob.isoformat() if dob else "",
            "national_id":                  bfa_id,
            "primary_position_code":        "",
            "nationality_code":             "",
            "nationality_status":           status,
            "eligible_from_date":           "",
            "bahrain_residency_start_date": "",     # NEVER invented
            "current_club_name":            club_en,
            "dominant_foot":                "",
            "height_cm":                    "",
            "weight_kg":                    "",
            "notes":                        notes,
        })

        flags = []
        if not bfa_id:
            flags.append("missing BFA ID (source says 'New')")
        if dob is None:
            flags.append("missing date of birth")
        if blank_nat:
            flags.append("blank Main Nationality in source file")
        if feedback == "سحب":
            flags.append("marked withdrawn (سحب) in source file")
        gap_rows.append({
            "bfa_id":             bfa_id or "(none)",
            "full_name":          full_name,
            "club":               club_en,
            "nationality_status": status,
            "needs_entry_date":   "YES",     # nobody has a residency date
            "needs_origin":       "YES" if status == "bahraini" else "",
            "flags":              "; ".join(flags),
        })

    if unmapped_clubs:
        raise SystemExit(
            "FATAL: unmapped Arabic club names (NO fuzzy matching — extend "
            f"the ratified table or fix the source): {sorted(unmapped_clubs)}")
    return import_rows, gap_rows, stats


def main() -> None:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCE
    if not source.exists():
        raise SystemExit(f"FATAL: source file not found: {source}")

    import_rows, gap_rows, stats = transform(source)

    EXPORT_DIR.mkdir(exist_ok=True)
    import_path = EXPORT_DIR / "residents_2627_import.csv"
    gap_path = EXPORT_DIR / "residents_2627_gap_list.csv"

    with import_path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=IMPORT_COLUMNS)
        w.writeheader()
        w.writerows(import_rows)

    with gap_path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(gap_rows[0].keys()))
        w.writeheader()
        w.writerows(gap_rows)

    print(f"source:            {source}")
    print(f"excluded rows:     {stats['excluded']} "
          f"(whole-row highlight: {stats['excluded_yellow']} yellow, "
          f"{stats['excluded_red']} red) — cross-checked vs ratified list")
    print(f"import CSV:        {import_path}  ({len(import_rows)} rows)")
    print(f"gap-list CSV:      {gap_path}  ({len(gap_rows)} rows)")
    print(f"status split:      bahraini(passport)={stats['bahraini']}  "
          f"foreign_residency={stats['foreign_residency']}")
    n_origin = sum(1 for g in gap_rows if g["needs_origin"] == "YES")
    print(f"needs entry date:  {len(gap_rows)} (all)")
    print(f"needs origin:      {n_origin} (the passport holders)")
    print(f"missing BFA ID:    {stats['no_bfa_id']}")
    print(f"missing DOB:       {stats['no_dob']}")
    print(f"blank nationality: {stats['blank_nationality']}")
    print(f"withdrawn (سحب):   {stats['withdrawn']}")


if __name__ == "__main__":
    main()
