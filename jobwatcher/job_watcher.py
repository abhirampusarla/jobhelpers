"""
Job Opening Watcher
Scans career pages and LLM web search for AI, data, and analyst roles.
Sends an hourly Gmail report with apply links and optional LLM ranking.
"""

import json
import smtplib
import schedule
import time
import logging
import unicodedata
import html
import re
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header

import requests
from bs4 import BeautifulSoup

try:
    from . import constants
except ImportError:
    import constants

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(constants.LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

companies = constants.COMPANIES

def load_prompts() -> dict[str, str]:
    prompts = {}
    current_key = None
    current_lines = []

    def flush_current():
        if current_key:
            prompts[current_key] = "\n".join(current_lines).strip()

    try:
        lines = constants.PROMPTS_FILE.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        log.error(f"Could not read prompts file: {e}")
        raise SystemExit("Missing prompts.yaml")

    for line in lines:
        if current_key and (line.startswith("  ") or not line.strip()):
            current_lines.append(line[2:] if line.startswith("  ") else "")
            continue

        flush_current()
        current_key = None
        current_lines = []

        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.endswith(": |"):
            current_key = stripped[:-3].strip()
            continue

        if ":" in stripped:
            key, value = stripped.split(":", 1)
            prompts[key.strip()] = value.strip().strip('"')

    flush_current()
    required_keys = {"search_jobs", "rank_system", "rank_user"}
    missing_keys = sorted(required_keys - prompts.keys())
    if missing_keys:
        raise SystemExit(f"prompts.yaml missing required prompt(s): {', '.join(missing_keys)}")
    return prompts

prompts = load_prompts()

def render_prompt(template: str, **values: object) -> str:
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace(f"{{{key}}}", str(value))
    return rendered

# ── Startup validation ────────────────────────────────────────────────────────

def validate_config():
    errors = []
    if not constants.GMAIL_USER or constants.GMAIL_USER == "you@gmail.com":
        errors.append("GMAIL_USER not set in .env")
    if not constants.GMAIL_PASSWORD:
        errors.append("GMAIL_APP_PASSWORD not set in .env")
    if not constants.ALERT_TO:
        errors.append("ALERT_TO not set in .env")
    if constants.LLM_PROVIDER not in {"openai", "claude", "gemini"}:
        errors.append("LLM_PROVIDER must be 'openai', 'claude', or 'gemini'")
    if constants.LLM_PROVIDER == "openai" and not constants.OPENAI_API_KEY:
        log.warning("OPENAI_API_KEY not set -- using rule-based report notes instead of LLM ranking.")
    if constants.LLM_PROVIDER == "claude" and not constants.CLAUDE_API_KEY:
        log.warning("CLAUDE_API_KEY or ANTHROPIC_API_KEY not set -- using rule-based report notes instead of LLM ranking.")
    if constants.LLM_PROVIDER == "gemini" and not constants.GEMINI_API_KEY:
        log.warning("GEMINI_API_KEY not set -- using rule-based report notes instead of LLM ranking.")
    if errors:
        for e in errors:
            log.error(f"Config error: {e}")
        raise SystemExit("Fix your .env file and restart.")

# ── Persistent memory ─────────────────────────────────────────────────────────

def load_seen() -> set:
    try:
        if constants.SEEN_FILE.exists():
            data = json.loads(constants.SEEN_FILE.read_text(encoding="utf-8"))
            return set(data) if isinstance(data, list) else set()
    except (json.JSONDecodeError, OSError) as e:
        log.warning(f"Could not read seen_jobs.json ({e}) — starting fresh.")
    return set()

def save_seen(seen: set):
    try:
        tmp = constants.SEEN_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(sorted(seen), indent=2), encoding="utf-8")
        tmp.replace(constants.SEEN_FILE)   # atomic write — no partial saves
    except OSError as e:
        log.error(f"Could not save seen_jobs.json: {e}")

# ── Text helpers ──────────────────────────────────────────────────────────────

