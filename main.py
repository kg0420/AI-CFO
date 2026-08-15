# pip install sqlalchemy
from fastapi import FastAPI, File, UploadFile, Request, Form, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from typing import List, Optional
import shutil
from fastapi import Body
import os
import pandas as pd
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

# Auth & Security Imports
import jwt
import bcrypt

# Database Imports (SQLAlchemy)
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import declarative_base, sessionmaker, Session

# Your custom imports (Make sure these files exist in your project)
from expense_processing import load_all_expenses, save_expenses, format_manual_entry
from report_utils import render_report_response
from ocr_extraction import process_invoice 
from google import genai
from dotenv import load_dotenv
from fastapi.templating import Jinja2Templates

load_dotenv()
app = FastAPI()

templates = Jinja2Templates(directory="templates")
api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    raise ValueError("GEMINI_API_KEY is missing! Check your .env file.")

client = genai.Client(api_key=api_key)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Ensure directories exist
os.makedirs("temp_uploads", exist_ok=True)
os.makedirs("data", exist_ok=True)

# ==================== DATABASE SETUP (SQLAlchemy) ====================

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

executor = ThreadPoolExecutor(max_workers=4)

@app.post("/generate-report", response_class=HTMLResponse)
async def generate_report(request: Request, receipts: List[UploadFile] = File(...), db: Session = Depends(get_db)):
    """Receives files, processes them through PaddleOCR, tags them, and renders report."""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/auth", status_code=302)

    temp_paths = []
    for file in receipts:
        if not file.filename:
            continue
        temp_file_path = f"temp_uploads/{file.filename}"
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        temp_paths.append(temp_file_path)
        
    loop = asyncio.get_event_loop()
    tasks = [
        loop.run_in_executor(executor, process_invoice, path)
        for path in temp_paths
    ]
    extracted_results = await asyncio.gather(*tasks)

    all_extracted_data = []
    for extracted_json in extracted_results:
        if extracted_json:
            extracted_json["data_source"] = "ai_ocr"
            # Optional: Link expense to user
            extracted_json["user"] = user 
            all_extracted_data.append(extracted_json)
            
    save_expenses(all_extracted_data)
    return render_report_response(request, all_extracted_data)

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
    manual_data["user"] = user

    save_expenses([manual_data])
    return render_report_response(request, [manual_data])

@app.post("/api/chat")
async def chat_with_cfo(request: Request, payload: dict = Body(...), db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})

    user_message = payload.get("message")
    if not user_message:
        return JSONResponse(status_code=400, content={"error": "Message is required"})

    expenses = load_all_expenses()
    
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
            model='gemini-2.5-flash',
            contents=prompt
        )
        return {"reply": response.text}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})