# processing_history.py

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Optional
import uuid

DATA_ROOT = Path("data")
USERS_ROOT = DATA_ROOT / "users"


def sanitize_username(username: str) -> str:
    """Make username safe to use as a directory name."""
    if not username:
        return "unknown_user"
    return "".join(
        c if c.isalnum() or c in ("-", "_") else "_"
        for c in str(username)
    ) or "unknown_user"


def get_user_directory(username: str) -> Path:
    user_dir = USERS_ROOT / sanitize_username(username)
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


def get_history_path(username: str) -> Path:
    return get_user_directory(username) / "processing_history.json"


def load_processing_history(username: str) -> list:
    """Load all processing sessions for one user."""
    path = get_history_path(username)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_processing_batch(username: str, expenses: list) -> dict:
    """Store one invoice-processing session."""
    history = load_processing_history(username)
    total_amount = 0.0

    for expense in expenses:
        amount = expense.get("financial_totals", {}).get("grand_total", 0) or 0
        try:
            total_amount += float(amount)
        except (TypeError, ValueError):
            pass

    batch = {
        "batch_id": uuid.uuid4().hex,
        "user_id": username,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "invoice_count": len(expenses),
        "total_amount": round(total_amount, 2),
        "expenses": expenses,
    }

    history.insert(0, batch)
    get_history_path(username).write_text(
        json.dumps(history, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return batch


def get_processing_batch(username: str, batch_id: str) -> Optional[dict]:
    """Get a single processing session."""
    return next(
        (b for b in load_processing_history(username) if b.get("batch_id") == batch_id),
        None,
    )