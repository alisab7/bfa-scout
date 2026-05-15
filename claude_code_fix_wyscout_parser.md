Fix the Wyscout parser — it can't handle the actual file format.

Working folder: D:\BFA-Scout
File to fix: app/wyscout/parser.py
Test file: D:\BFA-Scout\sample_data\Player_stats_Arthur_Rezende.xlsx (or whatever filename Ali has)

# What's wrong

The current parser fails because of two structural mismatches:

## Bug 1: Match label format

Current regex expects "Home X-Y Away" (score in middle).
Actual format is "Home - Away X:Y" (score at end, ":" separator, " - " between teams).

Examples from the file:
  "Al Hadd - Muharraq 0:1"
  "Muharraq - Sitra 3:0"
  "A'Ali - Muharraq 1:1"   (note apostrophe in team name — handle as literal)

Correct regex:
  MATCH_RE = re.compile(r'^(.+?)\s+-\s+(.+?)\s+(\d+):(\d+)\s*$')
  # groups: home_team, away_team, home_score, away_score

## Bug 2: Paired columns

Wyscout slash-headers like "Passes / accurate" mean column N holds the FIRST value and
column N+1 holds the SECOND value. The N+1 column has NO header (it's blank in row 1).

Cowork's WYSCOUT_COLUMN_MAP is keyed by header text only — so it captures column N
("passes") but ignores column N+1 ("passes_accurate") because there's no key to match.

Verified column layout from the actual file (header row is row 1):

  Col 1: Match
  Col 2: Competition
  Col 3: Date
  Col 4: Position
  Col 5: Minutes played
  Col 6: "Total actions / successful"  → total_actions
  Col 7: (blank header)                → total_actions_successful
  Col 8: Goals
  Col 9: Assists
  Col 10: "Shots / on target"          → shots
  Col 11: (blank)                      → shots_on_target
  Col 12: xG
  Col 13: "Passes / accurate"          → passes
  Col 14: (blank)                      → passes_accurate
  Col 15: "Long passes / accurate"     → long_passes
  Col 16: (blank)                      → long_passes_accurate
  Col 17: "Crosses / accurate"         → crosses
  Col 18: (blank)                      → crosses_accurate
  Col 19: "Dribbles / successful"      → dribbles
  Col 20: (blank)                      → dribbles_successful
  Col 21: "Duels / won"                → duels
  Col 22: (blank)                      → duels_won
  Col 23: "Aerial duels / won"         → aerial_duels
  Col 24: (blank)                      → aerial_duels_won
  Col 25: Interceptions
  Col 26: "Losses / own half"          → losses (ignore col 26 raw, use col 27 for losses_own_half)
                                          (Wyscout convention: "X / sub" means col N total, col N+1 sub-category)
  Col 27: (blank)                      → losses_own_half
  Col 28: "Recoveries / opp. half"     → (recoveries — not in our schema, skip)
  Col 29: (blank)                      → recoveries_opp_half
  Col 30: "Yellow card"                → SKIP (this is "minute of first card", different semantics)
  Col 31: "Red card"                   → SKIP (same)
  Col 32: "Defensive duels / won"      → defensive_duels
  Col 33: (blank)                      → defensive_duels_won
  Col 34: "Loose ball duels / won"     → loose_ball_duels
  Col 35: (blank)                      → loose_ball_duels_won
  Col 36: "Sliding tackles / successful" → sliding_tackles
  Col 37: (blank)                      → sliding_tackles_successful
  Col 38: Clearances
  Col 39: Fouls
  Col 40: "Yellow cards" (plural)      → yellow_cards (USE THIS, not col 30)
  Col 41: "Red cards" (plural)         → red_cards (USE THIS, not col 31)
  Col 42: Shot assists                 → shot_assists
  Col 43: "Offensive duels / won"      → offensive_duels
  Col 44: (blank)                      → offensive_duels_won
  Col 45: Touches in penalty area      → touches_in_box
  Col 46: Offsides
  Col 47: Progressive runs
  Col 48: Fouls suffered
  Col 49: "Through passes / accurate"  → through_passes
  Col 50: (blank)                      → through_passes_accurate
  Col 51-72: Additional Wyscout columns (xA, second assists, passes to final third,
              GK stats etc.) — NOT in our schema, store in raw_row only, do not map

# Fix approach

Rewrite parser.py with this strategy:

1. Use openpyxl directly (NOT pandas) for column-index control. pandas obscures
   the blank header columns we need to read.

2. Define explicit column-index → DB-field mapping based on the layout above.
   This is the most reliable approach given Wyscout's awkward format.

3. For each data row (rows 2 onward):
   a. Extract match_label from col 1, parse with the corrected regex
   b. Build a dict using the column-index map
   c. Coerce values: empty cells → None (NEVER 0); numeric strings → numbers
   d. Parse date from col 3 with multiple format fallbacks
   e. Extract position_raw from col 4 verbatim, take first comma-separated token
      as primary, look up positions.code → positions.id for position_primary_id
   f. Store the entire row dict (column index keyed) as raw_row JSON

4. Skip rows where match_label cell is empty. Don't skip rows where regex fails —
   store match_label verbatim, leave home_team/away_team/scores as NULL.

# is_home detection

Check if the player's current_club appears in home_team or away_team
(case-insensitive substring match):
  - Match in home_team → is_home = True
  - Match in away_team → is_home = False
  - No match → is_home = NULL

For the Arthur Rezende file (current_club = "Muharraq Club"), all rows have
"Muharraq" in either home or away. Substring match works.

# Verify the fix

After rewriting parser.py, test directly:

  cd D:\BFA-Scout
  .\.venv\Scripts\Activate.ps1
  python -c "
  from app.wyscout.parser import parse_wyscout_xlsx
  rows = parse_wyscout_xlsx('sample_data/Player_stats_Arthur_Rezende.xlsx')
  print(f'Parsed {len(rows)} rows')
  for r in rows[:2]:
      print('---')
      for k,v in r.items():
          if v is not None and k != 'raw_row':
              print(f'  {k}: {v}')
  "

Expected: 18 rows parsed (the file has 18 data rows). Each row should have
non-None values for match_label, competition, match_date, position_raw,
minutes_played, plus all the paired stats.

If parsing succeeds, restart Flask and re-test the upload via browser.
Should get "18 inserted, 0 updated" the first time. Re-upload → "0 inserted,
18 updated".

# Hard rules

- Do NOT change schema.sql
- Do NOT touch any file outside app/wyscout/parser.py
  (helpers, ingest, aggregations, blueprint stay as-is — only the parser is broken)
- Use openpyxl, not pandas (we already have openpyxl as a transitive dep)
- Empty cells → None, never 0
- Match label regex failure → store raw, leave parsed fields NULL, do NOT skip the row
- All parser-discoverable columns (1-50) get mapped explicitly
- Columns 51-72 go into raw_row JSON only, not mapped to DB fields
