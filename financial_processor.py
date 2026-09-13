import hashlib
import json
import os
import re
import time
import traceback
import threading
from dotenv import load_dotenv
from groq import Groq
from google import genai
from google.genai import types
import numpy as np
from PIL import Image

from financial_config import (
    DEFAULT_SYSTEM_PROMPT,
    FINANCIAL_JSON_SCHEMA,
    GROQ_MODEL,
    MAX_IMAGE_WIDTH,
)

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GROQ_API_KEY and not GEMINI_API_KEY:
    raise RuntimeError(
        "At least one LLM API key is required: GROQ_API_KEY or GEMINI_API_KEY."
    )

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
GROQ_MAX_RETRIES = int(os.getenv("GROQ_MAX_RETRIES", "2"))
GEMINI_MAX_RETRIES = int(os.getenv("GEMINI_MAX_RETRIES", "2"))

_provider_lock = threading.Lock()
_provider_index = 0


def _available_providers():
    providers = []
    if gemini_client is not None:
        providers.append("gemini")
    if groq_client is not None:
        providers.append("groq")
    return providers


def _next_provider():
    global _provider_index

    providers = _available_providers()
    if not providers:
        raise RuntimeError("No LLM provider is configured.")

    with _provider_lock:
        provider = providers[_provider_index % len(providers)]
        _provider_index += 1

    return provider


def _is_rate_limit_error(exc):
    message = str(exc).lower()
    return (
        "429" in message
        or "rate limit" in message
        or "rate_limit_exceeded" in message
        or "resource_exhausted" in message
    )


def _sleep_for_retry(exc, attempt):
    wait_seconds = min(2 ** attempt, 8)

    match = re.search(
        r"(?:in|after)\s+([0-9]+(?:\.[0-9]+)?)s",
        str(exc),
        re.I,
    )

    if match:
        try:
            wait_seconds = min(max(float(match.group(1)), 1.0), 15.0)
        except ValueError:
            pass

    print(f"⏳ Retrying in {wait_seconds:.1f}s...")
    time.sleep(wait_seconds)


def _execute_groq_json_call(system_prompt, user_prompt, schema_name):
    if groq_client is None:
        raise RuntimeError("Groq is not configured.")

    last_error = None

    for attempt in range(1, GROQ_MAX_RETRIES + 1):
        try:
            print(f"🤖 Groq attempt {attempt}/{GROQ_MAX_RETRIES}")

            response = groq_client.chat.completions.create(
                model=os.getenv("GROQ_MODEL", GROQ_MODEL),
                max_completion_tokens=4096,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema_name,
                        "strict": True,
                        "schema": FINANCIAL_JSON_SCHEMA,
                    },
                },
            )

            raw = response.choices[0].message.content if response.choices else None
            if not raw or not raw.strip():
                raise RuntimeError("Groq returned empty response.")

            parsed = json.loads(raw.strip())

            if not isinstance(parsed.get("line_items"), list):
                raise ValueError(
                    "Expected list for line_items, "
                    f"got {type(parsed.get('line_items')).__name__}"
                )

            print("✅ Groq response received")
            return parsed

        except Exception as exc:
            last_error = exc
            print(
                f"❌ Groq attempt {attempt} failed: "
                f"{type(exc).__name__}: {exc}"
            )

            if attempt < GROQ_MAX_RETRIES:
                _sleep_for_retry(exc, attempt)

    raise RuntimeError(
        f"Groq failed after {GROQ_MAX_RETRIES} attempts: {last_error}"
    )


def _gemini_compatible_schema(schema):
    """Convert OpenAI-style nullable JSON Schema to Gemini-compatible schema."""
    if isinstance(schema, dict):
        converted = {}
        for key, value in schema.items():
            # OpenAI JSON Schema uses additionalProperties, but Gemini's
            # response_schema does not accept that field.
            if key in {"additionalProperties", "additional_properties"}:
                continue
            if key == "type" and isinstance(value, list):
                non_null = [t for t in value if t != "null"]
                if len(non_null) == 1:
                    type_map = {
                        "string": "STRING",
                        "number": "NUMBER",
                        "integer": "INTEGER",
                        "boolean": "BOOLEAN",
                        "object": "OBJECT",
                        "array": "ARRAY",
                    }
                    converted["type"] = type_map.get(
                        non_null[0], str(non_null[0]).upper()
                    )
                    if "null" in value:
                        converted["nullable"] = True
                    continue

            if key == "type" and isinstance(value, str):
                type_map = {
                    "string": "STRING",
                    "number": "NUMBER",
                    "integer": "INTEGER",
                    "boolean": "BOOLEAN",
                    "object": "OBJECT",
                    "array": "ARRAY",
                    "null": "NULL",
                }
                converted[key] = type_map.get(value, value)
                continue

            converted[key] = _gemini_compatible_schema(value)
        return converted

    if isinstance(schema, list):
        return [_gemini_compatible_schema(x) for x in schema]

    return schema


