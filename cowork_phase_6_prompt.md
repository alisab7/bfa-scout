# Cowork/Claude Code Session: BFA-Scout Phase 6 — Player Passport PDF

## Context

Phase 4.2 committed. Thirteen phases on master. **Phase 6 is the demo-ready milestone** — the printable Player Passport PDF that BFA committee members take home from selection meetings. It fuses Wyscout stats, scout evaluations, eligibility status, and bio into a single shareable document.

**Working folder:** `D:\BFA-Scout`.

## Scope — one route, one PDF, two-page max

`GET /players/<id>/passport.pdf` — returns a PDF download.

Two variants via query param:
- **Default** (admin/TD): full data — scout names, evaluation summaries, eligibility notes
- `?public=1` (any logged-in user): redacted — scout names → "Scout N", no eligibility admin notes, no draft evaluations referenced. For sharing with player agents or external clubs.

**Page 1** — Bio + Eligibility + Wyscout summary:
- Header: BFA logo (top-left), player photo (centered, 100×100), full name (EN + AR), DOB/age, primary position + group, current club + division, nationality + flag
- Eligibility card: status icon + label + countdown
- Wyscout aggregates: Matches, Minutes, Goals, Assists, Shots, xG, Pass %, Duels %, Aerial %, Yellow/Red cards (the same 11 metrics as the comparison page)
- 6-axis Wyscout radar rendered as embedded SVG (use the same axis values as the comparison page radar)

**Page 2** — Scout evaluations (if any exist):
- "Latest scout evaluation" panel: scout name (or "Scout N" if redacted), date, match label, NT readiness, recommendation, category averages (4 sliders rendered as horizontal bars), summary text (truncated to 500 chars)
- "Evaluation history" compact table: up to 5 most-recent submitted/locked evaluations — date, scout (or redacted), match, NT level, recommendation
- Footer: "Generated YYYY-MM-DD HH:MM by BFA-Scout · Player Passport v1"

If player has zero active evaluations, Page 2 reads "No scout evaluations on file yet" and skips the panels.

## Locked decisions

