import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

# ============================================================
# STORAGE CONFIGURATION
# ============================================================
DATA_ROOT = Path("data")
USERS_ROOT = DATA_ROOT / "users"

DATA_ROOT.mkdir(parents=True, exist_ok=True)
USERS_ROOT.mkdir(parents=True, exist_ok=True)

# ============================================================
# USER PATH HELPERS
# ============================================================
def sanitize_username(username: str) -> str:
    """Convert username into a filesystem-safe directory name."""
    if not username:
        return "unknown_user"
    
    safe_username = re.sub(r"[^a-zA-Z0-9_-]", "_", str(username))
    return safe_username or "unknown_user"

def get_user_directory(username: str) -> Path:
    """Return the permanent storage directory for a user."""
    safe_username = sanitize_username(username)
    user_directory = USERS_ROOT / safe_username
    user_directory.mkdir(parents=True, exist_ok=True)
    return user_directory

def get_user_expense_path(username: str) -> Path:
    """Return the permanent expense JSON file belonging to a specific user."""
    return get_user_directory(username) / "expenses.json"

# ============================================================
# LOAD USER EXPENSES
# ============================================================
def load_all_expenses(username: str) -> list:
    """Load ONLY the expenses belonging to the specified user."""
    expense_path = get_user_expense_path(username)
    if not expense_path.exists():
        return []

    try:
        with open(expense_path, "r", encoding="utf-8") as file:
            data = json.load(file)
            if isinstance(data, list):
                return data
            return []
    except (json.JSONDecodeError, OSError):
        return []

# ============================================================
# SAVE USER EXPENSES
# ============================================================
def save_expenses(new_expenses: list) -> None:
    if not new_expenses:
        return

    expenses_by_user = {}
    for expense in new_expenses:
        if not isinstance(expense, dict):
            continue
        username = expense.get("user_id") or expense.get("user")
        if not username:
            print("⚠️ Expense skipped: No user identifier.")
            continue
        expenses_by_user.setdefault(str(username), []).append(expense)

    for username, user_expenses in expenses_by_user.items():
        existing_expenses = load_all_expenses(username)

        # de-dupe by (request_id, source_file) so re-runs don't pile up
        seen = {
            (e.get("request_id"), e.get("source_file"))
            for e in existing_expenses
        }
        for expense in user_expenses:
            key = (expense.get("request_id"), expense.get("source_file"))
            if key in seen:
                continue
            existing_expenses.append(expense)
            seen.add(key)

        expense_path = get_user_expense_path(username)
        with open(expense_path, "w", encoding="utf-8") as file:
            json.dump(existing_expenses, file, indent=4, ensure_ascii=False)

        print(f"💾 Saved {len(user_expenses)} expense(s) for user '{username}'")
        
# ============================================================
# MANUAL EXPENSE
# ============================================================
def format_manual_entry(
    merchant: str,
    date: str,
    total: float,
    category: str,
    description: Optional[str],
) -> dict:
    """Standardize manual input to match the AI OCR output structure."""
    desc = description if description else f"{category} Expense"

    return {
        "data_source": "manual_entry",
        "merchant_info": {
            "name": merchant,
            "date": date or datetime.today().strftime("%Y-%m-%d"),
        },
        "financial_totals": {
            "grand_total": total,
            "tax": 0.0,
        },
        "category": category,
        "line_items": [
            {
                "item_name": desc,
                "description": desc,
                "item_description": desc,
                "price": total,
                "quantity": 1,
            }
        ],
    }

# ============================================================
# PUBLIC API
# ============================================================
__all__ = [
    "load_all_expenses",
    "save_expenses",
    "format_manual_entry",
    "sanitize_username",
    "get_user_directory",
    "get_user_expense_path",
]