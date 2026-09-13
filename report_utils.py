from fastapi import Request
from fastapi.templating import Jinja2Templates

from graph_plotting import generate_graphs

templates = Jinja2Templates(directory="templates")

def render_report_response(request: Request, current_batch: list):
    """
    Render the report for the CURRENT upload only.

    Important:
    `current_batch` contains only the documents processed
    during the current /generate-report request.
    Historical expenses must NOT be loaded here.
    """
    current_expenses = current_batch or []
    combined_line_items = []
    total_spent = 0.0

    for data in current_expenses:
        financial_totals = data.get("financial_totals", {})
        grand_total = financial_totals.get("grand_total")

        if grand_total is None:
            line_items = data.get("line_items", [])
            grand_total = sum(
                (item.get("total_item_amount") or 0.0) for item in line_items
            )

        total_spent += grand_total or 0.0
        line_items = data.get("line_items", [])

        # ====================================================
        # FALLBACK WHEN NO LINE ITEMS EXIST
        # ====================================================
        if not line_items:
            fallback_desc = (
                data.get("merchant_info", {}).get("name")
                or data.get("seller_details", {}).get("vendor_name")
                or data.get("category")
                or "Expense Entry"
            )
            
            amount = financial_totals.get("grand_total", 0.0) or 0.0

            combined_line_items.append({
                "description": fallback_desc,
                "item_description": fallback_desc,
                "item_name": fallback_desc,
                "name": fallback_desc,
                "amount": float(amount),
                "price": float(amount),
                "quantity": 1,
            })
            continue

        # ====================================================
        # PROCESS LINE ITEMS
        # ====================================================
        for item in line_items:
            if not isinstance(item, dict):
                continue

            item_desc = (
                item.get("item_description")
                or item.get("description")
                or item.get("item_name")
                or item.get("name")
                or item.get("item")
                or item.get("product_name")
                or item.get("particulars")
                or data.get("seller_details", {}).get("vendor_name")
                or "General Item"
            )

            raw_amount = (
                item.get("total_item_amount") if item.get("total_item_amount") is not None
                else item.get("price") if item.get("price") is not None
                else item.get("unit_price") if item.get("unit_price") is not None
                else item.get("amount") if item.get("amount") is not None
                else 0.0
            )

            try:
                amount = float(raw_amount or 0.0)
            except (TypeError, ValueError):
                amount = 0.0

            combined_line_items.append({
                "description": item_desc,
                "item_description": item_desc,
                "item_name": item_desc,
                "name": item_desc,
                "amount": amount,
                "price": amount,
                "quantity": item.get("quantity") or 1,
            })

    # ========================================================
    # CURRENT BATCH METRICS
    # ========================================================
    ocr_count = sum(1 for exp in current_expenses if exp.get("data_source") == "ai_ocr")
    manual_count = sum(1 for exp in current_expenses if exp.get("data_source") == "manual_entry")
    automation_rate = (ocr_count / len(current_expenses) * 100) if current_expenses else 0.0

    # ========================================================
    # GRAPHS — CURRENT UPLOAD ONLY
    # ========================================================
    graphs = generate_graphs(current_expenses)

    # ========================================================
    # RENDER REPORT
    # ========================================================
    return templates.TemplateResponse(
        request=request,
        name="report.html",
        context={
            "raw_data": current_batch,
            "expenses": combined_line_items,
            "total_spent": total_spent,
            "metrics": {
                "total_entries": len(current_expenses),
                "ai_processed": ocr_count,
                "human_manual": manual_count,
            },
            "graph_donut": graphs.get("graph_donut"),
            "graph_vendor": graphs.get("graph_vendor"),
            "graph_timeline": graphs.get("graph_timeline"),
            "graph_cumulative": graphs.get("graph_cumulative"),
            "graph_tax": graphs.get("graph_tax"),
            "graph_gst": graphs.get("graph_gst"),
            "graph_payment_status": graphs.get("graph_payment_status"),
            "graph_payment_method": graphs.get("graph_payment_method"),
            "graph_treemap": graphs.get("graph_treemap"),
            "graph_line_items": graphs.get("graph_line_items"),
            "graph_source": graphs.get("graph_source"),
            "suggestions": [
                f"Total recorded spend: ₹{total_spent:.2f}",
                f"Automation Rate: {automation_rate:.1f}% AI vs {manual_count} Manual Fallbacks.",
            ],
            **graphs,
        },
    )