"""
Bahraini CPR (national ID) normalization — the master key for player
dedupe and CPR-matched photo import.

A Bahraini CPR is **9 digits**, and the leading digits encode the birth
year. Players born 2000-2009 therefore have CPRs that start with `0` (or
`00` for the year 2000). Excel stores CPRs as NUMBERS and silently strips
those leading zeros, and source registries are MIXED — some cells are
ints (zeros stripped), some are text (zeros intact).

`normalize_cpr` restores the canonical 9-digit TEXT form so the same key
is produced regardless of how the value arrived. CPR is NEVER stored as a
number (hard rule).

Examples:
    41209370    (int, 8d, born 2004)  -> '041209370'
    503061      (int, 6d, born 2000)  -> '000503061'   (double-zero case)
    605508418   (int, 9d)             -> '605508418'
    '060712619' (text, 9d)            -> '060712619'   (unchanged)
    ' 26/12'    (garbage)             -> None           (reject + report)
"""
from __future__ import annotations


def normalize_cpr(raw) -> str | None:
    """Return the canonical 9-digit CPR string, or None if malformed.

    None means "reject and report" — never import a player with an
    unparseable CPR (it's the master key for dedupe + photo matching).
    """
    if raw is None:
        return None
    # Ints/floats from Excel (e.g. 503061 or 503061.0) → drop any '.0'.
    if isinstance(raw, float):
        # Excel numeric cells can arrive as float; avoid '503061.0'.
        if raw != raw:           # NaN
            return None
        raw = int(raw)
    s = str(raw).strip()
    # Tolerate a leading apostrophe (Excel's text-number marker).
    if s.startswith("'"):
        s = s[1:].strip()
    if not s:
        return None
    # NOTE: the spec's reference impl deleted *all* non-digits, which would
    # turn garbage like ' 26/12' into '000002612' (a coincidentally valid
    # length) — but the spec's own examples say ' 26/12' must be REJECTED.
    # We implement to the examples: a CPR core must be PURE digits. This
    # rejects embedded symbols (/, -, letters) instead of silently
    # salvaging digits out of a date fragment.
    if not s.isdigit():
        return None              # embedded non-digit → garbage, reject
    s = s.zfill(9)               # restore stripped leading zeros to 9 digits
    if len(s) != 9:
        return None              # too long (or impossibly short) — reject
    return s
