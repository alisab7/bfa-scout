# Cowork Session: BFA-Scout Phase 3 — Players Module

## Context

**Project:** BFA-Scout — Flask + PostgreSQL scouting platform for the Bahrain FA.
**Location:** `D:\BFA-Scout` (independent from `D:\BFA-Analytics`).
**Stack (locked):** Python 3.11 · Flask 3.x · psycopg2 RealDictCursor · Jinja + HTMX + Alpine.js · Tailwind CDN · PostgreSQL 15 native.

**State coming in:**
- Phase 0 (scaffold) ✅ committed
- Phase 1 (Auth & RBAC) ⚠️ working, checkpoint committed — Flask-Login, 4 roles, admin CRUD, audit log. Minor polish deferred to Phase 8.
- Phase 2 (criteria admin) ⏭️ skipped — seeded criteria (13 tables, 8 position groups) are sufficient for Phases 5–6.

**Start this session by running:**
```
cd D:\BFA-Scout
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\flask --app wsgi run --debug
```
If the DB has never been seeded on this machine:
```
.venv\Scripts\flask --app wsgi init-db
```
(Flask startup auto-seeds the initial admin from `INITIAL_ADMIN_EMAIL` / `INITIAL_ADMIN_PASSWORD` in `.env`.)

---

## Goal of this session

Build the **Players module** — the central entity every later phase depends on. End state: scouts can create, search, view, and soft-delete player records with photos through real browser forms. No mocked data, no SQL inserts.

---

## Stack additions for Phase 3

Add to `requirements.txt`:
```
Pillow==10.3.0
```

---

## Files & folders to create / modify

```
D:\BFA-Scout\
├── app/
│   ├── players/
│   │   ├── __init__.py          # Blueprint — replaces stub
│   │   └── helpers.py           # get_player_photo(), get_player_pos()
│   ├── templates/
│   │   └── players/
│   │       ├── list.html        # Card grid + HTMX search bar
│   │       ├── new.html         # Create form
│   │       ├── edit.html        # Edit form + photo replace
│   │       └── profile.html     # Full profile — placeholder slots for Phase 4/5
│   └── static/
│       ├── photos/              # player photos — gitignored
│       │   └── placeholder.svg  # fallback SVG (BFA crest silhouette)
│       └── css/style.css        # add .player-card, .photo-thumb styles
├── requirements.txt             # add Pillow==10.3.0
├── .gitignore                   # add app/static/photos/*.jpg
```

---

## Implementation specifics

### `app/players/__init__.py` — Blueprint + routes

All routes `@login_required`. Edit/create/delete require `@scout_or_above` (imports from `app.auth.decorators`).

```python
bp = Blueprint('players', __name__, template_folder='../templates/players')
```

**Routes:**

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | /players/ | login_required | List / search (HTMX target: `#player-grid`) |
| GET | /players/new | scout_or_above | Create form |
| POST | /players/new | scout_or_above | Create player + upload photo |
| GET | /players/\<id\> | login_required | Profile page |
| GET | /players/\<id\>/edit | scout_or_above | Edit form |
| POST | /players/\<id\>/edit | scout_or_above | Update player + optional photo replace |
| POST | /players/\<id\>/deactivate | scout_or_above | Soft-delete (set is_active=FALSE) |

**List route — HTMX search:**
```python
@bp.route('/')
@login_required
def list_players():
    q = request.args.get('q', '').strip()
    pos = request.args.get('pos', '').strip()
    # Build parameterized query — search full_name_en, full_name_ar, national_id
    # Filter is_active=TRUE always
    # If request.headers.get('HX-Request'): return partial template 'players/_grid.html'
    # else: return full 'players/list.html'
```

**Create / update — photo handling:**
- Accept `multipart/form-data`
- If photo uploaded: use Pillow to center-crop to 400×400 JPEG, save to `app/static/photos/<player_id>.jpg`
- If no photo: keep existing (on edit) or leave blank (new)
- Never store raw upload — always re-encode through Pillow

**Soft-delete:**
```python
@bp.route('/<int:player_id>/deactivate', methods=['POST'])
@scout_or_above
def deactivate(player_id):
    # SET is_active = FALSE, updated_at = NOW() WHERE id = %s
    # log_audit('player.deactivate', 'player', player_id)
    # redirect to list
```

