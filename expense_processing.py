import os
import json
from datetime import datetime
from typing import Optional


EXPENSE_DB_PATH = "data/expenses.json"

def load_all_expenses() -> list:
    """Helper to read persistent expenses from JSON database."""
    if os.path.exists(EXPENSE_DB_PATH):
        try:
            with open(EXPENSE_DB_PATH, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return []
    return []

def save_expenses(new_expenses: list):
    """Helper to append new expenses to persistent JSON database."""
    existing = load_all_expenses()
    existing.extend(new_expenses)
    with open(EXPENSE_DB_PATH, "w") as f:
        json.dump(existing, f, indent=4)

def format_manual_entry(merchant: str, date: str, total: float, category: str, description: Optional[str]) -> dict:
    """Standardizes manual inputs to match the AI OCR output schema."""
    desc = description if description else f"{category} Expense"
    return {
        "data_source": "manual_entry",
        "merchant_info": {
            "name": merchant,
            "date": date or datetime.today().strftime("%Y-%m-%d")
        },
        "financial_totals": {
            "grand_total": total,
            "tax": 0.0
        },
        "category": category,
        "line_items": [
            {
                "item_name": desc,
                "description": desc,
                "item_description": desc,
                "price": total,
                "quantity": 1
            }
        ]
    }

