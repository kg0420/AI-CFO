import os
import json
import re
import glob
from paddleocr import PaddleOCR
from groq import Groq
from PIL import Image
import time
from dotenv import load_dotenv
load_dotenv()  # Load environment variables from .env file

# ==========================================
# 1. SETUP & INITIALIZATION
# ==========================================
api_key = os.environ.get("GROQ_API_KEY")
os.environ["GROQ_API_KEY"] = api_key
if not os.environ.get("GROQ_API_KEY"):
    raise ValueError("❌ GROQ_API_KEY is not set.")

os.environ["PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT"] = "0"
print("Initializing PaddleOCR...")
ocr = PaddleOCR(use_textline_orientation=True, lang="en", enable_mkldnn=False)

print("Initializing Groq...")
client = Groq(api_key=os.environ["GROQ_API_KEY"])

# ==========================================
# 2. HELPER FUNCTIONS
# ==========================================
def extract_text(obj):
    """Recursively extract text from PaddleOCR/PaddleX result objects."""
    found = []
    
    if hasattr(obj, "json"):
        try: found.extend(extract_text(obj.json() if callable(obj.json) else obj.json))
        except Exception: pass
    elif hasattr(obj, "__dict__"):
        try: found.extend(extract_text(vars(obj)))
        except Exception: pass
    elif isinstance(obj, dict):
        for key in ["rec_texts", "rec_text", "text", "texts", "value"]:
            if key in obj and obj[key]:
                val = obj[key]
                if isinstance(val, list):
                    for item in val:
                        if isinstance(item, str): found.append(item)
                        elif item: found.extend(extract_text(item))
                    return found
                elif isinstance(val, str):
                    return [val]
        for v in obj.values():
            found.extend(extract_text(v))
    elif isinstance(obj, (list, tuple)):
        if len(obj) == 2 and isinstance(obj[0], str) and isinstance(obj[1], (float, int)):
            return [obj[0]]
        for item in obj:
            found.append(item) if isinstance(item, str) else found.extend(extract_text(item))
    elif isinstance(obj, str):
        found.append(obj)
        
    return found

def append_to_json_file(new_data, filepath="database/ai_cfo_database.json"):
    """Appends new data to a JSON array safely."""
    existing_data = []
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content:
                    existing_data = json.loads(content)
                    if not isinstance(existing_data, list):
                        existing_data = [existing_data]
        except json.JSONDecodeError:
            pass 
            
    existing_data.append(new_data)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(existing_data, f, indent=4, ensure_ascii=False)

def append_to_text_file(new_data, filepath="database/ai_cfo_logs.txt"):
    """Appends JSON string to a text file separated by a blank line."""
    with open(filepath, 'a', encoding='utf-8') as f:
        f.write(json.dumps(new_data, indent=4, ensure_ascii=False) + "\n\n")


# ==========================================
# 3. CORE PROCESSING FUNCTION
# ==========================================
system_prompt = """
You are an advanced AI Data Extraction Engine for an AI-CFO platform. Your task is to extract every possible detail from raw OCR text of invoices, receipts, and bills, regardless of the format or country of origin.

CRITICAL INSTRUCTIONS:
1. Exhaustive Extraction: You must scan the text for all parameters listed in the JSON schema below. 
2. Strict Column Alignment (Anti-Shift Logic): OCR text often flattens tables into horizontal strings. You MUST map values to their correct headers by analyzing the context of the numbers. Do not blindly map sequential numbers to sequential JSON keys. Pay close attention to blank or null columns in the original document to prevent values from shifting into the wrong fields.
3. Mathematical Self-Validation: Where these fields exist on the document, verify standard accounting math (e.g., Taxable Amount = Gross - Discount; Grand Total = Taxable + Tax + Shipping). If the document contains these totals, your extracted values MUST balance according to the document's own mathematical logic. If they do not, your column mapping is likely wrong. Adjust it before outputting.
4. Strict Data Typing: 
   - Financial values MUST be floats (e.g., 1050.50). Remove all currency symbols (Rs, $, €, etc.), commas, and text.
   - Dates MUST be standardized to 'YYYY-MM-DD' format for database compatibility.
   - Quantities MUST be floats.
5. Missing Data Rule: If a parameter is not explicitly found or cannot be reasonably deduced from the OCR text, you MUST return `null`. Do not use "N/A", "None", 0.0 (unless explicitly stated as 0 on the document), or leave the string empty.
6. Auto-Categorization: Analyze the vendor and line items to determine a broad 'expense_category' (e.g., 'Software & IT', 'Office Supplies', 'Travel', 'Utilities', 'Marketing', 'Hardware', 'Clothing & Apparel', 'Logistics', 'Miscellaneous').
7. JSON Only: Output YOUR ENTIRE RESPONSE as a single, valid JSON object matching the exact schema below. Do not include markdown formatting (like ```json), conversational filler, or introductory text.

EXPECTED JSON SCHEMA:
{
  "document_metadata": {
    "document_type": "String (e.g., 'Tax Invoice', 'Proforma Invoice', 'Receipt', 'Credit Note') or null",
    "invoice_number": "String or null",
    "order_number": "String or null",
    "tracking_or_packet_id": "String or null",
    "invoice_date": "YYYY-MM-DD or null",
    "due_date": "YYYY-MM-DD or null",
    "billing_period_start": "YYYY-MM-DD or null",
    "billing_period_end": "YYYY-MM-DD or null",
    "place_of_supply": "String (State/Country) or null",
    "nature_of_transaction": "String (e.g., 'Inter-State', 'Intra-State', 'Export') or null",
    "expense_category": "String (AI-determined) or null",
    "currency_code": "3-letter ISO code (e.g., 'INR', 'USD') or null"
  },
  "seller_details": {
    "vendor_name": "String or null",
    "platform_or_marketplace": "String (e.g., 'Amazon', 'Myntra') or null",
    "billing_address": "String or null",
    "shipping_address": "String or null",
    "tax_id_gstin": "String or null",
    "pan_or_company_id": "String or null",
    "contact_phone": "String or null",
    "contact_email": "String or null"
  },
  "buyer_details": {
    "customer_name": "String or null",
    "customer_company": "String or null",
    "customer_type": "String (e.g., 'Registered', 'Unregistered', 'B2B', 'B2C') or null",
    "billing_address": "String or null",
    "shipping_address": "String or null",
    "tax_id_gstin": "String or null"
  },
  "financial_totals": {
    "gross_amount_pre_discount": "Float or null",
    "total_discount_amount": "Float or null",
    "taxable_amount_subtotal": "Float or null",
    "total_tax_amount": "Float or null",
    "shipping_and_handling_charges": "Float or null",
    "other_charges": "Float or null",
    "grand_total": "Float or null",
    "amount_paid": "Float or null",
    "balance_due": "Float or null"
  },
  "tax_breakdown": {
    "cgst_amount": "Float or null",
    "sgst_amount": "Float or null",
    "igst_amount": "Float or null",
    "vat_amount": "Float or null",
    "sales_tax_amount": "Float or null",
    "tax_cess_amount": "Float or null"
  },
  "payment_details": {
    "payment_method": "String (e.g., 'Credit Card', 'UPI', 'Bank Transfer', 'Cash') or null",
    "payment_transaction_id": "String or null",
    "payment_date": "YYYY-MM-DD or null"
  },
  "line_items": [
    {
      "item_id_or_sku": "String or null",
      "description": "String or null",
      "hsn_sac_code": "String or null",
      "quantity": "Float or null",
      "unit_price": "Float or null",
      "discount_amount": "Float or null",
      "taxable_value": "Float or null",
      "tax_percentage": "Float or null",
      "tax_amount": "Float or null",
      "total_item_amount": "Float or null"
    }
  ]
}
"""

