"""
gap_scorer.py — Score every market skill against the user's profile and sort
them into three actionable buckets.

The scoring formula (6 dimensions, weights sum to 1.0):

    S = 0.25 * frequency
      + 0.15 * trend
      + 0.20 * role_criticality
      + 0.20 * recoverability
      + 0.15 * proximity
      + 0.05 * resource_availability

Each dimension is normalized to [0, 1] before weighting. Final score is also in
[0, 1], higher = higher priority.

Buckets (output of rank_gaps):
    close_gaps: high-score, fit in the user's timeline, user has adjacent skills
                → "quick wins"
    polish:     user already has a related skill, just needs depth
                → "you're most of the way there"
    long_term:  needed by the market but won't fit in deadline
                → "goals to mark on a longer runway"

The scorer consumes the snapshot produced by aggregator.py (top_skills) plus a
user profile JSON and a skill-hours lookup.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .aggregator import _canonical_section, _normalize

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


# --- Weights (keep these in sync with the spec) ----------------------------

WEIGHTS = {
    "frequency": 0.25,
    "trend": 0.15,
    "role_criticality": 0.20,
    "recoverability": 0.20,
    "proximity": 0.15,
    "resource_availability": 0.05,
}
assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, "Weights must sum to 1.0"

# Beyond this many hours, a skill is considered "long-term" — can't be
# practically closed in a hackathon-style 12-week window.
LONG_TERM_HOUR_THRESHOLD = 200

# A skill must appear in at least this many JDs to be counted as a real market
# signal. Skills with freq=1 are single-company noise (e.g. one Instacart job
# mentioning "Shopper Routing") and bloat the long_term bucket with things
# nobody would call a real market trend.
MIN_SNAPSHOT_FREQUENCY = 2


# --- Adjacency table: which skills count as "the user is 80% of the way" ---
# Used for the `proximity` dimension. Keyed on the MARKET skill;
# values are skills the user might already have that get them close.
ADJACENCY: dict[str, list[str]] = {
    "SQL": ["PostgreSQL", "MySQL", "BigQuery", "Snowflake"],
    "Tableau": ["Power BI", "Looker", "Superset"],
    "Power BI": ["Tableau", "Looker", "Excel"],
    "Looker": ["Tableau", "Power BI"],
    "Superset": ["Tableau", "Metabase"],
    "R": ["Python", "pandas"],
    "PyTorch": ["TensorFlow", "Python", "numpy"],
    "TensorFlow": ["PyTorch", "Python", "numpy"],
    "Spark": ["Python", "SQL", "Scala"],
    "Airflow": ["Python", "Dagster", "Prefect"],
    "dbt": ["SQL", "Airflow"],
    "Snowflake": ["PostgreSQL", "BigQuery", "SQL"],
    "BigQuery": ["Snowflake", "PostgreSQL", "SQL"],
    "Causal Inference": ["Statistical Modeling", "A/B Testing", "Python", "R"],
    "A/B Testing": ["Hypothesis Testing", "Statistical Modeling"],
    "Hypothesis Testing": ["Significance Testing", "Statistical Modeling"],
    "Significance Testing": ["Hypothesis Testing", "Statistical Modeling"],
    "Statistical Modeling": ["R", "Python", "scipy"],
    "Machine Learning": ["scikit-learn", "Python", "Statistical Modeling"],
    "Natural Language Processing": ["Machine Learning", "PyTorch", "Hugging Face"],
    "Deep Learning": ["PyTorch", "TensorFlow", "Machine Learning"],
    "ETL": ["Python", "SQL", "Airflow", "dbt"],
    "Data Modeling": ["SQL", "dbt"],
    "Data Visualization": ["Tableau", "matplotlib", "seaborn", "Power BI"],
    "Data Pipelines": ["Airflow", "Python", "dbt"],
    "EDA": ["pandas", "matplotlib", "Python"],
    "Kubernetes": ["Docker"],
    "Docker": ["Linux"],
    "React": ["JavaScript", "TypeScript", "HTML", "CSS"],
    "TypeScript": ["JavaScript"],
    "FastAPI": ["Python", "Flask"],
    "Django": ["Python", "Flask"],
}


# --- Data classes -----------------------------------------------------------


@dataclass
class ScoredGap:
    skill: str
    total_score: float
    dimensions: dict[str, float]
    user_has: bool
    user_has_adjacent: list[str]
    hours_to_learn: int
    bucket: str = ""          # filled in by rank_gaps
    market_frequency_pct: float = 0.0
    market_criticality: float = 0.0
    reasoning: str = ""       # human-readable "why this bucket"


@dataclass
class GapReport:
    close_gaps: list[ScoredGap] = field(default_factory=list)
    polish: list[ScoredGap] = field(default_factory=list)
    long_term: list[ScoredGap] = field(default_factory=list)
    total_hours_close: int = 0
    feasible_in_deadline: bool = True

    def to_dict(self) -> dict[str, Any]:
        def sg_to_dict(sg: ScoredGap) -> dict[str, Any]:
            return {
                "skill": sg.skill,
                "total_score": round(sg.total_score, 3),
                "dimensions": {k: round(v, 3) for k, v in sg.dimensions.items()},
                "user_has": sg.user_has,
                "user_has_adjacent": sg.user_has_adjacent,
                "hours_to_learn": sg.hours_to_learn,
                "bucket": sg.bucket,
                "market_frequency_pct": sg.market_frequency_pct,
                "market_criticality": sg.market_criticality,
                "reasoning": sg.reasoning,
            }

        return {
            "close_gaps": [sg_to_dict(x) for x in self.close_gaps],
            "polish": [sg_to_dict(x) for x in self.polish],
            "long_term": [sg_to_dict(x) for x in self.long_term],
            "total_hours_close": self.total_hours_close,
            "feasible_in_deadline": self.feasible_in_deadline,
        }


# --- I/O helpers ------------------------------------------------------------


def _renormalize_snapshot(snap: dict[str, Any]) -> dict[str, Any]:
    """
    Self-healing pass over a snapshot. Applies the current skill alias table
    and merges rows that now share a canonical name. This means you don't have
    to re-run the Groq pipeline just because the alias table was updated.

    Rows that normalize to "" (generic terms like "AI") are dropped.
    """
    rows = snap.get("top_skills", [])
    if not rows:
        return snap

    merged: dict[str, dict[str, Any]] = {}
    total_jobs = snap.get("sample_size") or max(
        (r.get("frequency", 0) for r in rows), default=1
    )

    for r in rows:
        canonical = _normalize(r.get("skill", ""))
        if not canonical:
            continue  # generic term — drop

        if canonical not in merged:
            merged[canonical] = {
                "skill": canonical,
                "frequency": r.get("frequency", 0),
                "criticality_score": r.get("criticality_score", 0.0),
                "sections": dict(r.get("sections", {}) or {}),
            }
        else:
            # Merge: sum frequency and criticality, union sections.
            m = merged[canonical]
            m["frequency"] += r.get("frequency", 0)
            m["criticality_score"] += r.get("criticality_score", 0.0)
            for sec, n in (r.get("sections") or {}).items():
                canon_sec = _canonical_section(sec)
                m["sections"][canon_sec] = m["sections"].get(canon_sec, 0) + n

    # Recompute pct_of_jobs and re-sort by frequency.
    out_rows = []
    for m in merged.values():
        m["pct_of_jobs"] = round(
            100.0 * m["frequency"] / max(total_jobs, 1), 1
        )
        out_rows.append(m)
    out_rows.sort(key=lambda x: x["frequency"], reverse=True)

    snap = dict(snap)  # shallow copy so we don't mutate the caller's dict
    snap["top_skills"] = out_rows
    return snap


def load_snapshot(role: str) -> dict[str, Any]:
    path = DATA_DIR / f"summary_{role}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No snapshot at {path}. Run `python -m src.pipeline --role {role}` first."
        )
    raw = json.loads(path.read_text(encoding="utf-8"))
    # Self-healing: re-apply current aliases so stale snapshots work correctly
    # without needing a fresh pipeline run.
    return _renormalize_snapshot(raw)


def load_profile(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_skill_hours() -> dict[str, int]:
    path = DATA_DIR / "skill_hours.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    # Strip metadata keys like _comment, _default.
    return {k: v for k, v in data.items() if not k.startswith("_")}


# --- Dimension scorers ------------------------------------------------------


def _score_frequency(skill_row: dict, top_row: dict) -> float:
    """Normalized share of jobs requiring the skill. top_row = #1 skill."""
    top_freq = max(top_row.get("frequency", 1), 1)
    return skill_row.get("frequency", 0) / top_freq