| Decision | Choice |
|---|---|
| PDF library | WeasyPrint (HTML+CSS → PDF, free, mature, prints bilingual content reliably) |
| Page size | A4 portrait, 20mm margins all sides |
| Font (Latin) | Inter (already in project) or system fallback if Inter not loadable in WeasyPrint |
| Font (Arabic) | Cairo (already in project as Google Font; download .ttf for WeasyPrint local use) |
| Branding | BFA red `#C8102E` for headings; gold `#B5924C` for accents; dark text on white (NOT dark theme — printable) |
| Photos | Use existing `get_player_photo(player_id, national_id)` — embed as base64 in HTML so WeasyPrint renders without external fetch |
| Radar SVG | Render server-side as SVG (NOT Chart.js — Chart.js needs JS runtime, WeasyPrint doesn't run JS reliably). Hand-build a simple 6-axis polygon SVG. |
| Bilingual rendering | Player name shown as `Full Name EN / Full Name AR` if both exist; AR rendered with `dir="rtl"` block |
| Caching | NONE for v1 — regenerate on every request. Profile cache-then-invalidate is a v1.1 optimization. |
| Filename | `BFA-Scout_Player-{id}_{slug}_{YYYY-MM-DD}.pdf` (e.g. `BFA-Scout_Player-2_arthur-rezende_2026-05-11.pdf`) |
| Permissions | Default route: admin / TD / scout. `?public=1`: any authenticated. |
| Audit log | One entry per generation: `action='player.passport_generated'`, `details={player_id, mode, generator_id}` |
| Empty Wyscout | Page 1 renders bio + eligibility; stats panel reads "No Wyscout data on file" |
| Soft-deleted evaluations | EXCLUDED from page 2 (Phase 5c-3 invariant) |
| Locked evaluations | INCLUDED on page 2 (locked is workflow, not hidden) |

## Pre-flight gates

```powershell
git log --oneline | Select-Object -First 1   # expect: 4.2
git status                                    # expect: clean
.\.venv\Scripts\Activate.ps1
pip show weasyprint                           # may not be installed yet
```

If WeasyPrint not installed:
```powershell
pip install weasyprint
```

Note: WeasyPrint requires GTK on Windows. If pip install fails with GTK errors, follow https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#windows for the runtime DLLs. This is a one-time setup. If installation is genuinely blocked on Windows, **fall back to ReportLab** — uglier output but pure Python, no system dependencies. Document the fallback in CHANGELOG.

## Files to create / modify

```
app/passport/                              [NEW directory]
├── __init__.py                            [NEW] Blueprint with /players/<id>/passport.pdf
├── renderer.py                            [NEW] Orchestrates HTML → PDF
├── data.py                                [NEW] Aggregates all data needed for the PDF
└── radar_svg.py                           [NEW] Server-side 6-axis radar SVG

app/templates/passport/
├── passport.html                          [NEW] The full HTML doc rendered to PDF
└── _passport.css                          [NEW] Print-specific CSS

app/static/fonts/                          [MAY NEED] Cairo.ttf + Inter.ttf if local fonts needed for WeasyPrint

app/templates/players/profile.html         [MODIFY] Add "Download Player Passport (PDF)" button near top

app/__init__.py                            [MODIFY] Register passport blueprint

CHANGELOG.md                               [APPEND] v0.6.0 entry — major version bump (first non-incremental feature)
PROJECT.md                                 [UPDATE] Mark Phase 6 complete; queue Phase 8
```

**No schema changes.** Pure read + render.

## Data shape — `app/passport/data.py`

```python
def get_passport_data(player_id: int, mode: str = 'full') -> dict | None:
    """Returns all data needed to render the Player Passport PDF.
    mode='full': everything (admin/TD)
    mode='public': redacted (scout names → 'Scout N', no admin notes)

    Returns None if player not found or is_active=FALSE.
    """
    # Existing helpers to compose:
    # - get_player(player_id) — bio + eligibility cols + position info + club info
    # - compute_eligibility_status(player) — for the eligibility card
    # - get_player_evaluations(player_id) — list of active evaluations
    # - get_evaluation_count_active(player_id)
    # - get_player_evaluation_aggregate(player_id, mode='latest') — for latest panel
    # - Wyscout aggregates from app/wyscout/aggregations.py

    # If mode='public':
    # - replace evaluator_name with f"Scout {i}" where i is a per-passport-rendering counter
    # - omit player.eligibility_notes_admin from output
    # - omit player.bahrain_residency_notes from output

    return {
        'player': {...},
        'eligibility': {...},
        'wyscout': {...},  # may be None if no stats
        'latest_eval': {...} | None,
        'evaluation_history': [...],  # up to 5 most-recent, summarized
        'meta': {
            'mode': mode,
            'generated_at': datetime.now(timezone.utc),
            'generator_name': current_user.full_name,
        }
    }
```

## Radar SVG — `app/passport/radar_svg.py`

```python
def render_wyscout_radar_svg(values: dict, size: int = 280) -> str:
    """Returns an SVG string for the 6-axis Wyscout radar.
    `values`: dict of axis_label → normalized 0-100 value (same as Chart.js input)
    Output: standalone SVG, no external CSS dependencies.

    6 axes: Goals/90, Assists/90, Pass %, Duels won %, Aerial won %, Defensive actions/90.
    Same axes as the comparison page Wyscout radar (Phase 4.1).
    """
    # Hand-built polygon SVG:
    # - Background grid (5 concentric hexagons at 20/40/60/80/100)
    # - 6 axis lines from center to each vertex
    # - Polygon for the player's values (filled, BFA red, 30% alpha)
    # - Axis labels at each vertex
    # - Numeric value labels at each polygon vertex
```

Keep this self-contained — pure SVG string. ~100 lines of Python. The same code can later power Phase 4.2's PDF season-breakdown if/when 4.2.1 ships.

## Renderer — `app/passport/renderer.py`

```python
from weasyprint import HTML, CSS

def render_passport_pdf(data: dict) -> bytes:
    """Compose passport.html with data dict, render to PDF bytes via WeasyPrint."""
    html_str = render_template('passport/passport.html', **data)
    pdf_bytes = HTML(string=html_str, base_url=current_app.config['BASE_URL']).write_pdf(
        stylesheets=[CSS(filename='app/templates/passport/_passport.css')]
    )
    return pdf_bytes
```

`base_url` matters for embedded images. Use `request.url_root` or a config value.

## Route — `app/passport/__init__.py`

```python
@bp.route('/players/<int:player_id>/passport.pdf')
@login_required
def player_passport(player_id):
    mode = 'public' if request.args.get('public') == '1' else 'full'
    if mode == 'full' and not current_user.has_role('admin','technical_director','scout'):
        abort(403)

    data = get_passport_data(player_id, mode=mode)
    if not data:
        abort(404)

    # Render radar SVG; embed in data
    if data.get('wyscout'):
        data['wyscout_radar_svg'] = render_wyscout_radar_svg(data['wyscout']['radar_values'])

    pdf_bytes = render_passport_pdf(data)

    # Audit-log
    log_audit(action='player.passport_generated',
              details={'player_id': player_id, 'mode': mode})

    # Filename: BFA-Scout_Player-2_arthur-rezende_2026-05-11.pdf
    slug = slugify(data['player']['full_name'])
    filename = f"BFA-Scout_Player-{player_id}_{slug}_{date.today().isoformat()}.pdf"

    return send_file(BytesIO(pdf_bytes),
                     mimetype='application/pdf',
                     as_attachment=True,
                     download_name=filename)
```

## Templates — `passport.html` structure

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>BFA-Scout Player Passport — {{ player.full_name }}</title>
</head>
<body>
    <!-- Page 1: Bio + Eligibility + Wyscout -->
    <header class="passport-header">
        <img src="data:image/png;base64,{{ bfa_logo_base64 }}" alt="BFA">
        <h1>Player Passport</h1>
    </header>

    <section class="bio">
        {% if player.photo_path %}
            <img class="player-photo" src="{{ player.photo_data_uri }}" alt="{{ player.full_name }}">
        {% endif %}
        <div class="bio-text">
            <h2>{{ player.full_name }}</h2>
            {% if player.full_name_ar %}
                <h2 dir="rtl" class="ar-name">{{ player.full_name_ar }}</h2>
            {% endif %}
            <div class="bio-grid">
                <div><strong>DOB:</strong> {{ player.dob }} ({{ player.age }}y)</div>
                <div><strong>Position:</strong> {{ player.position_name }} ({{ player.position_group_code }})</div>
                <div><strong>Club:</strong> {{ player.club_name or 'Unaffiliated' }}{% if player.club_division %} · {{ player.club_division|title }} Division{% endif %}</div>
                <div><strong>Nationality:</strong> {{ player.nationality_label }} {{ flag_emoji(player.nationality_code) }}</div>
            </div>
        </div>
    </section>

    <section class="eligibility">
        <h3>National-Team Eligibility</h3>
        <div class="elig-row">
            <span class="elig-icon">{{ eligibility.icon }}</span>
            <span class="elig-label">{{ eligibility.label }}</span>
        </div>
        {% if eligibility.note %}
            <p class="elig-note">{{ eligibility.note }}</p>
        {% endif %}
    </section>

    {% if wyscout %}
    <section class="wyscout">
        <h3>Wyscout Career Statistics</h3>
        <div class="wyscout-grid">
            <div class="stats-table">
                <table>
                    <tr><th>Matches</th><td>{{ wyscout.matches }}</td></tr>
                    <tr><th>Minutes</th><td>{{ wyscout.minutes }}</td></tr>
                    <tr><th>Goals</th><td>{{ wyscout.goals }}</td></tr>
                    <tr><th>Assists</th><td>{{ wyscout.assists }}</td></tr>
                    <tr><th>Shots</th><td>{{ wyscout.shots }}</td></tr>
                    <tr><th>xG</th><td>{{ '%.2f'|format(wyscout.xg) }}</td></tr>
                    <tr><th>Pass %</th><td>{{ wyscout.pass_pct }}%</td></tr>
                    <tr><th>Duels won %</th><td>{{ wyscout.duels_won_pct }}%</td></tr>
                    <tr><th>Aerial won %</th><td>{{ wyscout.aerial_won_pct }}%</td></tr>
                    <tr><th>Yellow / Red cards</th><td>{{ wyscout.yellows }} / {{ wyscout.reds }}</td></tr>
                </table>
            </div>
            <div class="radar">
                {{ wyscout_radar_svg | safe }}
            </div>
        </div>
    </section>
    {% else %}
    <section class="wyscout-empty">
        <p>No Wyscout data on file.</p>
    </section>
    {% endif %}

    <!-- Page break -->
    <div class="page-break"></div>

    <!-- Page 2: Scout evaluations -->
    {% if evaluation_history %}
    <section class="scout-section">
        <h3>Scout Assessment ({{ evaluation_history|length }} evaluation{{ '' if evaluation_history|length == 1 else 's' }})</h3>

        {% if latest_eval %}
        <div class="latest-eval">
            <h4>Latest evaluation</h4>
            <p class="eval-meta">
                {{ latest_eval.evaluator_name }} ·
                {{ latest_eval.submitted_at.strftime('%Y-%m-%d') }} ·
                {{ latest_eval.match_label }}
            </p>
            <div class="elig-row">
                <span class="badge nt-level">{{ latest_eval.nt_readiness_level|upper }}</span>
                <span class="badge rec">{{ latest_eval.recommendation|replace('_',' ')|title }}</span>
            </div>
            <div class="cat-averages">
                {% for cat in ['TECH','TACT','PHYS','MENT'] %}
                    {% set avg = latest_eval.category_averages.get(cat) %}
                    <div class="cat-row">
                        <span class="cat-label">{{ {'TECH':'Technical','TACT':'Tactical','PHYS':'Physical','MENT':'Mentality'}[cat] }}</span>
                        <div class="bar-bg">
                            {% if avg %}
                                <div class="bar-fill" style="width: {{ (avg/10*100) }}%;"></div>
                            {% endif %}
                        </div>
                        <span class="cat-value">{{ avg if avg else '—' }}</span>
                    </div>
                {% endfor %}
            </div>
            {% if latest_eval.summary %}
                <p class="summary">{{ latest_eval.summary[:500] }}{% if latest_eval.summary|length > 500 %}…{% endif %}</p>
            {% endif %}
        </div>
        {% endif %}

        {% if evaluation_history|length > 1 %}
        <div class="history">
            <h4>Recent evaluations</h4>
            <table class="history-table">
                <thead>
                    <tr>
                        <th>Date</th><th>Scout</th><th>Match</th><th>NT Level</th><th>Recommendation</th>
                    </tr>
                </thead>
                <tbody>
                    {% for ev in evaluation_history[:5] %}
                    <tr>
                        <td>{{ ev.submitted_at.strftime('%Y-%m-%d') }}</td>
                        <td>{{ ev.evaluator_name }}</td>
                        <td>{{ ev.match_label }}</td>
                        <td>{{ ev.nt_readiness_level|upper }}</td>
                        <td>{{ ev.recommendation|replace('_',' ')|title }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        {% endif %}
    </section>
    {% else %}
    <section class="scout-empty">
        <p>No scout evaluations on file yet.</p>
    </section>
    {% endif %}

    <footer>
        Generated {{ meta.generated_at.strftime('%Y-%m-%d %H:%M UTC') }}
        by {{ meta.generator_name }} · BFA-Scout Player Passport v1
        {% if meta.mode == 'public' %} · (Public version — scout identities redacted){% endif %}
    </footer>
</body>
</html>
```

## CSS — `_passport.css`

```css
@page { size: A4; margin: 20mm; }
body {
    font-family: 'Inter', -apple-system, sans-serif;
    color: #1a1a1a;
    line-height: 1.4;
    font-size: 11pt;
}
.ar-name, [dir="rtl"] { font-family: 'Cairo', 'Inter', sans-serif; }

h1 { color: #C8102E; font-size: 22pt; margin: 0; }
h2 { color: #C8102E; font-size: 16pt; margin: 0 0 4pt 0; }
h3 { color: #C8102E; font-size: 12pt; margin: 18pt 0 6pt 0; border-bottom: 1pt solid #B5924C; padding-bottom: 2pt; }
h4 { color: #1a1a1a; font-size: 11pt; margin: 12pt 0 4pt 0; font-weight: 600; }

.passport-header { display: flex; align-items: center; gap: 12pt; margin-bottom: 12pt; }
.passport-header img { height: 32pt; }

.bio { display: flex; gap: 16pt; margin-bottom: 16pt; }
.player-photo { width: 100pt; height: 100pt; object-fit: cover; border-radius: 6pt; border: 2pt solid #C8102E; }
.bio-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 4pt 16pt; margin-top: 8pt; }

.elig-row { display: flex; align-items: center; gap: 8pt; }
.elig-icon { font-size: 18pt; }
.elig-label { font-weight: 600; }
.elig-note { color: #666; font-size: 10pt; margin: 4pt 0; }

.wyscout-grid { display: flex; gap: 16pt; }
.stats-table table { border-collapse: collapse; }
.stats-table th { text-align: left; padding: 2pt 8pt; color: #666; font-weight: 500; }
.stats-table td { padding: 2pt 8pt; font-weight: 600; color: #C8102E; }
.radar { flex-shrink: 0; }
.radar svg { width: 280px; height: 280px; }

.page-break { page-break-after: always; }

.badge { display: inline-block; padding: 2pt 8pt; border-radius: 3pt; font-size: 9pt; font-weight: 600; color: #fff; }
.badge.nt-level { background: #B5924C; }
.badge.rec { background: #C8102E; }

.cat-averages { margin: 8pt 0; }
.cat-row { display: grid; grid-template-columns: 80pt 1fr 30pt; gap: 8pt; align-items: center; margin: 3pt 0; }
.cat-label { font-size: 10pt; }
.bar-bg { height: 8pt; background: #eee; border-radius: 4pt; overflow: hidden; }
.bar-fill { height: 100%; background: #C8102E; }
.cat-value { text-align: right; font-weight: 600; font-size: 10pt; }

.summary { font-size: 10pt; color: #333; margin-top: 8pt; padding: 8pt; background: #fafafa; border-left: 3pt solid #B5924C; }

.history-table { width: 100%; border-collapse: collapse; margin-top: 8pt; font-size: 9pt; }
.history-table th { background: #fafafa; padding: 4pt 6pt; text-align: left; border-bottom: 1pt solid #ccc; }
.history-table td { padding: 4pt 6pt; border-bottom: 1pt solid #eee; }

footer { margin-top: 16pt; padding-top: 8pt; border-top: 1pt solid #ddd; color: #999; font-size: 8pt; }
```

## Profile page button

In `app/templates/players/profile.html`, near the top action buttons (next to "New Evaluation"):

```html
{% if current_user.has_role('admin','technical_director','scout') %}
  <a href="{{ url_for('passport.player_passport', player_id=player.id) }}"
     class="btn-secondary">
    📄 Download Passport (PDF)
  </a>
  <a href="{{ url_for('passport.player_passport', player_id=player.id, public=1) }}"
     class="btn-secondary text-sm"
     title="Redacted version — for sharing externally">
    Public PDF
  </a>
{% endif %}
```

## Verification

1. WeasyPrint installable: `pip show weasyprint` succeeds
2. Generate Arthur's passport: hit the URL, save the PDF, open it
3. Visual checks:
   - Page 1: photo + bio + eligibility + Wyscout stats + radar all visible
   - Page 1: Arabic name renders correctly (right-to-left, Cairo font visible)
   - Page 1: page break before page 2
   - Page 2: latest evaluation + recent evaluations table
   - Footer with generation timestamp + generator name
4. Public mode: `?public=1` produces a PDF with scout names → "Scout 1" / "Scout 2"
5. Empty Wyscout player: generates PDF with "No Wyscout data on file"
6. Empty evaluations player: generates PDF with "No scout evaluations on file yet"
7. Audit log: `psql -U bfa -d bfa_scout -c "SELECT action, details FROM audit_log WHERE action = 'player.passport_generated' ORDER BY id DESC LIMIT 5;"`
8. Filename: download produces `BFA-Scout_Player-2_arthur-rezende_2026-05-11.pdf`

## Synthetic E2E — `migrations/_e2e_phase_6.py`

```python
# Hit /players/2/passport.pdf
# Verify response.status_code = 200
# Verify response.content_type = 'application/pdf'
# Verify response.content[:4] == b'%PDF'
# Verify Content-Disposition includes 'attachment; filename=BFA-Scout_Player-2_'
# Verify PDF size > 5000 bytes (sanity — empty PDFs are ~1KB)

# Hit /players/2/passport.pdf?public=1
# Same checks + parse PDF text content (pdftotext or pypdf), verify no real scout names appear

# Hit /players/9999/passport.pdf (nonexistent player)
# Verify 404

# Hit /players/1/passport.pdf (soft-deleted player — Sayed)
# Verify 404 or appropriate handling
```

## Acceptance criteria

- ✅ Pre-flight gates pass (4.2 committed, clean tree, WeasyPrint installed)
- ✅ Route returns valid PDF (content-type, magic bytes, >5KB)
- ✅ Page 1 renders bio + eligibility + Wyscout stats + radar SVG
- ✅ Page 2 renders evaluations if any exist, "No evaluations" otherwise
- ✅ Arabic name renders correctly with Cairo font + RTL
- ✅ BFA red + gold colors used as headings/accents
- ✅ public=1 mode redacts scout names
- ✅ public=1 mode omits eligibility_notes_admin and bahrain_residency_notes
- ✅ Filename matches `BFA-Scout_Player-{id}_{slug}_{date}.pdf` pattern
- ✅ Audit log entry per generation
- ✅ Empty Wyscout player still generates (no crash)
- ✅ Empty evaluations player still generates (no crash)
- ✅ Soft-deleted evaluations excluded from passport
- ✅ Locked evaluations included
- ✅ Soft-deleted player returns 404
- ✅ Profile page has "Download Passport (PDF)" button
- ✅ Synthetic E2E PASS

## Hard rules

- ❌ Do NOT modify schema (no migration needed)
- ❌ Do NOT add JS to the passport HTML (WeasyPrint doesn't run JS reliably)
- ❌ Do NOT use Chart.js for the radar (use hand-built SVG via radar_svg.py)
- ❌ Do NOT use flask.test_client() for verification — restart real Flask + real HTTP
- ❌ Do NOT initialize git or commit — Ali commits manually
- ❌ Do NOT touch `D:\BFA-Analytics` or `D:\BFA-Analytics-AWS`
- ❌ Do NOT bypass soft-delete filter for evaluations (Phase 5c-3 invariant)
- ❌ Do NOT include `evaluator_name` in public mode (redact to "Scout N")
- ✅ Restart Flask after each significant code change
- ✅ Generate at least one real PDF and open it visually as part of session output
- ✅ Append v0.6.0 entry to CHANGELOG.md (major version bump — first non-incremental feature)
- ✅ Mark Phase 6 complete in PROJECT.md, queue Phase 8

## Fallback if WeasyPrint blocked

If `pip install weasyprint` fails on Windows due to GTK runtime, swap to **ReportLab** as fallback:

```python
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table
# ... build PDF programmatically
```

Output will look uglier but functions. Document the fallback in CHANGELOG. If ReportLab is also blocked, abort with `PHASE_6_BLOCKED.md` documenting the environment issue and we plan a Docker-based PDF service for Phase 8.

## Commit

```powershell
cd D:\BFA-Scout
git add -A
git commit -m "Phase 6: Player Passport PDF (bio + eligibility + Wyscout + scout evaluations, bilingual EN/AR, public/full modes)"
```
