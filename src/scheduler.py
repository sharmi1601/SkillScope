"""
scheduler.py — Turn a gap report + recommended resources into a week-by-week
study plan via one Groq call.

Contract:
  Input:  gap_report, recommendations (from recommender.py), hours_per_week,
          deadline_weeks, user name (optional)
  Output: structured plan — list of weeks, each with focus skill(s), activities
          (real resource URLs, never hallucinated), and hour budget.

Safety guardrails (CRITICAL — the product's core promise):
  1. The LLM sees the FULL resources list and is told to pick from it verbatim.
  2. After generation we VALIDATE every URL in the plan against the resources
     we showed it. Any hallucinated URL gets stripped and replaced with a real
     one for that skill (or drops the activity entirely if we can't match).
  3. Plans are cached to data/plan_{role}.json so repeat runs don't burn Groq
     calls. Pass force=True to regenerate.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential

load_dotenv()

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Provider dispatch — mirrors the extractor so the whole system speaks one provider.
#   LLM_PROVIDER=gemini (default) — uses GEMINI_MODEL_PLAN (default: gemini-2.5-flash-lite)
#   LLM_PROVIDER=groq              — uses GROQ_MODEL_EXTRACTION
_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").lower()
_GEMINI_MODEL_PLAN = os.getenv("GEMINI_MODEL_PLAN", "gemini-2.5-flash-lite")
_GROQ_MODEL = os.getenv("GROQ_MODEL_EXTRACTION", "llama-3.3-70b-versatile")


SYSTEM_PROMPT = """You are a learning-plan designer. Given a prioritized list of skills the user needs to learn, the curated resources available for each skill, and their weekly study budget + deadline, produce a STRUCTURED WEEK-BY-WEEK study plan.

## Critical rules
- Use ONLY the resources provided. NEVER invent a URL or resource. Every URL you include must be copied verbatim from the provided resources list.
- Every week's total hours must be ≤ the user's weekly budget.
- Distribute skills sensibly: front-load the highest-scored close_gaps; interleave lighter "polish" items when weeks have spare hours.
- Don't assign the same resource twice.
- If a skill requires more hours than one week's budget, spread it across consecutive weeks.

## Output schema (strict JSON)

{
  "plan_summary": "string — 2-3 sentence overview",
  "total_weeks": number,
  "total_hours": number,
  "weeks": [
    {
      "week_number": 1,
      "focus": "string — e.g. 'SQL fundamentals + first Tableau tutorial'",
      "hours_planned": number,
      "activities": [
        {
          "skill": "string — must match a skill from the input",
          "title": "string — copied verbatim from a provided resource",
          "url": "string — copied verbatim from the provided resources",
          "hours": number
        }
      ]
    }
  ]
}