def normalize(text: str) -> str:
    """Normalize unicode to closest ASCII equivalent (e.g. curly quotes -> straight)."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").strip()

def safe_text(text: str) -> str:
    """Keep unicode intact but strip control characters."""
    return "".join(c for c in text if not unicodedata.category(c).startswith("C")).strip()

def esc(text: object) -> str:
    return html.escape(safe_text(str(text)), quote=True)

# ── Role filtering ────────────────────────────────────────────────────────────

def is_target_role(title: str, location: str = "") -> bool:
    if not title or not title.strip():
        return False

    t = title.lower()
    l = location.lower()

    # Skip engineering / non-target roles
    if any(kw in t for kw in constants.IGNORE_KEYWORDS):
        return False

    # Location check — only flag non-USA if we have a real location string
    if l and len(l) > 2:
        if any(sig in l for sig in constants.NON_USA_SIGNALS):
            return False
        # If location is very specific and has no USA signal, skip
        has_usa = any(sig in l for sig in constants.USA_SIGNALS)
        if not has_usa and len(l) > 10:
            return False

    # Must match a complete role phrase, not loose substrings like "ai" in "paid".
    return any(re.search(pattern, t) for pattern in constants.TARGET_ROLE_PATTERNS)

# ── HTTP helper ───────────────────────────────────────────────────────────────

session = requests.Session()
session.headers.update(constants.SESSION_HEADERS)

def get_url(url: str) -> requests.Response | None:
    for attempt in range(1, constants.MAX_RETRIES + 2):
        try:
            resp = session.get(url, timeout=constants.REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp
        except requests.exceptions.Timeout:
            log.warning(f"Timeout on attempt {attempt}: {url}")
        except requests.exceptions.HTTPError as e:
            log.warning(f"HTTP {e.response.status_code} for {url}")
            return None   # don't retry 4xx
        except requests.exceptions.RequestException as e:
            log.warning(f"Request error attempt {attempt}: {e}")
        time.sleep(2)
    return None

# ── Scrapers ──────────────────────────────────────────────────────────────────

def make_job(company_name: str, title: str, location: str, url: str, job_id: str) -> dict:
    return {
        "id":         f"{company_name}::{job_id}",
        "company":    safe_text(company_name),
        "title":      safe_text(title),
        "location":   safe_text(location) or "USA (see posting)",
        "url":        url,
        "applicants": "Not listed",
        "deadline":   None,
    }

def make_llm_job(raw: dict) -> dict | None:
    company = safe_text(str(raw.get("company") or "Unknown company"))
    title = safe_text(str(raw.get("title") or ""))
    location = safe_text(str(raw.get("location") or "USA (see posting)"))
    url = safe_text(str(raw.get("apply_url") or raw.get("url") or raw.get("source_url") or ""))

    if not title or not url.startswith("http"):
        return None
    if not is_target_role(title, location):
        return None

    source_url = safe_text(str(raw.get("source_url") or url))
    job_key = normalize(f"{company}-{title}-{location}-{url}").lower().replace(" ", "-")[:180]
    job = make_job(company, title, location, url, f"llm-search::{job_key}")
    job["source"] = "llm_web_search"
    job["source_url"] = source_url
    if raw.get("reason"):
        job["search_reason"] = safe_text(str(raw["reason"]))
    return job

def fetch_greenhouse(company: dict) -> list[dict]:
    resp = get_url(company["jobs_api"])
    if not resp:
        return []
    try:
        data = resp.json()
    except ValueError as e:
        log.warning(f"Bad JSON from Greenhouse for {company['name']}: {e}")
        return []

    jobs = []
    for j in data.get("jobs", []):
        title    = j.get("title", "").strip()
        location = j.get("location", {}).get("name", "").strip()
        url      = j.get("absolute_url", company["careers_url"])
        job_id   = str(j.get("id", ""))
        if title and is_target_role(title, location):
            jobs.append(make_job(company["name"], title, location, url, job_id))
    return jobs

def fetch_scrape(company: dict) -> list[dict]:
    resp = get_url(company["careers_url"])
    if not resp:
        return []

    try:
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        log.warning(f"Parse error for {company['name']}: {e}")
        return []

    seen_ids = set()
    jobs = []

    for a in soup.find_all("a", href=True):
        text = a.get_text(separator=" ", strip=True)
        if not text or len(text) < 5 or len(text) > 150:
            continue

        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript", "mailto")):
            continue
        if not href.startswith("http"):
            from urllib.parse import urljoin
            href = urljoin(company["careers_url"], href)

        if not is_target_role(text):
            continue

        job_id = href.split("/")[-1].split("?")[0] or normalize(text)[:50]
        dedup_key = f"{company['name']}::{job_id}"
        if dedup_key in seen_ids:
            continue
        seen_ids.add(dedup_key)

        jobs.append(make_job(company["name"], text, "", href, job_id))

    return jobs

def fetch_all_jobs() -> list[dict]:
    all_jobs = []
    for co in companies:
        log.info(f"Checking {co['name']}...")
        try:
            if co["source"] == "greenhouse":
                results = fetch_greenhouse(co)
            else:
                results = fetch_scrape(co)
            log.info(f"  {co['name']}: {len(results)} matching role(s) found")
            all_jobs.extend(results)
        except Exception as e:
            log.error(f"Unexpected error fetching {co['name']}: {e}")
    all_jobs.extend(fetch_llm_search_jobs())
    return all_jobs

# ── LLM search/ranking/reporting ──────────────────────────────────────────────

def extract_response_text(data: dict) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]

    chunks = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            text = content.get("text")
            if isinstance(text, str):
                chunks.append(text)
    return "\n".join(chunks).strip()

def parse_json_object(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise

def parse_partial_jobs(text: str) -> list[dict]:
    """Recover valid job objects from a partially malformed {"jobs": [...]} response."""
    jobs_key = text.find('"jobs"')
    if jobs_key < 0:
        return []
    array_start = text.find("[", jobs_key)
    if array_start < 0:
        return []

    decoder = json.JSONDecoder()
    jobs = []
    index = array_start + 1
    while index < len(text):
        while index < len(text) and text[index] in " \n\r\t,":
            index += 1
        if index >= len(text) or text[index] == "]":
            break
        try:
            item, next_index = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            break
        if isinstance(item, dict):
            jobs.append(item)
        index = next_index
    return jobs

def selected_llm_has_key() -> bool:
    if constants.LLM_PROVIDER == "claude":
        return bool(constants.CLAUDE_API_KEY)
    if constants.LLM_PROVIDER == "gemini":
        return bool(constants.GEMINI_API_KEY)
    return bool(constants.OPENAI_API_KEY)

def post_llm_with_retries(provider: str, url: str, headers: dict, payload: dict, params: dict | None = None) -> dict:
    last_error = None
    for attempt in range(1, constants.LLM_MAX_RETRIES + 1):
        try:
            resp = session.post(
                url,
                headers=headers,
                params=params,
                json=payload,
                timeout=constants.LLM_TIMEOUT,
            )
            if resp.status_code == 429:
                retry_after = resp.headers.get("retry-after")
                wait_seconds = int(retry_after) if retry_after and retry_after.isdigit() else constants.LLM_RETRY_SECONDS
                last_error = resp
                if attempt < constants.LLM_MAX_RETRIES:
                    log.warning(f"{provider} rate limited the request. Retrying in {wait_seconds}s ({attempt}/{constants.LLM_MAX_RETRIES})...")
                    time.sleep(wait_seconds)
                    continue
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            last_error = e.response if getattr(e, "response", None) is not None else e
            if attempt < constants.LLM_MAX_RETRIES:
                log.warning(f"{provider} request failed. Retrying in {constants.LLM_RETRY_SECONDS}s ({attempt}/{constants.LLM_MAX_RETRIES}): {e}")
                time.sleep(constants.LLM_RETRY_SECONDS)
                continue
            break

    raise requests.exceptions.RequestException(f"{provider} request failed after retries: {last_error}")

def claude_text(data: dict) -> str:
    chunks = []
    for item in data.get("content", []):
        if item.get("type") == "text" and item.get("text"):
            chunks.append(item["text"])
    return "\n".join(chunks).strip()

def gemini_text(data: dict) -> str:
    chunks = []
    for candidate in data.get("candidates", []):
        content = candidate.get("content", {})
        for part in content.get("parts", []):
            text = part.get("text")
            if text:
                chunks.append(text)
    return "\n".join(chunks).strip()

def gemini_interaction_text(data: dict) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"].strip()

    chunks = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            text = content.get("text")
            if text:
                chunks.append(text)
    for step in data.get("steps", []):
        text = step.get("output_text") or step.get("text")
        if text:
            chunks.append(text)
        for content in step.get("content", []):
            text = content.get("text")
            if text:
                chunks.append(text)
    return "\n".join(chunks).strip()

def call_llm_json_text(system_prompt: str, user_prompt: str, max_tokens: int = 4096) -> str:
    if constants.LLM_PROVIDER == "claude":
        payload = {
            "model": constants.CLAUDE_MODEL,
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        data = post_llm_with_retries(
            "Claude",
            constants.ANTHROPIC_MESSAGES_URL,
            {
                "x-api-key": constants.CLAUDE_API_KEY,
                "anthropic-version": constants.ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            payload,
        )
        return claude_text(data)

    if constants.LLM_PROVIDER == "gemini":
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": system_prompt + "\n\n" + user_prompt}],
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": max_tokens,
                "responseMimeType": "application/json",
            },
        }
        data = post_llm_with_retries(
            "Gemini",
            constants.GEMINI_GENERATE_CONTENT_URL.format(model=constants.GEMINI_MODEL),
            {"Content-Type": "application/json"},
            payload,
            params={"key": constants.GEMINI_API_KEY},
        )
        return gemini_text(data)

    payload = {
        "model": constants.OPENAI_MODEL,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    data = post_llm_with_retries(
        "OpenAI",
        constants.OPENAI_CHAT_COMPLETIONS_URL,
        {
            "Authorization": f"Bearer {constants.OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        payload,
    )
    return data["choices"][0]["message"]["content"]

def call_llm_web_search_text(prompt: str, max_tokens: int = 4096) -> str:
    if constants.LLM_PROVIDER == "claude":
        payload = {
            "model": constants.CLAUDE_MODEL,
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "tools": [
                {
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": constants.LLM_WEB_SEARCH_MAX_USES,
                }
            ],
            "messages": [{"role": "user", "content": prompt}],
        }
        data = post_llm_with_retries(
            "Claude web search",
            constants.ANTHROPIC_MESSAGES_URL,
            {
                "x-api-key": constants.CLAUDE_API_KEY,
                "anthropic-version": constants.ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            payload,
        )
        return claude_text(data)

    if constants.LLM_PROVIDER == "gemini":
        payload = {
            "model": constants.GEMINI_MODEL,
            "input": prompt,
            "tools": [{"type": "google_search"}],
            "generation_config": {
                "temperature": 0.2,
                "max_output_tokens": max_tokens,
            },
        }
        data = post_llm_with_retries(
            "Gemini web search",
            constants.GEMINI_INTERACTIONS_URL,
            {
                "Content-Type": "application/json",
                "x-goog-api-key": constants.GEMINI_API_KEY,
            },
            payload,
        )
        return gemini_interaction_text(data)

    payload = {
        "model": constants.OPENAI_SEARCH_MODEL,
        "tools": [{"type": "web_search"}],
        "tool_choice": "required",
        "text": job_search_response_format(),
        "input": prompt,
    }
    data = post_llm_with_retries(
        "OpenAI web search",
        constants.OPENAI_RESPONSES_URL,
        {
            "Authorization": f"Bearer {constants.OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        payload,
    )
    return extract_response_text(data)

def job_search_response_format() -> dict:
    job_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "company": {"type": "string"},
            "title": {"type": "string"},
            "location": {"type": "string"},
            "apply_url": {"type": "string"},
            "source_url": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["company", "title", "location", "apply_url", "source_url", "reason"],
    }
    return {
        "format": {
            "type": "json_schema",
            "name": "job_search_results",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "jobs": {
                        "type": "array",
                        "items": job_schema,
                    }
                },
                "required": ["jobs"],
            },
        }
    }

def fetch_llm_search_jobs() -> list[dict]:
    if not selected_llm_has_key():
        log.info(f"Skipping LLM web search -- {constants.LLM_PROVIDER} API key is not set.")
        return []

    log.info(f"Searching web with {constants.LLM_PROVIDER} for AI and data roles across companies...")
    prompt = render_prompt(
        prompts["search_jobs"],
        search_limit=constants.LLM_SEARCH_LIMIT,
        search_queries=json.dumps(constants.LLM_SEARCH_QUERIES),
    )

    try:
        response_text = call_llm_web_search_text(prompt, max_tokens=4096)
        data = parse_json_object(response_text)
    except json.JSONDecodeError as e:
        recovered_jobs = parse_partial_jobs(response_text) if "response_text" in locals() else []
        if recovered_jobs:
            log.warning(f"LLM web search returned partial invalid JSON ({e}); recovered {len(recovered_jobs)} job(s).")
            data = {"jobs": recovered_jobs}
        else:
            preview = response_text[:500] if "response_text" in locals() else ""
            log.warning(f"LLM web search returned invalid JSON ({e}). Response preview: {preview}")
            return []
    except (KeyError, ValueError, requests.exceptions.RequestException) as e:
        log.warning(f"LLM web search failed -- continuing with configured career pages only: {e}")
        return []

    jobs = []
    seen_urls = set()
    for raw in data.get("jobs", []):
        if not isinstance(raw, dict):
            continue
        job = make_llm_job(raw)
        if not job or job["url"] in seen_urls:
            continue
        seen_urls.add(job["url"])
        jobs.append(job)

    log.info(f"  LLM web search: {len(jobs)} matching role(s) found")
    return jobs

def maybe_llm_report(jobs: list[dict], new_ids: set[str]) -> dict:
    if not new_ids:
        log.info("Skipping LLM report ranking -- no new roles found.")
        return {
            "headline": f"{len(jobs)} matching job{'s' if len(jobs) != 1 else ''} found.",
            "overview": "No new roles since the last sent report; using rule-based scoring.",
            "jobs": [fallback_job_analysis(j, False) for j in jobs],
        }
    if not constants.ENABLE_LLM_REPORT:
        log.info("Skipping LLM report ranking -- ENABLE_LLM_REPORT is false.")
        return {
            "headline": f"{len(jobs)} matching job{'s' if len(jobs) != 1 else ''} found.",
            "overview": f"{len(new_ids)} new role{'s' if len(new_ids) != 1 else ''} found; using rule-based scoring.",
            "jobs": [fallback_job_analysis(j, j["id"] in new_ids) for j in jobs],
        }
    return llm_report(jobs, new_ids)

def compact_job_for_llm(job: dict, is_new: bool) -> dict:
    return {
        "company": job["company"],
        "title": job["title"],
        "location": job["location"],
        "apply_link": job["url"],
        "source": job.get("source", "career_page"),
        "source_url": job.get("source_url", job["url"]),
        "is_new": is_new,
    }

def fallback_job_analysis(job: dict, is_new: bool) -> dict:
    title = job["title"]
    score = 70
    title_l = title.lower()
    if any(kw in title_l for kw in ("data engineer", "data scientist", "ai engineer", "machine learning", "ml engineer")):
        score += 15
    if any(kw in title_l for kw in ("data analyst", "business analyst", "analytics", "bi analyst")):
        score += 10
    if is_new:
        score += 5

    return {
        "id": job["id"],
        "fit_score": min(score, 95),
        "summary": why_it_matches(title),
        "action": "Review the posting and apply if the responsibilities match your recent experience.",
    }

def llm_report(jobs: list[dict], new_ids: set[str]) -> dict:
    fallback = {
        "headline": f"{len(jobs)} matching job{'s' if len(jobs) != 1 else ''} found.",
        "overview": "Ranked with keyword and location signals because no LLM result was available.",
        "jobs": [fallback_job_analysis(j, j["id"] in new_ids) for j in jobs],
    }

    if not selected_llm_has_key() or not jobs:
        return fallback

    output_schema = {
        "headline": "short report headline",
        "overview": "2 sentence overview",
        "jobs": [
            {
                "id": "company::job_id",
                "fit_score": 0,
                "summary": "why this role fits",
                "action": "what to do next",
            }
        ],
    }
    jobs_for_prompt = [
        {"id": j["id"], **compact_job_for_llm(j, j["id"] in new_ids)}
        for j in jobs[:constants.LLM_REPORT_LIMIT]
    ]

    try:
        content = call_llm_json_text(
            prompts["rank_system"],
            render_prompt(
                prompts["rank_user"],
                output_schema=json.dumps(output_schema, indent=2),
                jobs_json=json.dumps(jobs_for_prompt, indent=2),
            ),
            max_tokens=4096,
        )
        data = parse_json_object(content)
    except (KeyError, ValueError, requests.exceptions.RequestException) as e:
        log.warning(f"LLM report failed -- falling back to rule-based report: {e}")
        return fallback

    by_id = {item.get("id"): item for item in data.get("jobs", []) if isinstance(item, dict)}
    merged_jobs = []
    for job in jobs:
        item = by_id.get(job["id"]) or fallback_job_analysis(job, job["id"] in new_ids)
        merged_jobs.append({
            "id": job["id"],
            "fit_score": int(item.get("fit_score", 70)),
            "summary": safe_text(str(item.get("summary", why_it_matches(job["title"])))),
            "action": safe_text(str(item.get("action", "Review and apply if it fits."))),
        })

    merged_jobs.sort(key=lambda item: item["fit_score"], reverse=True)
    return {
        "headline": safe_text(str(data.get("headline") or fallback["headline"])),
        "overview": safe_text(str(data.get("overview") or fallback["overview"])),
        "jobs": merged_jobs,
    }

# ── Email ─────────────────────────────────────────────────────────────────────

def why_it_matches(title: str) -> str:
    t = title.lower()
    if "data engineer" in t or "data engineering" in t:
        return "Matches your target data engineering roles."
    if "data scientist" in t or "data science" in t:
        return "Matches your target data science roles."
    if "machine learning" in t or "ml " in t or "ai engineer" in t:
        return "Matches your target AI and machine learning roles."
    if "business analyst" in t or "bussiness analyst" in t:
        return "Matches your target business analyst roles."
    if "data analyst" in t or "analyst" in t:
        return "Matches your target analyst roles."
    if "analytics" in t or "business intelligence" in t or "bi analyst" in t:
        return "Matches your target analytics and BI roles."
    return "Matches your target AI, data, analytics, or analyst categories."

def build_email_html(jobs: list[dict], report: dict, new_ids: set[str]) -> str:
    analysis_by_id = {item["id"]: item for item in report.get("jobs", [])}
    sorted_jobs = sorted(
        jobs,
        key=lambda j: analysis_by_id.get(j["id"], {}).get("fit_score", 0),
        reverse=True,
    )

    cards = ""
    for j in sorted_jobs:
        analysis = analysis_by_id.get(j["id"], fallback_job_analysis(j, j["id"] in new_ids))
        title    = esc(j["title"])
        company  = esc(j["company"])
        location = esc(j["location"])
        is_new   = j["id"] in new_ids
        badge    = "New" if is_new else "Seen"
        badge_bg = "#d1fae5" if is_new else "#e5e7eb"
        badge_fg = "#065f46" if is_new else "#374151"
        deadline_row = (
            f"<tr><td style='color:#6b7280;padding:3px 0'>Deadline</td>"
            f"<td style='padding:3px 0'>{esc(j['deadline'])}</td></tr>"
        ) if j.get("deadline") else ""

        cards += f"""
        <div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:10px;padding:16px;margin-bottom:16px;">
          <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:8px">
            <div>
              <p style="margin:0;font-size:16px;font-weight:600;color:#111827">{title}</p>
              <p style="margin:4px 0 0;font-size:13px;color:#6b7280">{company}</p>
            </div>
            <span style="background:{badge_bg};color:{badge_fg};font-size:11px;padding:3px 10px;border-radius:20px;white-space:nowrap;flex-shrink:0">{badge} &middot; {analysis['fit_score']}%</span>
          </div>
          <table style="width:100%;font-size:13px;margin-top:10px;border-collapse:collapse">
            <tr><td style="color:#6b7280;padding:3px 8px 3px 0;width:90px">Location</td><td style="padding:3px 0">{location}</td></tr>
            <tr><td style="color:#6b7280;padding:3px 8px 3px 0">Applicants</td><td style="padding:3px 0">{j['applicants']}</td></tr>
            {deadline_row}
          </table>
          <p style="margin:10px 0 0;font-size:13px;color:#374151;border-left:3px solid #3b82f6;padding-left:8px">{esc(analysis['summary'])}</p>
          <p style="margin:8px 0 0;font-size:13px;color:#4b5563"><strong>Next:</strong> {esc(analysis['action'])}</p>
          <a href="{esc(j['url'])}" style="display:inline-block;margin-top:12px;padding:7px 16px;background:#111827;color:#fff;border-radius:6px;text-decoration:none;font-size:13px">Apply / view posting</a>
        </div>"""

    now_str = datetime.now(constants.CST).strftime("%A, %b %d at %I:%M %p CST")
    count_label = f"{len(jobs)} matching role{'s' if len(jobs) != 1 else ''} found"
    new_label = f"{len(new_ids)} new since last sent"
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:620px;margin:0 auto;padding:24px;color:#111827">
  <p style="font-size:13px;color:#6b7280;margin:0 0 4px">Job Watcher &middot; {now_str}</p>
  <h1 style="margin:0 0 8px;font-size:22px;font-weight:600">{esc(report.get("headline") or count_label)}</h1>
  <p style="margin:0 0 6px;font-size:14px;color:#374151">{esc(report.get("overview") or "")}</p>
  <p style="margin:0 0 20px;font-size:13px;color:#6b7280">{count_label} &middot; {new_label}</p>
  {cards}
  <p style="font-size:12px;color:#9ca3af;margin-top:24px;border-top:1px solid #e5e7eb;padding-top:16px">
    Watching: OpenAI &middot; Anthropic &middot; Perplexity &middot; Cursor &middot; LinkedIn<br>
    Categories: AI &middot; Data Engineering &middot; Data Science &middot; Business Analyst &middot; Data Analyst &middot; Analytics<br>
    <strong>Do not submit anything without reviewing first.</strong>
  </p>
</body></html>"""

