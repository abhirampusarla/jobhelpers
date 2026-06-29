"""Configuration for the resume maker."""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")
PROMPTS_FILE = BASE_DIR / "prompts.yaml"
OUTPUT_DIR = BASE_DIR / "outputs"
BASE_RESUME_PATH = Path(
    os.environ.get("BASE_RESUME_PATH", BASE_DIR / "base_resume.docx")
).expanduser()
OUTPUT_NAME_PREFIX = os.environ.get("OUTPUT_NAME_PREFIX", "ABHIRAM").strip()

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip()
OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "openai").strip().lower()
CLAUDE_API_KEY = (
    os.environ.get("CLAUDE_API_KEY", "").strip()
    or os.environ.get("ANTHROPIC_API_KEY", "").strip()
)
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-3-5-haiku-20241022").strip()
ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = os.environ.get("ANTHROPIC_VERSION", "2023-06-01").strip()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash").strip()
GEMINI_GENERATE_CONTENT_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

REQUEST_TIMEOUT = 30
LLM_TIMEOUT = 60
LLM_MAX_RETRIES = int(os.environ.get("LLM_MAX_RETRIES", "3"))
LLM_RETRY_SECONDS = int(os.environ.get("LLM_RETRY_SECONDS", "20"))
LLM_MAX_OUTPUT_TOKENS = int(os.environ.get("LLM_MAX_OUTPUT_TOKENS", "8192"))
MAX_JOB_TEXT_CHARS = 30000
MAX_RESUME_CHARS = 30000

SESSION_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}
