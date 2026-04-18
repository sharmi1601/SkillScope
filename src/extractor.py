"""
extractor.py — Turn a raw job description into a structured skill record via an LLM.

Provider-agnostic: supports Groq (Llama 3.x) and Google Gemini. Pick via the
`LLM_PROVIDER` env var — defaults to "gemini" because Gemini's free tier is
vastly more generous than Groq's for this workload.

Design notes:
- Uses the provider's native JSON mode so the LLM can't return broken JSON.
  Eliminates 90% of parsing bugs.
- Caches every result to `data/extractions/{job_id}.json` so restarts after a
  rate-limit hit only re-extract missing jobs.
- `tenacity` retry with exponential backoff for transient 429s.
- Skills come out tagged by JD section (title / requirements / nice_to_have /
  responsibilities) so the downstream scorer can weight "requirements" more
  heavily than "nice-to-have".
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from tenacity import (
    retry,
    retry_if_exception,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

load_dotenv()

EXTRACT_DIR = Path(__file__).resolve().parent.parent / "data" / "extractions"
EXTRACT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Provider selection.
#   LLM_PROVIDER=gemini  (default, recommended — generous free tier)
#   LLM_PROVIDER=groq    (fallback — llama-3.3-70b-versatile)
# ---------------------------------------------------------------------------
_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").lower()
_GROQ_MODEL = os.getenv("GROQ_MODEL_EXTRACTION", "llama-3.3-70b-versatile")
_GEMINI_MODEL = os.getenv("GEMINI_MODEL_EXTRACTION", "gemini-2.0-flash")


def _groq_client():
    from groq import Groq  # lazy import — not everyone has groq installed

    key = os.getenv("GROQ_API_KEY")
    if not key:
        raise RuntimeError(
            "GROQ_API_KEY not set. Copy .env.example to .env and add your key."
        )
    return Groq(api_key=key)


def _gemini_client():
    from google import genai  # lazy import — only needed if provider=gemini

    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY not set. Grab one at https://aistudio.google.com/apikey "
            "and add GEMINI_API_KEY=... to skillscope/.env"
        )
    return genai.Client(api_key=key)


# The prompt is deliberately strict about *what counts as a skill*. Without
# these guardrails, Llama loves to return fluff like "teamwork" and "passion".
SYSTEM_PROMPT = """You are a precise technical recruiter. Your job is to extract CONCRETE, TEACHABLE SKILLS from a job description.

## What counts as a skill

A "skill" is a SPECIFIC, NAMEABLE, LEARNABLE capability. Examples of valid skills:
- Programming languages: Python, SQL, Java, TypeScript, Go
- Libraries/frameworks: React, Django, PyTorch, pandas, Spring Boot
- Tools/platforms: Tableau, Airflow, Docker, Kubernetes, AWS S3, Snowflake, dbt
- Specific techniques: A/B Testing, Causal Inference, Time Series Analysis, ETL, REST API design

## What does NOT count as a skill — NEVER extract these

Fields/domains (too broad, not a skill):
  AI, Artificial Intelligence, Data Analysis, Data Science, Software Development,
  Software Engineering, Programming, Coding, Analytics, Engineering, Research,
  Web Development, Mobile Development, DevOps, Backend, Frontend, Full Stack

Soft skills (not teachable via a course):
  teamwork, communication, leadership, passion, ownership, collaboration,
  problem solving, critical thinking, attention to detail, self-starter,
  team player, adaptability, creativity

Credentials / experience levels:
  Bachelor's degree, Master's degree, PhD, "5 years experience"

## Section tagging — STRICT CLOSED ENUM

For EACH extracted skill, the `section` field MUST be EXACTLY one of these five values.
DO NOT copy the literal header from the job description. Map to the canonical value below:

- "title"            → the skill appears in the job title itself
- "requirements"     → required qualifications, must-haves, minimum qualifications,
                       basic qualifications, "Your Expertise", "What you bring",
                       "What we're looking for", "What you'll need"
- "responsibilities" → day-to-day duties, "What you'll do", "A Typical Day",
                       "The Role", "In this role", "Day-to-day"
- "nice_to_have"     → preferred qualifications, bonus, pluses, "Nice to have",
                       "Bonus points", "It's a plus"
- "qualifications"   → only use this if the section is ambiguous between
                       requirements and nice_to_have (prefer requirements if unsure)