def _execute_gemini_json_call(system_prompt, user_prompt, schema_name):
    if gemini_client is None:
        raise RuntimeError("Gemini is not configured.")

    last_error = None

    for attempt in range(1, GEMINI_MAX_RETRIES + 1):
        try:
            print(f"✨ Gemini attempt {attempt}/{GEMINI_MAX_RETRIES}")

            response = gemini_client.models.generate_content(
                model=GEMINI_MODEL,
                contents=(
                    f"SYSTEM INSTRUCTIONS:\n{system_prompt}\n\n"
                    f"USER INPUT:\n{user_prompt}"
                ),
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=_gemini_compatible_schema(FINANCIAL_JSON_SCHEMA),
                    thinking_config=types.ThinkingConfig(
                        thinking_level="low"
                    ),
                ),
            )

            raw = response.text if response else None
            if not raw or not raw.strip():
                raise RuntimeError("Gemini returned empty response.")

            parsed = json.loads(raw.strip())

            if not isinstance(parsed.get("line_items"), list):
                raise ValueError(
                    "Expected list for line_items, "
                    f"got {type(parsed.get('line_items')).__name__}"
                )

            print("✅ Gemini response received")
            return parsed

        except Exception as exc:
            last_error = exc
            print(
                f"❌ Gemini attempt {attempt} failed: "
                f"{type(exc).__name__}: {exc}"
            )

            if attempt < GEMINI_MAX_RETRIES:
                _sleep_for_retry(exc, attempt)

    raise RuntimeError(
        f"Gemini failed after {GEMINI_MAX_RETRIES} attempts: {last_error}"
    )


def _execute_llm_json_call(
    system_prompt,
    user_prompt,
    schema_name,
    preferred_provider=None,
):
    providers = _available_providers()

    if not providers:
        raise RuntimeError("No LLM provider is configured.")

    if preferred_provider in providers:
        first = preferred_provider
    else:
        first = _next_provider()

    ordered = [first] + [p for p in providers if p != first]
    errors = []

    for provider in ordered:
        try:
            print(f"🔀 LLM provider selected: {provider.upper()}")

            if provider == "gemini":
                return _execute_gemini_json_call(
                    system_prompt, user_prompt, schema_name
                )

            return _execute_groq_json_call(
                system_prompt, user_prompt, schema_name
            )

        except Exception as exc:
            errors.append(
                f"{provider}: {type(exc).__name__}: {exc}"
            )

            if _is_rate_limit_error(exc):
                print(
                    f"⚠️ {provider.upper()} rate limit reached. "
                    "Failing over to another provider..."
                )
            else:
                print(
                    f"⚠️ {provider.upper()} failed. "
                    "Failing over to another provider..."
                )

    raise RuntimeError(
        "All configured LLM providers failed. " + " | ".join(errors)
    )

def normalize_text(value):
    return re.sub(r"\s+", " ", str(value)).strip().lower() if value is not None else ""


def normalize_number(value):
    try:
        return round(float(value), 2) if value is not None else None
    except (ValueError, TypeError):
        return None


def create_expense_key(data):
    meta = data.get("document_metadata", {})
    seller = data.get("seller_details", {})
    totals = data.get("financial_totals", {})
    payment = data.get("payment_details", {})

    vendor = normalize_text(seller.get("vendor_name"))
    doc_id = normalize_text(
        meta.get("invoice_number") or meta.get("order_number") or payment.get("payment_transaction_id")
    )
    inv_date = normalize_text(meta.get("invoice_date"))
    grand_total = normalize_number(totals.get("grand_total"))

    return (vendor, doc_id, inv_date, grand_total) if doc_id else (vendor, inv_date, grand_total)


