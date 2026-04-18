"""
scraper.py — Fetch job postings from Greenhouse's public board API.

Greenhouse exposes every company's job board as JSON at:
    https://boards-api.greenhouse.io/v1/boards/{company_slug}/jobs?content=true

No auth required. `content=true` returns the full HTML description.

Two filtering stages:
  1. `filter_by_role(jobs, role)` — title keyword match (cheap, deterministic).
  2. `filter_by_level(jobs, level)` — title keyword match for seniority
     (e.g. new_grad). A second-stage filter on `years_experience_min` runs
     AFTER extraction, in pipeline.py.
"""

from __future__ import annotations

import html
import json
import re
import time
from pathlib import Path
from typing import Iterable

import requests

GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw_jobs"
RAW_DIR.mkdir(parents=True, exist_ok=True)


# --- Default companies ------------------------------------------------------
# Curated Greenhouse boards. Grouped by sector so it's easy to swap in/out.
# Some slugs may 404 — that's fine; fetch_all handles each company independently
# and logs the failure. Aim: enough volume that 6 roles × new-grad filter still
# yields 250+ matches per role.
DEFAULT_COMPANIES: list[str] = [
    # Consumer / marketplaces
    "airbnb", "stripe", "figma", "lyft", "instacart", "doordash",
    "dropbox", "pinterest", "reddit", "twitch", "robinhood", "coinbase",
    "duolingo", "opendoor", "squarespace", "faire",
    # Data / infra / developer tools
    "databricks", "snowflake", "datadog", "cloudflare", "mongodb",
    "hashicorp", "elastic", "confluent", "gitlab", "retool",
    "postman", "vercel", "linear", "netlify",
    # Fintech
    "affirm", "brex", "ramp", "plaid", "mercury", "wise", "chime",
    "marqeta", "gusto",
    # Productivity / SaaS
    "asana", "notion", "canva", "airtable", "miro",
    # AI / ML
    "anthropic", "scaleai", "huggingface", "cohere",
    # Communications / identity
    "twilio", "okta",
    # Enterprise / other
    "segment", "samsara", "rippling",
]


