# Cowork Session: BFA-Scout Phase 3 — Players Module

## Context

Phases 0 (scaffold) and 1 (auth) are committed. We are **skipping Phase 2** (criteria admin UI) for now — the 39 seeded criteria + 200 position-group mappings are sufficient for v1 evaluations. Admin UI for criteria gets built post-launch.

**Goal of Phase 3: stand up the player module — the central entity that everything else hangs off (evaluations link to players, Wyscout stats link to players, reports are about players).**

**Working folder:** `D:\BFA-Scout` (do NOT touch `D:\BFA-Analytics` or `D:\BFA-Analytics-AWS`).

**Local environment (already established):**
- PostgreSQL 15 native, database `bfa_scout`, user `bfa`, password `bfa2025`
- Flask runs via `flask --app wsgi run --debug`
- Auth working — admin user seeded, scout user can be created
- Tables exist: `players` table is empty, ready for inserts

## Goal

End state:
1. Admin or scout can create players (CPR-keyed, Arabic name support)
2. Player photos upload + center-crop to 400×400 JPEG
3. Player list page with HTMX live search (filter as you type)
4. Player profile page renders with photo, bio, position — **skeleton ready** for Wyscout (Phase 4) and evaluations (Phase 5)
5. Edit and soft-delete (`is_active = false`) flows
6. Mobile-first UI matching BFA branding

## Scope rules

**IN scope:**
- Player CRUD (list, create, view, edit, soft-delete)
- Photo upload + center-crop helper
- HTMX live search on the list page
- Position picker (uses 26 Wyscout codes grouped by 8 position_groups from `positions` + `position_groups` tables)
- `get_player_photo()` and `get_player_pos()` helpers (used everywhere player data is shown — Phases 4–6 will reuse them)

**OUT of scope (do NOT build):**
- Wyscout integration (Phase 4)
- Evaluations link / form (Phase 5)
- Bulk photo upload (deferred)
- OCR for ID card photos (deferred)
- Player merging / dedup logic (deferred)
- Admin UI for criteria (Phase 8)

## Files to create / modify

```
app/
├── players/
│   ├── __init__.py              [REPLACE STUB] full blueprint with routes
│   ├── routes.py                [NEW] split routes if __init__ gets large
│   ├── photos.py                [NEW] upload + Pillow center-crop helpers
│   ├── helpers.py               [NEW] get_player_photo, get_player_pos
│   └── forms.py                 [NEW] form validation helpers (no Flask-WTF needed unless useful)
├── templates/
│   └── players/
│       ├── list.html            [NEW] search + table/card view
│       ├── new.html             [NEW] create form
│       ├── edit.html            [NEW] edit form (extends new with a flag)
│       ├── profile.html         [NEW] profile page (Wyscout + eval slots are placeholders)
│       └── _row.html            [NEW] HTMX partial — single row for live search results
├── static/
│   ├── img/
│   │   └── player_placeholder.png   [NEW] fallback when no photo
│   └── uploads/
│       └── players/             [NEW] empty dir, .gitkeep
└── ...
```

## Implementation specifics

### `app/players/helpers.py` — the universal player-data helpers

These are STANDING REQUIREMENTS — every template and route showing player data **must** call these (Phases 4–6 will reuse). No exceptions.

```python
import os
from flask import url_for, current_app

PLACEHOLDER_PATH = '/static/img/player_placeholder.png'

def get_player_photo(player_id, national_id=None):
    """Return URL for a player's photo, with fallback to placeholder.
    Tries: by player_id first, then by national_id, else placeholder."""
    upload_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'players')
    candidates = []
    if player_id:
        candidates.append((f'{player_id}.jpg', f'/static/uploads/players/{player_id}.jpg'))
    if national_id:
        candidates.append((f'{national_id}.jpg', f'/static/uploads/players/{national_id}.jpg'))
    for filename, url_path in candidates:
        if os.path.exists(os.path.join(upload_dir, filename)):
            return url_path
    return PLACEHOLDER_PATH

def get_player_pos(player):
    """Return display name for a player's primary position.
    `player` is a dict (RealDictCursor row) that includes position_code and position_name.
    NEVER fall back to a hardcoded value like 'MID'. Return '—' if no position set."""
    if not player:
        return '—'
    name = player.get('position_name')
    code = player.get('position_code')
    if name and code:
        return f'{name} ({code})'
    if name:
        return name
    if code:
        return code
    return '—'
```

