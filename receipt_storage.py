"""Permanent per-user receipt storage."""

from datetime import datetime, timezone
import hashlib
import json
import mimetypes
from pathlib import Path
import re
from typing import Optional
import uuid

# Storage Configuration
DATA_ROOT = Path("data")
USERS_ROOT = DATA_ROOT / "users"
USERS_ROOT.mkdir(parents=True, exist_ok=True)

# Allowed File Types
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/bmp",
}


# User Directory Helpers
def sanitize_username(username: str) -> str:
    """Convert username into a safe directory name."""
    if not username:
        return "unknown_user"
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", str(username))
    return safe or "unknown_user"


def get_user_directory(username: str) -> Path:
    """Get/create the directory belonging to a user."""
    directory = USERS_ROOT / sanitize_username(username)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def get_receipts_directory(username: str) -> Path:
    """Get/create the permanent receipt directory."""
    directory = get_user_directory(username) / "receipts"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def get_receipts_index_path(username: str) -> Path:
    """Path of the receipt metadata JSON file."""
    return get_user_directory(username) / "receipts.json"


# Index Helpers
def _load_index(username: str) -> list:
    """Load receipt metadata."""
    path = get_receipts_index_path(username)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _save_index(username: str, records: list) -> None:
    path = get_receipts_index_path(username)
    path.write_text(
        json.dumps(records, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# Hashing
def _sha256(path: Path) -> str:
    """Calculate SHA-256 hash of a receipt to prevent duplicate uploads."""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


# Public API
def save_receipt(
    username: str,
    source_path: str,
    original_filename: str,
    request_id: Optional[str] = None,
) -> dict:
    """Permanently save an uploaded receipt and return its metadata."""
    source = Path(source_path)
    if not source.exists():
        raise FileNotFoundError("Receipt file does not exist.")

    ext = Path(original_filename or source.name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError("Unsupported receipt image type.")

    file_hash = _sha256(source)
    records = _load_index(username)

    # Check for duplicate
    for record in records:
        if record.get("sha256") == file_hash:
            if request_id:
                record["last_request_id"] = request_id
                _save_index(username, records)
            return record

    receipt_id = uuid.uuid4().hex[:16]
    destination = get_receipts_directory(username) / f"{receipt_id}{ext}"
    destination.write_bytes(source.read_bytes())

    record = {
        "receipt_id": receipt_id,
        "original_filename": Path(original_filename or source.name).name,
        "stored_filename": destination.name,
        "relative_path": destination.relative_to(get_user_directory(username)).as_posix(),
        "sha256": file_hash,
        "mime_type": mimetypes.guess_type(destination.name)[0] or "application/octet-stream",
        "size_bytes": destination.stat().st_size,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "request_id": request_id,
        "user_id": str(username),
    }

    records.insert(0, record)
    _save_index(username, records)
    return record


def list_receipts(username: str) -> list:
    """List all receipts, pruning records whose files no longer exist."""
    records = _load_index(username)
    valid_records, changed = [], False

    for record in records:
        path = get_user_directory(username) / record.get("relative_path", "")
        if path.is_file():
            valid_records.append(record)
        else:
            changed = True

    if changed:
        _save_index(username, valid_records)

    return valid_records


def get_receipt(username: str, receipt_id: str) -> Optional[dict]:
    """Retrieve metadata for a single receipt."""
    return next((r for r in list_receipts(username) if r.get("receipt_id") == receipt_id), None)


def get_receipt_path(username: str, receipt_id: str) -> Optional[Path]:
    """Retrieve the physical file Path for a receipt."""
    record = get_receipt(username, receipt_id)
    if not record:
        return None
    path = get_user_directory(username) / record["relative_path"]
    return path if path.is_file() else None


def delete_receipt(username: str, receipt_id: str) -> bool:
    """Delete a receipt file and its associated index record."""
    records = _load_index(username)
    target = next((r for r in records if r.get("receipt_id") == receipt_id), None)

    if not target:
        return False

    path = get_user_directory(username) / target.get("relative_path", "")
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        return False

    _save_index(username, [r for r in records if r.get("receipt_id") != receipt_id])
    return True


__all__ = [
    "ALLOWED_MIME_TYPES",
    "save_receipt",
    "list_receipts",
    "get_receipt",
    "get_receipt_path",
    "delete_receipt",
]