def strip_html(raw: str) -> str:
    """Crude HTML-to-text. Good enough for job descriptions."""
    if not raw:
        return ""
    text = html.unescape(raw)
    text = re.sub(r"</(p|div|li|h[1-6]|br|ul|ol)>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def fetch_company_jobs(company_slug: str, timeout: int = 30) -> list[dict]:
    """Pull every posting from a single Greenhouse-hosted board."""
    url = GREENHOUSE_URL.format(slug=company_slug)
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()
    jobs = payload.get("jobs", []) or []

    normalized = []
    for j in jobs:
        normalized.append(
            {
                "job_id": f"{company_slug}-{j.get('id')}",
                "company": company_slug,
                "title": j.get("title", "").strip(),
                "location": (j.get("location") or {}).get("name", ""),
                "absolute_url": j.get("absolute_url", ""),
                "updated_at": j.get("updated_at", ""),
                "description_html": j.get("content", "") or "",
                "description_text": strip_html(j.get("content", "") or ""),
                "departments": [d.get("name") for d in j.get("departments", []) or []],
            }
        )
    return normalized


def fetch_all(
    companies: Iterable[str],
    sleep_between: float = 0.6,
    use_cache: bool = True,
) -> list[dict]:
    """
    Fetch jobs for every company slug. Caches each board to data/raw_jobs/{slug}.json.
    Re-runs hit the cache (fast) unless use_cache=False.
    """
    all_jobs: list[dict] = []
    total = list(companies)
    for i, slug in enumerate(total, 1):
        cache = RAW_DIR / f"{slug}.json"
        if use_cache and cache.exists():
            try:
                jobs = json.loads(cache.read_text(encoding="utf-8"))
                print(f"[{i:>2}/{len(total)}] {slug:<15} ✓ {len(jobs):>4} jobs (cached)")
                all_jobs.extend(jobs)
                continue
            except Exception:
                pass  # fall through to refetch

        try:
            jobs = fetch_company_jobs(slug)
            cache.write_text(json.dumps(jobs, indent=2), encoding="utf-8")
            print(f"[{i:>2}/{len(total)}] {slug:<15} ✓ {len(jobs):>4} jobs")
            all_jobs.extend(jobs)
        except requests.HTTPError as e:
            print(f"[{i:>2}/{len(total)}] {slug:<15} ✗ HTTP {e.response.status_code} (skipping)")
        except Exception as e:
            print(f"[{i:>2}/{len(total)}] {slug:<15} ✗ {type(e).__name__}: {e}")
        time.sleep(sleep_between)
    return all_jobs


# --- Role filtering ---------------------------------------------------------
# Keyword phrases are matched as substrings in the lowercased title. Each role
# is kept deliberately tight so one title doesn't match multiple roles.
ROLE_KEYWORDS: dict[str, list[str]] = {
    "data_analyst": [
        "data analyst",
        "analytics",          # broad — catches "Marketing Analytics", "Growth Analytics"
        "business intelligence",
        "bi analyst", "bi engineer",
        "product analyst",
        "insights analyst",
        "reporting analyst",
        "data & insights", "data and insights",
        "marketing analyst", "growth analyst",
        "business analyst",
        "decision science", "decision scientist",
        "quantitative analyst", "quant analyst",
    ],
    "data_engineer": [
        "data engineer",
        "data engineering",
        "analytics engineer",
        "etl engineer",
        "data platform engineer",
        "data platform",
        "data infrastructure",
        "data warehouse engineer",
        "pipeline engineer",
        "big data engineer",
    ],
    "data_scientist": [
        # Intentionally does NOT include 'ml engineer' — that's its own role.
        "data scientist",
        "applied scientist",
        "research scientist",
        "applied research",
        "ai researcher", "ml researcher",
        "statistician",
    ],
    "ml_engineer": [
        "ml engineer", "mle",
        "machine learning engineer",
        "ai engineer",
        "ai/ml engineer",
        "deep learning engineer",
        "nlp engineer",
        "computer vision engineer",
        "ml platform",
        "mlops",
        "ml infrastructure",
    ],
    "fullstack_engineer": [
        "full stack", "full-stack", "fullstack",
        "software engineer",
        "software developer",
        "product engineer",
        "swe",
        "application engineer",
    ],
    "product_manager": [
        "product manager",
        "product management",
        "associate product manager",
        "apm",
        "technical product manager",
        "tpm",
        "group product manager",  # we'll level-filter these out
        "product owner",
    ],
    # Kept for backwards compatibility — not part of the 6 demo roles.
    "backend_engineer": [
        "backend", "back-end", "back end",
        "server engineer", "platform engineer",
        "api engineer", "services engineer",
        "infrastructure engineer",
        "distributed systems", "systems engineer",
    ],
    "frontend_engineer": [
        "frontend", "front-end", "front end",
        "ui engineer", "ui/ux engineer",
        "web engineer", "client engineer",
        "react engineer",
    ],
}


def filter_by_role(jobs: list[dict], role_key: str) -> list[dict]:
    """Keep jobs whose title matches the keyword list for `role_key`."""
    keywords = ROLE_KEYWORDS.get(role_key)
    if keywords is None:
        raise ValueError(
            f"Unknown role '{role_key}'. Options: {list(ROLE_KEYWORDS.keys())}"
        )
    out = []
    for j in jobs:
        t = j.get("title", "").lower()
        if any(kw in t for kw in keywords):
            out.append(j)
    return out


# --- Level filtering --------------------------------------------------------
# New-grad signals use a two-tier positive/negative scheme to handle tricky
# compound titles like "Associate Product Manager" (contains ' manager' but
# is actually new-grad).
#
# Decision rule (per title, in order):
#   1. If any STRONG_NEGATIVE matches  → REJECT  (e.g. "Senior ...", "Staff ...")
#   2. Else if any STRONG_POSITIVE matches → ACCEPT
#      (these override soft negatives; "Associate Product Manager" wins)
#   3. Else if any SOFT_POSITIVE matches AND no SOFT_NEGATIVE matches → ACCEPT
#   4. Else → REJECT
LEVEL_KEYWORDS: dict[str, dict[str, list[str]]] = {
    "new_grad": {
        # Unambiguous new-grad markers — accept even if a soft-negative also matches.
        "strong_positive": [
            "new grad", "new graduate",
            "early career", "early-career", "early in career",
            "entry level", "entry-level",
            "graduate program", "graduate engineer",
            "rotational program",
            "junior",
            "intern", "internship", "summer intern",
            "co-op", "coop",
            "fellow", "fellowship",
            "apprentice", "apprenticeship",
            "associate software engineer",
            "associate product manager",
            "associate data",
            "associate engineer",
            "apm",
            "software engineer i,", "software engineer i ",
            "software engineer 1 ",
        ],
        # Weaker signals — only accept if no soft-negative is also present.
        "soft_positive": [
            "university grad", "university graduate",
            "college grad", "college graduate",
            "university",
            "graduate",
        ],
        # Seniority markers that ALWAYS reject, even if a positive is present.
        "strong_negative": [
            "senior", "sr.", " sr ",
            "staff", "principal",
            "head of", "head,",
            " vp ", "vice president",
            "director",
            "distinguished",
            " ii,", " ii ", " iii", " iv",
        ],
        # Ambiguous seniority markers — reject only in absence of strong_positive.
        "soft_negative": [
            " lead ", "lead,", "lead ",
            " manager", "manager,",
            "architect",
            "expert",
        ],
    },
}


def _title_has_any(title_lower: str, phrases: list[str]) -> bool:
    return any(p in title_lower for p in phrases)


def filter_by_level(jobs: list[dict], level_key: str) -> list[dict]:
    """
    Title-stage level filter. Intentionally generous — the real level enforcement
    happens post-extraction (via years_experience_min).

    Decision rule (in order):
      1. Title has STRONG_NEGATIVE (senior/staff/principal/...) → REJECT
      2. Title has STRONG_POSITIVE (new grad/intern/junior/...) → ACCEPT
      3. Title has SOFT_NEGATIVE (manager/lead/architect/...) → REJECT
         (these are typically mid-to-senior if no positive signal is present)
      4. Title has SOFT_POSITIVE (university/graduate/college/...) → ACCEPT
      5. Otherwise (neutral title like "Data Analyst") → ACCEPT
         The post-extraction check (years_experience_min ≤ 3) decides.

    Rationale: most entry-level jobs aren't labeled — they just say
    "Data Analyst" or "Software Engineer". Rejecting neutral titles gave us
    only 5 DA matches out of 143. Accepting them + trusting the JD's stated
    experience requirement is more accurate.
    """
    spec = LEVEL_KEYWORDS.get(level_key)
    if spec is None:
        raise ValueError(
            f"Unknown level '{level_key}'. Options: {list(LEVEL_KEYWORDS.keys())}"
        )
    out = []
    for j in jobs:
        t = " " + j.get("title", "").lower() + " "
        if _title_has_any(t, spec["strong_negative"]):
            continue
        if _title_has_any(t, spec["strong_positive"]):
            out.append(j)
            continue
        if _title_has_any(t, spec["soft_negative"]):
            continue
        # Title is either soft_positive or neutral — accept either way.
        out.append(j)
    return out


if __name__ == "__main__":
    # Smoke test: fetch one board, filter by role + new-grad level.
    jobs = fetch_company_jobs("stripe")
    print(f"\nFetched {len(jobs)} jobs from stripe")
    for role in ["data_analyst", "fullstack_engineer", "product_manager"]:
        role_jobs = filter_by_role(jobs, role)
        ng_jobs = filter_by_level(role_jobs, "new_grad")
        print(f"  {role:<22} {len(role_jobs):>4} role / {len(ng_jobs):>3} new-grad")
        for j in ng_jobs[:3]:
            print(f"      • {j['title']}")