def build_empty_report_html() -> str:
    now_str = datetime.now(constants.CST).strftime("%A, %b %d at %I:%M %p CST")
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:620px;margin:0 auto;padding:24px;color:#111827">
  <p style="font-size:13px;color:#6b7280;margin:0 0 4px">Job Watcher &middot; {now_str}</p>
  <h1 style="margin:0 0 12px;font-size:22px;font-weight:600">No matching roles found this hour</h1>
  <p style="font-size:14px;color:#374151;margin:0">The watcher checked configured companies and LLM web search but did not find target AI, data engineering, data science, business analyst, data analyst, or analytics roles.</p>
</body></html>"""

def send_email(jobs: list[dict], report: dict | None = None, new_ids: set[str] | None = None):
    new_ids = new_ids or set()
    companies   = ", ".join(sorted(set(j["company"] for j in jobs))) if jobs else "No matches"
    count_label = f"{len(jobs)} matching role{'s' if len(jobs) != 1 else ''}"
    new_label   = f"{len(new_ids)} new"
    subject     = f"[Job Watcher] Hourly report: {count_label}, {new_label} -- {companies}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"]    = constants.GMAIL_USER
    msg["To"]      = constants.ALERT_TO

    if jobs:
        analysis_by_id = {item["id"]: item for item in (report or {}).get("jobs", [])}
        sorted_jobs = sorted(
            jobs,
            key=lambda j: analysis_by_id.get(j["id"], {}).get("fit_score", 0),
            reverse=True,
        )
        plain = [
            normalize((report or {}).get("headline") or count_label),
            normalize((report or {}).get("overview") or ""),
            "",
        ]
        for j in sorted_jobs:
            analysis = analysis_by_id.get(j["id"], fallback_job_analysis(j, j["id"] in new_ids))
            plain.append(
                f"{normalize(j['company'])} - {normalize(j['title'])}\n"
                f"Fit: {analysis['fit_score']}% | {'NEW' if j['id'] in new_ids else 'seen'}\n"
                f"Location: {normalize(j['location'])}\n"
                f"Why: {normalize(analysis['summary'])}\n"
                f"Next: {normalize(analysis['action'])}\n"
                f"Apply: {j['url']}"
            )
        plain = "\n\n".join(plain)
        html_body = build_email_html(jobs, report or {}, new_ids)
    else:
        plain = "No matching roles found this hour."
        html_body = build_empty_report_html()

    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(constants.GMAIL_USER, constants.GMAIL_PASSWORD)
            server.sendmail(constants.GMAIL_USER, constants.ALERT_TO, msg.as_bytes())
        log.info(f"Hourly report sent to {constants.ALERT_TO} ({len(jobs)} roles)")
        return True
    except smtplib.SMTPAuthenticationError:
        log.error("Gmail auth failed — check your App Password in .env")
    except smtplib.SMTPException as e:
        log.error(f"SMTP error: {e}")
    except OSError as e:
        log.error(f"Network error sending email: {e}")
    return False

# ── Main scan ─────────────────────────────────────────────────────────────────

def scan():
    now = datetime.now(constants.CST)
    log.info(f"=== Scan started at {now.strftime('%I:%M %p CST')} ===")

    seen     = load_seen()
    all_jobs = fetch_all_jobs()

    # Deduplicate within this scan (scraper can return dupes)
    seen_this_scan = set()
    seen_urls = set()
    unique_jobs = []
    for j in all_jobs:
        job_url = j.get("url")
        if j["id"] in seen_this_scan or (job_url and job_url in seen_urls):
            continue
        seen_this_scan.add(j["id"])
        if job_url:
            seen_urls.add(job_url)
        unique_jobs.append(j)

    new_ids = {j["id"] for j in unique_jobs if j["id"] not in seen}
    log.info(f"Total matching: {len(unique_jobs)} | New: {len(new_ids)} | Already seen: {len(seen)}")

    report = maybe_llm_report(unique_jobs, new_ids)
    success = send_email(unique_jobs, report, new_ids)
    if success:
        for job_id in new_ids:
            seen.add(job_id)
        save_seen(seen)
    else:
        log.warning("Email failed -- roles NOT marked as seen; will retry next scan.")

    log.info("=== Scan complete ===\n")

# ── Scheduler ─────────────────────────────────────────────────────────────────

def is_active_hour() -> bool:
    return 7 <= datetime.now(constants.CST).hour < 17  # 7am inclusive, 5pm exclusive

def maybe_scan():
    if not constants.ACTIVE_HOURS_ONLY or is_active_hour():
        scan()
    else:
        log.info(f"Outside active hours ({datetime.now(constants.CST).strftime('%I:%M %p CST')}) -- skipping.")

if __name__ == "__main__":
    validate_config()
    hours_label = "hourly 7am-5pm CST" if constants.ACTIVE_HOURS_ONLY else "hourly, all day"
    log.info(f"Job Watcher starting -- {hours_label}")
    log.info(f"Alerts -> {constants.ALERT_TO}")

    maybe_scan()  # immediate scan on start

    schedule.every().hour.at(":00").do(maybe_scan)

    while True:
        schedule.run_pending()
        time.sleep(30)
