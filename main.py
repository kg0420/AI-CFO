import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from fastapi import FastAPI, File, UploadFile, Request, Form, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from typing import List, Optional
import shutil
from fastapi import Body
import os
import asyncio
import os
import shutil
import uuid
from pathlib import Path
import pandas as pd
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
# Auth & Security Imports
import jwt
import json
import bcrypt
from dotenv import load_dotenv
from processing_history import (
    load_processing_history,
    get_processing_batch,
    save_processing_batch,
)
load_dotenv()
# Database Imports (SQLAlchemy)
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import declarative_base, sessionmaker, Session
# Your custom imports (Make sure these files exist in your project)
from expense_processing import (
    load_all_expenses,
    save_expenses,
    format_manual_entry,
    delete_user_expense,
    update_user_expense,
) 

from report_utils import render_report_response
from ocr_extraction import process_invoice 
from google import genai
from fastapi.templating import Jinja2Templates
from receipt_storage import (
    save_receipt,
    list_receipts,
    get_receipt,
    get_receipt_path,
    delete_receipt,
    ALLOWED_MIME_TYPES,
)
from processing_history import save_processing_batch
from runway_simulator import (
    compute_baseline_metrics,
    simulate_runway,
    generate_cfo_strategic_advisory,
)

app = FastAPI()

templates = Jinja2Templates(directory="templates")
api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    raise ValueError("GEMINI_API_KEY is missing! Check your .env file.")

client = genai.Client(api_key=api_key)
# app.mount("/static", StaticFiles(directory="static"), name="static")

# Ensure directories exist
os.makedirs("temp_uploads", exist_ok=True)
os.makedirs("data", exist_ok=True)

# ==================== DATABASE SETUP (SQLAlchemy) ====================


TEMP_UPLOAD_DIR = Path("temp_uploads")
TEMP_UPLOAD_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

SQLALCHEMY_DATABASE_URL = "sqlite:///./data/users.db"

# Create database engine
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# Define the User Model
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password_hash = Column(String)

# Create the database tables
Base.metadata.create_all(bind=engine)

# Dependency to get the database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ==================== AUTHENTICATION SETUP ====================

SECRET_KEY = os.environ.get("SECRET_KEY", "super-secret-default-key-change-this")
ALGORITHM = "HS256"

# ADD THESE LINES INSTEAD:

def get_password_hash(password: str) -> str:
    # bcrypt requires bytes, so encode the password
    pwd_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed_password = bcrypt.hashpw(pwd_bytes, salt)
    # decode back to string to store in the database
    return hashed_password.decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    password_byte_enc = plain_password.encode('utf-8')
    hashed_password_bytes = hashed_password.encode('utf-8')
    return bcrypt.checkpw(password_byte_enc, hashed_password_bytes)

