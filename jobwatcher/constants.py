"""Configuration constants for the job watcher."""

import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

GMAIL_USER = os.environ.get("GMAIL_USER", "").strip()
GMAIL_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "").strip()
ALERT_TO = os.environ.get("ALERT_TO", GMAIL_USER).strip()

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip()
OPENAI_SEARCH_MODEL = os.environ.get("OPENAI_SEARCH_MODEL", "gpt-4o-mini").strip()
OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"

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
GEMINI_INTERACTIONS_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"

ACTIVE_HOURS_ONLY = os.environ.get("ACTIVE_HOURS_ONLY", "false").strip().lower() in {
    "1",
    "true",
    "yes",
}
ENABLE_LLM_REPORT = os.environ.get("ENABLE_LLM_REPORT", "false").strip().lower() in {
    "1",
    "true",
    "yes",
}

SEEN_FILE = BASE_DIR / "seen_jobs.json"
LOG_FILE = BASE_DIR / "job_watcher.log"
PROMPTS_FILE = BASE_DIR / "prompts.yaml"
CST = ZoneInfo("America/Chicago")

REQUEST_TIMEOUT = 20
MAX_RETRIES = 2
LLM_TIMEOUT = 45
LLM_SEARCH_LIMIT = int(os.environ.get("LLM_SEARCH_LIMIT", "10"))
LLM_REPORT_LIMIT = int(os.environ.get("LLM_REPORT_LIMIT", "10"))
LLM_WEB_SEARCH_MAX_USES = int(os.environ.get("LLM_WEB_SEARCH_MAX_USES", "5"))
LLM_MAX_RETRIES = int(os.environ.get("LLM_MAX_RETRIES", "3"))
LLM_RETRY_SECONDS = int(os.environ.get("LLM_RETRY_SECONDS", "20"))

ROLE_FAMILIES = [
    "artificial intelligence",
    "ai",
    "machine learning",
    "ml",
    "data engineering",
    "data engineer",
    "analytics engineering",
    "analytics engineer",
    "data science",
    "data scientist",
    "business analyst",
    "bussiness analyst",
    "data analyst",
    "bi analyst",
    "business intelligence",
    "analytics",
    "decision science",
    "product analyst",
    "marketing analyst",
    "operations analyst",
    "financial analyst",
    "research analyst",
    "prompt engineer",
    "ai engineer",
    "ml engineer",
]

TARGET_ROLE_PATTERNS = [
    r"\b(?:ai|artificial intelligence)\s+(?:engineer|developer|architect|scientist|specialist|analyst|product manager)\b",
    r"\b(?:generative ai|genai|llm|rag|agentic ai)\b",
    r"\b(?:machine learning|ml)\s+(?:engineer|scientist|researcher|developer|architect|specialist)\b",
    r"\bdata\s+(?:engineer|engineering|scientist|science|analyst|analytics|architect|modeler|modeller)\b",
    r"\banalytics\s+(?:engineer|analyst|consultant|specialist|manager)\b",
    r"\b(?:business|bussiness|product|marketing|operations|financial|research)\s+analyst\b",
    r"\b(?:bi analyst|business intelligence)\b",
    r"\bdecision science\b",
    r"\bprompt engineer\b",
]

IGNORE_KEYWORDS = [
    "security",
    "hardware",
    "counsel",
    "legal",
    "recruiter",
]

LLM_SEARCH_QUERIES = [

    "AI Engineer USA",

    "Generative AI Engineer USA",

    "LLM Engineer USA",

    "Machine Learning Engineer USA",

    "Data Engineer USA",

    "Analytics Engineer USA",

    "Data Scientist USA",

    "Data Analyst USA",

    "Business Analyst USA",

    "Product Analyst USA",

    "Operations Analyst USA",

    "Remote USA jobs"

]

USA_SIGNALS = [
    "united states",
    "usa",
    ", us",
    "remote",
    "san francisco",
    "new york",
    "seattle",
    "chicago",
    "austin",
    "boston",
    "los angeles",
    "denver",
    "washington",
    "atlanta",
    "miami",
    "dallas",
    "houston",
    "portland",
]

NON_USA_SIGNALS = [
    "uk",
    "united kingdom",
    "london",
    "canada",
    "toronto",
    "india",
    "berlin",
    "singapore",
    "sydney",
    "paris",
    "amsterdam",
    "dublin",
    "tokyo",
    "beijing",
    "shanghai",
    "seoul",
    "mexico",
]

SESSION_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

COMPANIES = [
    {
        "name": "OpenAI",
        "careers_url": "https://openai.com/careers",
        "jobs_api": "https://boards-api.greenhouse.io/v1/boards/openai/jobs?content=true",
        "source": "greenhouse",
    },
    {
        "name": "Anthropic",
        "careers_url": "https://anthropic.com/careers",
        "jobs_api": "https://boards-api.greenhouse.io/v1/boards/anthropic/jobs?content=true",
        "source": "greenhouse",
    },
    {
        "name": "Perplexity",
        "careers_url": "https://perplexity.ai/careers",
        "jobs_api": None,
        "source": "scrape",
    },
    {
        "name": "Cursor",
        "careers_url": "https://cursor.com/careers",
        "jobs_api": None,
        "source": "scrape",
    },
    {
        "name": "LinkedIn",
        "careers_url": "https://careers.linkedin.com",
        "jobs_api": None,
        "source": "scrape",
    },
]