def _score_trend(skill_row: dict) -> float:
    """
    Trend dimension — would be a real YoY delta if we had historical data.
    For v1 we don't, so we return a neutral 0.5 for every skill. This keeps
    the formula stable; we'll replace with real deltas once the offline
    pipeline gets scaled to multiple time-window snapshots.
    """
    return 0.5


def _score_role_criticality(skill_row: dict, max_crit: float) -> float:
    """How often the skill is in the REQUIREMENTS / TITLE section, not nice-to-have."""
    if max_crit <= 0:
        return 0.0
    return min(skill_row.get("criticality_score", 0) / max_crit, 1.0)


def _score_recoverability(hours: int) -> float:
    """Fewer hours to learn → more recoverable. Linear, capped at 200h."""
    if hours <= 0:
        return 1.0
    return max(0.0, 1.0 - (hours / LONG_TERM_HOUR_THRESHOLD))


def _score_proximity(skill: str, user_skill_names: set[str]) -> tuple[float, list[str]]:
    """
    1.0 if user already lists the skill itself, else 0.5 per adjacent skill the
    user has, capped at 1.0. Returns (score, list of adjacent matches for UI).
    """
    if skill in user_skill_names:
        return 1.0, [skill]
    adj = ADJACENCY.get(skill, [])
    matches = [a for a in adj if a in user_skill_names]
    if not matches:
        return 0.0, []
    return min(1.0, 0.5 * len(matches)), matches


