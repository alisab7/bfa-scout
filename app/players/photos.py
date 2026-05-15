from io import BytesIO
from PIL import Image

from app import storage

PHOTO_SIZE = (400, 400)
PHOTO_QUALITY = 85


def save_player_photo(player_id, file_obj):
    """
    Center-crop file_obj to 400x400, re-encode as JPEG, and persist via
    the storage backend (DO Spaces in production, local filesystem in
    dev — chosen by app/storage.py:_use_spaces()).

    Args:
        player_id: integer player ID (used as the object/file name)
        file_obj:  werkzeug FileStorage object from request.files

    Returns:
        True on success, raises on error.

    Hard rules (unchanged from pre-Phase-8):
    - Never store the raw upload — always re-encode through Pillow.
    - Always center-crop (not distort) to exactly 400x400.

    Phase 8: the only change is the *destination*. Pillow processing
    happens here exactly as before; the resulting JPEG bytes go to
    storage.put_player_photo() instead of straight to local disk. Prod
    therefore never touches the local filesystem for photos (hard
    rule) and the bytes are still guaranteed Pillow-re-encoded.
    """
    img = Image.open(file_obj)

    # Convert to RGB so we can save as JPEG (strips alpha if present)
    if img.mode in ('RGBA', 'P', 'LA'):
        img = img.convert('RGB')
    elif img.mode != 'RGB':
        img = img.convert('RGB')

    # Center-crop to square
    w, h = img.size
    side = min(w, h)
    left   = (w - side) // 2
    top    = (h - side) // 2
    right  = left + side
    bottom = top  + side
    img = img.crop((left, top, right, bottom))

    # Resize to 400x400
    img = img.resize(PHOTO_SIZE, Image.LANCZOS)

    # Re-encode to an in-memory JPEG, then hand the bytes to storage.
    buf = BytesIO()
    img.save(buf, format='JPEG', quality=PHOTO_QUALITY, optimize=True)
    storage.put_player_photo(player_id, buf.getvalue())

    return True


def delete_player_photo(player_id):
    """Remove player photo via the storage backend. Never raises
    (best-effort cleanup — matches the pre-Phase-8 contract)."""
    storage.delete_player_photo(player_id)
