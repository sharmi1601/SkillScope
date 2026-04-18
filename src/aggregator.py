"""
aggregator.py — Roll up individual extractions into per-skill statistics.

This is the "did the pipeline work?" sanity check. If we target 'data_analyst'
and the top skills come out as SQL / Python / Tableau / Excel / Statistics,
we're golden. If it's "teamwork / communication / passion", the extractor prompt
needs tuning before we scale to 5k jobs.

Produces:
  - `top_skills`: list of {skill, frequency, criticality_score, sections}
  - Section weights match what the live Gap Scorer will use:
        title         = 1.5x   (skill appears in the job title)
        requirements  = 1.0x   (must-have)
        responsibilities = 0.7x  (day-to-day, often indirect signal)
        nice_to_have  = 0.3x   (bonus)
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

EXTRACT_DIR = Path(__file__).resolve().parent.parent / "data" / "extractions"

# Section weights — heavier weight = more signal the skill is a real requirement.
SECTION_WEIGHTS = {
    "title": 1.5,
    "requirements": 1.0,
    "qualifications": 1.0,  # synonym bucket the extractor may use
    "responsibilities": 0.7,
    "nice_to_have": 0.3,
}

# Map any non-canonical section name (raw JD headers leaking through from the
# LLM) back to one of the canonical buckets. The keys are lowercase.
SECTION_ALIASES = {
    # Canonical (identity mapping so .get() works)
    "title": "title",
    "requirements": "requirements",
    "qualifications": "requirements",  # treat as requirements-equivalent
    "responsibilities": "responsibilities",
    "nice_to_have": "nice_to_have",
    # Common raw headers seen in the wild
    "your expertise": "requirements",
    "what you bring": "requirements",
    "what we're looking for": "requirements",
    "what we are looking for": "requirements",
    "minimum qualifications": "requirements",
    "must-haves": "requirements",
    "must haves": "requirements",
    "basic qualifications": "requirements",
    "required qualifications": "requirements",
    "what you'll need": "requirements",
    "what you will need": "requirements",
    "a typical day": "responsibilities",
    "what you'll do": "responsibilities",
    "what you will do": "responsibilities",
    "the role": "responsibilities",
    "in this role": "responsibilities",
    "your role": "responsibilities",
    "day to day": "responsibilities",
    "day-to-day": "responsibilities",
    "preferred qualifications": "nice_to_have",
    "nice to have": "nice_to_have",
    "nice-to-have": "nice_to_have",
    "nice-to-haves": "nice_to_have",
    "bonus points": "nice_to_have",
    "bonus": "nice_to_have",
    "pluses": "nice_to_have",
    "it's a plus": "nice_to_have",
}


def _canonical_section(section: str) -> str:
    """Map any section string back to one of the canonical buckets."""
    if not section:
        return "requirements"
    return SECTION_ALIASES.get(section.strip().lower(), "requirements")


# Skills that legitimately live in lowercase (package/tool names).
# If we title-cased these, they'd look wrong. Keep this set *only* to names
# whose canonical written form is actually lowercase — check the official docs.
LOWERCASE_SKILLS = {
    # Python data/ml packages written lowercase
    "pandas", "numpy", "scipy", "matplotlib", "seaborn", "plotly",
    "scikit-learn", "sklearn", "statsmodels", "nltk", "spacy",
    # Data tooling (dbt is lowercase; Airflow/Dagster/Prefect are Title Case — see SKILL_ALIASES)
    "dbt",
    # Python libraries
    "pytest", "unittest", "requests", "httpx", "aiohttp",
    # Web servers / infra tools
    "nginx", "redis", "celery", "kafka", "rabbitmq",
    # Package managers / dev tools
    "npm", "yarn", "pnpm", "pip", "conda", "poetry",
    "git", "svn", "jq", "sed", "awk",
}

# Canonical-form-preserving set: skills whose form has mixed/uppercase that
# the LLM is likely to lowercase. The normalizer uses these via SKILL_ALIASES
# mostly, but this is documentation of intent.

# Skill-name aliases — lowercase key, canonical display value.
SKILL_ALIASES = {
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "javascript": "JavaScript",
    "js": "JavaScript",
    "typescript": "TypeScript",
    "ts": "TypeScript",
    "nodejs": "Node.js",
    "node": "Node.js",
    "node.js": "Node.js",
    "reactjs": "React",
    "react.js": "React",
    "ml": "Machine Learning",
    "nlp": "Natural Language Processing",
    "ci/cd": "CI/CD",
    "cicd": "CI/CD",
    "aws": "AWS",
    "gcp": "GCP",
    "k8s": "Kubernetes",
    "kubernetes": "Kubernetes",
    "sql": "SQL",
    "nosql": "NoSQL",
    "api": "API",
    "apis": "API",
    "rest": "REST",
    "rest api": "REST",
    "restful": "REST",
    "restful api": "REST",
    "etl": "ETL",
    "elt": "ELT",
    "a/b testing": "A/B Testing",
    "ab testing": "A/B Testing",
    "a/b test": "A/B Testing",
    "html": "HTML",
    "css": "CSS",
    "golang": "Go",
    "go lang": "Go",
    "c++": "C++",
    "c#": "C#",
    ".net": ".NET",
    "dotnet": ".NET",
    "power bi": "Power BI",
    "powerbi": "Power BI",
    "google cloud": "GCP",
    "google cloud platform": "GCP",
    "amazon web services": "AWS",
    "ec2": "AWS EC2",
    "s3": "AWS S3",
    "lambda": "AWS Lambda",
    "big query": "BigQuery",
    "bigquery": "BigQuery",
    "dynamo db": "DynamoDB",
    "dynamodb": "DynamoDB",
    "mongo db": "MongoDB",
    "mongodb": "MongoDB",
    "github actions": "GitHub Actions",
    "jupyter": "Jupyter",
    "jupyter notebook": "Jupyter",
    "jupyter notebooks": "Jupyter",
    "causal inference": "Causal Inference",
    "statistical modeling": "Statistical Modeling",
    "statistical modelling": "Statistical Modeling",
    "data visualization": "Data Visualization",
    "data visualisation": "Data Visualization",
    "experimentation": "Experimentation",
    "machine learning": "Machine Learning",
    "deep learning": "Deep Learning",
    "natural language processing": "Natural Language Processing",
    "computer vision": "Computer Vision",
    "time series": "Time Series Analysis",
    "time series analysis": "Time Series Analysis",
    "significance testing": "Hypothesis Testing",
    "statistical significance testing": "Hypothesis Testing",
    "hypothesis testing": "Hypothesis Testing",
    "statistical hypothesis testing": "Hypothesis Testing",
    "exploratory data analysis": "EDA",
    "pytorch": "PyTorch",
    "tensorflow": "TensorFlow",
    "tensor flow": "TensorFlow",
    "keras": "Keras",
    "xgboost": "XGBoost",
    "lightgbm": "LightGBM",
    "huggingface": "Hugging Face",
    "hugging face": "Hugging Face",
    "beautifulsoup": "BeautifulSoup",
    "flask": "Flask",
    "django": "Django",
    "fastapi": "FastAPI",
    "sqlalchemy": "SQLAlchemy",
    "jinja": "Jinja",
    "ios": "iOS",
    "macos": "macOS",
    "linux": "Linux",
    "airflow": "Airflow",
    "apache airflow": "Airflow",
    "dagster": "Dagster",
    "prefect": "Prefect",
    "looker": "Looker",
    "tableau": "Tableau",
    "snowflake": "Snowflake",
    "databricks": "Databricks",
    "spark": "Spark",
    "apache spark": "Spark",
    "presto": "Presto",
    "trino": "Trino",
    "hadoop": "Hadoop",
    "kafka": "Kafka",
    "apache kafka": "Kafka",
    # Excel and its sub-skills — fold into a single "Excel" bucket.
    "microsoft excel": "Excel",
    "ms excel": "Excel",
    "excel": "Excel",
    "pivot tables": "Excel",
    "pivot table": "Excel",
    "vlookups": "Excel",
    "vlookup": "Excel",
    "xlookup": "Excel",
    "xlookups": "Excel",
    "excel formulas": "Excel",
    "excel macros": "Excel",
    # Mode Analytics (BI tool — distinct from "mode" in stats)
    "mode analytics": "Mode",
    # LLM/AI product names — bucket under "Generative AI" so we don't
    # fragment into Gemini / ChatGPT / Claude / Copilot entries.
    "gemini": "Generative AI",
    "chatgpt": "Generative AI",
    "gpt-4": "Generative AI",
    "gpt-3": "Generative AI",
    "claude": "Generative AI",
    "copilot": "Generative AI",
    "llm": "Generative AI",
    "llms": "Generative AI",
    "large language models": "Generative AI",
    "generative ai": "Generative AI",
    "genai": "Generative AI",
    "superset": "Superset",
    "apache superset": "Superset",

    # --- Collapsed duplicate clusters seen across JDs ----------------------
    # Each lowercase key here maps many near-synonyms to ONE canonical name
    # so they don't show up as 5 separate long-term items in the gap report.

    # RAG — every wording the JDs use lands here
    "rag": "RAG",
    "rag systems": "RAG",
    "rag architectures": "RAG",
    "rag pipelines": "RAG",
    "rag/search": "RAG",
    "retrieval augmented generation": "RAG",
    "retrieval-augmented generation": "RAG",

    # LangChain — LLM libs keep getting spelled three ways
    "langchain": "LangChain",
    "lang chain": "LangChain",

    # MLOps
    "mlops": "MLOps",
    "ml ops": "MLOps",
    "ml-ops": "MLOps",

    # Fine-Tuning — collapse every variant
    "fine-tuning": "Fine-Tuning",
    "fine tuning": "Fine-Tuning",
    "finetuning": "Fine-Tuning",
    "llm fine-tuning": "Fine-Tuning",
    "fine-tuning llms": "Fine-Tuning",
    "model fine-tuning": "Fine-Tuning",
    "adapter-based fine-tuning": "Fine-Tuning",

    # LoRA
    "lora": "LoRA",
    "lora adaptors": "LoRA",
    "lora adapters": "LoRA",

    # Recommender Systems — several wordings
    "recommender systems": "Recommender Systems",
    "recommendation systems": "Recommender Systems",
    "recommendation engines": "Recommender Systems",
    "recommendation": "Recommender Systems",

    # AI Agents — huge cluster of near-synonyms in current JDs
    "ai agents": "AI Agents",
    "agentic ai": "AI Agents",
    "agentic systems": "AI Agents",
    "agentic frameworks": "AI Agents",
    "agentic workflows": "AI Agents",
    "agent frameworks": "AI Agents",
    "ai agent frameworks": "AI Agents",
    "agent architectures": "AI Agents",
    "agent systems": "AI Agents",
    "multi-agent systems": "AI Agents",
    "multi-agent orchestration": "AI Agents",
    "tool-calling agents": "AI Agents",
    "orchestration of autonomous ai agents": "AI Agents",
    "agent development": "AI Agents",
    "agent builder": "AI Agents",

    # Prompt Engineering
    "prompting": "Prompt Engineering",
    "prompt management": "Prompt Engineering",

    # Evaluation — collapse the eval-cluster
    "evals": "Evaluation",
    "llm evaluation": "Evaluation",
    "ai evaluation": "Evaluation",
    "model evaluation": "Evaluation",
    "offline evals": "Evaluation",
    "online evals": "Evaluation",
    "evaluation frameworks": "Evaluation",
    "llm testing automation": "Evaluation",
    "ai evaluation tools": "Evaluation",

    # Observability
    "ai observability": "Observability",
    "observability tools": "Observability",
    "tracing": "Observability",
    "distributed tracing": "Observability",
    "model monitoring": "Observability",
    "drift monitoring": "Observability",
    "data drift": "Observability",
    "model decay": "Observability",

    # Data Pipelines
    "data pipelines": "Data Pipelines",
    "data processing pipelines": "Data Pipelines",
    "data processing": "Data Pipelines",
    "data ingestion": "Data Pipelines",
    "data integration": "Data Pipelines",
    "feature pipelines": "Data Pipelines",
    "retraining workflows": "Data Pipelines",
    "stream data processing": "Data Pipelines",

    # Model Deployment / Serving
    "model deployment": "Model Deployment",
    "productionization": "Model Deployment",
    "model serving": "Model Deployment",
    "canary releases": "Model Deployment",

    # Vector search / DBs
    "vector search": "Vector Databases",

    # Retrieval
    "retrieval systems": "Retrieval",
    "retrieval frameworks": "Retrieval",
}

# Generic/meta terms that are fields or soft skills rather than teachable,
# specific, nameable skills. Dropped at aggregation time.
GENERIC_TERMS = {
    # Fields, not skills
    "ai", "artificial intelligence", "data analysis", "data science",
    "software development", "software engineering", "programming",
    "coding", "computer science", "analytics", "engineering", "development",
    "research", "web development", "mobile development", "devops",
    "backend", "frontend", "full stack", "full-stack", "fullstack",
    # Soft skills
    "teamwork", "communication", "leadership", "passion", "ownership",
    "collaboration", "problem solving", "problem-solving", "critical thinking",
    "attention to detail", "self-starter", "team player", "adaptability",
    "creativity", "time management", "organization", "interpersonal skills",
    # Credentials (not teachable skills)
    "bachelor's degree", "master's degree", "phd", "ph.d.", "degree",
    # Non-skills
    "experience", "years of experience", "english",
    # Job-posting fluff that sneaks in as "skills" — not teachable, not specific
    "documentation", "tutorials", "sample code", "code reviews",
    "hackathons", "technical workshops", "developer-focused events",
    "code contributions", "technical lead", "solution engineering",
    "architecture", "architecture reviews", "architecture diagrams",
    "ml conferences", "publications at top ml conferences",
    "on-call rotation", "tooling", "workflows", "automation", "saas",
    "growth", "lifecycle marketing", "seo", "paid acquisition",
    "system integrations", "developer tools",
    # Observability primitives on their own (the real skill is "Observability")
    "traces", "metrics", "logs", "alerting", "monitoring",
    # Ads-domain terms that are really one umbrella (Advertising Systems)
    "ads ranking", "bidding models", "bid optimization",
    "auction-based systems", "roas feedback loops", "marketplace dynamics",
    # Service/ops generic
    "service design", "deployment", "testing", "incident response",
    # Miscellaneous meta "skills" seen in the 358-item bucket
    "api", "apis", "agent features", "agent skills", "agent tools",
    "tool invocation", "reasoning loops", "memory (ai agents)",
    "cost optimization", "benchmarks",
}


def _normalize(name: str) -> str:
    """
    Return the canonical display name for a skill, or "" if the name is generic
    and should be dropped.

    Strategy:
      1. Lowercase + strip for the lookup key
      2. Drop if in GENERIC_TERMS
      3. Check SKILL_ALIASES for a canonical mapping
      4. Check LOWERCASE_SKILLS (package names that stay lowercase)
      5. Fall back to Title Case — which cleanly merges "Causal Inference"
         and "causal inference" into one skill.
    """
    if not name:
        return ""
    lower = name.strip().lower()
    if not lower:
        return ""
    if lower in GENERIC_TERMS:
        return ""
    if lower in SKILL_ALIASES:
        return SKILL_ALIASES[lower]
    if lower in LOWERCASE_SKILLS:
        return lower
    # Preserve explicit uppercase acronym forms (e.g. "XGBoost" → "XGBoost"
    # should become "Xgboost" under title(), which is wrong). If the original
    # has internal uppercase past position 0, keep it verbatim.
    stripped = name.strip()
    if any(c.isupper() for c in stripped[1:]):
        return stripped
    # Default: Title Case — so "causal inference" and "Causal Inference" merge.
    return stripped.title()


def load_extractions(path: Path = EXTRACT_DIR) -> list[dict]:
    """Read every cached extraction file."""
    records = []
    for f in sorted(path.glob("*.json")):
        try:
            records.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception as e:
            print(f"  ! Skipping malformed {f.name}: {e}")
    return records


def aggregate(
    records: Iterable[dict],
    section_weights: dict[str, float] = SECTION_WEIGHTS,
) -> list[dict]:
    """
    Compute frequency and criticality per skill across all provided records.

    - frequency: raw count of jobs mentioning the skill
    - criticality_score: sum of section weights (a skill in 10 "requirements"
      sections is weighted 10.0; a skill in 10 "nice_to_have" is only 3.0)
    """
    freq: Counter[str] = Counter()
    crit: dict[str, float] = defaultdict(float)
    sections: dict[str, Counter[str]] = defaultdict(Counter)
    seen_per_job: dict[str, set[str]] = defaultdict(set)

    total_jobs = 0
    for rec in records:
        total_jobs += 1
        job_id = rec.get("job_id", "?")
        for skill in rec.get("skills") or []:
            name = _normalize(skill.get("name", ""))
            if not name:
                continue  # generic term or empty — skip
            # Map any raw section header the LLM leaked through back to a
            # canonical bucket so the weights apply consistently.
            section = _canonical_section(skill.get("section", "requirements"))
            # Count each skill once per job for frequency (so "Python" listed
            # 3x in one JD still counts as 1 job). But accumulate criticality.
            if name not in seen_per_job[job_id]:
                freq[name] += 1
                seen_per_job[job_id].add(name)
            crit[name] += section_weights.get(section, 1.0)
            sections[name][section] += 1

    rows = []
    for name, count in freq.most_common():
        rows.append(
            {
                "skill": name,
                "frequency": count,
                "pct_of_jobs": round(100.0 * count / max(total_jobs, 1), 1),
                "criticality_score": round(crit[name], 2),
                "sections": dict(sections[name]),
            }
        )
    return rows


def print_top(rows: list[dict], n: int = 20) -> None:
    """Human-readable sanity check dump."""
    print()
    print(f"{'Skill':<30} {'Jobs':>6} {'%':>6} {'Crit':>8}  Sections")
    print("-" * 80)
    for r in rows[:n]:
        sections_str = ", ".join(f"{k}:{v}" for k, v in r["sections"].items())
        print(
            f"{r['skill']:<30} {r['frequency']:>6} {r['pct_of_jobs']:>5}% "
            f"{r['criticality_score']:>8}  {sections_str}"
        )


if __name__ == "__main__":
    records = load_extractions()
    print(f"Loaded {len(records)} extractions from {EXTRACT_DIR}")
    rows = aggregate(records)
    print_top(rows, 20)
