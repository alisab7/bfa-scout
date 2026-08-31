"""
Bulk-import helpers (Phase 9). Pure functions — parsing, validation,
duplicate detection. No request/session state; the blueprint route
in `bulk_import.py` owns the lifecycle.

Public API:
  parse_file(file_storage)      -> list[dict]  raw rows from CSV/xlsx
  classify_rows(rows)           -> (parsed_rows, summary)
  build_insert_params(row)      -> dict        ready for INSERT
  build_update_params(row)      -> dict        partial UPDATE (skips NULLs)

Validation rules and duplicate detection live here so the route stays
thin and so the synthetic E2E can exercise them directly without
going through HTTP.
"""
from __future__ import annotations

from datetime import date, datetime
import io

import pandas as pd

from app.db import get_db
from app.players.nationalities import NATIONALITY_LABEL


# ───────── Constants & validation enums ─────────────────────────────────────

# Max rows per file. Configurable cap — spec locks this at 500.
MAX_ROWS_PER_IMPORT = 500

# Canonical accepted columns (lowercased). Anything else in the upload is
# silently ignored — flagged in `unknown_columns` so the preview can warn.
ACCEPTED_COLUMNS = (
    'full_name',
    'dob',
    'national_id',
    'primary_position_code',
    'nationality_code',
    'nationality_status',
    'eligible_from_date',
    'bahrain_residency_start_date',
    'current_club_name',
    'dominant_foot',           # → players.foot in the DB
    'height_cm',
    'weight_kg',
    'notes',                   # → players.notes (free text, optional)
)

VALID_NATIONALITY_STATUSES = (
    'bahraini', 'foreign_ancestry', 'foreign_residency',
    'foreign_other', 'not_eligible', 'unknown',
)

VALID_FOOT_VALUES = ('right', 'left', 'both')

# 'N/A'-like cell content that should be treated as NULL.
# Note: 'nan' is included because pandas 3.x StringDtype can leak float
# NaN past `dtype=str, keep_default_na=False` for some multi-row CSV
# patterns; after str(v) the value becomes the literal 'nan'. The
# str-coerce in _norm then catches it via this list.
NULL_SENTINELS = ('', 'n/a', 'na', 'none', 'null', '-', 'nan')


# ───────── File parsing ─────────────────────────────────────────────────────

def parse_file(file_storage) -> list[dict]:
    """
    Parse an uploaded CSV or Excel file into a list of row dicts.

    `file_storage` is a `werkzeug.datastructures.FileStorage` (the
    `request.files[...]` shape). Empty/N/A cells normalise to None.
    Column names lowercased + stripped.

    Raises:
      ValueError if file extension is unsupported, file is unreadable,
      or row count exceeds MAX_ROWS_PER_IMPORT.
    """
    fname = (file_storage.filename or '').lower()

    # Read bytes once so we can wrap in BytesIO and let pandas pick
    # the right reader. FileStorage.read() consumes the stream.
    raw = file_storage.read()
    if not raw:
        raise ValueError("Uploaded file is empty.")

    if fname.endswith('.csv'):
        try:
            df = pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False)
        except Exception as exc:
            raise ValueError(f"Could not parse CSV: {exc}") from exc
    elif fname.endswith('.xlsx'):
        try:
            df = pd.read_excel(io.BytesIO(raw), dtype=str, engine='openpyxl')
        except Exception as exc:
            raise ValueError(f"Could not parse Excel: {exc}") from exc
    else:
        raise ValueError(
            f"Unsupported file type {fname!r}. Use .csv or .xlsx."
        )

    if len(df) > MAX_ROWS_PER_IMPORT:
        raise ValueError(
            f"File has {len(df)} rows; max is {MAX_ROWS_PER_IMPORT}. "
            "Split into multiple imports."
        )

    # Normalise column names: lowercase, strip whitespace.
    df.columns = [str(c).lower().strip() for c in df.columns]

    # Cell-level normalisation:
    #  - NaN / pd.NA / empty string / 'N/A' (case-insensitive) → None
    #  - Strip surrounding whitespace
    #
    # Done at the dict layer (after `to_dict('records')`) rather than
    # via `DataFrame.map`. pandas 3.x StringDtype + .map skip NaN
    # cells by default (na_action behaviour differs from pandas 2.x
    # applymap), which let `nan` slip through to validate_row and
    # caused false "unknown nationality_code: 'nan'" errors. Dict-
    # layer normalisation is unaffected by that quirk.
    def _norm(v):
        try:
            if pd.isna(v):
                return None
        except (TypeError, ValueError):
            # pd.isna can raise on exotic types (rare); treat as not-na.
            pass
        if v is None:
            return None
        s = str(v).strip()
        if s.lower() in NULL_SENTINELS:
            return None
        return s

    records = df.to_dict('records')
    return [{k: _norm(v) for k, v in r.items()} for r in records]