**Critical:** Every player query must include `position_code` and `position_name` via JOIN to `positions` table. Example:
```sql
SELECT p.id, p.full_name, p.full_name_ar, p.national_id, p.dob, p.nationality,
       p.foot, p.height_cm, p.weight_kg, p.current_club, p.is_active,
       p.primary_position_id, pos.code AS position_code, pos.name AS position_name,
       pg.code AS position_group_code, pg.name_en AS position_group_name
FROM players p
LEFT JOIN positions pos ON pos.id = p.primary_position_id
LEFT JOIN position_groups pg ON pg.id = pos.position_group_id
WHERE p.id = %s
```

### `app/players/photos.py` — photo upload + Pillow center-crop

```python
import os
from io import BytesIO
from PIL import Image
from werkzeug.utils import secure_filename

ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png'}
TARGET_SIZE = (400, 400)
JPEG_QUALITY = 85

def is_allowed(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_player_photo(file_storage, player_id, upload_dir):
    """Center-crop to 400x400 JPEG, save as <player_id>.jpg.
    Returns the saved filename or raises ValueError on bad input."""
    if not file_storage or not file_storage.filename:
        raise ValueError('No file provided')
    if not is_allowed(file_storage.filename):
        raise ValueError(f'Invalid file type. Allowed: {", ".join(ALLOWED_EXTENSIONS)}')

    img = Image.open(file_storage.stream)
    img = img.convert('RGB')

    # Center-crop square
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top  = (h - side) // 2
    img = img.crop((left, top, left + side, top + side))

    # Resize to 400x400
    img = img.resize(TARGET_SIZE, Image.LANCZOS)

    os.makedirs(upload_dir, exist_ok=True)
    filename = f'{player_id}.jpg'
    path = os.path.join(upload_dir, filename)
    img.save(path, 'JPEG', quality=JPEG_QUALITY, optimize=True)
    return filename
```

Add `Pillow==10.4.0` (or current stable) to `requirements.txt`. Cowork must run `pip install -r requirements.txt` after editing.

### `app/players/__init__.py` — Blueprint with routes

Routes (all decorated, see RBAC table below):

| Method | Path | Decorator | Purpose |
|---|---|---|---|
| GET | `/players/` | `@any_authenticated` | List with search bar |
| GET | `/players/search` | `@any_authenticated` | HTMX endpoint — partial HTML rows for live search |
| GET | `/players/new` | `@scout_or_above` | Create form |
| POST | `/players/new` | `@scout_or_above` | Insert player + optional photo |
| GET | `/players/<int:id>` | `@any_authenticated` | Profile page |
| GET | `/players/<int:id>/edit` | `@scout_or_above` | Edit form |
| POST | `/players/<int:id>/edit` | `@scout_or_above` | Update player + optional new photo |
| POST | `/players/<int:id>/deactivate` | `@admin_or_td_required` | Soft-delete (`is_active=false`) |
| POST | `/players/<int:id>/reactivate` | `@admin_or_td_required` | Restore |

### `templates/players/list.html` — search + cards

Mobile-first card grid, NOT a dense table. Each card:
- Photo (square, ~100px, with `onerror` to placeholder)
- Full name (EN + AR if present)
- Position badge using `get_player_pos()` and `position_group_code` for color
- Current club + DOB year
- Click → profile

Search input at top with HTMX:
```html
<input type="search"
       name="q"
       placeholder="Search by name, CPR, or club…"
       hx-get="{{ url_for('players.search') }}"
       hx-trigger="keyup changed delay:200ms"
       hx-target="#player-results"
       hx-indicator="#search-spinner"
       class="...">
<div id="search-spinner" class="htmx-indicator">Searching…</div>
<div id="player-results">
  {% include 'players/_results.html' %}
</div>
```

