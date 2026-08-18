# 🤖 AI CFO — Intelligent Expense & Financial Dashboard

[![Python](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![PaddleOCR](https://img.shields.io/badge/PaddleOCR-Powered-orange.svg)](https://github.com/PaddlePaddle/PaddleOCR)
[![Gemini](https://img.shields.io/badge/Google_Gemini-2.5_Flash-8A2BE2.svg)](https://ai.google.dev/)

AI CFO is an end-to-end intelligent personal finance application that transforms raw, unstructured receipts into actionable financial insights.

The application combines **PaddleOCR** for automated receipt extraction with **Google Gemini 2.5 Flash** for AI-powered financial analysis and conversational assistance. Users can upload receipts, track expenses, visualize spending patterns, and interact with an AI financial advisor that understands their ledger.

---

## ✨ Features

### 📄 1. Automated Receipt Processing

* **Batch Processing:** Upload multiple receipts simultaneously.
* **Concurrent OCR:** Uses Python's `asyncio` and `ThreadPoolExecutor` to process multiple receipts concurrently.
* **Smart Extraction:** Extracts important financial information including:

  * Merchant name
  * Invoice/receipt date
  * Base amount
  * Tax amount
  * Grand total
  * Line items

---

### 📊 2. Interactive Financial Analytics

The application normalizes extracted financial data using **Pandas** and generates interactive visualizations using **Plotly**.

#### Available Visualizations

* 🍩 **Donut Chart** — Expense breakdown by category.
* 📊 **Bar Chart** — Total spending by top vendors.
* 📈 **Line Chart** — Spending trends over time.
* 🥞 **Stacked Bar Chart** — Tax vs. base amount by vendor.
* 🟩 **Treemap** — Hierarchical spending breakdown:
  `Total Spend → Category → Vendor`
* 🥧 **Pie Chart** — Automated OCR expenses vs. manual entries.

---

### 💬 3. AI Financial Advisor

The built-in AI assistant uses **Google Gemini 2.5 Flash** to analyze the user's financial ledger.

#### Key Capabilities

* **Context-Aware Analysis:** Converts the financial ledger into a lightweight CSV representation before sending relevant context to Gemini.
* **Conversational Interface:** Ask questions about your expenses directly from the dashboard.
* **Actionable Insights:** Receive concise financial analysis based on your actual ledger.
* **HTML Responses:** Gemini responses are formatted as HTML for clean rendering inside the dashboard.

---

### ✍️ 4. Human-in-the-Loop Data Entry

OCR may occasionally fail on blurry, damaged, or incomplete receipts.

AI CFO provides a **manual expense entry** workflow that allows users to enter:

* Merchant
* Date
* Amount
* Category
* Description

Manual entries are normalized into the same structure used by automatically extracted expenses.

---

## 🏗️ System Architecture

```text
┌─────────────────────────────┐
│          User Interface     │
│      HTML / Jinja2 / CSS    │
└──────────────┬──────────────┘
               │
        ┌──────┴───────┐
        │              │
     Uploads       Chat Queries
        │              │
        ▼              ▼
┌─────────────────────────────────┐
│          FastAPI Backend        │
└──────────────┬──────────────────┘
               │
       ┌───────┴────────┐
       │                │
       ▼                ▼
┌──────────────┐  ┌────────────────┐
│  PaddleOCR   │  │ Google Gemini  │
│ Receipt OCR  │  │  2.5 Flash     │
└──────┬───────┘  └───────┬────────┘
       │                  │
       ▼                  │
┌─────────────────┐       │
│ Pandas          │       │
│ Data Processing │◄──────┘
└────────┬────────┘
         │
         ▼
┌─────────────────────────┐
│ Plotly Analytics        │
│ Dashboard               │
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│ data/expenses.json      │
│ Central Financial Ledger│
└─────────────────────────┘
```

---

## 🛠️ Tech Stack

| Technology                  | Purpose                              |
| --------------------------- | ------------------------------------ |
| **Python**                  | Core programming language            |
| **FastAPI**                 | Backend API and web server           |
| **PaddleOCR**               | Receipt text extraction              |
| **Google Gemini 2.5 Flash** | AI financial analysis                |
| **Pandas**                  | Data processing and normalization    |
| **Plotly**                  | Interactive financial visualizations |
| **Jinja2**                  | HTML template rendering              |
| **SQLAlchemy**              | User authentication database         |
| **SQLite**                  | User account storage                 |
| **bcrypt**                  | Password hashing                     |
| **PyJWT**                   | Authentication tokens                |
| **HTML/CSS/JavaScript**     | Frontend interface                   |

---

# 🚀 Installation & Setup

## 1. Prerequisites

Make sure you have:

* Python **3.9, 3.10, or 3.11**
* Google Gemini API key
* Git
* C++ Build Tools on Windows if required by your PaddleOCR/PaddlePaddle setup

You can obtain a Gemini API key from **Google AI Studio**.

---

## 2. Clone the Repository

```bash
git clone https://github.com/kg0420/AI_CFO.git
cd AI_CFO
```


---

## 3. Create a Virtual Environment

### Windows

```bash
python -m venv venv
venv\Scripts\activate
```

### macOS / Linux

```bash
python3 -m venv venv
source venv/bin/activate
```

---

## 4. Install Dependencies

Install the core dependencies:

```bash
pip install fastapi uvicorn pandas plotly google-genai python-dotenv python-multipart jinja2 sqlalchemy PyJWT bcrypt
```

### Install PaddleOCR

PaddleOCR requires PaddlePaddle as its backend.

For a CPU-based setup, install PaddlePaddle according to your operating system and Python version, then install PaddleOCR:

```bash
python -m pip install paddlepaddle
pip install "paddleocr>=2.0.1"
```

> **Note:** PaddlePaddle installation can vary depending on your operating system, Python version, CPU architecture, and whether you are using CPU or GPU acceleration. Refer to the official PaddleOCR/PaddlePaddle installation instructions if the standard command does not work.

---

## 5. Configure Environment Variables

Create a `.env` file in the project root:

```env
GEMINI_API_KEY=your_actual_gemini_api_key
SECRET_KEY=your_long_random_secret_key
```

**Do not commit `.env` to GitHub.**

Add the following to `.gitignore`:

```text
.env
venv/
.venv/
__pycache__/
*.pyc
temp_uploads/
```

---

## 6. Run the Application

Start the FastAPI development server:

```bash
uvicorn main:app --reload
```

Open your browser and navigate to:

```text
http://localhost:8000
```

---

# 🌐 API Endpoints

| Method | Endpoint              | Description                                                        |
| ------ | --------------------- | ------------------------------------------------------------------ |
| `GET`  | `/`                   | Renders the main dashboard and expense interface.                  |
| `GET`  | `/auth`               | Renders the authentication page.                                   |
| `POST` | `/register`           | Creates a new user account.                                        |
| `POST` | `/login`              | Authenticates a user and creates a JWT session.                    |
| `GET`  | `/logout`             | Logs the current user out.                                         |
| `POST` | `/generate-report`    | Processes uploaded receipts and generates the financial dashboard. |
| `POST` | `/add-manual-expense` | Adds a manually entered expense.                                   |
| `POST` | `/api/chat`           | Sends a financial question to the AI CFO assistant.                |

---

# 🤖 Example AI CFO Queries

Once your ledger contains financial data, try asking:

```text
What is my highest spending category this month?

Are there any anomalies or duplicate charges from this vendor?

Summarize my spending trends in 3 bullet points.

Calculate the total amount of tax I paid across all my receipts.

Which vendor do I spend the most money with?

What are my biggest areas of unnecessary spending?
```

---

# 📁 Project Structure

```text
AI_CFO/
│
├── main.py
├── ocr_extraction.py
├── expense_processing.py
├── report_utils.py
│
├── requirements.txt
├── .env
├── .gitignore
│
├── data/
│   ├── expenses.json
│   └── users.db
│
├── temp_uploads/
│
├── static/
│   ├── css/
│   └── js/
│
└── templates/
    ├── auth.html
    ├── index.html
    └── report.html
```

### Core Files

| File                    | Responsibility                                                                  |
| ----------------------- | ------------------------------------------------------------------------------- |
| `main.py`               | FastAPI application, authentication, API routes, OCR orchestration, and AI chat |
| `ocr_extraction.py`     | PaddleOCR initialization and receipt extraction                                 |
| `expense_processing.py` | Expense data processing and JSON ledger operations                              |
| `report_utils.py`       | Report/dashboard rendering utilities                                            |
| `templates/auth.html`   | Login and registration interface                                                |
| `templates/index.html`  | Receipt upload and manual expense interface                                     |
| `templates/report.html` | Financial analytics dashboard and AI assistant                                  |
| `data/expenses.json`    | Central expense ledger                                                          |
| `data/users.db`         | SQLite database containing user accounts                                        |

---

# 🔐 Authentication & Security

AI CFO includes a basic authentication system using:

* **bcrypt** for password hashing.
* **JWT** for session authentication.
* **HTTP-only cookies** for storing authentication tokens.
* **SQLite + SQLAlchemy** for user account management.
* Environment variables for sensitive API keys and secrets.

> For production deployments, use a strong `SECRET_KEY` and a persistent production database such as PostgreSQL instead of relying on local SQLite storage.

---

# ☁️ Deployment on Render

AI CFO can be deployed as a **FastAPI Web Service** on Render.

### Build Command

```bash
pip install -r requirements.txt
```

### Start Command

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

### Required Environment Variables

Add these variables in the Render dashboard:

```text
GEMINI_API_KEY=your_gemini_api_key
SECRET_KEY=your_production_secret_key
```

> **Important:** Local files such as `users.db` and `expenses.json` should not be treated as permanent storage on an ephemeral deployment environment. For a production deployment, migrate persistent application data to a managed database.

---

# 🔮 Roadmap

* [ ] **Database Migration** — Move the expense ledger from JSON to SQLite/PostgreSQL for better concurrency and CRUD operations.
* [ ] **Data Export** — Add one-click CSV and PDF exports for financial/tax reporting.
* [ ] **Budget Alerts** — Allow users to define category budgets and receive burn-rate warnings.
* [ ] **Receipt Compression** — Downscale receipt images before OCR to improve processing speed.
* [ ] **Advanced Financial Insights** — Add forecasting and spending trend prediction.
* [ ] **Multi-User Data Isolation** — Fully isolate financial data between authenticated users.

---

# 🤝 Contributing

Contributions, issues, and feature requests are welcome.

1. Fork the repository.
2. Create a feature branch.
3. Make your changes.
4. Commit your changes.
5. Push the branch.
6. Open a Pull Request.

---

# 📄 License

This project is licensed under the **MIT License**.

---

## ⭐ Support

If you find AI CFO useful, consider giving the repository a ⭐ on GitHub.