**Hard rule:** Never `DELETE FROM players`. Only `UPDATE ... SET is_active = FALSE`.

---

### `app/players/helpers.py`

```python
import os
from flask import url_for, current_app

def get_player_photo(player_id):
    """
    Return URL for player photo, falling back to placeholder.svg.
    Checks filesystem so it works before and after upload.
    """
    path = os.path.join(current_app.root_path, 'static', 'photos', f'{player_id}.jpg')
    if os.path.exists(path):
        return url_for('static', filename=f'photos/{player_id}.jpg')
    return url_for('static', filename='photos/placeholder.svg')

def get_player_pos(position_code):
    """
    Return (position_code, position_group_code, position_group_name_en)
    for a given Wyscout position code. Queries DB via pool directly
    so it works outside request context too.
    Returns (code, None, None) if not found.
    """
    from app.db import _get_pool
    conn = _get_pool().getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.code, pg.code AS group_code, pg.name_en AS group_name
                FROM   positions p
                JOIN   position_groups pg ON pg.id = p.position_group_id
                WHERE  p.code = %s
                """,
                (position_code,)
            )
            row = cur.fetchone()
        return (position_code, row['group_code'], row['group_name']) if row else (position_code, None, None)
    finally:
        _get_pool().putconn(conn)
```

**Register both as Jinja globals in `app/__init__.py`:**
```python
from .players.helpers import get_player_photo, get_player_pos
app.jinja_env.globals['get_player_photo'] = get_player_photo
app.jinja_env.globals['get_player_pos']   = get_player_pos
```

---

### `app/static/photos/placeholder.svg`

SVG showing a generic player silhouette in BFA brand colors (`--brand` red circle + white figure). Keep it under 1 KB inline SVG. Must render at 400×400 viewBox.

---

### `app/static/css/style.css` additions

```css
/* Player card grid */
.player-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 1rem;
}
.player-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  transition: border-color 0.15s;
}
.player-card:hover { border-color: var(--accent); }
.photo-thumb {
  width: 100%;
  aspect-ratio: 1 / 1;
  object-fit: cover;
  background: var(--bg);
}
```

---

### `app/templates/players/list.html`

- Extends `base.html`
- Search bar: `<input hx-get="{{ url_for('players.list_players') }}" hx-trigger="input changed delay:300ms" hx-target="#player-grid" name="q">`
- Position filter: `<select name="pos" hx-get="..." hx-trigger="change" hx-target="#player-grid">`
  - Options: blank + one `<optgroup>` per position_group, `<option>` per position inside it
  - Load groups+positions from DB in the route, pass to template
- `<div id="player-grid">` renders a grid of `.player-card` elements
- Each card: photo thumb, name (EN + AR), position badge, age, "View" link
- `onerror` on every `<img>`: `onerror="this.src='{{ url_for('static', filename='photos/placeholder.svg') }}'"`
- Empty state: "No players found. Add the first player." with link to `/players/new`
- "Add player" button (scout_or_above only — use `current_user.has_role(...)`)

---

### `app/templates/players/new.html` + `edit.html`

**Fields (map to `players` table columns):**
- `full_name_en` — required
- `full_name_ar` — optional, RTL input
- `national_id` — required, unique
- `date_of_birth` — `<input type="date">`
- `position` — `<select>` with optgroups (same position picker as list filter)
- `nationality` — text, default "BH"
- `club_name` — text
- `club_country` — text
- `height_cm`, `weight_kg` — number inputs, optional
- `notes` — `<textarea>`, optional
- `photo` — `<input type="file" accept="image/*">` — show current thumb on edit

**Validation (server-side):**
- `full_name_en` required
- `national_id` required + unique check (exclude self on edit)
- `date_of_birth` must be in the past
- Photo: if uploaded, must be image MIME type, max 10 MB before Pillow processing

---

### `app/templates/players/profile.html`

Full player profile page. Sections:

1. **Header** — large photo, name (EN + AR), position badge, age, club, nationality
2. **Bio grid** — DOB, height/weight, national ID, notes
3. **Wyscout stats** *(Phase 4 placeholder)* — `<div id="wyscout-stats" class="...">Coming in Phase 4</div>`
4. **Evaluations** *(Phase 5 placeholder)* — `<div id="evaluations" class="...">Coming in Phase 5</div>`
5. **Actions** — Edit button (scout_or_above), Deactivate form with confirm (scout_or_above)

