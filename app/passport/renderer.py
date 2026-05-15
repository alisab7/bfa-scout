"""
WeasyPrint orchestration for Phase 6.

Single public function `render_passport_pdf(data)` — takes the dict
returned by `get_passport_data()`, renders the HTML template, and
returns PDF bytes.

GTK runtime requirement: documented in CHANGELOG v0.6.0 — WeasyPrint
68.x requires Pango/GLib/cairo native libraries (the GTK3 runtime on
Windows). Without GTK installed, `import weasyprint` raises at module
load time before this file is touched.

Phase 6.1: timing instrumentation. PDF generation takes ~5–10s on
Windows because WeasyPrint goes through GTK's Pango for layout
(roughly 80% of wall time). Logging template and WeasyPrint phases
separately lets us spot regressions: if `template` ever climbs
above ~100ms it's an N+1 query in the data layer; if `weasyprint`
grows it's content (more rows, more SVG, etc.). Latency expectation
is documented in CHANGELOG v0.6.1.
"""
import os
import time
from pathlib import Path

from flask import render_template, current_app
from weasyprint import HTML, CSS


# CSS file path is resolved once at import time — the file ships with
# the templates/passport directory so deployment is one tree to copy.
_CSS_PATH = (
    Path(__file__).resolve().parent.parent
    / "templates" / "passport" / "_passport.css"
)


def render_passport_pdf(data: dict) -> bytes:
    """
    Compose `passport/passport.html` with `data`, then render to PDF
    bytes via WeasyPrint.

    `base_url` is set to the Flask static-files root so the rare case
    of an inline image reference resolves. The player photo is embedded
    as a data URI so this is belt-and-braces only.

    Phase 6.1: per-phase timing logged at INFO. Typical breakdown on
    this Windows dev box: template ~30-80ms, weasyprint ~6-9s.
    """
    t0 = time.perf_counter()
    html_str = render_template('passport/passport.html', **data)
    t1 = time.perf_counter()

    base_url = current_app.root_path  # local FS root for any relative refs

    pdf_bytes = HTML(string=html_str, base_url=base_url).write_pdf(
        stylesheets=[CSS(filename=str(_CSS_PATH))]
    )
    t2 = time.perf_counter()

    # Log at WARNING so operators see PDF render latency in the default
    # Flask log without needing to bump the level. Each render is also
    # an audit_log row (in the route), so this isn't double-logging the
    # event itself — just surfacing the timing.
    current_app.logger.warning(
        "passport PDF render: template=%.3fs  weasyprint=%.3fs  total=%.3fs  bytes=%d",
        t1 - t0, t2 - t1, t2 - t0, len(pdf_bytes),
    )
    return pdf_bytes
