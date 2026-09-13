import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

# ============================================================
# BASE PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

CONFIG_DIR = BASE_DIR / "config"
DATABASE_DIR = BASE_DIR / "database"


# ============================================================
# CONFIG FILES
# ============================================================

SCHEMA_PATH = CONFIG_DIR / "financial_schema.json"
SYSTEM_PROMPT_PATH = CONFIG_DIR / "system_prompt.txt"
# CORRECTION_PROMPT_PATH = CONFIG_DIR / "correction_prompt.txt"


# ============================================================
# DATABASE
# ============================================================

DATABASE_PATH = DATABASE_DIR / "ai_cfo_database.json"
LOG_PATH = DATABASE_DIR / "ai_cfo_logs.txt"


# ============================================================
# GROQ
# ============================================================

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

if not GROQ_API_KEY:
    raise ValueError("❌ GROQ_API_KEY is not set.")

GROQ_MODEL = "openai/gpt-oss-20b"


# ============================================================
# OCR PERFORMANCE
# ============================================================

OCR_CPU_THREADS = 8
MAX_IMAGE_WIDTH = 1200
MAX_GROQ_WORKERS = 5


# ============================================================
# PADDLE PERFORMANCE
# ============================================================

os.environ["PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT"] = "1"
os.environ["OMP_NUM_THREADS"] = str(OCR_CPU_THREADS)
os.environ["MKL_NUM_THREADS"] = str(OCR_CPU_THREADS)