def _score_resource_availability(skill: str) -> float:
    """
    Placeholder — real value comes from counting resources in the Resources DB.
    Most reasonable skills have plenty of tutorials, so default to 0.8.
    Obscure/proprietary skills would score lower.
    """
    return 0.8


# --- Main scorer ------------------------------------------------------------


def score_skills(
    snapshot: dict[str, Any],
    profile: dict[str, Any],
    skill_hours: dict[str, int],
    weights: dict[str, float] = WEIGHTS,
    long_term_hour_threshold: int = LONG_TERM_HOUR_THRESHOLD,
) -> list[ScoredGap]:
    """Score every market skill against the profile; returns sorted by total_score desc."""
    top_skills: list[dict] = snapshot.get("top_skills", [])
    if not top_skills:
        return []

    # Drop single-mention skills — they're company-specific noise, not market signal.
    top_skills = [
        r for r in top_skills if r.get("frequency", 0) >= MIN_SNAPSHOT_FREQUENCY
    ]
    if not top_skills:
        return []

    top_row = top_skills[0]
    max_crit = max((s.get("criticality_score", 0) for s in top_skills), default=1.0)

    # Normalize the user's resume skills through the same alias table the
    # market snapshot uses, so "Pandas" matches "pandas", "Scikit-learn"
    # matches "scikit-learn", "Apache Kafka" matches "Kafka", etc. Without
    # this, the case-sensitive set lookup misses real matches and reports
    # skills the user already has as "missing".
    user_skill_names: set[str] = set()
    for s in profile.get("skills", []):
        canon = _normalize(s.get("name", ""))
        if canon:
            user_skill_names.add(canon)

    scored: list[ScoredGap] = []
    for row in top_skills:
        name = row["skill"]
        hours = skill_hours.get(name, skill_hours.get("_default", 40))

        dims = {
            "frequency": _score_frequency(row, top_row),
            "trend": _score_trend(row),
            "role_criticality": _score_role_criticality(row, max_crit),
            "recoverability": _score_recoverability(hours),
        }
        prox_score, adj_matches = _score_proximity(name, user_skill_names)
        dims["proximity"] = prox_score
        dims["resource_availability"] = _score_resource_availability(name)

        total = sum(weights[k] * dims[k] for k in weights)
        scored.append(
            ScoredGap(
                skill=name,
                total_score=total,
                dimensions=dims,
                user_has=name in user_skill_names,
                user_has_adjacent=adj_matches if name not in user_skill_names else [],
                hours_to_learn=hours,
                market_frequency_pct=row.get("pct_of_jobs", 0.0),
                market_criticality=row.get("criticality_score", 0.0),
            )
        )

    scored.sort(key=lambda x: x.total_score, reverse=True)
    return scored


