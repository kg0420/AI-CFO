import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
# ============================================================
# PERFORMANCE CONFIGURATION
# IMPORTANT: These environment variables must be set BEFORE 
# importing PaddleOCR/PaddlePaddle.
# ============================================================
os.environ["PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT"] = "0"
os.environ["FLAGS_use_mkldnn"] = "0"
os.environ["OMP_NUM_THREADS"] = "4"
os.environ["MKL_NUM_THREADS"] = "4"

from paddleocr import PaddleOCR

from financial_config import DEFAULT_SYSTEM_PROMPT, MAX_GROQ_WORKERS
from financial_processor import (
    calculate_file_hash,
    extract_text_fast,
    load_and_optimize_image,
    parse_with_llm,
    recheck_with_llm,
    save_batch_results,
)

# ============================================================
# CONFIGURATION
# ============================================================
TEMP_ROOT = Path("temp") / "requests"

# ============================================================
# PADDLEOCR INITIALIZATION
# ============================================================
print("🚀 Initializing PaddleOCR...")
ocr = PaddleOCR(
    lang="en",
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False,
    text_detection_model_name="PP-OCRv5_mobile_det",
    text_recognition_model_name="PP-OCRv5_mobile_rec",
    enable_mkldnn=False,       # turn CPU acceleration back on
    cpu_threads=4,
    enable_hpi=False,
)
print("✅ PaddleOCR initialized")

