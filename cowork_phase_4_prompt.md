# Cowork Session: BFA-Scout Phase 4 — Wyscout Import + Player Dashboard

## Context

Phases 0 (scaffold), 1 (auth), and 3 (players module) are committed. Phase 2 was skipped intentionally — seeded criteria are sufficient for evaluations.

**Phase 4 scope:** Build the Wyscout integration end-to-end:
1. Admin/TD uploads a Wyscout xlsx for a specific player
2. Parser extracts ~35 per-match metrics into `wyscout_match_stats`
3. Player profile fills with a dashboard: aggregate panel, **6-axis radar chart**, **3 trend line charts**, per-match table

This is the phase where the project starts to feel real — each player profile transforms from a skeleton into a populated scouting view.

**Working folder:** `D:\BFA-Scout` (do NOT touch `D:\BFA-Analytics` or `D:\BFA-Analytics-AWS`).

**Local environment:**
- PostgreSQL 15 native, database `bfa_scout`, user `bfa`, password `bfa2025`
- Python 3.11 venv at `.venv`
- Flask runs via `flask --app wsgi run --debug`
- `wyscout_imports` and `wyscout_match_stats` tables exist (Phase 0 schema)
- Players module fully working — Phase 3 created players, photos, search

## Critical lesson from Phase 3 — DO NOT INVENT COLUMN NAMES

Phase 3 cost half a day because Cowork wrote queries against invented column names (`pl.position`, `pl.club_name`, `pl.date_of_birth` — none existed). **The schema in `D:\BFA-Scout\schema.sql` is the source of truth.** Before writing any SQL, read schema.sql and use the exact column names listed there.

## Pre-session prep — Ali does this

Before starting Cowork, copy the Wyscout sample file to project:
```powershell
mkdir D:\BFA-Scout\sample_data -ErrorAction SilentlyContinue
# Then drop Player_stats_Arthur_Rezende.xlsx into D:\BFA-Scout\sample_data\
```

Cowork will use it for end-to-end verification.

## Locked decisions (do not re-litigate)

| Decision | Choice |
|---|---|
| Parser library | pandas + openpyxl |
| Re-upload behavior | UPSERT (`ON CONFLICT DO UPDATE`) — Wyscout corrections propagate |
| Multi-position cell handling | Split by comma, take first token as primary, store full string in `position_raw` |
| Match label parsing | Regex on `home_team SCORE-SCORE away_team` pattern, BFA's team is auto-detected |
| Charts library | Chart.js via CDN |
| Radar design | Generic 6-axis, fixed normalization thresholds (position-specific radars deferred to v1.1) |
| Aggregations | Computed in Python on demand — no materialized views in v1 |
| Audit logging | One row per import (summary), not per match-stat row |

## Goal — End state acceptance

1. Admin/TD logs in, navigates to `/wyscout/upload`, picks a player from dropdown, uploads Arthur Rezende xlsx
2. Result page shows "X matches inserted, Y updated, 0 skipped (UPSERT mode)"
3. Player profile (`/players/<id>`) renders Wyscout dashboard:
   - Aggregate panel: total matches, total minutes, totals for goals/assists/shots, average pass% and duel%
   - 6-axis radar chart of player's averaged percentile-style scores
   - 3 trend lines: minutes per match, goals+assists per match, pass accuracy% per match
   - Per-match table sortable by date / minutes / rating columns
4. Re-upload same file: row counts confirm UPSERT (no duplicates created)
5. Player without Wyscout data: profile shows existing "No Wyscout data" placeholder unchanged
6. All routes RBAC-gated correctly

## File structure to create/modify

