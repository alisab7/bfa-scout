# Flag SVGs

Source: [flag-icons](https://github.com/lipis/flag-icons) by Panayiotis Lipiridis.
License: **MIT** (see `LICENSE-flag-icons` in this directory).

Vendored in Phase 6.1 (BFA-Scout v0.6.1) to render national flags in the
Player Passport PDF. Emoji flags (Unicode regional indicators) render
unreliably under WeasyPrint because they require an emoji-capable font,
and the GTK Pango fallback chain on Windows doesn't always include one.

All 271 SVGs are from the `flags/4x3/` directory of the upstream
project at commit time. Filenames are ISO 3166-1 alpha-2 codes,
lowercase (e.g. `bh.svg`, `br.svg`, `gb-eng.svg`).

The passport data layer (`app/passport/data.py:_flag_svg_inline`)
maps ISO alpha-3 (the platform's internal nationality code) to alpha-2
via `app.players.nationalities.ALPHA3_TO_ALPHA2`, then reads the
corresponding file. Missing/unknown codes return None and the
template omits the flag entirely.

## Updating

To refresh from upstream:
```bash
curl -sL https://github.com/lipis/flag-icons/archive/refs/heads/main.tar.gz \
  -o /tmp/flag-icons.tar.gz
tar -xzf /tmp/flag-icons.tar.gz -C /tmp/flag-extract \
  --wildcards '*/flags/4x3/*.svg'
cp /tmp/flag-extract/*/flags/4x3/*.svg app/static/flags/
```