# ============================================================
# REQUEST MANAGEMENT
# ============================================================
def create_request_id():
    """Create a unique request ID for each extraction request (e.g., 20260819_130500_a81f3c42)."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    short_id = uuid.uuid4().hex[:8]
    return f"{timestamp}_{short_id}"

def create_request_directory(request_id):
    """Create a temporary directory for the current request."""
    request_dir = TEMP_ROOT / request_id
    request_dir.mkdir(parents=True, exist_ok=True)
    return request_dir

# ============================================================
# TEMPORARY OCR STORAGE
# ============================================================
def save_temp_ocr_text(request_dir, filename, ocr_text):
    """Save OCR text temporarily for the current request."""
    ocr_path = request_dir / "ocr.txt"
    with open(ocr_path, "a", encoding="utf-8") as file:
        file.write(f"\n\n===== {filename} =====\n\n")
        file.write(ocr_text)
    return ocr_path

def save_temp_extraction(request_dir, filename, result):
    """Save the intermediate Groq extraction temporarily."""
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
# MAIN BATCH PROCESSOR
# ============================================================
def process_invoices(image_paths, system_prompt=DEFAULT_SYSTEM_PROMPT):
    """
    Process multiple financial documents.
    Pipeline: Image -> Optimize -> PaddleOCR -> Temp OCR text -> Multi-LLM -> Validation -> Correction -> DB
    """
    overall_start = time.perf_counter()

    # --------------------------------------------------------
    # CREATE UNIQUE REQUEST
    # --------------------------------------------------------
    request_id = create_request_id()
    request_dir = create_request_directory(request_id)

    print("\n" + "=" * 70)
    print(f"🆔 Request ID: {request_id}")
    print(f"🚀 Processing {len(image_paths)} image(s)")
    print("=" * 70)

    save_request_status(request_dir, "STARTED")

    # ========================================================
    # STEP 1 — IMAGE PREPARATION
    # ========================================================
    image_start = time.perf_counter()
    valid_paths, images, file_hashes = [], [], {}

    for path in image_paths:
        if not os.path.exists(path):
            print(f"⚠️ File not found: {path}")
            continue

        image = load_and_optimize_image(path)
        if image is None:
            continue

        valid_paths.append(path)
        images.append(image)
        
        filename = os.path.basename(path)
        file_hashes[filename] = calculate_file_hash(path)

    image_time = time.perf_counter() - image_start
    print(f"⚡ Image preparation: {image_time:.2f}s")

    if not images:
        print("❌ No valid images.")
        save_request_status(request_dir, "FAILED", "No valid images found.")
        return []

    # ========================================================
    # STEP 2 — BATCH OCR
    # ========================================================
    ocr_start = time.perf_counter()
    print("\n🔎 Running PaddleOCR batch inference...")

    try:
        ocr_results = list(ocr.predict(images))
    except Exception as exc:
        print(f"❌ PaddleOCR failed: {exc}")
        save_request_status(request_dir, "OCR_FAILED", str(exc))
        return []

    ocr_time = time.perf_counter() - ocr_start
    print(f"⚡ OCR completed: {ocr_time:.2f}s")

    # ========================================================
    # STEP 3 — OCR TEXT EXTRACTION
    # ========================================================
    image_texts = []
    
    for idx, result in enumerate(ocr_results):
        if idx >= len(valid_paths):
            break

        filename = os.path.basename(valid_paths[idx])
        
        try:
            receipt_text = "\n".join(extract_text_fast([result]))
            if not receipt_text.strip():
                print(f"⚠️ No text found: {filename}")
                continue

            # Save OCR immediately
            save_temp_ocr_text(request_dir, filename, receipt_text)
            
            image_texts.append((filename, receipt_text, file_hashes.get(filename)))
            print(f"📝 {filename}: {len(receipt_text)} characters")
            print(f"🔍 [{request_id}] OCR lines: {len(receipt_text.splitlines())}")

        except Exception as exc:
            print(f"❌ Text extraction failed for {filename}: {exc}")

    if not image_texts:
        print("❌ No OCR text extracted.")
        save_request_status(request_dir, "OCR_EMPTY", "No OCR text was extracted.")
        return []

    # ========================================================
    # STEP 4 — MULTI-LLM EXTRACTION
    # ========================================================
    llm_start = time.perf_counter()
    print("\n🤖 Running multi-LLM extraction in parallel...")
    print("   🔀 Routing receipts between Gemini and Groq")
    print("   🛡️ Automatic fallback enabled if one provider fails")

    final_results = []
    max_workers = min(MAX_GROQ_WORKERS, len(image_texts))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {}

        for index, (filename, receipt_text, file_hash) in enumerate(image_texts):
            # Deterministic round-robin:
            # receipt 1 -> Gemini, receipt 2 -> Groq, receipt 3 -> Gemini, ...
            preferred_provider = "gemini" if index % 2 == 0 else "groq"

            future = executor.submit(
                parse_with_llm,
                filename,
                receipt_text,
                system_prompt,
                preferred_provider,
            )

            future_map[future] = (
                filename,
                receipt_text,
                file_hash,
                preferred_provider,
            )

        for future in as_completed(future_map):
            filename, receipt_text, file_hash, preferred_provider = future_map[future]

            try:
                print(
                    f"🤖 [{request_id}] Processing {filename} "
                    f"(preferred: {preferred_provider})"
                )

                result = future.result()

                if result is None:
                    print(f"⚠️ All LLM providers failed for {filename}")
                    continue

                result["document_hash"] = file_hash

                # Save intermediate extraction immediately.
                save_temp_extraction(request_dir, filename, result)

                # ------------------------------------------------
                # SECOND PASS — CORRECTION
                # ------------------------------------------------
                validation_status = result.get("validation", {}).get("status")

                if validation_status == "REVIEW_REQUIRED":
                    # Prefer the opposite provider for correction to spread load.
                    correction_provider = (
                        "groq" if preferred_provider == "gemini" else "gemini"
                    )

                    print(
                        f"🔄 [{request_id}] Running correction for {filename} "
                        f"(preferred: {correction_provider})"
                    )

                    corrected = recheck_with_llm(
                        filename,
                        receipt_text,
                        result,
                        correction_provider,
                    )

                    if corrected:
                        corrected["document_hash"] = file_hash
                        result = corrected
                        save_temp_extraction(request_dir, filename, result)

                final_results.append(result)

            except Exception as exc:
                print(
                    f"❌ Worker error {filename}: "
                    f"{type(exc).__name__}: {exc}"
                )

    llm_time = time.perf_counter() - llm_start
    print(f"⚡ Multi-LLM processing: {llm_time:.2f}s")

    # ========================================================
    # STEP 5 — SAVE PERMANENT DATABASE
    # ========================================================
    save_start = time.perf_counter()
    
    if final_results:
        save_batch_results(final_results)
        
    save_time = time.perf_counter() - save_start
    print(f"💾 Database save: {save_time:.2f}s")

    # ========================================================
    # STEP 6 — SUMMARY
    # ========================================================
    total_time = time.perf_counter() - overall_start
    
    valid_count = sum(1 for res in final_results if res.get("validation", {}).get("status") == "VALID")
    review_count = sum(1 for res in final_results if res.get("validation", {}).get("status") == "REVIEW_REQUIRED")
    unknown_count = len(final_results) - valid_count - review_count

    print("\n" + "=" * 70)
    print("✅ BATCH COMPLETE")
    print("=" * 70)
    print(f"Request ID      : {request_id}")
    print(f"Images received : {len(image_paths)}")
    print(f"Images processed: {len(final_results)}")
    print(f"Valid documents : {valid_count}")
    print(f"Needs review    : {review_count}")
    print(f"Unknown status  : {unknown_count}")
    print(f"OCR time        : {ocr_time:.2f}s")
    print(f"LLM time       : {llm_time:.2f}s")
    print(f"Save time       : {save_time:.2f}s")
    print(f"TOTAL TIME      : {total_time:.2f}s")
    print(f"Temporary data  : {request_dir}")
    print("=" * 70)

    if final_results:
        save_request_status(
            request_dir,
            "COMPLETED"
        )
    else:
        save_request_status(
            request_dir,
            "FAILED",
            "OCR completed but all configured LLM providers failed."
        )

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
    test_images = [] # e.g., ["invoices/invoice1.jpg", "invoices/invoice2.jpg"]

    if test_images:
        results = process_invoices(test_images)
        print("\n📊 FINAL RESULTS:")
        print(json.dumps(results, indent=4, ensure_ascii=False))
    else:
        print("\nℹ️ No test images configured.")