```
app/
├── wyscout/
│   ├── __init__.py              [REPLACE STUB] Blueprint + routes
│   ├── parser.py                [NEW] xlsx → list of dicts
│   ├── ingest.py                [NEW] DB insert/upsert logic
│   ├── aggregations.py          [NEW] computes dashboard stats
│   └── helpers.py               [NEW] Jinja globals for radar normalization
├── templates/
│   ├── wyscout/
│   │   ├── upload.html          [NEW] form: player picker + file input
│   │   ├── result.html          [NEW] post-upload summary
│   │   └── imports.html         [NEW] list of all past imports
│   └── players/
│       └── profile.html         [MODIFY] replace Wyscout placeholder section
├── static/
│   └── js/
│       └── player_dashboard.js  [NEW] Chart.js config for radar + trends
└── __init__.py                  [MODIFY] register Wyscout Jinja globals,
                                          add Chart.js CDN to base.html

requirements.txt                 [MODIFY] add pandas, openpyxl
sample_data/                     [Ali pre-creates with the xlsx]
└── Player_stats_Arthur_Rezende.xlsx
```

## Implementation specifics

### Schema columns — USE EXACTLY (from schema.sql)

`wyscout_imports` columns:
```
id, uploaded_by, file_name, player_id, row_count, status, error_message, imported_at
```

`wyscout_match_stats` columns (study these carefully — every INSERT and UPDATE must use these exact names):
```
id, player_id, import_id,
match_label, competition, match_date, home_team, away_team,
home_score, away_score, is_home,
position_raw, position_primary_id, minutes_played,
total_actions, total_actions_successful,
goals, assists, shots, shots_on_target, xg, shot_assists,
touches_in_box, offsides, progressive_runs,
passes, passes_accurate, long_passes, long_passes_accurate,
crosses, crosses_accurate, through_passes, through_passes_accurate,
dribbles, dribbles_successful,
duels, duels_won, aerial_duels, aerial_duels_won,
defensive_duels, defensive_duels_won,
offensive_duels, offensive_duels_won,
loose_ball_duels, loose_ball_duels_won,
interceptions, sliding_tackles, sliding_tackles_successful,
clearances, recoveries_opp_half, losses_own_half,
fouls, fouls_suffered, yellow_cards, red_cards,
raw_row, created_at
```

UNIQUE constraint: `(player_id, match_label, match_date)` — this is the upsert conflict target.

### `app/wyscout/parser.py`

Single function: `parse_wyscout_xlsx(file_storage_or_path) -> list[dict]`

Logic:
```python
def parse_wyscout_xlsx(source) -> list[dict]:
    """
    Parse a Wyscout per-match xlsx export into a list of normalized dicts.
    Each dict has keys matching wyscout_match_stats columns (minus id, player_id,
    import_id, created_at).

    Wyscout exports vary slightly across periods/versions. Be defensive:
    - Header row may be on row 1, 2, or 3 — detect by looking for 'Match' column
    - Some columns may be missing — treat missing as None, NEVER as 0
    - Numeric columns may be empty strings — coerce to None, not 0
    - Column names may have trailing spaces — strip them
    """
    df = pd.read_excel(source, engine='openpyxl', header=None)
    # Find the header row by scanning for 'Match' or 'Date' column
    header_row = _find_header_row(df)
    df = pd.read_excel(source, engine='openpyxl', header=header_row)
    df.columns = [str(c).strip() for c in df.columns]

    rows = []
    for _, row in df.iterrows():
        if pd.isna(row.get('Match')) and pd.isna(row.get('Date')):
            continue  # skip empty rows
        rows.append(_normalize_row(row))
    return rows
```

**Column mapping** — Wyscout column name → DB field. Use this dict verbatim:

