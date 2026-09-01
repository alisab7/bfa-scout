# BFA-Scout production image (Phase 8).
#
# python:3.13-slim + the GTK/Pango/Cairo runtime WeasyPrint needs on
# Linux (the Linux equivalent of the Windows GTK3-Runtime install we
# documented in Phase 6). Noto fonts cover Latin + Arabic (Cairo-style
# shaping) + colour emoji so passport PDFs render the same as dev.
FROM python:3.13-slim

# WeasyPrint native deps + Arabic/emoji fonts + curl (HEALTHCHECK uses it).
# `shared-mime-info` lets WeasyPrint sniff embedded image types.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libcairo2 \
        libgdk-pixbuf-2.0-0 libffi-dev shared-mime-info \
        fonts-noto fonts-noto-core fonts-noto-color-emoji \
        fonts-liberation \
        libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first for layer caching. boto3 + gunicorn are in
# requirements.txt (Phase 8), so no separate pip line is needed —
# keeping a single source of truth for dependency versions.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application.
COPY . .

# Run as a non-root user (uid 1000 so droplet-side bind mounts, if any,
# map cleanly).
RUN useradd -m -u 1000 bfa && chown -R bfa:bfa /app
USER bfa

# Git SHA of the commit this image was built from. Declared LAST (after
# the expensive COPY/chown layers) so changing it only invalidates this
# cheap ENV layer, never the pip install. Defaults to "unknown" so a
# plain `docker build` with no --build-arg still produces a working
# image whose /healthz passes — ship.sh always supplies the real value.
ARG GIT_SHA=unknown
ENV GIT_SHA=${GIT_SHA}

EXPOSE 5000

# Container-level healthcheck. Compose ALSO declares one; both point at
# the same /healthz (app up + DB reachable). start-period covers the
# pool warm-up + first DB connect.
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:5000/healthz || exit 1

CMD ["gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"]
