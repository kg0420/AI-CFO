from expense_processing import load_all_expenses    
from fastapi import Request
from graph_plotting import generate_graphs
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")

def render_report_response(request: Request, current_batch: list):
    """Helper to calculate totals, metrics, ledger items, and graphs."""
    all_stored_expenses = load_all_expenses()
    
    combined_line_items = []
    total_spent = 0.0
    
    for data in all_stored_expenses:
        total_spent += data.get("financial_totals", {}).get("grand_total", 0) or 0
        
        line_items = data.get("line_items", [])
        
        # If line_items is empty, create a fallback entry using merchant / category description
        if not line_items:
            fallback_desc = (
                data.get("merchant_info", {}).get("name") or 
                data.get("category") or 
                "Expense Entry"
            )
            amount = data.get("financial_totals", {}).get("grand_total", 0.0)
            combined_line_items.append({
                "description": fallback_desc,
                "item_description": fallback_desc,
                "item_name": fallback_desc,
                "name": fallback_desc,
                "amount": float(amount) if amount else 0.0,
                "price": float(amount) if amount else 0.0,
                "quantity": 1
            })
        else:
            for item in line_items:
                if isinstance(item, dict):
                    # Check ALL possible item description key aliases
                    item_desc = (
                        item.get("item_description") or 
                        item.get("description") or 
                        item.get("item_name") or 
                        item.get("name") or 
                        item.get("item") or 
                        item.get("product_name") or 
                        item.get("particulars") or 
                        data.get("merchant_info", {}).get("name") or
                        "General Item"
                    )
                    
                    raw_amount = (
                        item.get("total_item_amount") or 
                        item.get("price") or 
                        item.get("unit_price") or 
                        item.get("amount") or 
                        0.0
                    )
                    
                    # Store all possible key variations so Jinja template renders correctly
                    combined_line_items.append({
                        "description": item_desc,
                        "item_description": item_desc,
                        "item_name": item_desc,
                        "name": item_desc,
                        "amount": float(raw_amount) if raw_amount else 0.0,
                        "price": float(raw_amount) if raw_amount else 0.0,
                        "quantity": item.get("quantity") or 1
                    })
            
    ocr_count = sum(1 for e in all_stored_expenses if e.get("data_source") == "ai_ocr")
    manual_count = sum(1 for e in all_stored_expenses if e.get("data_source") == "manual_entry")

    # Generate all graphs
    graphs = generate_graphs(all_stored_expenses)

    return templates.TemplateResponse(
        request=request, 
        name="report.html", 
        context={
            "raw_data": current_batch,
            "expenses": combined_line_items,
            "total_spent": total_spent,
            "metrics": {
                "total_entries": len(all_stored_expenses),
                "ai_processed": ocr_count,
                "human_manual": manual_count
            },
            # --- PASS ALL 6 GRAPHS TO HTML ---
            "graph_donut": graphs["graph_donut"],
            "graph_vendor": graphs["graph_vendor"],
            "graph_timeline": graphs["graph_timeline"],
            "graph_tax": graphs["graph_tax"],
            "graph_treemap": graphs["graph_treemap"],
            "graph_source": graphs["graph_source"],
            # ---------------------------------
            "suggestions": [
                f"Total recorded spend: ₹{total_spent:.2f}",
                f"Automation Rate: {(ocr_count / len(all_stored_expenses) * 100) if all_stored_expenses else 0:.1f}% AI vs {manual_count} Manual Fallbacks."
            ]
        }
    )
