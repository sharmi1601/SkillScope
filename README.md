---
title: Skillscope Backend
emoji: 👁
colorFrom: gray
colorTo: yellow
sdk: docker
pinned: false
---

# SkillScope

Turn your resume into a 12-week learning plan grounded in real job postings.

SkillScope scrapes live Greenhouse job listings for four target roles, extracts the skills employers actually ask for, scores your resume against that market snapshot across six dimensions, and produces a week-by-week study plan with curated, hallucination-checked resource links.

## Target roles

Data Analyst · Data Engineer · Data Scientist · ML Engineer.

## How it works

1. **Scrape + extract** — pull live JDs from Greenhouse, call an LLM to extract concrete skills with frequency, criticality, and trend signals.
2. **Aggregate** — canonicalize skill names (RAG / LangChain / MLOps clusters all collapse), filter single-JD noise, build a per-role snapshot.
3. **Parse resume** — PDF / DOCX / TXT → structured profile (skills + confidence, experiences, projects, education).
4. **Score** — six-dimension gap scorer (frequency × trend × criticality × recoverability × proximity × resource availability) buckets each skill into close-gap / polish / long-term.
5. **Recommend + plan** — retrieve top-K curated resources per gap (pure retrieval, never hallucinated), then ask an LLM to weave them into a week-by-week plan. URLs are post-hoc sanitized against the curated list to enforce the "no fake links" guarantee.

## Stack

- Backend: Python 3.10+, FastAPI, Pydantic, google-genai (Gemini 2.5 Flash-Lite), PyMuPDF, python-docx
- Frontend: React 18, Vite, Tailwind (CDN)
- Data: handcurated `data/resources.json` (~56 skills, 3–4 links each)

## Run locally

### 1. Backend

```bash
# from repo root
pip install -r requirements.txt
cp .env.example .env    # then fill in GEMINI_API_KEY
python -m uvicorn src.api:app --reload --port 8000
```

Health check: http://localhost:8000/api/health · Swagger: http://localhost:8000/docs

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
# open http://localhost:5173
```

## CLI workflows (no frontend needed)

```bash
# Parse a resume into a profile
python -m src.resume_cli --resume my_resume.pdf --role ml_engineer \
    --name sharmi --hours 10 --weeks 12 --style video

# Score it
python -m src.score_cli --role ml_engineer \
    --profile data/profile_sharmi.json --plan
```

## Repo layout

```
src/
  api.py              FastAPI backend
  scraper.py          Greenhouse JD scraper
  extractor.py        LLM skill extraction
  aggregator.py       Canonicalization + snapshot build
  resume_parser.py    PDF/DOCX → profile
  gap_scorer.py       Six-dimension scoring + bucketing
  recommender.py      Top-K resource retrieval (no LLM)
  scheduler.py        Week-by-week plan + URL sanitization
  resume_cli.py       CLI wrapper for resume_parser
  score_cli.py        CLI wrapper for the full gap pipeline
  pipeline.py         End-to-end scrape → extract → aggregate

data/
  resources.json      Curated learning resources, skill-indexed
  skill_hours.json    Hours-to-learn lookup
  summary_*.json      Per-role market snapshots

frontend/
  src/                React SPA (3 screens: role → upload → results)
```