def optimize_image_for_ocr(image_path):
    """
    Resizes and compresses high-resolution images so PaddleOCR can process 
    them much faster without losing text clarity.
    """
    print(f"[{os.path.basename(image_path)}] Optimizing image size...")
    try:
        with Image.open(image_path) as img:
            # Convert to RGB if it has an alpha channel (like PNGs)
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
                
            # If the image is wider than 1200px, shrink it.
            # 1200px is the sweet spot: large enough to read text, small enough to process fast.
            max_width = 1200
            if img.width > max_width:
                ratio = max_width / img.width
                new_size = (max_width, int(img.height * ratio))
                # Use Resampling.LANCZOS for high-quality downscaling
                img = img.resize(new_size, Image.Resampling.LANCZOS)
                
            # Save the compressed version over the original temp file
            # Quality 85 reduces file size dramatically with almost no visual loss
            img.save(image_path, optimize=True, quality=85)
            print(f"[{os.path.basename(image_path)}] Optimization complete.")
    except Exception as e:
        print(f"⚠️ Warning: Image optimization failed for {image_path}: {e}")
        # If optimization fails for any reason, we just continue with the original image


start = time.time()
def process_invoice(img_path):
    """
    Processes an invoice and returns the structured JSON data.
    Modified to return data instead of just saving it.
    """
    print(f"\n[{os.path.basename(img_path)}] Starting processing...")
    
    if not os.path.exists(img_path):
        print(f"❌ ERROR: Image not found: {img_path}")
        return None # Return None on failure

    optimize_image_for_ocr(img_path)
    # RUN OCR
    print(f"[{os.path.basename(img_path)}] Running OCR...")
    result = list(ocr.predict(img_path))
    
    # CLEAN TEXT
    raw_text_lines = extract_text(result)
    cleaned_lines = [line.strip() for line in raw_text_lines if isinstance(line, str) and len(line.strip()) > 1]
    full_receipt_text = "\n".join(list(dict.fromkeys(cleaned_lines)))

    if not full_receipt_text.strip():
        print(f"❌ ERROR: No text extracted for {img_path}.")
        return None

    # GROQ LLM PARSING
    print(f"[{os.path.basename(img_path)}] Sending text to Groq LLM...")
    try:
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Extract financial info from this OCR text. Return ONLY JSON.\n\n{full_receipt_text}"}
            ],
            temperature=0,
            response_format={"type": "json_object"}
        )
    except Exception as e:
        print(f"❌ API Error for {img_path}: {e}")
        return None

    # JSON CLEANUP
    raw_output = response.choices[0].message.content.strip()
    clean_json_str = re.sub(r"^\s*```(?:json)?|```\s*$", "", raw_output, flags=re.IGNORECASE).strip()

    try:
        structured_data = json.loads(clean_json_str)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", clean_json_str)
        if match:
            try:
                structured_data = json.loads(match.group(0))
            except json.JSONDecodeError:
                print(f"❌ JSON parsing failed for {img_path}")
                return None
        else:
            print(f"❌ No valid JSON object returned for {img_path}")
            return None

    # ASSEMBLE FINAL DATA
    structured_data["source_file"] = os.path.basename(img_path)
    structured_data["raw_ocr_text_reference"] = full_receipt_text

    # SAVE TO DATABASE
    os.makedirs("database", exist_ok=True) # Ensure directory exists
    append_to_json_file(structured_data)
    append_to_text_file(structured_data)
    
    print(f"✅ [{os.path.basename(img_path)}] Successfully processed and saved!")
    
    # NEW: Return the parsed data back to FastAPI
    return structured_data

end = time.time() # Record the end time

print(f"Processing time: {end - start:.2f} seconds")
