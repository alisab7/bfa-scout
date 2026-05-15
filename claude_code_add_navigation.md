Add navigation links and a logged-in home dashboard. Cowork shipped auth without
updating the nav or home page, so users can only reach pages by typing URLs.

Working folder: D:\BFA-Scout

# Files to modify

1. app/templates/base.html
2. app/templates/index.html

DO NOT touch any other files. This is a UX-only fix.

# Change 1: base.html — add primary nav for authenticated users

In base.html, find the existing top nav. It currently shows BFA wordmark on left
and user name + role badge + (Users link if admin) on right. Add a primary nav
section between them — visible only when authenticated.

Add these links between the BFA wordmark and the user info:

  - Players   → url_for('players.list_players')   [visible to all authenticated]
  - Wyscout   → url_for('wyscout.upload')         [admin and technical_director only]
  - Imports   → url_for('wyscout.list_imports')   [admin and technical_director only]
  - Users     → url_for('admin_users.list_users') [admin only]   (if not already there)

Use Jinja conditionals based on current_user.role:

  {% if current_user.is_authenticated %}
    <a href="{{ url_for('players.list_players') }}" class="...">Players</a>
    {% if current_user.has_role('admin', 'technical_director') %}
      <a href="{{ url_for('wyscout.upload') }}" class="...">Wyscout</a>
      <a href="{{ url_for('wyscout.list_imports') }}" class="...">Imports</a>
    {% endif %}
    {% if current_user.has_role('admin') %}
      <a href="{{ url_for('admin_users.list_users') }}" class="...">Users</a>
    {% endif %}
  {% endif %}

IMPORTANT: Confirm the actual route endpoint names by reading these files first:
  - app/players/__init__.py (look for the bp.route('/') endpoint name)
  - app/wyscout/__init__.py (look for upload and imports endpoint names)
  - app/admin/users.py (look for the user list endpoint name)

The endpoint names may differ from what I guessed above. Use what's actually defined
in the code, not my guesses. If url_for() fails for any of those endpoints, the build
error will be obvious.

Style: hide the nav on small screens behind a hamburger button (Alpine.js toggle is
fine), or just stack the links vertically for now if hamburger is too much. Use
existing Tailwind classes from the rest of base.html for consistency. Keep it simple.

# Change 2: index.html — split into anonymous vs authenticated views

The current index.html shows "BFA Scouting & Evaluation" hero with Sign In / Learn
more buttons. Wrap that in {% if not current_user.is_authenticated %}.

Add an {% else %} branch that renders a logged-in landing page with:

  - Welcome message: "Welcome back, {{ current_user.full_name }}"
  - 3-4 quick-action cards in a responsive grid (mobile = stack, desktop = row):
      a. Players card — title "Players", description "Browse, create, and manage
         player profiles", link to /players/
      b. Wyscout card — admin/TD only — title "Wyscout Import", description
         "Upload xlsx exports", link to /wyscout/upload
      c. Recent activity card — show last 5 audit_log entries (most recent first)
         with action and timestamp. Use {{ get_recent_audit_log() }} if it exists,
         or just write a quick query inline.

Keep styling consistent with the rest of the app — BFA red and gold accents,
dark theme, Cairo font already loaded.

If quick-action card grid feels like overengineering, a simpler version is fine:
just three big buttons linking to /players/, /wyscout/upload (admin/TD), and
/admin/users (admin), with the welcome message above.

# Verify

After the changes, restart Flask and check:

  1. Logged out: home page looks the same as before (Sign In / Learn more)
  2. Logged in as admin: home page shows welcome + Players/Wyscout/Users quick links
  3. Logged in as scout: home page shows welcome + Players link only
     (NO Wyscout, NO Users link)
  4. Top nav on every page shows correct links per role
  5. Click each nav link → arrives at correct page, no 404 or url_for error

# Hard rules

- Do NOT change route logic, only templates
- Do NOT modify auth, players, wyscout, or any blueprint code
- Confirm endpoint names by reading the blueprint files BEFORE writing url_for() calls
- Restart Flask after the change and verify in browser, not test_client()