```python
WYSCOUT_COLUMN_MAP = {
    # match identity
    'Match':                          'match_label',
    'Competition':                    'competition',
    'Date':                           'match_date',
    'Position':                       'position_raw',
    'Minutes played':                 'minutes_played',
    # actions
    'Total actions':                  'total_actions',
    'Total actions / successful':     'total_actions_successful',
    # attacking
    'Goals':                          'goals',
    'Assists':                        'assists',
    'Shots':                          'shots',
    'Shots on target':                'shots_on_target',
    'xG':                             'xg',
    'Shot assists':                   'shot_assists',
    'Touches in box':                 'touches_in_box',
    'Offsides':                       'offsides',
    'Progressive runs':               'progressive_runs',
    # passing
    'Passes':                         'passes',
    'Accurate passes':                'passes_accurate',
    'Long passes':                    'long_passes',
    'Accurate long passes':           'long_passes_accurate',
    'Crosses':                        'crosses',
    'Accurate crosses':               'crosses_accurate',
    'Through passes':                 'through_passes',
    'Accurate through passes':        'through_passes_accurate',
    # dribbling
    'Dribbles':                       'dribbles',
    'Successful dribbles':            'dribbles_successful',
    # duels
    'Duels':                          'duels',
    'Duels won':                      'duels_won',
    'Aerial duels':                   'aerial_duels',
    'Aerial duels won':               'aerial_duels_won',
    'Defensive duels':                'defensive_duels',
    'Defensive duels won':            'defensive_duels_won',
    'Offensive duels':                'offensive_duels',
    'Offensive duels won':            'offensive_duels_won',
    'Loose ball duels':               'loose_ball_duels',
    'Loose ball duels won':           'loose_ball_duels_won',
    # defending
    'Interceptions':                  'interceptions',
    'Sliding tackles':                'sliding_tackles',
    'Successful sliding tackles':     'sliding_tackles_successful',
    'Clearances':                     'clearances',
    'Recoveries':                     'recoveries_opp_half',
    'Losses':                         'losses_own_half',
    # discipline
    'Fouls':                          'fouls',
    'Fouls suffered':                 'fouls_suffered',
    'Yellow cards':                   'yellow_cards',
    'Red cards':                      'red_cards',
}

# Column names that may not be present in every export — these are tolerated.
# Anything else missing should NOT crash — log a warning and proceed with None.
```

**Match label parsing** — extract home_team, away_team, scores. Regex:
```python
MATCH_RE = re.compile(r'^\s*(.+?)\s+(\d+)\s*[-–:]\s*(\d+)\s+(.+?)\s*$')
# Groups: home_team, home_score, away_score, away_team
```
Examples that must parse:
- `"Bahrain U23 1-0 UAE U23"` → home=Bahrain U23, away=UAE U23, 1-0
- `"Manama 2:1 Muharraq"` → home=Manama, away=Muharraq, 2-1
- `"Al-Hidd 0-0 Riffa SC"` → home=Al-Hidd, away=Riffa SC, 0-0

If regex fails, store the raw string in `match_label` and leave home_team/away_team/scores as NULL — never crash.

**Date parsing** — Wyscout uses inconsistent formats. Try these in order: `YYYY-MM-DD`, `DD/MM/YYYY`, `DD-MM-YYYY`, `Mon DD, YYYY`. Use pandas' `pd.to_datetime` with `errors='coerce'`. If unparseable, raise a descriptive error and skip the row (don't insert garbage).

**Position parsing** — split `position_raw` by comma:
```python
def parse_position_primary(position_raw, db_cursor):
    """Return positions.id matching the first token, or None if no match."""
    if not position_raw or pd.isna(position_raw):
        return None
    tokens = [t.strip() for t in str(position_raw).split(',') if t.strip()]
    if not tokens:
        return None
    primary_code = tokens[0]
    db_cursor.execute("SELECT id FROM positions WHERE code = %s", (primary_code,))
    row = db_cursor.fetchone()
    return row['id'] if row else None
```

