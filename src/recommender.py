"""
recommender.py — Retrieve top learning resources per skill.

Pure retrieval, NO LLM. This is critical: we never hallucinate URLs.

Ranking formula for each resource:
    rank = style_match × freshness × engagement

Where:
    style_match    = 1.0 if resource.style matches user's learning_style,
                     0.6 if it's a reasonable alternative, else 0.3
    freshness      = [0,1] from resources.json (decays with age)
    engagement     = [0,1] from resources.json (log-normalized popularity)

We return top-K resources per skill.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Maps user's declared learning_style to how well each resource style fits.
STYLE_AFFINITY: dict[str, dict[str, float]] = {
    "video": {"video": 1.0, "youtube": 1.0, "interactive": 0.7, "reading": 0.4, "audio": 0.5, "book": 0.3},
    "reading": {"reading": 1.0, "book": 1.0, "article": 1.0, "docs": 0.9, "video": 0.4, "youtube": 0.4, "interactive": 0.6, "audio": 0.5},
    "interactive": {"interactive": 1.0, "video": 0.7, "youtube": 0.7, "reading": 0.5, "book": 0.4},
    "audio": {"audio": 1.0, "video": 0.8, "youtube": 0.8, "reading": 0.5, "book": 0.4, "interactive": 0.4},
    # Default when user hasn't specified.
    "any": {"video": 0.9, "youtube": 0.9, "reading": 0.8, "book": 0.8, "article": 0.9, "docs": 0.8, "interactive": 0.9, "course": 0.9, "audio": 0.7, "podcast": 0.7},
}


def load_resources() -> dict[str, list[dict[str, Any]]]:
    """Read the curated resources DB. Strips metadata keys like _comment."""
    path = DATA_DIR / "resources.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def _style_score(resource_style: str, user_style: str) -> float:
    table = STYLE_AFFINITY.get(user_style, STYLE_AFFINITY["any"])
    # Fall back: if we don't have a mapping for this resource style, give 0.6.
    return table.get(resource_style, 0.6)


def _rank_resource(resource: dict[str, Any], user_style: str) -> float:
    """Combine style match × freshness × engagement."""
    style = resource.get("style", resource.get("platform", ""))
    return (
        _style_score(style, user_style)
        * float(resource.get("freshness_score", 0.5))
        * float(resource.get("engagement_score", 0.5))
    )


def recommend_for_skill(
    skill: str,
    user_style: str = "any",
    k: int = 3,
    resources_db: dict[str, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Return top-k ranked resources for a given skill (may be fewer if DB is thin)."""
    db = resources_db if resources_db is not None else load_resources()
    candidates = db.get(skill, [])
    scored = []
    for r in candidates:
        rank = _rank_resource(r, user_style)
        scored.append({**r, "rank": round(rank, 3)})
    scored.sort(key=lambda x: x["rank"], reverse=True)
    return scored[:k]


def recommend_for_report(
    gap_report: dict[str, Any] | Any,
    user_style: str = "any",
    k: int = 3,
) -> dict[str, list[dict[str, Any]]]:
    """
    Given a Gap Scorer report (dict form), return {skill_name: [resources]} for
    every skill in close_gaps AND polish. (We skip long_term because those are
    goals, not active plan items.)
    """
    # Accept both GapReport dataclasses and already-serialized dicts.
    if hasattr(gap_report, "to_dict"):
        gap_report = gap_report.to_dict()

    db = load_resources()
    out: dict[str, list[dict[str, Any]]] = {}
    for bucket in ("close_gaps", "polish"):
        for sg in gap_report.get(bucket, []):
            skill = sg["skill"]
            out[skill] = recommend_for_skill(skill, user_style, k, resources_db=db)
    return out


def coverage_report(db: dict[str, list[dict[str, Any]]] | None = None) -> dict[str, int]:
    """Quick diagnostic — how many resources we have per skill in the DB."""
    db = db if db is not None else load_resources()
    return {skill: len(items) for skill, items in sorted(db.items())}


if __name__ == "__main__":
    # Standalone smoke test.
    db = load_resources()
    print(f"Resources DB covers {len(db)} skills.\n")
    for skill in ["Tableau", "Hypothesis Testing", "A/B Testing", "Looker"]:
        recs = recommend_for_skill(skill, user_style="video", k=3)
        print(f"=== {skill} (video-first) ===")
        for r in recs:
            print(f"  [{r['rank']:.2f}] {r['title']}")
            print(f"         {r['url']}")
        print()
