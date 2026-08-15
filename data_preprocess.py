import json
from collections import defaultdict

def transform_invoice_data(input_file_path, output_json_path, output_jsonl_path):
    # 1. Load your raw flattened JSON file
    with open(input_file_path, 'r', encoding='utf-8') as f:
        flat_records = json.load(f)

    # 2. Group line items by invoice_no
    grouped_invoices = defaultdict(list)
    for record in flat_records:
        grouped_invoices[record['invoice_no']].append(record)

    training_dataset = []

    # 3. Process each invoice group into training samples
    for inv_id, items in grouped_invoices.items():
        first_item = items[0]
        
        # Calculate invoice summary metrics
        total_revenue = sum(item['revenue'] for item in items)
        total_items_count = sum(item['quantity'] for item in items)
        
        # Format the structured target output (Nested JSON)
        structured_output = {
            "invoice_no": inv_id,
            "order_date": first_item["order_date"],
            "ship_date": first_item["ship_date"],
            "customer_id": first_item["customer_id"],
            "customer": first_item["customer"],
            "summary": {
                "total_line_items": len(items),
                "total_quantity": total_items_count,
                "total_amount": round(total_revenue, 2)
            },
            "line_items": [
                {
                    "product_id": item["product_id"],
                    "product": item["product"],
                    "category": item["category"],
                    "segment": item["segment"],
                    "quantity": item["quantity"],
                    "unit_price": item["unit_price"],
                    "revenue": item["revenue"]
                }
                for item in items
            ]
        }

        # Format synthetic raw OCR text (Input Prompt)
        ocr_lines = [
            "==================================================",
            "                   TAX INVOICE                    ",
            "==================================================",
            f"INVOICE NO: {inv_id}",
            f"ORDER DATE: {first_item['order_date']}",
            f"SHIP DATE:  {first_item['ship_date']}",
            f"CUSTOMER:   {first_item['customer']} (ID: {first_item['customer_id']})",
            "--------------------------------------------------",
            "ITEMS PURCHASED:",
        ]
        
        for item in items:
            ocr_lines.append(
                f"- [{item['category'].upper()}] {item['product']} | Qty: {item['quantity']} x ${item['unit_price']} = ${item['revenue']}"
            )
            
        ocr_lines.extend([
            "--------------------------------------------------",
            f"TOTAL AMOUNT DUE: ${round(total_revenue, 2)}",
            "=================================================="
        ])
        
        raw_ocr_prompt = "\n".join(ocr_lines)

        # 4. Construct the complete training record
        training_sample = {
            "invoice_no": inv_id,
            "instruction": "You are an AI financial data extractor. Extract key invoice metadata and all line items into structured JSON format.",
            "prompt": raw_ocr_prompt,
            "response": json.dumps(structured_output, indent=2)
        }
        
        training_dataset.append(training_sample)

    # 5. Save as a standard structured JSON file
    with open(output_json_path, 'w', encoding='utf-8') as f:
        json.dump(training_dataset, f, indent=2)

    # 6. Save as JSONL (Standard format for OpenAI / Hugging Face fine-tuning)
    with open(output_jsonl_path, 'w', encoding='utf-8') as f:
        for entry in training_dataset:
            f.write(json.dumps(entry) + '\n')

    print(f"✅ Success! Processed {len(flat_records)} rows into {len(training_dataset)} unique invoice samples.")
    print(f"📁 Saved JSON dataset to: {output_json_path}")
    print(f"📁 Saved JSONL dataset to: {output_jsonl_path}")

# Run the transformation
transform_invoice_data(
    input_file_path="b2b_invoices.json",
    output_json_path="formatted_training_invoices.json",
    output_jsonl_path="formatted_training_invoices.jsonl"
)