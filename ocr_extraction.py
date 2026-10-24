import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from financial_config import DEFAULT_SYSTEM_PROMPT, MAX_GROQ_WORKERS
from financial_processor import (
    calculate_file_hash,
    load_and_optimize_image,
    parse_image_with_gemini_vision,
    save_batch_results,
)

# ============================================================
# CONFIGURATION
# ============================================================
TEMP_ROOT = Path("temp") / "requests"

# ============================================================
# REQUEST MANAGEMENT
# ============================================================
def create_request_id():
    """Create a unique request ID for each extraction request."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    short_id = uuid.uuid4().hex[:8]
    return f"{timestamp}_{short_id}"

def create_request_directory(request_id):
    """Create a temporary directory for the current request."""
    request_dir = TEMP_ROOT / request_id
    request_dir.mkdir(parents=True, exist_ok=True)
    return request_dir

# ============================================================
# TEMPORARY LOGGING & STORAGE
# ============================================================
def save_temp_extraction(request_dir, filename, result):
    """Save the intermediate extraction temporarily."""
    safe_filename = Path(filename).stem
    extraction_path = request_dir / f"{safe_filename}_extracted.json"
    with open(extraction_path, "w", encoding="utf-8") as file:
        json.dump(result, file, indent=4, ensure_ascii=False)
    return extraction_path

def save_request_status(request_dir, status, message=None):
    """Save request status for debugging/transparency."""
    status_path = request_dir / "status.json"
    status_data = {"status": status}
    if message:
        status_data["message"] = message
        
    with open(status_path, "w", encoding="utf-8") as file:
        json.dump(status_data, file, indent=4, ensure_ascii=False)
    return status_path

# ============================================================
# MAIN BATCH PROCESSOR (GEMINI MULTIMODAL VISION)
# ============================================================
def process_invoices(image_paths, system_prompt=DEFAULT_SYSTEM_PROMPT, progress_callback=None):
    """
    Process multiple financial documents directly using Gemini Multimodal Vision.
    Zero heavy local OCR memory footprint - ideal for Render cloud deployments.
    Pipeline: Image -> Optimize -> Gemini Vision -> Validation -> DB
    """
    overall_start = time.perf_counter()

    # --------------------------------------------------------
    # CREATE UNIQUE REQUEST
    # --------------------------------------------------------
    request_id = create_request_id()
    request_dir = create_request_directory(request_id)

    print("\n" + "=" * 70)
    print(f"🆔 Request ID: {request_id}")
    print(f"🚀 Processing {len(image_paths)} image(s) via Gemini Multimodal Vision")
    print("=" * 70)

    save_request_status(request_dir, "STARTED")

    if progress_callback:
        progress_callback({
            "step": "prep",
            "message": f"Pre-processing and optimizing {len(image_paths)} receipt images...",
            "total": len(image_paths),
            "percent": 15
        })

    # ========================================================
    # STEP 1 — IMAGE PREPARATION
    # ========================================================
    image_start = time.perf_counter()
    valid_items = []

    for path in image_paths:
        if not os.path.exists(path):
            print(f"⚠️ File not found: {path}")
            continue

        image = load_and_optimize_image(path)
        if image is None:
            continue

        filename = os.path.basename(path)
        file_hash = calculate_file_hash(path)
        valid_items.append((path, filename, image, file_hash))

    image_time = time.perf_counter() - image_start
    print(f"⚡ Image preparation: {image_time:.2f}s")

    if not valid_items:
        print("❌ No valid images.")
        save_request_status(request_dir, "FAILED", "No valid images found.")
        return []

    # ========================================================
    # STEP 2 — GEMINI VISION MULTIMODAL EXTRACTION
    # ========================================================
    vision_start = time.perf_counter()
    print("\n🤖 Running Gemini Multimodal Vision extraction in parallel...")

    if progress_callback:
        progress_callback({
            "step": "llm_batch",
            "message": f"Extracting financial details via Gemini Vision on {len(valid_items)} documents...",
            "total": len(valid_items),
            "percent": 35,
        })

    final_results = []
    max_workers = min(MAX_GROQ_WORKERS, len(valid_items))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {}

        for _, filename, image, file_hash in valid_items:
            future = executor.submit(
                parse_image_with_gemini_vision,
                filename,
                image,
                system_prompt,
            )
            future_map[future] = (filename, file_hash)

        for future in as_completed(future_map):
            filename, file_hash = future_map[future]

            try:
                result = future.result()

                if result is None:
                    print(f"⚠️ Gemini Vision failed for {filename}")
                    continue

                result["document_hash"] = file_hash
                save_temp_extraction(request_dir, filename, result)
                final_results.append(result)

                seller = result.get("seller_details", {})
                merchant_name = (
                    result.get("merchant_info", {}).get("name")
                    or seller.get("vendor_name")
                    or seller.get("platform_or_marketplace")
                    or "Unknown Merchant"
                )
                totals = result.get("financial_totals", {})
                grand_total = totals.get("grand_total") or 0.0
                category = (
                    result.get("category")
                    or result.get("document_metadata", {}).get("expense_category")
                    or "General"
                )

                if progress_callback:
                    progress_callback({
                        "step": "llm_item",
                        "filename": filename,
                        "merchant": merchant_name,
                        "amount": grand_total,
                        "category": category,
                        "status": result.get("validation", {}).get("status", "VALID"),
                        "index": len(final_results),
                        "total": len(valid_items),
                        "message": f"Extracted: {merchant_name} · ₹{grand_total:,.2f}",
                        "percent": 35 + int((len(final_results) / len(valid_items)) * 55),
                    })

            except Exception as exc:
                print(f"❌ Worker error {filename}: {type(exc).__name__}: {exc}")

    vision_time = time.perf_counter() - vision_start
    print(f"⚡ Gemini Vision processing: {vision_time:.2f}s")

    # ========================================================
    # STEP 3 — SAVE PERMANENT DATABASE
    # ========================================================
    save_start = time.perf_counter()
    if final_results:
        save_batch_results(final_results)
    save_time = time.perf_counter() - save_start
    print(f"💾 Database save: {save_time:.2f}s")

    # ========================================================
    # STEP 4 — SUMMARY
    # ========================================================
    total_time = time.perf_counter() - overall_start

    valid_count = sum(1 for res in final_results if res.get("validation", {}).get("status") == "VALID")
    review_count = sum(1 for res in final_results if res.get("validation", {}).get("status") == "REVIEW_REQUIRED")
    unknown_count = len(final_results) - valid_count - review_count

    print("\n" + "=" * 70)
    print("✅ BATCH COMPLETE (Gemini Vision)")
    print("=" * 70)
    print(f"Request ID      : {request_id}")
    print(f"Images received : {len(image_paths)}")
    print(f"Images processed: {len(final_results)}")
    print(f"Valid documents : {valid_count}")
    print(f"Needs review    : {review_count}")
    print(f"Unknown status  : {unknown_count}")
    print(f"Vision time     : {vision_time:.2f}s")
    print(f"Save time       : {save_time:.2f}s")
    print(f"TOTAL TIME      : {total_time:.2f}s")
    print(f"Temporary data  : {request_dir}")
    print("=" * 70)

    if final_results:
        save_request_status(request_dir, "COMPLETED")
    else:
        save_request_status(request_dir, "FAILED", "Vision processing failed for all documents.")

    return final_results

# ============================================================
# SINGLE INVOICE
# ============================================================
def process_invoice(img_path, system_prompt=DEFAULT_SYSTEM_PROMPT):
    """Process one invoice/image."""
    results = process_invoices([img_path], system_prompt=system_prompt)
    return results[0] if results else None

# ============================================================
# BATCH ALIAS
# ============================================================
def process_documents(image_paths, system_prompt=DEFAULT_SYSTEM_PROMPT):
    """Alias for processing multiple documents."""
    return process_invoices(image_paths, system_prompt=system_prompt)

# ============================================================
# PUBLIC API
# ============================================================
__all__ = [
    "process_invoice",
    "process_invoices",
    "process_documents",
]

# ============================================================
# DIRECT TEST
# ============================================================
if __name__ == "__main__":
    test_images = ["receipt.jpeg"] if os.path.exists("receipt.jpeg") else []

    if test_images:
        results = process_invoices(test_images)
        print("\n📊 FINAL RESULTS:")
        print(json.dumps(results, indent=4, ensure_ascii=False))
    else:
        print("\nℹ️ No test images configured.")
