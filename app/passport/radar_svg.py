"""
Hand-built 6-axis radar SVG for the Player Passport PDF (Phase 6).

WeasyPrint runs no JavaScript reliably, so Chart.js is unusable here.
This module emits a self-contained SVG string the template embeds via
`{{ wyscout_radar_svg | safe }}`. No external CSS or font dependencies
— colors and font are inlined.

Axes match `app/wyscout/helpers.py:RADAR_AXES` (Scoring/Passing/
Dribbling/Defending/Aerial/Work Rate), so the passport radar is
visually consistent with what users already see on the player
dashboard and comparison page.

Layout:
  - 5 concentric polygons at 20/40/60/80/100 as the grid
  - 6 axis lines from centre to each vertex
  - One filled polygon for the player's normalized scores (BFA red, 30% alpha)
  - Axis labels positioned just outside the outermost ring
  - The 100 ring and labels are slightly darker for readability
"""
import math


# Palette (mirrors the passport CSS variables — don't drift)
BFA_RED   = "#C8102E"
BFA_GOLD  = "#B5924C"
GRID_LINE = "#D9D9D9"
GRID_TEXT = "#666666"
AXIS_TEXT = "#1A1A1A"

# Axis label order — must match RADAR_AXES in app/wyscout/helpers.py.
# Listed here to keep the renderer self-contained (no import cycle risk
# if the data layer is being built up).
DEFAULT_AXIS_ORDER = [
    "Scoring", "Passing", "Dribbling", "Defending", "Aerial", "Work Rate",
]


def render_wyscout_radar_svg(
    scores: dict,
    size: int = 320,
    axis_order: list[str] | None = None,
) -> str:
    """
    `scores`:     dict {axis_label: 0..100}  (output of get_player_radar_scores)
    `size`:       overall SVG width/height in user-units (default 320 as of
                  Phase 6.2 — see history below).
    `axis_order`: optional explicit ordering of axes; defaults to
                  DEFAULT_AXIS_ORDER (Scoring → Work Rate clockwise)

    Returns a complete SVG string (with <svg> root). Self-contained:
    no external fonts, no JS, no CSS dependency.

    Geometry history (axis-label clipping fights):
      - 6.0:  size=280, margin=12%  — labels at θ=±π/6 (Passing,
              Defending) crossed the viewBox edge → clipped.
      - 6.1:  size=360, margin=22%  — labels fit but the radar got too
              wide for any side-by-side layout; got block-stacked alone.
      - 6.2:  size=320, margin=18%  — re-tightened so the radar fits in
              a 45%-width flex column on page 1 while keeping all 6
              axis labels (incl. the multi-word 'Work Rate') readable.
              CSS sizes the SVG to 100% column width; aspect 1:1.
    """
    axes = axis_order or DEFAULT_AXIS_ORDER
    n = len(axes)
    if n < 3:
        # SVG radar with <3 axes is meaningless; render an empty placeholder.
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{size}" height="{size}" viewBox="0 0 {size} {size}">'
            f'<text x="{size//2}" y="{size//2}" text-anchor="middle" '
            f'fill="{GRID_TEXT}" font-size="11">No radar data</text>'
            f'</svg>'
        )

    # Geometry: 18% margin gives axis labels room inside a 320-unit
    # viewBox without pushing the polygon too small.
    margin   = int(size * 0.18)
    cx       = size / 2
    cy       = size / 2
    r_outer  = size / 2 - margin

    # Angle 0 points straight up (12 o'clock); increases clockwise.
    def vertex(value_0_100: float, axis_idx: int) -> tuple[float, float]:
        """Return (x, y) for a point at `value_0_100` along axis `axis_idx`."""
        angle = -math.pi / 2 + (2 * math.pi * axis_idx / n)
        r = r_outer * (value_0_100 / 100.0)
        return (cx + r * math.cos(angle), cy + r * math.sin(angle))

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{size}" height="{size}" viewBox="0 0 {size} {size}" '
        f'font-family="Inter, Arial, sans-serif">'
    ]

    # ── Grid: concentric polygons at 20/40/60/80/100 ────────────────
    ring_levels = [20, 40, 60, 80, 100]
    for level in ring_levels:
        pts = [vertex(level, i) for i in range(n)]
        d = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        # Outer ring slightly darker for emphasis
        stroke = "#A6A6A6" if level == 100 else GRID_LINE
        parts.append(
            f'<polygon points="{d}" fill="none" stroke="{stroke}" '
            f'stroke-width="0.8"/>'
        )

    # ── Axis spokes (centre → outermost vertex) ─────────────────────
    for i in range(n):
        x, y = vertex(100, i)
        parts.append(
            f'<line x1="{cx:.1f}" y1="{cy:.1f}" '
            f'x2="{x:.1f}" y2="{y:.1f}" '
            f'stroke="{GRID_LINE}" stroke-width="0.6"/>'
        )

    # ── Tick labels on one spoke (the rightmost — index 1 for 6-axis) ─
    # Placed slightly to the right of the value point. Skip 0 (centre)
    # and 100 (already implied by the outer ring/labels).
    tick_axis = 1 if n >= 6 else 0
    for level in (20, 40, 60, 80):
        x, y = vertex(level, tick_axis)
        parts.append(
            f'<text x="{x + 4:.1f}" y="{y + 3:.1f}" '
            f'fill="{GRID_TEXT}" font-size="7">{level}</text>'
        )

    # ── Player polygon ──────────────────────────────────────────────
    poly_pts = [vertex(float(scores.get(label) or 0), i)
                for i, label in enumerate(axes)]
    d_poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in poly_pts)
    parts.append(
        f'<polygon points="{d_poly}" '
        f'fill="{BFA_RED}" fill-opacity="0.30" '
        f'stroke="{BFA_RED}" stroke-width="1.4" '
        f'stroke-linejoin="round"/>'
    )
    # Vertex dots
    for x, y in poly_pts:
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.5" '
            f'fill="{BFA_RED}" stroke="#fff" stroke-width="0.8"/>'
        )

    # ── Axis labels just outside the 100 ring ──────────────────────
    label_r = r_outer + 14
    for i, label in enumerate(axes):
        angle = -math.pi / 2 + (2 * math.pi * i / n)
        lx = cx + label_r * math.cos(angle)
        ly = cy + label_r * math.sin(angle)
        # Vertical alignment baseline tweak so labels at top/bottom
        # don't clip the polygon.
        if abs(math.sin(angle)) > 0.9:
            ly += 4 if math.sin(angle) > 0 else -2
        # Horizontal anchor: left/centre/right depending on x position.
        if math.cos(angle) > 0.3:
            anchor = "start"
        elif math.cos(angle) < -0.3:
            anchor = "end"
        else:
            anchor = "middle"

        # Value badge on a second line under the label so the eye gets
        # the polygon + the number without zooming.
        val = float(scores.get(label) or 0)
        parts.append(
            f'<text x="{lx:.1f}" y="{ly:.1f}" '
            f'text-anchor="{anchor}" fill="{AXIS_TEXT}" '
            f'font-size="10" font-weight="600">{label}</text>'
        )
        parts.append(
            f'<text x="{lx:.1f}" y="{ly + 11:.1f}" '
            f'text-anchor="{anchor}" fill="{BFA_RED}" '
            f'font-size="9" font-weight="700">{val:.0f}</text>'
        )

    parts.append('</svg>')
    return "".join(parts)
