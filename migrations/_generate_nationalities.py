"""
One-shot generator for app/players/nationalities.py.

Run once at build time with `pycountry` installed. Produces a frozen
static dict of all ISO 3166-1 alpha-3 nation codes + their EN names,
plus the alpha-3 → alpha-2 mapping needed for flag emojis.

After this runs, `pycountry` can be uninstalled — the runtime app uses
only the committed static file.

Usage:
    .venv/Scripts/python.exe migrations/_generate_nationalities.py
"""
from pathlib import Path
import pycountry

# Bahrain pinned first; everything else alphabetical by name.
BAHRAIN_ALPHA3 = "BHR"

countries = []
for c in pycountry.countries:
    if c.alpha_3 == BAHRAIN_ALPHA3:
        continue
    countries.append((c.alpha_3, c.name))
countries.sort(key=lambda r: r[1])

bahrain = pycountry.countries.get(alpha_3=BAHRAIN_ALPHA3)
choices = [(BAHRAIN_ALPHA3, bahrain.name)] + countries

# alpha-3 → alpha-2 mapping for flag emoji
alpha3_to_alpha2 = {c.alpha_3: c.alpha_2 for c in pycountry.countries}

OUT_PATH = Path(__file__).parent.parent / "app" / "players" / "nationalities.py"

lines: list[str] = []
lines.append('"""')
lines.append('FIFA / ISO 3166-1 nationality dictionary (Phase 5c-3).')
lines.append('')
lines.append('Generated once via migrations/_generate_nationalities.py from `pycountry`.')
lines.append('No runtime dependency on pycountry — this file is the source of truth.')
lines.append('')
lines.append("Bahrain (BHR) is pinned first since this is a Bahrain-focused platform;")
lines.append('the rest is alphabetical by EN name.')
lines.append(f'Total: {len(choices)} entries.')
lines.append('"""')
lines.append('')
lines.append('NATIONALITY_CHOICES = [')
for code, name in choices:
    safe = name.replace("'", "\\'")
    lines.append(f"    ({code!r:>7}, '{safe}'),")
lines.append(']')
lines.append('')
lines.append('NATIONALITY_LABEL = dict(NATIONALITY_CHOICES)')
lines.append('')
lines.append('')
lines.append('# alpha-3 → alpha-2 lookup for flag-emoji conversion')
lines.append(f'# {len(alpha3_to_alpha2)} entries')
lines.append('ALPHA3_TO_ALPHA2 = {')
for a3 in sorted(alpha3_to_alpha2.keys()):
    lines.append(f"    {a3!r}: {alpha3_to_alpha2[a3]!r},")
lines.append('}')
lines.append('')
lines.append('')
lines.append('def flag_emoji(alpha3_code: str) -> str:')
lines.append('    """ISO 3166-1 alpha-3 → flag emoji via Unicode regional indicators."""')
lines.append('    if not alpha3_code or len(alpha3_code) != 3:')
lines.append("        return ''")
lines.append('    alpha2 = ALPHA3_TO_ALPHA2.get(alpha3_code.upper())')
lines.append('    if not alpha2 or len(alpha2) != 2:')
lines.append("        return ''")
lines.append('    base = 0x1F1E6')
lines.append("    return chr(base + ord(alpha2[0]) - ord('A')) + chr(base + ord(alpha2[1]) - ord('A'))")
lines.append('')

OUT_PATH.write_text("\n".join(lines), encoding="utf-8")
print(f"Wrote {OUT_PATH}")
print(f"  {len(choices)} nationality entries (Bahrain first, then alphabetical)")
print(f"  {len(alpha3_to_alpha2)} alpha-3 → alpha-2 mappings")