WRONG: {"name": "SQL", "section": "Your Expertise"}
RIGHT: {"name": "SQL", "section": "requirements"}

WRONG: {"name": "Python", "section": "A Typical Day"}
RIGHT: {"name": "Python", "section": "responsibilities"}

## Normalize skill names

Use the canonical form for well-known skills:
- "Postgres" | "postgresql" → "PostgreSQL"
- "JS" | "Javascript"       → "JavaScript"
- "ML"                      → "Machine Learning"
- "NLP"                     → "Natural Language Processing"
- "causal inference"        → "Causal Inference" (Title Case for technique names)
- Lowercase for Python package names: "pandas", "numpy", "dbt", "scikit-learn"

## Output schema — STRICT JSON, no extra keys, no prose

{
  "role_title": "string (canonicalized, e.g. 'Data Analyst')",
  "seniority_level": "intern | junior | mid | senior | staff | principal | unspecified",
  "years_experience_min": number or null,
  "years_experience_max": number or null,
  "skills": [
    {"name": "string", "section": "title | requirements | responsibilities | nice_to_have | qualifications"}
  ]
}
"""


USER_TEMPLATE = """Job title: {title}

Job description:
---
{description}
---

Extract the structured record. Respond with JSON only."""


@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
def _call_groq(client, title: str, description: str) -> dict[str, Any]:
    """Single Groq call with retries. Truncates absurdly long JDs to 8k chars."""
    trimmed = (description or "")[:8000]
    resp = client.chat.completions.create(
        model=_GROQ_MODEL,
        response_format={"type": "json_object"},
        temperature=0.1,  # low temp → more consistent extraction
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": USER_TEMPLATE.format(title=title, description=trimmed),
            },
        ],
    )
    content = resp.choices[0].message.content or "{}"
    return json.loads(content)


def _is_transient_error(exc: BaseException) -> bool:
    """
    Only retry on truly transient errors (network blips, 5xx).
    DO NOT retry on 429 (quota exhausted) — retrying burns more quota and
    won't succeed. Let the outer batch handle it as a clean failure.

    Called ONLY when an exception was raised (never on success) because we
    use tenacity's `retry_if_exception` helper below.
    """
    s = str(exc)
    # Google SDK returns status codes in the exception message.
    if "429" in s or "RESOURCE_EXHAUSTED" in s or "quota" in s.lower():
        return False
    if "401" in s or "403" in s or "INVALID_ARGUMENT" in s:
        return False  # auth / bad-request errors won't fix themselves
    return True


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=20),
    retry=retry_if_exception(_is_transient_error),
    reraise=True,
)
def _call_gemini(client, title: str, description: str) -> dict[str, Any]:
    """Single Gemini call. Retries transient network errors but NOT 429 quota errors."""
    from google.genai import types

    trimmed = (description or "")[:8000]
    resp = client.models.generate_content(
        model=_GEMINI_MODEL,
        contents=USER_TEMPLATE.format(title=title, description=trimmed),
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.1,
            response_mime_type="application/json",
        ),
    )
    return json.loads(resp.text or "{}")


def _call_llm(title: str, description: str) -> dict[str, Any]:
    """Dispatch to the configured provider. Hides SDK differences from extract_one."""
    if _PROVIDER == "gemini":
        return _call_gemini(_gemini_client(), title, description)
    if _PROVIDER == "groq":
        return _call_groq(_groq_client(), title, description)
    raise RuntimeError(
        f"Unknown LLM_PROVIDER={_PROVIDER!r}. Use 'gemini' or 'groq'."
    )


def extract_one(job: dict, force: bool = False) -> dict | None:
    """Extract structured data for one job. Cached to disk by job_id."""
    job_id = job["job_id"]
    out_path = EXTRACT_DIR / f"{job_id}.json"

    if out_path.exists() and not force:
        # Cached — skip.
        return json.loads(out_path.read_text(encoding="utf-8"))

    try:
        extracted = _call_llm(job["title"], job.get("description_text", ""))
    except json.JSONDecodeError as e:
        print(f"  ✗ JSON parse error for {job_id}: {e}")
        return None
    except Exception as e:
        print(f"  ✗ {_PROVIDER} error for {job_id}: {e}")
        return None

    record = {
        "job_id": job_id,
        "company": job.get("company"),
        "source_title": job.get("title"),
        "url": job.get("absolute_url"),
        **extracted,
    }
    out_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def _default_throttle() -> float:
    """Pick a safe throttle based on the selected provider's free-tier RPM."""
    # Gemini 2.0 Flash free tier = 15 RPM → 4.0s between calls.
    # Groq llama-3.3-70b free tier = 30 RPM → 2.1s between calls.
    return 4.1 if _PROVIDER == "gemini" else 2.1


