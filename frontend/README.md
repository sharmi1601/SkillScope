# SkillScope frontend

Vite + React + Tailwind (CDN) single-page app. Talks to the FastAPI backend on
`:8000` via the Vite dev proxy.

## Dev

```bash
# terminal 1 — backend
cd ..
pip install -r requirements.txt
uvicorn src.api:app --reload --port 8000

# terminal 2 — frontend
cd frontend
npm install
npm run dev
# open http://localhost:5173
```

## Screens

`App.jsx` is a 3-step state machine:

1. **RolePicker** — 4 canonical roles pulled from `GET /api/roles`.
2. **ResumeUpload** — form + file input. POSTs to `/api/parse-resume`, then
   chains into `/api/score`.
3. **Results** — close gaps, polish, long-term, and the week-by-week plan with
   real, sanitized resource URLs.
