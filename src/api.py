"""
api.py — FastAPI backend for SkillScope.

Endpoints:
  GET  /api/roles             → the 4 canonical target roles with labels/descriptions
  POST /api/parse-resume      → multipart upload (PDF/DOCX/TXT) → structured profile JSON
  POST /api/score             → profile + role → full gap report + resources + plan
  GET  /api/health            → liveness probe

Run locally:
    uvicorn src.api:app --reload --port 8000

CORS is wide-open (allow_origins=["*"]) because this is a hackathon demo served
from localhost; tighten before shipping anywhere real.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os

from .gap_scorer import (
    load_skill_hours,
    load_snapshot,
    rank_gaps,
    score_skills,
)
from .recommender import recommend_for_report
from .resume_parser import parse_resume
from .scheduler import generate_plan
from dotenv import load_dotenv
load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")

app = FastAPI(title="SkillScope API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Static role catalog — keep in sync with the snapshots under data/
# ---------------------------------------------------------------------------

VALID_ROLES = {"data_analyst", "data_engineer", "data_scientist", "ml_engineer"}
VALID_STYLES = {"video", "reading", "hands_on", "any"}

ROLES = [
    {
        "id": "data_analyst",
        "label": "Data Analyst",
        "description": "SQL, dashboards, stakeholder reporting. Heavy on Tableau / Looker / Power BI and business metrics.",
    },
    {
        "id": "data_engineer",
        "label": "Data Engineer",
        "description": "Pipelines, warehouses, and infra. Python + SQL + Spark/Airflow/dbt on top of cloud data platforms.",
    },
    {
        "id": "data_scientist",
        "label": "Data Scientist",
        "description": "Experimentation, statistical modeling, ML prototyping. A/B testing, causal inference, Python + notebooks.",
    },
    {
        "id": "ml_engineer",
        "label": "ML Engineer",
        "description": "Production ML systems. PyTorch/TensorFlow, serving, MLOps, and increasingly GenAI / agents / RAG.",
    },
]


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------


class ScoreRequest(BaseModel):
    profile: dict[str, Any]
    role: str
    plan: bool = True  # whether to also run the Groq plan call


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/roles")
def get_roles() -> list[dict[str, str]]:
    return ROLES


@app.post("/api/parse-resume")
async def api_parse_resume(
    resume: UploadFile = File(...),
    role: str = Form(...),
    name: str | None = Form(None),
    hours_per_week: int = Form(10),
    deadline_weeks: int = Form(12),
    learning_style: str = Form("any"),
) -> dict[str, Any]:
    """
    Accept a resume file + user metadata, return a SkillScope profile JSON.

    The profile is NOT persisted server-side — the frontend holds it in state
    and posts it back to /api/score.
    """
    if role not in VALID_ROLES:
        raise HTTPException(400, f"Unknown role: {role!r}. Expected one of {sorted(VALID_ROLES)}.")
    if learning_style not in VALID_STYLES:
        raise HTTPException(400, f"Unknown learning_style: {learning_style!r}.")

    # parse_resume() expects a filesystem path, so we round-trip via tempfile.
    suffix = Path(resume.filename or "resume").suffix.lower() or ".pdf"
    try:
        raw = await resume.read()
    except Exception as e:  # pragma: no cover
        raise HTTPException(400, f"Could not read uploaded file: {e}") from e

    if not raw:
        raise HTTPException(400, "Uploaded resume is empty.")

    with tempfile.NamedTemporaryFile("wb", suffix=suffix, delete=False) as f:
        f.write(raw)
        tmp_path = Path(f.name)

    try:
        profile = parse_resume(
            path=tmp_path,
            target_role=role,
            name=name,
            hours_per_week=hours_per_week,
            deadline_weeks=deadline_weeks,
            learning_style=learning_style,
        )
    except Exception as e:
        raise HTTPException(500, f"Resume parse failed: {e}") from e
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass

    return profile


@app.post("/api/score")
def api_score(req: ScoreRequest) -> dict[str, Any]:
    """
    Given a parsed profile + target role, return the gap report, curated
    resources per skill, and (optionally) a week-by-week study plan.
    """
    if req.role not in VALID_ROLES:
        raise HTTPException(400, f"Unknown role: {req.role!r}.")

    try:
        snapshot = load_snapshot(req.role)
    except FileNotFoundError as e:
        raise HTTPException(
            500,
            f"No market snapshot for role {req.role!r}. "
            "Run the scraper/extractor pipeline first.",
        ) from e

    skill_hours = load_skill_hours()

    try:
        scored = score_skills(snapshot, req.profile, skill_hours)
        report = rank_gaps(
            scored,
            hours_per_week=req.profile.get("hours_per_week", 10),
            deadline_weeks=req.profile.get("deadline_weeks", 12),
        )
    except Exception as e:
        raise HTTPException(500, f"Gap scoring failed: {e}") from e

    user_style = req.profile.get("learning_style", "any")
    recs = recommend_for_report(report, user_style=user_style, k=3)

    plan = None
    if req.plan:
        try:
            plan = generate_plan(
                report,
                recs,
                hours_per_week=req.profile.get("hours_per_week", 10),
                deadline_weeks=req.profile.get("deadline_weeks", 12),
                user_name=req.profile.get("name", "user"),
                role=req.role,
                # Always regenerate — each profile produces a different plan,
                # and the cached plan_{role}.json shouldn't bleed across users.
                force=True,
            )
        except Exception as e:
            # Plan is a nice-to-have — don't fail the whole response.
            plan = {"error": str(e), "weeks": []}

    out = report.to_dict()
    out["recommendations"] = recs
    if plan is not None:
        out["plan"] = plan
    out["role"] = req.role
    out["profile_name"] = req.profile.get("name", "user")
    return out