def get_current_user(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username is None:
            return None
        # Verify user actually exists in database
        user = db.query(User).filter(User.username == username).first()
        if user:
            return user.username
        return None
    except jwt.PyJWTError:
        return None

# ==================== AUTHENTICATION ROUTES ====================

@app.get("/auth", response_class=HTMLResponse)
async def auth_page(request: Request):
    """Renders the login/register page."""
    return templates.TemplateResponse(
        request=request, 
        name="auth.html"
    )

@app.post("/register")
async def register(
    request: Request, 
    username: str = Form(...), 
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    # Check if user already exists in the database
    existing_user = db.query(User).filter(User.username == username).first()
    
    if existing_user:
        return templates.TemplateResponse(
            request=request, 
            name="auth.html", 
            context={"error": "Username already exists."}
        )
    
    # Create new user and save to database
    new_user = User(
        username=username, 
        password_hash=get_password_hash(password)
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    return templates.TemplateResponse(
        request=request, 
        name="auth.html", 
        context={"message": "Registration successful! Please log in."}
    )

@app.post("/login")
async def login(
    request: Request, 
    username: str = Form(...), 
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    # Retrieve user from database
    user = db.query(User).filter(User.username == username).first()
    
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request=request, 
            name="auth.html", 
            context={"error": "Invalid username or password."}
        )
    
    # Generate JWT Token
    expire = datetime.now(timezone.utc) + timedelta(hours=12)
    to_encode = {"sub": username, "exp": expire}
    token = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    
    # Redirect to home and set secure HTTP-only cookie
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(key="access_token", value=token, httponly=True, max_age=43200, samesite="lax") # 12 hours
    return response

@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/auth", status_code=302)
    response.delete_cookie("access_token")
    return response


# ==================== CORE ROUTES ====================

@app.get("/", response_class=HTMLResponse)
async def upload_page(request: Request, db: Session = Depends(get_db)):
    """Renders the upload and manual entry form."""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/auth", status_code=302)
        
    return templates.TemplateResponse(
        request=request, 
        name="index.html", 
        context={"username": user}
    )


# ============================================================
# REPORTS PAGE
# ============================================================

@app.get("/reports", response_class=HTMLResponse)
async def reports_page(
    request: Request,
    db: Session = Depends(get_db)
):

    # Check login
    user = get_current_user(request, db)

    if not user:
        return RedirectResponse(
            url="/auth",
            status_code=302
        )

    # Load all expenses belonging to current user
    expenses = load_all_expenses(user)

    # If there are no expenses
    if not expenses:
        return HTMLResponse(
            content="""
            <html>
            <head>
                <title>aiCFO — Reports</title>
            </head>

            <body>
                <h2>No expenses found</h2>

                <p>
                    Upload a receipt or add a manual expense
                    to generate your report.
                </p>

                <a href="/">
                    ← Back to Dashboard
                </a>
            </body>
            </html>
            """
        )

    # Generate/render report
    return render_report_response(
        request,
        expenses
    )

executor = ThreadPoolExecutor(max_workers=2)

@app.post("/generate-report", response_class=HTMLResponse)
async def generate_report(
    request: Request,
    receipts: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    # 1. Authentication
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/auth", status_code=302)

    # 2. Request ID & Temp Directory Setup
    request_id = uuid.uuid4().hex[:12]
    safe_user = "".join(c for c in str(user) if c.isalnum() or c in ("_", "-"))
    request_dir = TEMP_UPLOAD_DIR / safe_user / request_id
    request_dir.mkdir(parents=True, exist_ok=True)

    # 3. Save Uploaded Files
    temp_paths = []
    valid_uploaded_files = [r for r in receipts if r.filename]

    for index, file in enumerate(valid_uploaded_files):
        original_name = Path(file.filename).name
        unique_name = f"{index}_{uuid.uuid4().hex[:8]}_{original_name}"
        temp_file_path = request_dir / unique_name

        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        temp_paths.append(str(temp_file_path))

    if not temp_paths:
        return render_report_response(request, [])

    # 4. Permanent Receipt Storage
    permanent_receipts = {}
    for temp_path, uploaded in zip(temp_paths, valid_uploaded_files):
        try:
            receipt_record = save_receipt(
                username=user,
                source_path=temp_path,
                original_filename=uploaded.filename,
                request_id=request_id,
            )
            # Map both unique disk filename and original upload filename
            permanent_receipts[Path(temp_path).name] = receipt_record
            permanent_receipts[Path(uploaded.filename).name] = receipt_record
        except Exception as exc:
            print(f"⚠️ Receipt storage error: {exc}")

    # 5. OCR Processing
    from ocr_extraction import process_invoices

    loop = asyncio.get_running_loop()
    all_extracted_data_raw = await loop.run_in_executor(
        executor, process_invoices, temp_paths
    )

    # 6. Collect Results & Link Receipts
    all_extracted_data = []
    for result in all_extracted_data_raw:
        if not result:
            continue

        result["id"] = uuid.uuid4().hex[:12]
        result["request_id"] = request_id
        result["data_source"] = "ai_ocr"
        result["user_id"] = user

        if source_file := result.get("source_file"):
            source_filename = Path(source_file).name
            if receipt_record := permanent_receipts.get(source_filename):
                result["receipt_id"] = receipt_record["receipt_id"]
                result["receipt_original_filename"] = receipt_record["original_filename"]

        all_extracted_data.append(result)

    if not all_extracted_data:
        return render_report_response(request, [])

    # 7. Persist & Render
    save_expenses(all_extracted_data)
    save_processing_batch(username=user, expenses=all_extracted_data)

    extracted_path = request_dir / "extracted.json"
    with open(extracted_path, "w", encoding="utf-8") as file:
        json.dump(all_extracted_data, file, indent=4, ensure_ascii=False)

    all_user_expenses = load_all_expenses(user)
    return render_report_response(request, all_user_expenses, current_batch=all_extracted_data)


# ============================================================
# LIVE STREAMING REPORT GENERATION (SSE PROGRESS HUD)
# ============================================================

@app.post("/api/generate-report-stream")
async def generate_report_stream(
    request: Request,
    receipts: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    """
    Streams Server-Sent Events (SSE) detailing real-time extraction progress:
    PaddleOCR text scan per receipt, Multi-LLM financial parsing, and final ledger save.
    """
    user = get_current_user(request, db)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    request_id = uuid.uuid4().hex[:12]
    safe_user = "".join(c for c in str(user) if c.isalnum() or c in ("_", "-"))
    request_dir = TEMP_UPLOAD_DIR / safe_user / request_id
    request_dir.mkdir(parents=True, exist_ok=True)

    temp_paths = []
    valid_uploaded_files = [r for r in receipts if r.filename]

    for index, file in enumerate(valid_uploaded_files):
        original_name = Path(file.filename).name
        unique_name = f"{index}_{uuid.uuid4().hex[:8]}_{original_name}"
        temp_file_path = request_dir / unique_name

        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        temp_paths.append(str(temp_file_path))

    if not temp_paths:
        return JSONResponse({"error": "No valid receipt files uploaded"}, status_code=400)

    # Permanent Vault Storage
    permanent_receipts = {}
    for temp_path, uploaded in zip(temp_paths, valid_uploaded_files):
        try:
            receipt_record = save_receipt(
                username=user,
                source_path=temp_path,
                original_filename=uploaded.filename,
                request_id=request_id,
            )
            permanent_receipts[Path(temp_path).name] = receipt_record
            permanent_receipts[Path(uploaded.filename).name] = receipt_record
        except Exception as exc:
            print(f"⚠️ Receipt vault storage error: {exc}")

    event_queue: asyncio.Queue = asyncio.Queue()
    main_loop = asyncio.get_running_loop()

    def sync_progress_callback(event: dict):
        main_loop.call_soon_threadsafe(event_queue.put_nowait, event)

    from ocr_extraction import process_invoices

    def run_ocr_pipeline():
        try:
            results = process_invoices(temp_paths, progress_callback=sync_progress_callback)
            main_loop.call_soon_threadsafe(event_queue.put_nowait, {"_done": True, "results": results})
        except Exception as exc:
            main_loop.call_soon_threadsafe(event_queue.put_nowait, {"_error": str(exc)})

    executor.submit(run_ocr_pipeline)

    async def event_generator():
        # Initial event informing client of total uploaded files
        file_names = [Path(p).name for p in temp_paths]
        yield f"data: {json.dumps({'step': 'init', 'total_files': len(temp_paths), 'files': file_names, 'percent': 5})}\n\n"

        while True:
            event = await event_queue.get()

            if "_error" in event:
                yield f"data: {json.dumps({'step': 'error', 'message': event['_error']})}\n\n"
                break

            if "_done" in event:
                raw_results = event.get("results") or []
                all_extracted_data = []

                for result in raw_results:
                    if not result:
                        continue
                    result["id"] = uuid.uuid4().hex[:12]
                    result["request_id"] = request_id
                    result["data_source"] = "ai_ocr"
                    result["user_id"] = user

                    if source_file := result.get("source_file"):
                        source_filename = Path(source_file).name
                        if receipt_record := permanent_receipts.get(source_filename):
                            result["receipt_id"] = receipt_record["receipt_id"]
                            result["receipt_original_filename"] = receipt_record["original_filename"]

                    all_extracted_data.append(result)

                if all_extracted_data:
                    save_expenses(all_extracted_data)
                    save_processing_batch(username=user, expenses=all_extracted_data)

                    extracted_path = request_dir / "extracted.json"
                    with open(extracted_path, "w", encoding="utf-8") as file:
                        json.dump(all_extracted_data, file, indent=4, ensure_ascii=False)

                yield f"data: {json.dumps({'step': 'finished', 'percent': 100, 'count': len(all_extracted_data), 'redirect_url': '/reports'})}\n\n"
                break

            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ============================================================
# RUNWAY & WHAT-IF SCENARIO SIMULATOR (PERSONAL & ORG)
# ============================================================

@app.get("/simulator", response_class=HTMLResponse)
async def runway_simulator_page(request: Request, db: Session = Depends(get_db)):
    """Personal & Household Runway and What-If Scenario Simulator."""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/auth", status_code=302)

    expenses = load_all_expenses(user)
    baseline = compute_baseline_metrics(expenses)

    default_monthly_burn = baseline.get("monthly_burn", 30000.0)
    default_savings = round(max(default_monthly_burn * 5.0, 150000.0), -3)
    default_income = round(default_monthly_burn * 1.15, -3)

    simulation = simulate_runway(
        savings_balance=default_savings,
        baseline_monthly_expenses=default_monthly_burn,
        monthly_income=default_income,
        income_change_pct=0.0,
        expense_cut_pct=0.0,
        extra_monthly_expense=0.0,
        one_time_expense=0.0,
        one_time_month=1,
        horizon_months=24,
    )

    advisory_html = generate_cfo_strategic_advisory(baseline, simulation, client)

    return templates.TemplateResponse(
        request=request,
        name="simulator.html",
        context={
            "username": user,
            "baseline": baseline,
            "simulation": simulation,
            "advisory_html": advisory_html,
        },
    )


@app.post("/api/simulator/simulate")
async def api_runway_simulate(request: Request, payload: dict = Body(...), db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})

    savings_balance = float(payload.get("savings_balance", 150000.0))
    baseline_monthly_expenses = float(payload.get("baseline_monthly_expenses", 30000.0))
    monthly_income = float(payload.get("monthly_income", 35000.0))
    income_change_pct = float(payload.get("income_change_pct", 0.0))
    expense_cut_pct = float(payload.get("expense_cut_pct", 0.0))
    extra_monthly_expense = float(payload.get("extra_monthly_expense", 0.0))
    one_time_expense = float(payload.get("one_time_expense", 0.0))
    one_time_month = int(payload.get("one_time_month", 1))
    horizon_months = int(payload.get("horizon_months", 24))

    sim_result = simulate_runway(
        savings_balance=savings_balance,
        baseline_monthly_expenses=baseline_monthly_expenses,
        monthly_income=monthly_income,
        income_change_pct=income_change_pct,
        expense_cut_pct=expense_cut_pct,
        extra_monthly_expense=extra_monthly_expense,
        one_time_expense=one_time_expense,
        one_time_month=one_time_month,
        horizon_months=horizon_months,
    )
    return sim_result


@app.post("/api/simulator/advisory")
async def api_runway_advisory(request: Request, payload: dict = Body(...), db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})

    expenses = load_all_expenses(user)
    baseline = compute_baseline_metrics(expenses)

    savings_balance = float(payload.get("savings_balance", 150000.0))
    baseline_monthly_expenses = float(payload.get("baseline_monthly_expenses", baseline.get("monthly_burn", 30000.0)))
    monthly_income = float(payload.get("monthly_income", 35000.0))
    income_change_pct = float(payload.get("income_change_pct", 0.0))
    expense_cut_pct = float(payload.get("expense_cut_pct", 0.0))
    extra_monthly_expense = float(payload.get("extra_monthly_expense", 0.0))
    one_time_expense = float(payload.get("one_time_expense", 0.0))
    one_time_month = int(payload.get("one_time_month", 1))
    horizon_months = int(payload.get("horizon_months", 24))

    sim_result = simulate_runway(
        savings_balance=savings_balance,
        baseline_monthly_expenses=baseline_monthly_expenses,
        monthly_income=monthly_income,
        income_change_pct=income_change_pct,
        expense_cut_pct=expense_cut_pct,
        extra_monthly_expense=extra_monthly_expense,
        one_time_expense=one_time_expense,
        one_time_month=one_time_month,
        horizon_months=horizon_months,
    )

    advisory_html = generate_cfo_strategic_advisory(baseline, sim_result, client)
    return {"advisory_html": advisory_html}


@app.get("/receipts", response_class=HTMLResponse)
async def receipts_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/auth", status_code=302)

    return templates.TemplateResponse(
        request=request,
        name="receipts.html",
        context={"username": user},
    )


# ============================================================
# GET RECEIPT LIST
# ============================================================


@app.get("/api/receipts")
async def api_list_receipts(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})

    return {"success": True, "receipts": list_receipts(user)}


# ============================================================
# VIEW RECEIPT
# ============================================================


@app.get("/receipts/{receipt_id}")
async def view_receipt(
    receipt_id: str, request: Request, db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/auth", status_code=302)

    path = get_receipt_path(user, receipt_id)
    record = get_receipt(user, receipt_id)
    if not path or not record:
        return JSONResponse(status_code=404, content={"error": "Receipt not found"})

    return FileResponse(
        path=str(path),
        media_type=record.get("mime_type", "application/octet-stream"),
        filename=record.get("original_filename", path.name),
        content_disposition_type="inline",
    )


# ============================================================
# DOWNLOAD RECEIPT
# ============================================================


@app.get("/receipts/{receipt_id}/download")
async def download_receipt(
    receipt_id: str, request: Request, db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/auth", status_code=302)

    path = get_receipt_path(user, receipt_id)
    record = get_receipt(user, receipt_id)
    if not path or not record:
        return JSONResponse(status_code=404, content={"error": "Receipt not found"})

    return FileResponse(
        path=str(path),
        media_type=record.get("mime_type", "application/octet-stream"),
        filename=record.get("original_filename", path.name),
        content_disposition_type="attachment",
    )


@app.get("/ledger", response_class=HTMLResponse)
async def ledger_history(
    request: Request,
    db: Session = Depends(get_db)
):
    user = get_current_user(request, db)

    if not user:
        return RedirectResponse(
            url="/auth",
            status_code=302
        )

    history = load_processing_history(user)

    return templates.TemplateResponse(
        request=request,
        name="ledger_history.html",
        context={
            "request": request,
            "username": user,
            "history": history,
        }
    )

@app.get("/ledger/{batch_id}",response_class=HTMLResponse)
async def ledger_detail(batch_id:str, request:Request, db:Session=Depends(get_db)):
    user=get_current_user(request,db)

    if not user:
        return RedirectResponse( url="/auth",status_code=302)

    batch=get_processing_batch(username=user,batch_id=batch_id)

    if not batch:
        return HTMLResponse(
            "<h1>Processing record not found</h1>",
            status_code=404
        )
    return templates.TemplateResponse(
        request=request, name="ledger_detail.html",
        context={
            "request":request,
            "username":user,
            "batch":batch
        }
    )

# ============================================================
# DELETE RECEIPT
# ============================================================


@app.delete("/api/receipts/{receipt_id}")
async def remove_receipt(
    receipt_id: str, request: Request, db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})

    if not delete_receipt(user, receipt_id):
        return JSONResponse(status_code=404, content={"error": "Receipt not found"})

    return {"success": True, "message": "Receipt deleted successfully"}


@app.post("/add-manual-expense", response_class=HTMLResponse)
async def add_manual_expense(
    request: Request,
    merchant_name: str = Form(...),
    expense_date: str = Form(...),
    grand_total: float = Form(...),
    category: str = Form("General"),
    description: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """Receives human fallback form submission."""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/auth", status_code=302)

    manual_data = format_manual_entry(
        merchant=merchant_name,
        date=expense_date,
        total=grand_total,
        category=category,
        description=description
    )
    manual_data["user_id"] = user

    save_expenses([manual_data])
    save_processing_batch(username=user, expenses=[manual_data])
    all_user_expenses = load_all_expenses(user)
    return render_report_response(request, all_user_expenses, current_batch=[manual_data])

@app.post("/api/chat")
async def chat_with_cfo(request: Request, payload: dict = Body(...), db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})

    user_message = payload.get("message")
    if not user_message:
        return JSONResponse(status_code=400, content={"error": "Message is required"})

    expenses = load_all_expenses(user)
    
    # Optional: Filter expenses by the logged-in user if your JSON handles multiple users
    # expenses = [e for e in expenses if e.get("user") == user]
    
    if not expenses:
        return {"reply": "Your ledger is currently empty. Add some expenses first!"}

    normalized_rows = []
    for exp in expenses:
        meta = exp.get("document_metadata", {})
        seller = exp.get("seller_details", {})
        merchant = exp.get("merchant_info", {})
        totals = exp.get("financial_totals", {})

        date_val = meta.get("invoice_date") or merchant.get("date") or "Unknown Date"
        vendor_val = (
            seller.get("vendor_name")
            or merchant.get("name")
            or seller.get("platform_or_marketplace")
            or "Unknown Vendor"
        )
        cat_val = meta.get("expense_category") or exp.get("category") or "General"
        amount_val = totals.get("grand_total", 0.0)

        normalized_rows.append({
            "Date": date_val,
            "Vendor": vendor_val,
            "Category": cat_val,
            "Amount": amount_val,
        })

    df = pd.DataFrame(normalized_rows)
    csv_context = df.to_csv(index=False)

    prompt = f"""
    You are an expert AI CFO analyzing financial data. 

    Data Context (CSV format):
    {csv_context}
    
    User Question: "{user_message}"
    
    Formatting Rules:
    1. Format your entire response in valid HTML. 
    2. Do NOT use Markdown symbols like asterisks (*) or hash signs (#).
    3. Use <h3> for section headers.
    4. Use <ul> and <li> for bulleted lists.
    5. Use <p> for paragraphs and <b> for bolding important numbers or terms.
    6. Keep your insights concise and highly actionable.
    7. Start directly with the analysis, do not include intro text.
    """

    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash-lite',
            contents=prompt
        )
        return {"reply": response.text}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/upload")
async def upload_receipt(
    request: Request,
    file: UploadFile = File(...),
    auto_process: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    # 1. Get logged-in user
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/auth", status_code=302)

    # 2. Check file presence
    if not file.filename:
        return RedirectResponse(url="/receipts?error=no_file", status_code=303)

    # 3. Validate allowed file types
    allowed_types = {
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/gif",
    }
    if file.content_type not in allowed_types:
        return RedirectResponse(url="/receipts?error=invalid_file", status_code=303)

    # 4. Safe original filename & temporary storage setup
    original_filename = Path(file.filename).name
    temp_dir = Path("data/temp_uploads")
    temp_dir.mkdir(parents=True, exist_ok=True)

    temp_path = temp_dir / f"{uuid.uuid4().hex}_{original_filename}"

    try:
        # 5. Save uploaded file temporarily
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 6. Permanent user-specific storage
        receipt_record = save_receipt(
            username=str(user),
            source_path=str(temp_path),
            original_filename=original_filename,
            request_id=uuid.uuid4().hex[:12],
        )

        print(f"✅ Receipt uploaded by user {user}: {original_filename}")

        # 7. Optional immediate OCR & expense extraction
        if auto_process:
            from ocr_extraction import process_invoices

            loop = asyncio.get_running_loop()
            extracted_raw = await loop.run_in_executor(
                executor, process_invoices, [str(temp_path)]
            )
            extracted_data = []
            for item in extracted_raw:
                if not item:
                    continue
                item["id"] = uuid.uuid4().hex[:12]
                item["request_id"] = receipt_record.get("request_id")
                item["data_source"] = "ai_ocr"
                item["user_id"] = user
                item["receipt_id"] = receipt_record.get("receipt_id")
                item["receipt_original_filename"] = receipt_record.get("original_filename")
                extracted_data.append(item)

            if extracted_data:
                save_expenses(extracted_data)
                save_processing_batch(username=user, expenses=extracted_data)
                return RedirectResponse(url="/reports", status_code=303)

        return RedirectResponse(url="/receipts?uploaded=success", status_code=303)

    except Exception as exc:
        print(f"❌ Receipt upload failed for user {user}: {exc}")
        return RedirectResponse(url="/receipts?error=upload_failed", status_code=303)

    finally:
        # 8. Clean up temporary file
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError as exc:
            print(f"⚠️ Could not delete temporary file: {exc}")


@app.post("/api/receipts/{receipt_id}/process")
async def process_vault_receipt(
    receipt_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Trigger OCR and extract expenses from an existing receipt stored in the vault."""
    user = get_current_user(request, db)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})

    receipt_path = get_receipt_path(user, receipt_id)
    receipt_record = get_receipt(user, receipt_id)
    if not receipt_path or not receipt_record:
        return JSONResponse(status_code=404, content={"error": "Receipt not found"})

    from ocr_extraction import process_invoices

    loop = asyncio.get_running_loop()
    extracted_raw = await loop.run_in_executor(
        executor, process_invoices, [str(receipt_path)]
    )

    extracted_data = []
    request_id = receipt_record.get("request_id") or uuid.uuid4().hex[:12]
    for item in extracted_raw:
        if not item:
            continue
        item["id"] = uuid.uuid4().hex[:12]
        item["request_id"] = request_id
        item["data_source"] = "ai_ocr"
        item["user_id"] = user
        item["receipt_id"] = receipt_id
        item["receipt_original_filename"] = receipt_record.get("original_filename")
        extracted_data.append(item)

    if not extracted_data:
        return JSONResponse(
            status_code=422,
            content={"error": "Could not extract structured financial data from this receipt."}
        )

    save_expenses(extracted_data)
    save_processing_batch(username=user, expenses=extracted_data)

    return {
        "success": True,
        "message": f"Successfully extracted and saved {len(extracted_data)} expense(s) to ledger.",
        "count": len(extracted_data),
    }


@app.put("/api/expenses/{expense_id}")
async def edit_expenses(
    expense_id: str,
    request: Request,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    success = update_user_expense(user, expense_id, payload)
    if not success:
        return JSONResponse(status_code=404, content={"error": "Expense not found"})
    return {"success": True, "message": "User expense updated successfully"}

@app.delete("/api/expenses/{expense_id}")
async def remove_expense(
    expense_id: str,
    request: Request,
    db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})

    success = delete_user_expense(user, expense_id)
    if not success:
        return JSONResponse(status_code=404, content={"error": "Expense not found"})

    return {"success": True, "message": "Expense deleted successfully"}