---

### SQL patterns

All queries must:
- Select `id, full_name_en, full_name_ar, national_id, position, date_of_birth, ...` explicitly — no `SELECT *`
- JOIN `positions p ON p.code = players.position` and `position_groups pg ON pg.id = p.position_group_id`
- Always include `WHERE players.is_active = TRUE` unless explicitly showing inactive
- Use `RealDictCursor` (already default via pool config)
- Parameterized only — never f-string or % format into SQL

**Position picker query:**
```sql
SELECT pg.code AS group_code, pg.name_en AS group_name, pg.sort_order,
       p.code  AS pos_code,   p.name_en  AS pos_name
FROM   position_groups pg
JOIN   positions p ON p.position_group_id = pg.id
ORDER  BY pg.sort_order, p.name_en
```

**Player list query (parameterized search):**
```sql
SELECT pl.id, pl.full_name_en, pl.full_name_ar, pl.national_id,
       pl.position, pl.date_of_birth, pl.club_name,
       p.name_en AS pos_name, pg.code AS group_code, pg.name_en AS group_name
FROM   players pl
LEFT JOIN positions p  ON p.code = pl.position
LEFT JOIN position_groups pg ON pg.id = p.position_group_id
WHERE  pl.is_active = TRUE
  AND  (%s = '' OR pl.full_name_en ILIKE %s OR pl.full_name_ar ILIKE %s OR pl.national_id ILIKE %s)
  AND  (%s = '' OR pl.position = %s)
ORDER  BY pl.full_name_en
```
Bind as: `(q, f'%{q}%', f'%{q}%', f'%{q}%', pos, pos)`

---

## Acceptance criteria

Before ending the session, verify all of these against a live Flask process:

1. ✅ `pip install Pillow` succeeds, `import PIL` in flask shell works
2. ✅ `GET /players/` returns 200 with search bar and empty state
3. ✅ `GET /players/new` returns 200 with position optgroups populated from DB
4. ✅ Create **Player 1**: full English name, Arabic name, national_id, DOB, position=GK, photo uploaded → redirect to list, card visible
5. ✅ Create **Player 2**: no photo → placeholder SVG renders on card, no broken image
6. ✅ Create **Player 3**: duplicate national_id of Player 1 → validation error, no DB insert
7. ✅ `GET /players/<id>` profile page renders: photo, name, position, Phase 4/5 placeholder slots visible
8. ✅ HTMX search: type 3 chars of Player 1's name → grid updates without full page reload (check Network tab: 200 response with partial HTML, no full `<html>`)
9. ✅ Position filter: select GK → only GK players shown
10. ✅ Edit Player 1: change club name → saved, visible on profile
11. ✅ Edit Player 1: upload replacement photo → new photo renders (old file overwritten)
12. ✅ `POST /players/<id>/deactivate` → player disappears from list, DB row has `is_active=FALSE`
13. ✅ `get_player_photo()` and `get_player_pos()` accessible as Jinja globals (verify in template — no import needed)
14. ✅ `GET /players/` unauthenticated → 302 to `/auth/login`
15. ✅ `git add -A && git commit -m "Phase 3: Players module"` succeeds

---

## Hard rules (never violate)

- ❌ No `DELETE FROM players` — soft-delete only
- ❌ No hardcoded position fallback (`'MID'`, `'FW'`, etc.) — always from DB
- ❌ No `SELECT *` in player queries — explicit column list
- ❌ No f-string SQL — parameterized only
- ❌ No raw file storage — all uploads through Pillow re-encode
- ✅ `onerror` placeholder on every player `<img>`
- ✅ All photo paths derived from `get_player_photo(player_id)` — never hardcoded
- ✅ `RealDictCursor` on all queries
- ✅ `log_audit()` on create, edit, deactivate
- ✅ CSRF token on all POST forms

## Out of scope (do NOT build)

- Wyscout stats display (Phase 4)
- Evaluation form (Phase 5)
- Criteria admin UI (Phase 8)
- Bulk import
- Player comparison
- Export to PDF

## Session discipline

- Target: 8 messages or fewer
- End by updating `PROJECT.md` ("Phase 3 complete, next: Phase 4 Wyscout import")
- End by appending to `CHANGELOG.md` (v0.2.0)
- Last action: print 15-item acceptance checklist with ✅/❌ per item