def extract_batch(
    jobs: list[dict],
    throttle_s: float | None = None,
    abort_after_consecutive_failures: int = 5,
) -> list[dict]:
    """
    Extract skills for a batch of jobs.

    Resume semantics:
      - Every successful extraction is cached to disk (data/extractions/{job_id}.json)
        BEFORE this function returns, so a Ctrl+C or process-kill loses nothing.
      - If a job fails (e.g. rate limit), NO cache file is written, so a rerun
        will retry it automatically.
      - If `abort_after_consecutive_failures` jobs fail in a row, we abort the
        batch cleanly with a message telling you what to do. This is the
        "Groq quota exhausted — swap your key and rerun" path.

    Groq free tier ≈ 30 RPM / 6k TPM on the 70B model, so 2.1s between calls
    is actually too aggressive for free tier. The per-call tenacity retry
    catches most 429s, but consecutive failures mean the key is done. Cached
    jobs don't count toward the throttle.

    Override throttle via env var LLM_THROTTLE_S if you hit ratelimits often:
      setx LLM_THROTTLE_S 5.0    (Windows)
      export LLM_THROTTLE_S=5.0  (macOS/Linux)
    """
    import time

    from tqdm import tqdm

    if throttle_s is None:
        throttle_s = _default_throttle()
    # Respect explicit env override (new name first, then legacy GROQ_THROTTLE_S).
    throttle_s = float(
        os.getenv("LLM_THROTTLE_S", os.getenv("GROQ_THROTTLE_S", throttle_s))
    )

    # Show the user which provider + model is being used, so when something
    # goes wrong they don't have to guess.
    _model = _GEMINI_MODEL if _PROVIDER == "gemini" else _GROQ_MODEL
    print(f"  [extractor] provider={_PROVIDER}  model={_model}  throttle={throttle_s}s")

    results: list[dict] = []
    cached_hits = 0
    fresh_success = 0
    consecutive_failures = 0

    for job in tqdm(jobs, desc="Extracting skills"):
        job_id = job["job_id"]
        out_path = EXTRACT_DIR / f"{job_id}.json"
        was_cached = out_path.exists()

        rec = extract_one(job)

        if rec is not None:
            results.append(rec)
            if was_cached:
                cached_hits += 1
            else:
                fresh_success += 1
            consecutive_failures = 0
        else:
            consecutive_failures += 1
            if consecutive_failures >= abort_after_consecutive_failures:
                key_env = "GEMINI_API_KEY" if _PROVIDER == "gemini" else "GROQ_API_KEY"
                print()
                print("=" * 70)
                print(f"ABORTING: {consecutive_failures} consecutive extraction failures.")
                print(f"Most likely cause: {_PROVIDER} API key exhausted or quota hit.")
                print()
                print("How to resume:")
                print(f"  1. Put a fresh {key_env} into skillscope/.env")
                print("  2. Re-run the exact same command.")
                print(f"  3. Already-cached jobs ({fresh_success + cached_hits} so far)")
                print("     will be skipped automatically.")
                print("=" * 70)
                break

        # Throttle between NEW calls (cached hits are free).
        if not was_cached:
            time.sleep(throttle_s)

    print(
        f"\n  Extraction summary: {fresh_success} new, "
        f"{cached_hits} from cache, {consecutive_failures} failed at end."
    )
    return results


if __name__ == "__main__":
    # Smoke test with a hand-crafted fake job.
    fake = {
        "job_id": "test-0",
        "company": "testco",
        "title": "Senior Data Analyst",
        "description_text": (
            "We're looking for a senior data analyst with 5+ years of experience.\n\n"
            "Requirements:\n- Strong SQL skills\n- Python (pandas, numpy)\n- Tableau or Looker\n"
            "- A/B testing experience\n\nNice to have:\n- dbt\n- Snowflake\n\n"
            "You will build dashboards, run experiments, and present findings to stakeholders."
        ),
        "absolute_url": "https://example.com/job/0",
    }
    result = extract_one(fake, force=True)
    print(json.dumps(result, indent=2))