def rank_gaps(
    scored: list[ScoredGap],
    hours_per_week: int,
    deadline_weeks: int,
    long_term_hour_threshold: int = LONG_TERM_HOUR_THRESHOLD,
) -> GapReport:
    """
    Partition scored skills into close_gaps / polish / long_term.

    Rules (applied in order):
      - user_has:  dropped entirely (they already know it)
      - hours > threshold:      long_term
      - user_has_adjacent:      polish (they're most of the way there)
      - otherwise → close_gaps, packed into the budget until we run out of hours
      - anything left that couldn't fit → long_term
    """
    budget_hours = hours_per_week * deadline_weeks
    report = GapReport()
    remaining = budget_hours

    for sg in scored:
        if sg.user_has:
            continue

        if sg.hours_to_learn > long_term_hour_threshold:
            sg.bucket = "long_term"
            sg.reasoning = (
                f"Needs ~{sg.hours_to_learn}h — exceeds the "
                f"{long_term_hour_threshold}h practical-in-timeline threshold."
            )
            report.long_term.append(sg)
            continue

        if sg.user_has_adjacent:
            sg.bucket = "polish"
            sg.reasoning = (
                f"You already have {', '.join(sg.user_has_adjacent)} — "
                f"{sg.skill} is a natural extension."
            )
            report.polish.append(sg)
            continue

        if remaining >= sg.hours_to_learn:
            sg.bucket = "close_gap"
            sg.reasoning = (
                f"High market demand ({sg.market_frequency_pct}% of jobs) and "
                f"fits your {budget_hours}h budget ({sg.hours_to_learn}h to learn)."
            )
            report.close_gaps.append(sg)
            remaining -= sg.hours_to_learn
        else:
            sg.bucket = "long_term"
            sg.reasoning = (
                f"Worth it but doesn't fit your {budget_hours}h budget "
                f"after higher-priority skills ({sg.hours_to_learn}h needed)."
            )
            report.long_term.append(sg)

    report.total_hours_close = sum(sg.hours_to_learn for sg in report.close_gaps)
    report.feasible_in_deadline = report.total_hours_close <= budget_hours
    return report


# --- Convenience entry point ------------------------------------------------


def run(role: str, profile_path: str | Path) -> GapReport:
    snapshot = load_snapshot(role)
    profile = load_profile(profile_path)
    skill_hours = load_skill_hours()
    scored = score_skills(snapshot, profile, skill_hours)
    return rank_gaps(
        scored,
        hours_per_week=profile.get("hours_per_week", 10),
        deadline_weeks=profile.get("deadline_weeks", 12),
    )


if __name__ == "__main__":
    # Quick sanity run using the example profile.
    report = run("data_analyst", DATA_DIR / "example_profile.json")
    print(f"\nCLOSE GAPS ({len(report.close_gaps)}, {report.total_hours_close}h):")
    for sg in report.close_gaps:
        print(f"  {sg.skill:<28} score={sg.total_score:.2f}  {sg.hours_to_learn}h  — {sg.reasoning}")
    print(f"\nPOLISH ({len(report.polish)}):")
    for sg in report.polish:
        print(f"  {sg.skill:<28} score={sg.total_score:.2f}  {sg.hours_to_learn}h  — {sg.reasoning}")
    print(f"\nLONG-TERM ({len(report.long_term)}):")
    for sg in report.long_term:
        print(f"  {sg.skill:<28} score={sg.total_score:.2f}  {sg.hours_to_learn}h  — {sg.reasoning}")