def validate_financial_data(data):
    totals = data.get("financial_totals", {})
    taxes = data.get("tax_breakdown", {})
    items = data.get("line_items", [])

    grand_total = normalize_number(totals.get("grand_total"))
    subtotal = normalize_number(totals.get("taxable_amount_subtotal"))
    total_tax = normalize_number(totals.get("total_tax_amount"))
    shipping = normalize_number(totals.get("shipping_and_handling_charges")) or 0.0
    other = normalize_number(totals.get("other_charges")) or 0.0

    valid_lines = [normalize_number(i.get("total_item_amount")) for i in items if normalize_number(i.get("total_item_amount")) is not None]
    line_items_total = round(sum(valid_lines), 2)

    tax_keys = ["cgst_amount", "sgst_amount", "igst_amount", "vat_amount", "sales_tax_amount", "tax_cess_amount"]
    tax_values = [normalize_number(taxes.get(k)) or 0.0 for k in tax_keys]
    tax_breakdown_total = round(sum(tax_values), 2)

    accounting_total = round(subtotal + (total_tax or 0.0) + shipping + other, 2) if subtotal is not None else None
    line_diff = round(grand_total - line_items_total, 2) if grand_total is not None else None
    acc_diff = round(grand_total - accounting_total, 2) if grand_total is not None and accounting_total is not None else None
    tax_diff = round(total_tax - tax_breakdown_total, 2) if total_tax is not None else None

    checks = []
    if grand_total is not None:
        checks.append(abs(line_diff or 0) <= 0.05)
    if acc_diff is not None:
        checks.append(abs(acc_diff) <= 0.05)
    if total_tax is not None and any(tax_values):
        checks.append(abs(tax_diff or 0) <= 0.05)

    status = "UNKNOWN" if not checks else ("VALID" if all(checks) else "REVIEW_REQUIRED")
    data["validation"] = {
        "status": status,
        "line_items_count": len(items),
        "valid_line_items": len(valid_lines),
        "line_items_total": line_items_total,
        "grand_total": grand_total,
        "line_items_difference": line_diff,
        "accounting_total": accounting_total,
        "accounting_difference": acc_diff,
        "tax_breakdown_total": tax_breakdown_total,
        "tax_difference": tax_diff,
    }
    return data


def remove_duplicate_line_items(data):
    seen, unique = set(), []
    for item in data.get("line_items", []):
        key = (
            normalize_text(item.get("description")),
            normalize_number(item.get("quantity")),
            normalize_number(item.get("unit_price")),
            normalize_number(item.get("total_item_amount")),
        )
        if key not in seen:
            seen.add(key)
            unique.append(item)
    data["line_items"] = unique
    return data


def parse_with_llm(
    filename,
    receipt_text,
    system_prompt=DEFAULT_SYSTEM_PROMPT,
    preferred_provider=None,
):
    print(f"🤖 [{filename}] Sending to LLM router...")
    start = time.perf_counter()

    user_prompt = (
        "Extract the financial document from the OCR text below.\n\n"
        "IMPORTANT: 'line_items' MUST be a JSON array directly "
        '(e.g. "line_items": []).\n\n'
        f"OCR TEXT:\n{receipt_text}"
    )

    try:
        data = _execute_llm_json_call(
            system_prompt,
            user_prompt,
            "financial_document",
            preferred_provider=preferred_provider,
        )

        data["source_file"] = filename
        data["raw_ocr_text_reference"] = receipt_text
        data = validate_financial_data(
            remove_duplicate_line_items(data)
        )

        print(
            f"✅ [{filename}] Done in "
            f"{time.perf_counter() - start:.2f}s | "
            f"Status: {data['validation']['status']}"
        )

        return data

    except Exception as exc:
        print(
            f"❌ LLM error [{filename}]: "
            f"{type(exc).__name__}: {exc}"
        )
        traceback.print_exc()
        return None


def parse_with_groq(
    filename,
    receipt_text,
    system_prompt=DEFAULT_SYSTEM_PROMPT,
    preferred_provider=None,
):
    # Backward-compatible wrapper. Existing callers can keep this name.
    return parse_with_llm(
        filename,
        receipt_text,
        system_prompt,
        preferred_provider=preferred_provider,
    )


def parse_with_gemini(
    filename,
    receipt_text,
    system_prompt=DEFAULT_SYSTEM_PROMPT,
):
    if gemini_client is None:
        raise RuntimeError("GEMINI_API_KEY is not configured.")

    print(f"✨ [{filename}] Sending to Gemini...")
    start = time.perf_counter()

    user_prompt = (
        "Extract the financial document from the OCR text below.\n\n"
        "IMPORTANT: 'line_items' MUST be a JSON array directly "
        '(e.g. "line_items": []).\n\n'
        f"OCR TEXT:\n{receipt_text}"
    )

    try:
        data = _execute_gemini_json_call(
            system_prompt,
            user_prompt,
            "financial_document",
        )

        data["source_file"] = filename
        data["raw_ocr_text_reference"] = receipt_text
        data = validate_financial_data(
            remove_duplicate_line_items(data)
        )

        print(
            f"✅ [{filename}] Gemini done in "
            f"{time.perf_counter() - start:.2f}s | "
            f"Status: {data['validation']['status']}"
        )

        return data

    except Exception as exc:
        print(
            f"❌ Gemini error [{filename}]: "
            f"{type(exc).__name__}: {exc}"
        )
        traceback.print_exc()
        return None


