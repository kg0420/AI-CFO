import json

from .settings import (
    SCHEMA_PATH,
    SYSTEM_PROMPT_PATH,
    # CORRECTION_PROMPT_PATH,
)


def load_json_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_text_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


FINANCIAL_JSON_SCHEMA = load_json_file(SCHEMA_PATH)

DEFAULT_SYSTEM_PROMPT = load_text_file(
    SYSTEM_PROMPT_PATH
)

# CORRECTION_PROMPT = load_text_file(
#     CORRECTION_PROMPT_PATH
# )