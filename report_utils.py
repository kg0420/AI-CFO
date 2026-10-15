from fastapi import Request
from fastapi.templating import Jinja2Templates

from graph_plotting import generate_graphs

templates = Jinja2Templates(directory="templates")

def render_report_response(request: Request, expenses: list, current_batch: list = None):
    """
    Render the financial report for the user's ledger expenses.
    Historical graphs and spend totals remain consistent, while current batch
    metrics highlight the latest upload when present.
    """
    all_expenses = expenses or []
    combined_line_items = []
    total_spent = 0.0

    for data in all_expenses:
        expense_id = data.get("id") or ""
        merchant = (
            data.get("merchant_info", {}).get("name")
            or data.get("seller_details", {}).get("vendor_name")
            or data.get("seller_details", {}).get("platform_or_marketplace")
            or "Unknown Vendor"
        )
        date = (
            data.get("merchant_info", {}).get("date")
            or data.get("document_metadata", {}).get("invoice_date")
            or "-"
        )
        category = (
            data.get("category")
            or data.get("document_metadata", {}).get("expense_category")
            or "General"
        )
        financial_totals = data.get("financial_totals", {})
        grand_total = financial_totals.get("grand_total")

        if grand_total is None:
            line_items = data.get("line_items", [])
            grand_total = sum(
                (item.get("total_item_amount") or item.get("price") or 0.0) for item in line_items
            )

        try:
            amount = float(grand_total or 0.0)
        except (ValueError, TypeError):
            amount = 0.0

        total_spent += amount

        combined_line_items.append({
            "id": expense_id,
            "merchant": merchant,
            "date": str(date),
            "category": str(category),
            "description": merchant,
            "item_description": merchant,
            "item_name": merchant,
            "name": merchant,
            "amount": amount,
            "price": amount,
            "quantity": 1,
        })

    # ========================================================
    # METRICS (CURRENT BATCH OR FULL LEDGER)
    # ========================================================
    metrics_source = current_batch if current_batch is not None else all_expenses
    ocr_count = sum(1 for exp in metrics_source if exp.get("data_source") == "ai_ocr")
    manual_count = sum(1 for exp in metrics_source if exp.get("data_source") == "manual_entry")
    automation_rate = (ocr_count / len(metrics_source) * 100) if metrics_source else 0.0

    # ========================================================
    # GRAPHS — FULL LEDGER VISUALIZATIONS
    # ========================================================
    graphs = generate_graphs(all_expenses)

    # ========================================================
    # RENDER REPORT
    # ========================================================
    return templates.TemplateResponse(
        request=request,
        name="report.html",
        context={
            "raw_data": current_batch if current_batch is not None else all_expenses,
            "expenses": combined_line_items,
            "total_spent": total_spent,
            "metrics": {
                "total_entries": len(metrics_source),
                "ai_processed": ocr_count,
                "human_manual": manual_count,
            },
            "graph_donut": graphs.get("graph_donut"),
            "graph_vendor": graphs.get("graph_vendor"),
            "graph_timeline": graphs.get("graph_timeline"),
            "graph_tax": graphs.get("graph_tax"),
            "graph_treemap": graphs.get("graph_treemap"),
            "graph_source": graphs.get("graph_source"),
            "suggestions": [
                f"Total recorded spend: ₹{total_spent:.2f}",
                f"Automation Rate: {automation_rate:.1f}% AI vs {manual_count} Manual Fallbacks.",
            ],
        },
    )