Return JSON only. No prose, no markdown fences."""


def _build_user_prompt(
    close_gaps: list[dict],
    polish: list[dict],
    recommendations: dict[str, list[dict]],
    hours_per_week: int,
    deadline_weeks: int,
    user_name: str,
) -> str:
    lines = [
        f"User: {user_name}",
        f"Weekly study budget: {hours_per_week} hours",
        f"Deadline: {deadline_weeks} weeks",
        f"Total available hours: {hours_per_week * deadline_weeks}",
        "",
        "## Close gaps (highest priority — these are the main plan items)",
    ]
    for sg in close_gaps:
        lines.append(
            f"- {sg['skill']}: {sg['hours_to_learn']}h, score={sg['total_score']:.2f}, {sg['market_frequency_pct']}% of jobs"
        )
        for r in recommendations.get(sg["skill"], []):
            lines.append(f"    • {r['title']} — {r['url']} ({r.get('duration_hours', '?')}h, {r.get('platform', '')})")

    lines.append("")
    lines.append("## Polish items (user has adjacent skills — include these in spare hours if available)")
    for sg in polish[:6]:  # cap to 6 polish items so the prompt stays short
        lines.append(
            f"- {sg['skill']}: {sg['hours_to_learn']}h, adjacent: {', '.join(sg.get('user_has_adjacent', []))}"
        )
        for r in recommendations.get(sg["skill"], [])[:2]:
            lines.append(f"    • {r['title']} — {r['url']} ({r.get('duration_hours', '?')}h, {r.get('platform', '')})")

    lines.append("")
    lines.append(
        "Build the plan. Remember: every URL in your output MUST appear verbatim in the "
        "list above. Never invent a URL."
    )
    return "\n".join(lines)


def _extract_allowed_urls(recommendations: dict[str, list[dict]]) -> set[str]:
    urls = set()
    for items in recommendations.values():
        for r in items:
            if "url" in r:
                urls.add(r["url"])
    return urls


def _build_url_to_resource(recommendations: dict[str, list[dict]]) -> dict[str, dict]:
    out = {}
    for skill, items in recommendations.items():
        for r in items:
            if "url" in r:
                out[r["url"]] = {**r, "skill": skill}
    return out


def _sanitize_plan(plan: dict, recommendations: dict[str, list[dict]]) -> dict:
    """
    Post-process the LLM output to enforce the "no hallucinated URLs" guarantee.
    Any activity whose URL isn't in our curated set gets swapped for a real
    resource from that skill. If no real resource exists, the activity is
    dropped.
    """
    allowed = _extract_allowed_urls(recommendations)
    url_info = _build_url_to_resource(recommendations)

    removed = 0
    swapped = 0
    for wk in plan.get("weeks", []):
        clean_activities = []
        used_urls = {a.get("url") for a in wk.get("activities", []) if a.get("url") in allowed}
        for act in wk.get("activities", []):
            url = act.get("url", "")
            if url in allowed:
                clean_activities.append(act)
                continue
            # URL hallucinated — try to rescue.
            skill = act.get("skill", "")
            fallback = None
            for r in recommendations.get(skill, []):
                if r["url"] not in used_urls:
                    fallback = r
                    break
            if fallback is not None:
                act["url"] = fallback["url"]
                act["title"] = fallback["title"]
                used_urls.add(fallback["url"])
                clean_activities.append(act)
                swapped += 1
            else:
                removed += 1
        wk["activities"] = clean_activities
        wk["hours_planned"] = sum(a.get("hours", 0) for a in clean_activities)

    plan["_sanitization"] = {"hallucinated_urls_swapped": swapped, "activities_removed": removed}
    plan["total_hours"] = sum(wk.get("hours_planned", 0) for wk in plan.get("weeks", []))
    return plan


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=20), reraise=True)
def _call_groq(system: str, user: str) -> dict:
    from groq import Groq  # lazy import — not needed when LLM_PROVIDER=gemini

    key = os.getenv("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY not set.")
    client = Groq(api_key=key)
    resp = client.chat.completions.create(
        model=_GROQ_MODEL,
        response_format={"type": "json_object"},
        temperature=0.3,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    return json.loads(resp.choices[0].message.content or "{}")


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=20), reraise=True)
def _call_gemini(system: str, user: str) -> dict:
    from google import genai
    from google.genai import types

    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set.")
    client = genai.Client(api_key=key)
    resp = client.models.generate_content(
        model=_GEMINI_MODEL_PLAN,
        contents=user,
        config=types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.3,
            response_mime_type="application/json",
        ),
    )
    return json.loads(resp.text or "{}")


def _call_llm(system: str, user: str) -> dict:
    """Dispatch to the configured provider. Same contract as _call_groq / _call_gemini."""
    if _PROVIDER == "gemini":
        return _call_gemini(system, user)
    if _PROVIDER == "groq":
        return _call_groq(system, user)
    raise RuntimeError(f"Unknown LLM_PROVIDER={_PROVIDER!r}. Use 'gemini' or 'groq'.")


def generate_plan(
    gap_report: dict | Any,
    recommendations: dict[str, list[dict]],
    hours_per_week: int,
    deadline_weeks: int,
    user_name: str = "the user",
    role: str = "data_analyst",
    force: bool = False,
) -> dict:
    """Generate (or retrieve cached) week-by-week plan."""
    if hasattr(gap_report, "to_dict"):
        gap_report = gap_report.to_dict()

    cache_path = DATA_DIR / f"plan_{role}.json"
    if cache_path.exists() and not force:
        return json.loads(cache_path.read_text(encoding="utf-8"))

    user_prompt = _build_user_prompt(
        close_gaps=gap_report.get("close_gaps", []),
        polish=gap_report.get("polish", []),
        recommendations=recommendations,
        hours_per_week=hours_per_week,
        deadline_weeks=deadline_weeks,
        user_name=user_name,
    )

    raw = _call_llm(SYSTEM_PROMPT, user_prompt)
    clean = _sanitize_plan(raw, recommendations)

    cache_path.write_text(json.dumps(clean, indent=2), encoding="utf-8")
    return clean


if __name__ == "__main__":
    from .gap_scorer import run
    from .recommender import recommend_for_report

    report = run("data_analyst", DATA_DIR / "example_profile.json")
    profile = json.loads((DATA_DIR / "example_profile.json").read_text(encoding="utf-8"))
    recs = recommend_for_report(report, user_style=profile.get("learning_style", "any"), k=3)

    plan = generate_plan(
        report,
        recs,
        hours_per_week=profile.get("hours_per_week", 10),
        deadline_weeks=profile.get("deadline_weeks", 12),
        user_name=profile.get("name", "user"),
        role="data_analyst",
        force=True,
    )
    print(json.dumps(plan, indent=2)[:2000])