**`is_home` detection** — The selected player belongs to either home or away team. Phase 4 has the player's `current_club` available. Compare to `home_team` and `away_team`:
- If `current_club` matches `home_team` (case-insensitive substring): is_home = True
- If matches `away_team`: is_home = False
- Otherwise: is_home = NULL (don't guess)

### `app/wyscout/ingest.py`

```python
def ingest_wyscout(player_id: int, parsed_rows: list[dict],
                   uploaded_by: int, file_name: str) -> dict:
    """
    Insert/upsert wyscout_match_stats rows.
    Returns: {'inserted': int, 'updated': int, 'failed': int, 'errors': list[str], 'import_id': int}

    Flow:
    1. INSERT into wyscout_imports with status='pending', returning id
    2. For each row, INSERT ... ON CONFLICT (player_id, match_label, match_date)
       DO UPDATE SET <all stat columns> = EXCLUDED.<col>, import_id = EXCLUDED.import_id
       Track xmax to differentiate insert vs update
    3. UPDATE wyscout_imports status='success', row_count=inserted+updated
    4. On any unhandled exception inside the loop: rollback ENTIRE transaction,
       set wyscout_imports.status='failed' with error_message
    5. Return summary dict
    """
```

**Critical**: Wrap the entire ingest in a transaction. On any failure, rollback the transaction AND mark wyscout_imports.status='failed'. This was a pre-deploy "Important finding" in BFA-Analytics (I-1/I-2: missing rollbacks in ingest_match) — do not repeat that mistake.

**Insert vs update detection**:
```sql
INSERT INTO wyscout_match_stats (...) VALUES (...)
ON CONFLICT (player_id, match_label, match_date) DO UPDATE SET
    competition = EXCLUDED.competition,
    home_team = EXCLUDED.home_team,
    -- ... all stat columns ...
    import_id = EXCLUDED.import_id,
    raw_row = EXCLUDED.raw_row
RETURNING (xmax = 0) AS inserted;
-- xmax = 0 means newly inserted; xmax != 0 means updated
```

**Audit invariants** — after ingest, assert:
1. No `wyscout_match_stats` rows have `player_id` not present in `players`
2. No rows have `match_date` in the future
3. No rows for this `import_id` are missing `match_label`

If any invariant fails, log it loudly. Do not auto-rollback (data is already committed) but make it visible.

### `app/wyscout/__init__.py` — Blueprint with routes

| Method | Path | Decorator | Purpose |
|---|---|---|---|
| GET  | `/wyscout/upload`            | `@admin_or_td_required` | Form: player picker + file input |
| POST | `/wyscout/upload`            | `@admin_or_td_required` | Parse + ingest, redirect to result |
| GET  | `/wyscout/result/<import_id>`| `@admin_or_td_required` | Show inserted/updated counts |
| GET  | `/wyscout/imports`           | `@admin_or_td_required` | List of all past imports with row counts |
| POST | `/wyscout/imports/<id>/delete` | `@admin_required`     | Delete an import + all its match_stats rows (transactional) |

**Audit log entries** (single row per upload):
- action: `wyscout.upload.success` or `wyscout.upload.failed`
- entity_type: `wyscout_import`
- entity_id: import_id
- details: JSON `{"inserted": N, "updated": M, "file_name": "...", "player_id": X}`

### `app/wyscout/aggregations.py`

```python
def get_player_summary(player_id: int) -> dict:
    """
    Returns aggregate stats for a player's Wyscout history.
    Queries wyscout_match_stats, returns dict with keys:
    - matches_count, total_minutes, avg_minutes_per_match
    - goals, assists, goals_plus_assists, shots, shots_on_target, xg_total
    - passes_total, passes_accurate, pass_accuracy_pct
    - duels_total, duels_won, duels_won_pct
    - aerial_duels_won_pct, defensive_duels_won_pct, offensive_duels_won_pct
    - tackles, interceptions, clearances
    - yellow_cards, red_cards, fouls

    All percentages: NULL when denominator is 0 (don't divide by zero).
    """

def get_player_match_history(player_id: int, limit: int = 30) -> list[dict]:
    """Per-match rows ordered by match_date DESC, with computed columns:
    - minutes_played
    - rating_estimate (computed: see below)
    - goals_plus_assists
    """

def get_player_radar_scores(player_id: int) -> dict:
    """6-axis radar values normalized to 0-100. Returns:
    {
      'attacking':   0-100,  # goals + assists + xg + shots normalized
      'creating':    0-100,  # key passes + crosses + through_passes_accurate
      'passing':     0-100,  # pass accuracy %
      'dribbling':   0-100,  # dribbles_successful / dribbles
      'defending':   0-100,  # interceptions + tackles + clearances per 90
      'aerial':      0-100,  # aerial_duels_won %
    }
    Use the normalization thresholds in helpers.py — NEVER inline magic numbers."""
```

### `app/wyscout/helpers.py` — normalization thresholds

```python
# Generic normalization thresholds for radar (v1).
# Position-specific thresholds deferred to v1.1.
RADAR_THRESHOLDS = {
    # axis: (zero_score_value, hundred_score_value, calculation_kind)
    'attacking':  (0,    1.0,  'per_90'),    # 1 G+A per 90 = 100
    'creating':   (0,    3.0,  'per_90'),    # 3 key passes per 90 = 100
    'passing':    (50,   90,   'percentage'), # 50% accuracy = 0, 90% = 100
    'dribbling':  (0,    70,   'percentage'), # 0% success = 0, 70% = 100
    'defending':  (0,    8.0,  'per_90'),    # 8 def actions per 90 = 100
    'aerial':     (0,    70,   'percentage'),
}

def normalize_radar_axis(value, axis_name, total_minutes=None):
    """Clamp 0-100 with linear interpolation between thresholds."""
```

Register `get_player_summary`, `get_player_match_history`, `get_player_radar_scores` as Jinja globals in `app/__init__.py`.

### `templates/wyscout/upload.html`

Form layout (mobile-first):
- Player picker — HTMX search dropdown reusing the Phase 3 search endpoint
- File input — `<input type="file" name="wyscout_file" accept=".xlsx" required>`
- Submit button — disabled until both fields filled (Alpine.js)
- Help text: "Upload a Wyscout per-match xlsx export. Existing matches will be updated."

### `templates/wyscout/result.html`

After upload, show:
- ✅ Successful: "X new matches inserted, Y existing matches updated for [Player Name]"
- ❌ Failed: error message + link back to upload form
- Link to player profile: "View [Player Name]'s dashboard →"

### `templates/players/profile.html` — REPLACE the Wyscout placeholder

The profile already has a placeholder div. Replace its inner content with:

```html
{% set wy = get_player_summary(player.id) %}

{% if wy.matches_count == 0 %}
  <div class="text-center py-8 text-muted">
    <p>No Wyscout data uploaded yet for this player.</p>
    {% if current_user.has_role('admin', 'technical_director') %}
      <a href="{{ url_for('wyscout.upload') }}?player_id={{ player.id }}"
         class="btn-primary mt-3">Upload Wyscout xlsx</a>
    {% endif %}
  </div>
{% else %}
  <!-- AGGREGATE PANEL -->
  <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
    <!-- 8 stat cards: matches, minutes, goals, assists, pass%, duel%, etc. -->
  </div>

  <!-- RADAR + TRENDS -->
  <div class="grid grid-cols-1 md:grid-cols-2 gap-6 mt-6">
    <div>
      <h3>Performance Profile</h3>
      <canvas id="radar-chart" data-scores='{{ get_player_radar_scores(player.id) | tojson }}'></canvas>
    </div>
    <div>
      <h3>Trends</h3>
      <canvas id="trend-minutes"></canvas>
      <canvas id="trend-ga" class="mt-3"></canvas>
      <canvas id="trend-pass" class="mt-3"></canvas>
    </div>
  </div>

  <!-- PER-MATCH TABLE -->
  <h3 class="mt-6">Match History</h3>
  <div class="overflow-x-auto">
    <table class="w-full text-sm">
      <thead>
        <tr>
          <th>Date</th><th>Match</th><th>Position</th><th>Min</th>
          <th>G</th><th>A</th><th>Sh</th><th>xG</th>
          <th>Pass%</th><th>Duel%</th><th>Cards</th>
        </tr>
      </thead>
      <tbody>
        {% for m in get_player_match_history(player.id) %}
          <tr>
            <td>{{ m.match_date }}</td>
            <td>{{ m.match_label }}</td>
            <td>{{ m.position_raw }}</td>
            <td>{{ m.minutes_played }}</td>
            <!-- etc. — be defensive with NULLs, show "—" -->
          </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
{% endif %}
```

### `static/js/player_dashboard.js`

```javascript
// Initialized on profile page load if charts exist.
// Reads data from canvas data-* attributes — no inline JSON in HTML <script> tags.

document.addEventListener('DOMContentLoaded', function() {
  initRadar();
  initTrends();
});

function initRadar() {
  const canvas = document.getElementById('radar-chart');
  if (!canvas) return;
  const scores = JSON.parse(canvas.dataset.scores);
  new Chart(canvas, {
    type: 'radar',
    data: {
      labels: ['Attacking', 'Creating', 'Passing', 'Dribbling', 'Defending', 'Aerial'],
      datasets: [{
        label: 'Profile',
        data: [scores.attacking, scores.creating, scores.passing,
               scores.dribbling, scores.defending, scores.aerial],
        backgroundColor: 'rgba(200, 16, 46, 0.2)',
        borderColor:     '#C8102E',
        pointBackgroundColor: '#B5924C',
      }]
    },
    options: {
      scales: { r: { min: 0, max: 100, ticks: { stepSize: 25 } } },
      plugins: { legend: { display: false } },
      maintainAspectRatio: false,
    }
  });
}

function initTrends() {
  // Fetch trend data from /wyscout/api/trends/<player_id> via fetch()
  // Render 3 line charts (minutes, G+A, pass%)
}
```

Trend data endpoint:
- `GET /wyscout/api/trends/<player_id>` → JSON `{labels: [dates], minutes: [], ga: [], pass_pct: []}`
- Decorator: `@any_authenticated`
- Use this from JS to populate trend charts after page load

### `app/__init__.py` modifications

```python
# Add to existing Jinja globals
from .wyscout.aggregations import (
    get_player_summary, get_player_match_history, get_player_radar_scores
)
app.jinja_env.globals.update(
    get_player_photo=get_player_photo,
    get_player_pos=get_player_pos,
    get_player_summary=get_player_summary,
    get_player_match_history=get_player_match_history,
    get_player_radar_scores=get_player_radar_scores,
)
```

### `templates/base.html` — add Chart.js CDN

Inside `<head>`, after Tailwind:
```html
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
```

And before `</body>`:
```html
<script src="{{ url_for('static', filename='js/player_dashboard.js') }}"></script>
```

### `requirements.txt` additions

```
pandas>=2.0
openpyxl>=3.1
```

Cowork must run `.venv\Scripts\pip install -r requirements.txt` after editing.

## Verification protocol — REAL Flask, not test_client

After all code is written:

1. Install deps:
   ```powershell
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

2. Restart Flask:
   ```powershell
   flask --app wsgi run --debug
   ```

3. Create test player **Arthur Rezende** via the existing `/players/new` form:
   - Full name: `Arthur Rezende`
   - National ID: `999999999` (placeholder, valid format)
   - DOB: `1995-01-01` (placeholder)
   - Primary position: AMF (will be overwritten by xlsx in some sense, but irrelevant — xlsx position_primary_id stays per match)
   - Current club: `Muharraq Club`

4. Visit `/wyscout/upload`, pick Arthur Rezende, upload `D:\BFA-Scout\sample_data\Player_stats_Arthur_Rezende.xlsx`. Verify:
   - Result page shows N matches inserted, 0 updated
   - `psql -U bfa -d bfa_scout -c "SELECT COUNT(*) FROM wyscout_match_stats;"` returns N

5. Visit Arthur Rezende's profile. Verify:
   - Aggregate panel renders with non-zero values
   - Radar chart visible with 6 axes
   - 3 trend line charts visible
   - Per-match table populated with all matches
   - Position display per match is sensible (e.g., "LCMF, RCMF" for multi-position rows)

6. Re-upload the same xlsx. Verify:
   - Result page: 0 inserted, N updated
   - DB count unchanged
   - `psql -U bfa -d bfa_scout -c "SELECT COUNT(*) FROM wyscout_match_stats;"` still N

7. Visit `/wyscout/imports`. Verify list shows 2 import rows.

8. Spot-check a row in DB:
   ```powershell
   psql -U bfa -d bfa_scout -c "SELECT match_label, position_raw, position_primary_id, minutes_played, goals, passes, passes_accurate FROM wyscout_match_stats WHERE player_id = (SELECT id FROM players WHERE full_name = 'Arthur Rezende') LIMIT 3;"
   ```
   Expected: real values, position_raw verbatim from xlsx, position_primary_id resolved correctly for the first token.

9. Audit invariants — run after ingest:
   ```sql
   -- No orphan stats:
   SELECT COUNT(*) FROM wyscout_match_stats wms
   LEFT JOIN players p ON p.id = wms.player_id
   WHERE p.id IS NULL;  -- expect 0

   -- No future dates:
   SELECT COUNT(*) FROM wyscout_match_stats WHERE match_date > CURRENT_DATE;  -- expect 0

   -- No NULL match_label:
   SELECT COUNT(*) FROM wyscout_match_stats WHERE match_label IS NULL;  -- expect 0
   ```

## Acceptance checklist (Cowork prints at end)

- ✅ `pip install -r requirements.txt` succeeds (pandas + openpyxl install cleanly)
- ✅ All 5 schema column references in queries match `schema.sql` exactly (no inventions)
- ✅ Flask starts without import errors
- ✅ Logged in as scout, GET `/wyscout/upload` returns 403 (correct RBAC)
- ✅ Logged in as admin, GET `/wyscout/upload` returns 200 with player picker + file input
- ✅ Upload Arthur Rezende xlsx → result page with insert count
- ✅ Player profile renders aggregate + radar + trends + per-match table
- ✅ Re-upload same xlsx → 0 inserted, N updated (UPSERT working)
- ✅ Imports list `/wyscout/imports` shows 2 entries
- ✅ Audit invariants (orphans / future dates / null match_label) all return 0
- ✅ DB row count after re-upload identical to first upload

## Hard rules

- ❌ Do NOT modify `schema.sql` — schema is the source of truth, code conforms to schema
- ❌ Do NOT touch auth code, players module, or any file outside `app/wyscout/`, `app/templates/wyscout/`, `app/templates/players/profile.html`, `app/static/js/`, `app/__init__.py`, `app/templates/base.html`, `requirements.txt`
- ❌ Do NOT use `flask.test_client()` for verification — restart real Flask + curl/browser
- ❌ Do NOT default missing numeric columns to 0 — use NULL (we lose information by zero-defaulting)
- ❌ Do NOT crash on bad data — skip the bad row, log it, continue
- ❌ Do NOT commit anything — Ali commits from PowerShell after the session
- ❌ Do NOT initialize git
- ❌ Do NOT touch `D:\BFA-Analytics` or `D:\BFA-Analytics-AWS`
- ✅ All SQL parameterized via `%s` (NEVER f-string SQL)
- ✅ Use `RealDictCursor` everywhere
- ✅ Wrap entire ingest in a transaction; rollback on any failure AND mark import status='failed'
- ✅ Match label parsing tolerates regex failures — store raw, leave home/away/scores NULL
- ✅ Audit log: ONE row per upload (summary), not per match
- ✅ Test against the real running Flask process — restart after every code change

## Out of scope (do NOT build)

- Position-specific radars (v1.1)
- Bulk uploads (multiple files)
- Wyscout API integration
- Editing or deleting individual stat rows
- Comparison views (player vs cohort)
- Xls / xlsm support — xlsx only
- Manual stat entry forms
- AI summaries (Phase 7)
- Phase 5 evaluation form integration

## Session discipline

- Target: 8–10 messages
- After every code change: restart Flask + curl OR browser verify
- End with full acceptance checklist printed (✅/❌ each)
- Append `v0.4.0 — Wyscout import + dashboard` to `CHANGELOG.md`
- Update `PROJECT.md` to mark Phase 4 complete, point at Phase 5 (Evaluation form)
- After session, Ali commits from PowerShell:
  ```powershell
  cd D:\BFA-Scout
  git add -A
  git commit -m "Phase 4: Wyscout import + player dashboard (radar + trends + table)"
  ```

If the session runs long and the dashboard side isn't fully done, **prioritize**:
1. Parser + ingest + UPSERT working (most critical)
2. Per-match table on profile (next critical)
3. Aggregate panel
4. Radar chart
5. Trend charts (last — defer to a follow-up Cowork session if needed)

Anything in 1-3 is non-negotiable for v1. Items 4-5 can ship in a Phase 4.1.