# ───────── Validation ───────────────────────────────────────────────────────

def _parse_date_field(value: str | None) -> date | None:
    """Accept YYYY-MM-DD or YYYY/MM/DD or DD-MM-YYYY (Excel quirks).
    Returns date or None. Raises ValueError if the string is non-None
    but unparseable."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    # Try a few common formats. ISO first (matches the template).
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%d-%m-%Y', '%d/%m/%Y'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    # Excel may export dates as '2025-09-12 00:00:00'
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        raise ValueError(f"unrecognised date format: {value!r}")


def _str(v) -> str:
    """Defensive string coerce. pandas can leak floats/ints past
    `dtype=str` for some cell configurations (e.g. all-numeric
    columns with `keep_default_na=False`). Cast here so the rest of
    validate_row can `.strip()` and `.lower()` without crashing."""
    if v is None:
        return ''
    if isinstance(v, str):
        return v
    return str(v)


def validate_row(fields: dict,
                 valid_position_codes: set,
                 valid_club_names: set) -> tuple[list[str], list[str]]:
    """
    Returns (errors, warnings). Errors block the import; warnings are
    cosmetic and don't block.

    `valid_position_codes` and `valid_club_names` are passed in
    (rather than queried per-row) so the caller can fetch them once
    per upload.
    """
    errors: list[str] = []
    warnings: list[str] = []
    # Defensive coerce — pandas can leak floats past dtype=str.
    fields = {k: (None if v is None else _str(v)) for k, v in fields.items()}

    # full_name is the only required field per spec.
    if not (fields.get('full_name') or '').strip():
        errors.append('full_name is required')

    # dob — must be a parseable past date; pre-1950 is a warning.
    raw_dob = fields.get('dob')
    if raw_dob:
        try:
            d = _parse_date_field(raw_dob)
            if d and d > date.today():
                errors.append(f"dob in future: {raw_dob!r}")
            if d and d < date(1950, 1, 1):
                warnings.append(f"dob unusually old: {raw_dob!r}")
        except ValueError as exc:
            errors.append(f"dob {exc}")

    # national_id — if present, length sanity check (full uniqueness
    # gets enforced by the UNIQUE constraint at INSERT time AND by the
    # duplicate-detection pass below).
    nat_id = (fields.get('national_id') or '').strip()
    if nat_id and len(nat_id) < 5:
        errors.append(f"national_id too short (min 5 chars): {nat_id!r}")

    # primary_position_code — must match a known positions.code (case-insens).
    pos_code = (fields.get('primary_position_code') or '').strip()
    if pos_code and pos_code.upper() not in valid_position_codes:
        errors.append(f"unknown position_code: {pos_code!r}")

    # nationality_code — must be a known ISO alpha-3.
    nat_code = (fields.get('nationality_code') or '').strip()
    if nat_code and nat_code.upper() not in NATIONALITY_LABEL:
        errors.append(f"unknown nationality_code: {nat_code!r}")

    # nationality_status — must be one of the documented enum values.
    status = (fields.get('nationality_status') or '').strip().lower() or None
    if status and status not in VALID_NATIONALITY_STATUSES:
        errors.append(
            f"invalid nationality_status: {status!r}; "
            f"one of {VALID_NATIONALITY_STATUSES}"
        )

    # eligible_from_date / bahrain_residency_start_date — date parse only.
    # The spec says these are "only valid if foreign_residency" but the
    # admin form happily accepts them on any nationality_status today,
    # so we don't gate that here. We do flag the warning.
    for date_field in ('eligible_from_date', 'bahrain_residency_start_date'):
        raw = fields.get(date_field)
        if raw:
            try:
                _parse_date_field(raw)
            except ValueError as exc:
                errors.append(f"{date_field} {exc}")
    if (status == 'foreign_residency'
            and not fields.get('bahrain_residency_start_date')):
        warnings.append(
            "nationality_status='foreign_residency' with no "
            "bahrain_residency_start_date — admin should set later"
        )

    # current_club_name — soft-link to clubs.name. If it doesn't match,
    # it's stored as free-text in players.current_club. Warning only.
    club_name = (fields.get('current_club_name') or '').strip()
    if club_name and club_name not in valid_club_names:
        warnings.append(
            f"current_club_name {club_name!r} doesn't match any club; "
            f"will be stored as free-text"
        )

    # dominant_foot — enum.
    foot = (fields.get('dominant_foot') or '').strip().lower() or None
    if foot and foot not in VALID_FOOT_VALUES:
        errors.append(
            f"invalid dominant_foot: {foot!r}; one of {VALID_FOOT_VALUES}"
        )

    # height_cm — integer in reasonable range. Out-of-range = warning,
    # not error, so a 130-cm U14 player doesn't fail import.
    for num_field, lo, hi in (('height_cm', 140, 220),
                               ('weight_kg', 40,  120)):
        raw = fields.get(num_field)
        if raw is None or raw == '':
            continue
        try:
            n = int(float(raw))     # tolerate "175.0" from Excel
            if not (lo <= n <= hi):
                warnings.append(
                    f"{num_field} {n} outside reasonable range "
                    f"[{lo}, {hi}]"
                )
        except (ValueError, TypeError):
            errors.append(f"{num_field} not a number: {raw!r}")

    return errors, warnings


# ───────── Duplicate detection ──────────────────────────────────────────────

def find_duplicate(fields: dict) -> int | None:
    """
    Returns the existing players.id of a duplicate row, or None.

    Strategy (in order):
      1. If `national_id` is set: lookup by national_id (UNIQUE column).
         If found → duplicate. If not → NOT a duplicate (UNIQUE will
         let the INSERT succeed; or this is a brand-new ID).
      2. Else if `full_name` + `dob` + `primary_position_code` all set:
         exact case-insensitive name match, exact DOB match, and exact
         (case-insensitive) position-code match. Active players only.
      3. Else if `full_name` + `dob` set (no position code — e.g. a
         registry file imported before positions are assigned): exact
         case-insensitive name match + exact DOB match. Active only.
      4. Else if ONLY `full_name` is set (no id, no dob, no position):
         exact case-insensitive name match against active players whose
         dob IS NULL — catches re-imports of id-less/dob-less rows
         without ever matching a same-named player who has a real DOB.
      5. Else: return None (insufficient info to dedupe).
    """
    conn = get_db()
    with conn.cursor() as cur:
        nat_id = (fields.get('national_id') or '').strip()
        if nat_id:
            cur.execute(
                "SELECT id FROM players WHERE national_id = %s",
                (nat_id,)
            )
            r = cur.fetchone()
            return r['id'] if r else None

        name = (fields.get('full_name') or '').strip()
        raw_dob = fields.get('dob')
        pos = (fields.get('primary_position_code') or '').strip()
        if name and raw_dob and pos:
            try:
                d = _parse_date_field(raw_dob)
            except ValueError:
                return None
            if not d:
                return None
            cur.execute(
                """
                SELECT pl.id FROM players pl
                LEFT JOIN positions p ON p.id = pl.primary_position_id
                WHERE  LOWER(BTRIM(pl.full_name)) = LOWER(BTRIM(%s))
                  AND  pl.dob = %s
                  AND  LOWER(p.code) = LOWER(%s)
                  AND  pl.is_active = TRUE
                LIMIT 1
                """,
                (name, d, pos)
            )
            r = cur.fetchone()
            return r['id'] if r else None

        # Strategy 3: name + dob, position not supplied (files imported
        # before positions are assigned — e.g. the 26/27 residents
        # registry). Exact name + exact DOB is the same evidence bar as
        # strategy 2 minus the position, which the file simply lacks.
        if name and raw_dob and not pos:
            try:
                d = _parse_date_field(raw_dob)
            except ValueError:
                return None
            if not d:
                return None
            cur.execute(
                """
                SELECT id FROM players
                WHERE  LOWER(BTRIM(full_name)) = LOWER(BTRIM(%s))
                  AND  dob = %s
                  AND  is_active = TRUE
                LIMIT 1
                """,
                (name, d)
            )
            r = cur.fetchone()
            return r['id'] if r else None

        # Strategy 4: name only — the row has NO id, NO dob, NO position
        # (registry rows awaiting a BFA ID). Only match a player whose
        # dob IS NULL too, so a same-named player with a real DOB is
        # never silently swallowed. Keeps re-imports idempotent.
        if name and not raw_dob and not pos:
            cur.execute(
                """
                SELECT id FROM players
                WHERE  LOWER(BTRIM(full_name)) = LOWER(BTRIM(%s))
                  AND  dob IS NULL
                  AND  is_active = TRUE
                LIMIT 1
                """,
                (name,)
            )
            r = cur.fetchone()
            return r['id'] if r else None
    return None


# ───────── Row classification pass ──────────────────────────────────────────

def _fetch_position_codes() -> set:
    """Returns set of UPPERCASE position codes from the DB. Cached
    per-request would be nicer but the row count is tiny (~26)."""
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute('SELECT UPPER(code) AS code FROM positions')
        return {r['code'] for r in cur.fetchall() or []}


def _fetch_club_names() -> set:
    """Returns set of club display names (case-sensitive — matches the
    DB UI which keeps club names as canonical strings)."""
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute('SELECT name FROM clubs')
        return {r['name'] for r in cur.fetchall() or []}


def classify_rows(rows: list[dict]) -> tuple[list[dict], dict]:
    """
    Walk every row, run validation + duplicate detection, return
    (parsed_rows, summary).

    Each parsed_row dict:
      {
        'row_number': int   (1-based; row 1 = first data row, not header)
        'fields':     dict  (original normalised fields)
        'errors':     list[str]
        'warnings':   list[str]
        'duplicate_of': int | None     # existing players.id if duplicate
        'unknown_columns': list[str]   # extra cols ignored from this row
        'status':     'valid' | 'duplicate' | 'invalid'
      }

    summary:
      {'total', 'valid', 'duplicate', 'invalid', 'to_import',
       'unknown_columns'}  (unknown_columns is union across all rows)
    """
    valid_pos   = _fetch_position_codes()
    valid_clubs = _fetch_club_names()

    parsed = []
    union_unknown: set = set()
    for i, raw in enumerate(rows, start=1):
        # Split known vs unknown columns. Spec says "ignore unknown
        # with a warning."
        known   = {k: v for k, v in raw.items() if k in ACCEPTED_COLUMNS}
        unknown = sorted(k for k in raw.keys() if k not in ACCEPTED_COLUMNS)
        union_unknown.update(unknown)

        errors, warnings = validate_row(known, valid_pos, valid_clubs)
        dup_id = None
        # Skip dup detection if there are validation errors — the row
        # can't be imported anyway, and dup detection on garbage data
        # could surface confusing "duplicate of X" labels.
        if not errors:
            try:
                dup_id = find_duplicate(known)
            except Exception as exc:
                errors.append(f"duplicate detection failed: {exc}")

        if errors:
            status = 'invalid'
        elif dup_id is not None:
            status = 'duplicate'
        else:
            status = 'valid'

        parsed.append({
            'row_number':    i,
            'fields':        known,
            'errors':        errors,
            'warnings':      warnings,
            'duplicate_of':  dup_id,
            'unknown_columns': unknown,
            'status':        status,
        })

    summary = {
        'total':           len(parsed),
        'valid':           sum(1 for r in parsed if r['status'] == 'valid'),
        'duplicate':       sum(1 for r in parsed if r['status'] == 'duplicate'),
        'invalid':         sum(1 for r in parsed if r['status'] == 'invalid'),
        # `to_import` is the optimistic upper bound (valid + duplicates
        # if admin chooses 'update' for all). Actual count is decided
        # at commit time based on per-row action.
        'to_import':       sum(1 for r in parsed if r['status'] != 'invalid'),
        'unknown_columns': sorted(union_unknown),
    }
    return parsed, summary


# ───────── INSERT / UPDATE parameter builders ───────────────────────────────

def _maybe_int(v):
    if v is None or v == '':
        return None
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return None


def _maybe_date(v):
    if v is None or v == '':
        return None
    try:
        return _parse_date_field(v)
    except ValueError:
        return None


def _resolve_position_id(conn, code: str | None) -> int | None:
    if not code:
        return None
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM positions WHERE UPPER(code) = UPPER(%s)",
            (code.strip(),)
        )
        r = cur.fetchone()
    return r['id'] if r else None


def _resolve_club(conn, name: str | None) -> tuple[int | None, str | None]:
    """Returns (club_id, current_club_text). The text fallback is the
    raw name string when no clubs.name match is found — the existing
    `players.current_club` column already accepts free-text."""
    if not name:
        return (None, None)
    name = name.strip()
    with conn.cursor() as cur:
        cur.execute("SELECT id, name FROM clubs WHERE name = %s", (name,))
        r = cur.fetchone()
    if r:
        return (r['id'], r['name'])
    return (None, name)


def build_db_params(conn, fields: dict) -> dict:
    """
    Map normalised row fields → players-table column values, resolving
    FK lookups (positions, clubs) as we go. Used by both INSERT (new
    player) and UPDATE (duplicate-with-action=update).

    For UPDATE: NULL values mean "don't change", so callers should
    filter the dict before composing the SQL.
    """
    pos_id = _resolve_position_id(conn, fields.get('primary_position_code'))
    club_id, club_text = _resolve_club(conn, fields.get('current_club_name'))

    return {
        'full_name':                    (fields.get('full_name') or '').strip() or None,
        'national_id':                  (fields.get('national_id') or '').strip() or None,
        'dob':                          _maybe_date(fields.get('dob')),
        'primary_position_id':          pos_id,
        'nationality_code':             ((fields.get('nationality_code') or '').strip().upper() or None),
        'nationality_status':           ((fields.get('nationality_status') or '').strip().lower() or None),
        'eligible_from_date':           _maybe_date(fields.get('eligible_from_date')),
        'bahrain_residency_start_date': _maybe_date(fields.get('bahrain_residency_start_date')),
        'club_id':                      club_id,
        'current_club':                 club_text,
        'foot':                         ((fields.get('dominant_foot') or '').strip().lower() or None),
        'height_cm':                    _maybe_int(fields.get('height_cm')),
        'weight_kg':                    _maybe_int(fields.get('weight_kg')),
        'notes':                        (fields.get('notes') or '').strip() or None,
    }
