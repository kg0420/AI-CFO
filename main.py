# pip install sqlalchemy
from fastapi import FastAPI, File, UploadFile, Request, Form, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse,FileResponse
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
from expense_processing import load_all_expenses,save_expenses,format_manual_entry

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
    response.set_cookie(key="access_token", value=token, httponly=True, max_age=43200) # 12 hours
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
    save_processing_batch(username=user, expenses=all_extracted_data, batch_id=request_id)

    extracted_path = request_dir / "extracted.json"
    with open(extracted_path, "w", encoding="utf-8") as file:
        json.dump(all_extracted_data, file, indent=4, ensure_ascii=False)

    return render_report_response(request, all_extracted_data)


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
    merchant_name: List[str] = Form(...),
    expense_date: List[str] = Form(...),
    grand_total: List[float] = Form(...),
    category: List[str] = Form(...),
    description: Optional[List[str]] = Form(None),
    db: Session = Depends(get_db)
):
    """Receives multiple manual expense entries at once."""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/auth", status_code=302)

    descriptions = description or [""] * len(merchant_name)
    manual_entries = []

    # Iterate through all submitted rows
    for i in range(len(merchant_name)):
        m = merchant_name[i].strip()
        if not m:
            continue

        d = expense_date[i] if i < len(expense_date) else ""
        t = grand_total[i] if i < len(grand_total) else 0.0
        c = category[i] if i < len(category) else "General"
        desc = descriptions[i] if i < len(descriptions) else None

        entry = format_manual_entry(
            merchant=m,
            date=d,
            total=t,
            category=c,
            description=desc
        )
        entry["user_id"] = user
        manual_entries.append(entry)

    if not manual_entries:
        return RedirectResponse(url="/", status_code=303)

    # Save to user expenses and archive into processing ledger
    save_expenses(manual_entries)
    save_processing_batch(username=user, expenses=manual_entries)

    return render_report_response(request, manual_entries)

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

    df = pd.json_normalize(expenses)
    
    cols_to_keep = [
        'document_metadata.invoice_date', 
        'seller_details.platform_or_marketplace', 
        'document_metadata.expense_category',
        'financial_totals.grand_total'
    ]
    available_cols = [c for c in cols_to_keep if c in df.columns]
    csv_context = df[available_cols].to_csv(index=False)

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
            model='gemini-3.6-flash',
            contents=prompt
        )
        return {"reply": response.text}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/upload")
async def upload_receipt(
    request: Request,
    file: UploadFile = File(...),
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
        return RedirectResponse(url="/receipts?uploaded=success", status_code=303)

    except Exception as exc:
        print(f"❌ Receipt upload failed for user {user}: {exc}")
        return RedirectResponse(url="/receipts?error=upload_failed", status_code=303)

    finally:
        # 7. Clean up temporary file
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError as exc:
            print(f"⚠️ Could not delete temporary file: {exc}")