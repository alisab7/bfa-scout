"""
Phase 8 — pluggable player-photo storage.

Two backends, chosen at runtime by presence of the `SPACES_BUCKET`
env var:

  * Production  → DigitalOcean Spaces (S3-compatible, boto3)
  * Dev / local → app/static/photos/<player_id>.jpg on the filesystem

DESIGN NOTE — why this is more than the spec's 2-function module:

The spec's `storage.py` sketch uploaded the raw `file_obj` straight to
Spaces. That would violate the project's own hard rule in
`app/players/photos.py`: *"Never store the raw upload — always
re-encode through Pillow"* (centre-crop to 400×400, strip EXIF/alpha,
re-encode JPEG). So the Pillow pipeline in `photos.py` STAYS the entry
point; it hands the already-processed JPEG bytes to
`put_player_photo()` here. This module never sees a raw upload.

Three operations, each backend-aware:
  put_player_photo(player_id, jpeg_bytes)   — write processed JPEG
  get_player_photo_url(player_id)           — URL for <img src> / templates
  read_player_photo_bytes(player_id)        — raw JPEG bytes (passport
                                              PDF embeds these as a
                                              base64 data-URI so the
                                              PDF stays self-contained;
                                              WeasyPrint network fetch
                                              is flaky — Phase 6 call)
  delete_player_photo(player_id)            — remove (never raises)

Filenames are keyed by **player_id** (e.g. `photos/2.jpg`), matching
the convention every existing read site already uses
(profile/list/grid/compare/passport/wyscout). The spec proposed
`national_id or player_id` keying; adopting it would have silently
broken ~6 read sites that look up `<player_id>.jpg`. Kept player_id.

boto3 is imported lazily so dev machines without it (and the test
suite) can import this module freely; only the Spaces code path needs
it, and prod installs it via requirements.txt.
"""
from __future__ import annotations

import os
from io import BytesIO


def _use_spaces() -> bool:
    """Spaces is active iff a bucket is configured. Evaluated per-call
    (not module-level) so tests can monkeypatch the environment."""
    return bool(os.environ.get('SPACES_BUCKET'))


def _local_photo_path(player_id: int) -> str:
    """Filesystem path for local/dev mode. Mirrors the legacy layout
    in app/players/photos.py so a dev DB created before Phase 8 keeps
    working with zero migration."""
    # app/ is the package root; static/photos lives under it.
    app_root = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(app_root, 'static', 'photos', f'{player_id}.jpg')


def _spaces_key(player_id: int) -> str:
    return f"photos/{player_id}.jpg"


def _s3_client():
    """Lazily build a boto3 S3 client pointed at Spaces. Region +
    endpoint both come from env (the spec sketch hard-coded 'nyc3' in
    the client but read SPACES_REGION in the URL builder — those would
    drift; here both read the same env var)."""
    import boto3  # lazy — only prod needs it
    return boto3.client(
        's3',
        region_name=os.environ['SPACES_REGION'],
        endpoint_url=os.environ['SPACES_ENDPOINT'],
        aws_access_key_id=os.environ['SPACES_KEY'],
        aws_secret_access_key=os.environ['SPACES_SECRET'],
    )


def _spaces_cdn_url(player_id: int) -> str:
    bucket = os.environ['SPACES_BUCKET']
    region = os.environ['SPACES_REGION']
    return (f"https://{bucket}.{region}.cdn.digitaloceanspaces.com/"
            f"{_spaces_key(player_id)}")


# ── Write ───────────────────────────────────────────────────────────

def put_player_photo(player_id: int, jpeg_bytes: bytes) -> str:
    """
    Persist the ALREADY-PROCESSED JPEG (400×400, re-encoded by Pillow
    in app/players/photos.py). Returns the public URL.

    Prod  → Spaces object photos/<id>.jpg, public-read, image/jpeg.
    Dev   → app/static/photos/<id>.jpg.
    """
    if _use_spaces():
        client = _s3_client()
        client.put_object(
            Bucket=os.environ['SPACES_BUCKET'],
            Key=_spaces_key(player_id),
            Body=jpeg_bytes,
            ACL='public-read',
            ContentType='image/jpeg',
            CacheControl='public, max-age=86400',
        )
        return _spaces_cdn_url(player_id)

    path = _local_photo_path(player_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(jpeg_bytes)
    return f"/static/photos/{player_id}.jpg"


# ── Read: URL (templates) ───────────────────────────────────────────

def get_player_photo_url(player_id: int) -> str | None:
    """
    URL for `<img src>`. Returns None when there's no photo so callers
    can fall back to the placeholder (the legacy `get_player_photo`
    contract that every template's `onerror` also backstops).

    Spaces mode: we DON'T do a per-render `head_object` existence probe
    (that's an S3 round-trip on every player card on every list page).
    We return the CDN URL unconditionally and rely on the template's
    existing `onerror="...placeholder.svg"` to handle a 404. Documented
    trade-off: one wasted image request for photoless players vs. an
    S3 HEAD on every render. The legacy local path keeps its existence
    check since `os.path.exists` is essentially free.
    """
    if _use_spaces():
        return _spaces_cdn_url(player_id)
    path = _local_photo_path(player_id)
    return f"/static/photos/{player_id}.jpg" if os.path.exists(path) else None


# ── Read: bytes (passport PDF) ──────────────────────────────────────

def read_player_photo_bytes(player_id: int) -> bytes | None:
    """
    Raw JPEG bytes, or None if the player has no photo. Used by the
    passport renderer to base64-embed the photo so the generated PDF
    is fully self-contained (no network fetch at WeasyPrint render
    time — a deliberate Phase 6 decision; WeasyPrint's URL fetcher is
    unreliable under load).
    """
    if _use_spaces():
        try:
            client = _s3_client()
            resp = client.get_object(
                Bucket=os.environ['SPACES_BUCKET'],
                Key=_spaces_key(player_id),
            )
            return resp['Body'].read()
        except Exception:
            # Missing key, network blip, creds — passport degrades to
            # the placeholder block (the template already guards on
            # `player.photo_data_uri`). Never raise from a read path.
            return None

    path = _local_photo_path(player_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'rb') as f:
            return f.read()
    except OSError:
        return None


# ── Delete ──────────────────────────────────────────────────────────

def delete_player_photo(player_id: int) -> None:
    """Remove the photo. Never raises (matches the legacy
    `delete_player_photo` contract — best-effort cleanup)."""
    if _use_spaces():
        try:
            client = _s3_client()
            client.delete_object(
                Bucket=os.environ['SPACES_BUCKET'],
                Key=_spaces_key(player_id),
            )
        except Exception:
            pass
        return

    try:
        path = _local_photo_path(player_id)
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
