import json
from pathlib import Path

# ============================================================
# BASE DIRECTORIES & CONFIG FILE PATHS
# ============================================================
BASE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = BASE_DIR / "config"

SYSTEM_PROMPT_PATH = CONFIG_DIR / "system_prompt.txt"
FINANCIAL_SCHEMA_PATH = CONFIG_DIR / "financial_schema.json"

# ============================================================
# LOADERS
# ============================================================
def load_text_file(path: Path | str) -> str:
    """Load a text configuration file."""
    try:
        with open(path, "r", encoding="utf-8") as file:
            return file.read().strip()
    except FileNotFoundError:
        raise FileNotFoundError(f"❌ Configuration file not found: {path}")
    except OSError as e:
        raise RuntimeError(f"❌ Failed to read configuration file {path}: {e}")

def load_json_file(path: Path | str) -> dict:
    """Load a JSON configuration file."""
    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        raise FileNotFoundError(f"❌ JSON configuration file not found: {path}")
    except json.JSONDecodeError as e:
        raise ValueError(f"❌ Invalid JSON in {path}: {e}")
    except OSError as e:
        raise RuntimeError(f"❌ Failed to read JSON file {path}: {e}")

# ============================================================
# LOAD APPLICATION CONFIGURATION
# ============================================================
DEFAULT_SYSTEM_PROMPT = load_text_file(SYSTEM_PROMPT_PATH)
FINANCIAL_JSON_SCHEMA = load_json_file(FINANCIAL_SCHEMA_PATH)

# ============================================================
# APPLICATION SETTINGS
# ============================================================
GROQ_MODEL = "openai/gpt-oss-120b"
MAX_GROQ_WORKERS = 5
MAX_IMAGE_WIDTH = 1200  