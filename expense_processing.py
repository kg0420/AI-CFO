import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional
import uuid
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
                modified=False
                for item in data:
                    if not item.get("id"):
                        item["id"]=uuid.uuid4().hex[:12]
                        modified=True
                if modified:
                    with open(expense_path,"w",encoding="utf-8") as wf:
                        json.dump(data,wf,indent=4,ensure_ascii=False)

                return data
            return []
    except (json.JSONDecodeError, OSError):
        return []

def update_user_expense(username: str, expense_id: str, updates: dict) -> bool:
    """Update merchant, date, category, or amount for a specific expense."""
    expenses = load_all_expenses(username)
    target = None

    for exp in expenses:
        if exp.get("id") == expense_id:
            target = exp
            break

    if not target:
        return False

    # Apply updates
    if "merchant" in updates:
        target.setdefault("merchant_info", {})["name"] = updates["merchant"]
        target.setdefault("seller_details", {})["vendor_name"] = updates["merchant"]
    if "date" in updates:
        target.setdefault("merchant_info", {})["date"] = updates["date"]
        target.setdefault("document_metadata", {})["invoice_date"] = updates["date"]
    if "category" in updates:
        target["category"] = updates["category"]
        target.setdefault("document_metadata", {})["expense_category"] = updates["category"]
    if "amount" in updates:
        try:
            amt = float(updates["amount"])
            target.setdefault("financial_totals", {})["grand_total"] = amt
        except (ValueError, TypeError):
            pass

    expense_path = get_user_expense_path(username)
    with open(expense_path, "w", encoding="utf-8") as f:
        json.dump(expenses, f, indent=4, ensure_ascii=False)
    return True

def delete_user_expense(username: str, expense_id: str) -> bool:
    """Remove a specific expense from the user's ledger."""
    expenses = load_all_expenses(username)
    initial_len = len(expenses)
    filtered = [e for e in expenses if e.get("id") != expense_id]

    if len(filtered) == initial_len:
        return False

    expense_path = get_user_expense_path(username)
    with open(expense_path, "w", encoding="utf-8") as f:
        json.dump(filtered, f, indent=4, ensure_ascii=False)
    return True

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

        # de-dupe by unique id or (request_id, source_file)
        seen = {
            e.get("id") or (e.get("request_id"), e.get("source_file"))
            for e in existing_expenses
        }
        for expense in user_expenses:
            if not expense.get("id"):
                expense["id"] = uuid.uuid4().hex[:12]
            key = expense.get("id") or (expense.get("request_id"), expense.get("source_file"))
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
    entry_date = date or datetime.today().strftime("%Y-%m-%d")

    return {
        "id": uuid.uuid4().hex[:12],
        "data_source": "manual_entry",
        "document_metadata": {
            "document_type": "manual_entry",
            "invoice_number": None,
            "invoice_date": entry_date,
            "expense_category": category,
            "currency_code": "INR",
        },
        "seller_details": {
            "vendor_name": merchant,
            "platform_or_marketplace": merchant,
        },
        "merchant_info": {
            "name": merchant,
            "date": entry_date,
        },
        "financial_totals": {
            "grand_total": total,
            "taxable_amount_subtotal": total,
            "total_tax_amount": 0.0,
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
                "total_item_amount": total,
            }
        ],
    }

# ============================================================
# PUBLIC API
# ============================================================
__all__ = [
    "load_all_expenses",
    "save_expenses",
    "update_user_expense",
    "delete_user_expense",
    "format_manual_entry",
    "sanitize_username",
    "get_user_directory",
    "get_user_expense_path",
]