def recheck_with_llm(filename, receipt_text, previous_result, preferred_provider=None):
    # Correction also uses the router, so one provider's 429 does not
    # automatically lose the correction request.
    print(f"🔄 [{filename}] Re-running extraction pass...")

    validation = previous_result.get("validation", {})

    system_prompt = f"""
You are a financial document extraction engine. Re-extract and fix validation errors from OCR.
The supplied schema is the ONLY output contract. "line_items" MUST be a flat array.
Do not invent values; set missing to null.
Previous validation details: {json.dumps(validation, ensure_ascii=False)}
"""

    user_prompt = (
        "Re-extract and correct this financial document:\n\n"
        f"OCR TEXT:\n{receipt_text}"
    )

    try:
        corrected = _execute_llm_json_call(
            system_prompt,
            user_prompt,
            "financial_document_correction",
            preferred_provider=preferred_provider,
        )

        corrected["source_file"] = filename
        corrected["raw_ocr_text_reference"] = receipt_text
        corrected = validate_financial_data(
            remove_duplicate_line_items(corrected)
        )

        print(
            f"🔍 [{filename}] Correction result: "
            f"{corrected['validation']['status']}"
        )

        return corrected

    except Exception as exc:
        print(
            f"❌ Correction failed [{filename}]: "
            f"{type(exc).__name__}: {exc}"
        )
        traceback.print_exc()
        return previous_result


def recheck_with_groq(
    filename,
    receipt_text,
    previous_result,
    preferred_provider=None,
):
    # Backward-compatible wrapper.
    return recheck_with_llm(
        filename,
        receipt_text,
        previous_result,
        preferred_provider=preferred_provider,
    )

def load_and_optimize_image(image_path, max_width=MAX_IMAGE_WIDTH):
    try:
        with Image.open(image_path) as img:
            img = img.convert("RGB")
            if img.width > max_width:
                img = img.resize((max_width, int(img.height * (max_width / img.width))), Image.Resampling.LANCZOS)
            return np.array(img)
    except Exception as e:
        print(f"❌ Image load failed {image_path}: {e}")
        return None


def calculate_file_hash(filepath):
    sha256 = hashlib.sha256()
    try:
        with open(filepath, "rb") as file:
            while chunk := file.read(1024 * 1024):
                sha256.update(chunk)
        return sha256.hexdigest()
    except Exception as e:
        print(f"⚠️ Hash calculation failed for {filepath}: {e}")
        return None


def extract_text_fast(results):
    all_text = []
    for result in results:
        try:
            data = result if isinstance(result, dict) else getattr(result, "json", None)
            if callable(data):
                data = data()
            if isinstance(data, str):
                data = json.loads(data)
            if isinstance(data, dict):
                all_text.extend([t.strip() for t in data.get("rec_texts", []) if isinstance(t, str) and t.strip()])
        except Exception as exc:
            print(f"⚠️ OCR parsing error: {exc}")
    return all_text


def save_batch_results(results, json_path="database/ai_cfo_database.json", log_path="database/ai_cfo_logs.txt"):
    os.makedirs(os.path.dirname(json_path) or ".", exist_ok=True)
    existing_data = []

    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as file:
                content = file.read().strip()
                if content:
                    existing_data = json.loads(content)
                    if not isinstance(existing_data, list):
                        existing_data = [existing_data]
        except (json.JSONDecodeError, OSError):
            print("⚠️ Existing database could not be parsed. Starting empty.")

    existing_hashes = {i.get("document_hash") for i in existing_data if i.get("document_hash")}
    existing_keys = {create_expense_key(i) for i in existing_data}

    added_results, added, skipped = [], 0, 0
    for res in results:
        doc_hash, sem_key = res.get("document_hash"), create_expense_key(res)
        if (doc_hash and doc_hash in existing_hashes) or (any(sem_key) and sem_key in existing_keys):
            print(f"⚠️ Duplicate skipped: {res.get('source_file')}")
            skipped += 1
            continue

        existing_data.append(res)
        added_results.append(res)
        if doc_hash:
            existing_hashes.add(doc_hash)
        existing_keys.add(sem_key)
        added += 1

    with open(json_path, "w", encoding="utf-8") as file:
        json.dump(existing_data, file, indent=4, ensure_ascii=False)

    if added_results:
        with open(log_path, "a", encoding="utf-8") as file:
            file.write("\n\n".join(json.dumps(r, indent=4, ensure_ascii=False) for r in added_results) + "\n\n")

    print(f"💾 Database updated | Added: {added} | Duplicates skipped: {skipped}")