The `players/_results.html` partial is what `/players/search` returns — just the inner card grid HTML, no full page wrapper.

### `templates/players/profile.html` — skeleton

Layout (top to bottom):
1. Hero: photo + name (EN/AR) + position badge + key bio (DOB age, height, weight, foot, club)
2. Edit / Deactivate buttons (role-gated via `{% if current_user.has_role('admin','technical_director','scout') %}`)
3. **Placeholder section**: "Wyscout statistics" — `<div>No Wyscout data uploaded yet.</div>` (Phase 4 fills)
4. **Placeholder section**: "Evaluations" — `<div>No evaluations yet.</div>` (Phase 5 fills)
5. **Placeholder section**: "Player Passport report" — disabled button (Phase 6 enables)

Use the helpers everywhere photo or position is shown:
```html
<img src="{{ get_player_photo(player.id, player.national_id) }}"
     alt="{{ player.full_name }}"
     onerror="this.onerror=null;this.src='/static/img/player_placeholder.png'"
     class="w-32 h-32 rounded-full object-cover">

<span class="px-2 py-1 rounded text-sm" data-position-group="{{ player.position_group_code }}">
  {{ get_player_pos(player) }}
</span>
```

Register `get_player_photo` and `get_player_pos` as Jinja globals in `app/__init__.py` so templates can call them without explicit import:

```python
from .players.helpers import get_player_photo, get_player_pos
app.jinja_env.globals.update(
    get_player_photo=get_player_photo,
    get_player_pos=get_player_pos,
)
```

### `templates/players/new.html` — create form

Fields:
- Full name EN (required)
- Full name AR (optional)
- National ID / CPR (optional, but if present must be 9 digits — regex `^\d{9}$` — TEXT to preserve leading zeros)
- DOB (date picker)
- Nationality (text input)
- Primary position (`<select>` grouped by position_groups using `<optgroup>`):
  ```html
  <select name="primary_position_id">
    <option value="">— Select position —</option>
    {% for group in position_groups %}
      <optgroup label="{{ group.name_en }} ({{ group.code }})">
        {% for pos in group.positions %}
          <option value="{{ pos.id }}">{{ pos.name }} ({{ pos.code }})</option>
        {% endfor %}
      </optgroup>
    {% endfor %}
  </select>
  ```
- Foot (radio: left / right / both)
- Height (cm), Weight (kg) — number inputs
- Current club
- Photo upload (`<input type="file" name="photo" accept="image/*">`)

Server-side validation:
- Reject if national_id present but doesn't match `^\d{9}$`
- Reject duplicate national_id (UNIQUE constraint will throw — catch and show user-friendly error)
- DOB must be in the past, and player must be 14+ years old (sanity)

### Standing requirements — DO NOT VIOLATE

Carried over from BFA-Analytics learnings:

1. ✅ Every query that returns player data MUST include: `id`, `national_id`, `primary_position_id`, plus the JOIN-derived `position_code` and `position_name`
2. ✅ Every photo `<img>` MUST use `get_player_photo()` AND `onerror="...placeholder.png"`
3. ✅ Every position display MUST use `get_player_pos()` — **NEVER** hardcode `'MID'` or any default
4. ✅ All SQL parameterized via `%s` — NEVER f-string SQL
5. ✅ Use `RealDictCursor` everywhere
6. ✅ Soft-delete only (`is_active = false`) — NEVER `DELETE FROM players`
7. ✅ Photo files: `<player_id>.jpg`, saved to `app/static/uploads/players/`
8. ✅ All routes use existing decorators from `app/auth/decorators.py` — NEVER inline role checks

## Branding (already established in style.css)

| Token | Value |
|---|---|
| Primary | `#C8102E` (BFA Red) |
| Accent | `#B5924C` (BFA Gold) |
| Font | Cairo (already loaded) |

Position-group badge colors (add to style.css):
```css
[data-position-group="GK"] { background: #6B7280; color: white; }
[data-position-group="CB"] { background: #1E40AF; color: white; }
[data-position-group="FB"] { background: #2563EB; color: white; }
[data-position-group="DM"] { background: #7C3AED; color: white; }
[data-position-group="CM"] { background: #9333EA; color: white; }
[data-position-group="AM"] { background: #DB2777; color: white; }
[data-position-group="W"]  { background: #EA580C; color: white; }
[data-position-group="ST"] { background: #DC2626; color: white; }
```

## Acceptance criteria

After all code changes, restart Flask (Ctrl+C + restart — NOT test_client) and verify:

1. ✅ `pip install -r requirements.txt` completes without error (Pillow new)
2. ✅ Logged in as admin, GET `/players/` returns 200 with empty-state message
3. ✅ POST `/players/new` with full form creates a player, redirects to profile
4. ✅ Profile page shows photo (or placeholder), name, position via `get_player_pos()`
5. ✅ Edit form pre-fills correctly, POST updates DB
6. ✅ HTMX search: typing in the search box updates results without full page reload (verify in browser DevTools network tab)
7. ✅ Photo upload: image is center-cropped to 400×400 JPEG (check file size + dimensions in `app/static/uploads/players/`)
8. ✅ Logged in as scout, can create + edit players. Cannot deactivate (returns 403)
9. ✅ Logged in as scout, deactivate button is hidden in templates
10. ✅ Soft-delete: `is_active = false` after deactivate, player vanishes from default list, reappears with "Show inactive" filter
11. ✅ Position dropdown shows all 26 Wyscout codes grouped under 8 position_groups
12. ✅ National ID validation: `^\d{9}$` enforced server-side, friendly error on duplicate
13. ✅ All `<img>` tags have `onerror` placeholder
14. ✅ No occurrence of hardcoded `'MID'` or position string fallback anywhere in the codebase

## Hard rules

- ❌ Do NOT modify auth code, schema.sql, or any file outside `app/players/`, `app/templates/players/`, `app/static/`, `app/__init__.py` (Jinja globals only), and `requirements.txt`
- ❌ Do NOT use `flask.test_client()` for verification — restart real Flask + curl/browser
- ❌ Do NOT hardcode positions or fall back to `'MID'`
- ❌ Do NOT delete players — soft-delete only
- ❌ Do NOT touch `D:\BFA-Analytics` or `D:\BFA-Analytics-AWS`
- ❌ Do NOT initialize git or commit — Ali commits from PowerShell after the session
- ✅ All player templates and routes use `get_player_photo()` and `get_player_pos()`
- ✅ All SQL parameterized
- ✅ Test with at least 3 sample players before declaring done

## Test data

Have Cowork seed 3 sample players via `/players/new` form during verification (not via SQL — exercise the real flow):

| Full Name | National ID | DOB | Position | Club |
|---|---|---|---|---|
| Sayed Mohammed | 050111111 | 2005-03-12 | LCMF (CM group) | Riffa SC |
| Ali Hassan | 060222222 | 2006-07-04 | CB | Manama Club |
| Ahmed Khaled | 070333333 | 2007-11-22 | LWF (W group) | Muharraq Club |

After all 3 created, verify:
- They appear in `/players/`
- Search "Hassan" filters to just Ali Hassan via HTMX
- Each profile loads with correct position display

## Stale-Flask-process protocol (REMEMBER)

After ANY code change:
```powershell
# In Flask terminal: Ctrl+C
flask --app wsgi run --debug
# In second terminal:
curl http://localhost:5000/players/
```

Do NOT use `flask.test_client()` for verification.

## Session discipline

- Target: 8–10 messages
- Run `pip install -r requirements.txt` once after adding Pillow
- After every code change → restart Flask → verify via curl OR browser
- End with full acceptance checklist printed (✅/❌ each)
- Append to `CHANGELOG.md` as `v0.3.0 — Players module`
- Update `PROJECT.md` to mark Phase 3 complete, point at Phase 4
- After session, Ali commits from PowerShell:
  ```powershell
  cd D:\BFA-Scout
  git add -A
  git commit -m "Phase 3: Players module — CRUD, photo upload, HTMX search"
  ```
