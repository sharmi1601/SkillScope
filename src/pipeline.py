"""
pipeline.py — End-to-end offline pipeline: scrape → role filter → level filter
              → extract → (second-stage level validation) → aggregate.

Usage:
    # One-shot scrape of all default companies + run the data_analyst pipeline
    python -m src.pipeline --role data_analyst

    # Explicit level + sample cap
    python -m src.pipeline --role data_scientist --level new_grad --sample 250

    # Restrict to a specific company subset
    python -m src.pipeline --role product_manager --companies stripe airbnb

Design:
  - Scrape is cached per-company at data/raw_jobs/{slug}.json. After the first
    scrape all six roles can run instantly against the cache.
  - Level filter is applied TWICE:
      (1) on titles before extraction (saves Groq calls)
      (2) on extracted records (drops jobs whose years_experience_min > 3)
  - Summary persisted to data/summary_{role}.json for the scorer/recommender.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from . import aggregator, extractor, scraper

SUMMARY_DIR = Path(__file__).resolve().parent.parent / "data"

# Second-stage filter: after extraction, drop jobs whose inferred experience
# requirement is beyond what a new-grad can reasonably claim.
LEVEL_MAX_YEARS = {
    "new_grad": 3,
}

LEVEL_ALLOWED_SENIORITY = {
    "new_grad": {"intern", "junior", "unspecified"},
}


def _passes_post_extraction_level(record: dict, level: str) -> bool:
    """Second-stage level filter applied to already-extracted records."""
    if level not in LEVEL_MAX_YEARS:
        return True
    yrs_min = record.get("years_experience_min")
    max_allowed = LEVEL_MAX_YEARS[level]
    if yrs_min is not None and yrs_min > max_allowed:
        return False
    seniority = (record.get("seniority_level") or "unspecified").lower()
    if seniority not in LEVEL_ALLOWED_SENIORITY[level]:
        return False
    return True


def run(
    role: str,
    sample_n: int,
    companies: list[str],
    level: str | None = None,
    seed: int = 42,
) -> None:
    print(f"\n=== SkillScope offline pipeline ===")
    print(f"Role:       {role}")
    print(f"Level:      {level or 'any'}")
    print(f"Sample cap: {sample_n}")
    print(f"Companies:  {len(companies)} boards")
    print(f"Seed:       {seed}\n")

    # 1. Scrape ---------------------------------------------------------------
    print("[1/5] Fetching Greenhouse boards (cached per-company)...")
    all_jobs = scraper.fetch_all(companies)
    print(f"     total raw jobs: {len(all_jobs)}")

    # 2. Role filter ----------------------------------------------------------
    print(f"\n[2/5] Filtering to role '{role}'...")
    role_jobs = scraper.filter_by_role(all_jobs, role)
    print(f"     matched {len(role_jobs)} jobs by title keyword")

    # 2b. Level filter (title-stage) -----------------------------------------
    if level:
        before = len(role_jobs)
        role_jobs = scraper.filter_by_level(role_jobs, level)
        print(f"     {before} → {len(role_jobs)} after '{level}' title filter")

    if not role_jobs:
        print(
            "\n  !! No jobs matched. Try a different role/level, expand the "
            "companies list, or loosen keywords in scraper.py."
        )
        return

    # Sample per-company distribution so the demo can show diversity.
    companies_hit = sorted({j["company"] for j in role_jobs})
    print(f"     spanning {len(companies_hit)} companies: {', '.join(companies_hit[:10])}"
          f"{'...' if len(companies_hit) > 10 else ''}")

    # 3. Sample ---------------------------------------------------------------
    random.seed(seed)
    sample = random.sample(role_jobs, k=min(sample_n, len(role_jobs)))
    print(f"\n[3/5] Sampled {len(sample)} jobs for extraction (seed={seed})")

    # 4. Extract --------------------------------------------------------------
    print("\n[4/5] Extracting skills via Groq (cached per-job)...")
    extracted = extractor.extract_batch(sample)
    print(f"     extracted {len(extracted)} / {len(sample)} jobs")

    # 4b. Post-extraction level filter ---------------------------------------
    if level:
        before = len(extracted)
        extracted = [r for r in extracted if _passes_post_extraction_level(r, level)]
        print(f"     {before} → {len(extracted)} after post-extraction {level} filter "
              f"(years_min ≤ {LEVEL_MAX_YEARS[level]}, "
              f"seniority ∈ {sorted(LEVEL_ALLOWED_SENIORITY[level])})")

    if not extracted:
        print("\n  !! All extracted jobs were filtered out by the level check.")
        return

    # 5. Aggregate ------------------------------------------------------------
    print("\n[5/5] Aggregating top skills...")
    rows = aggregator.aggregate(extracted)
    aggregator.print_top(rows, 20)

    # 6. Persist summary ------------------------------------------------------
    summary_path = SUMMARY_DIR / f"summary_{role}.json"
    summary = {
        "role": role,
        "level": level,
        "sample_size": len(extracted),
        "companies_in_sample": sorted({r.get("company", "") for r in extracted}),
        "companies_scraped": companies,
        "top_skills": rows,
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\n✓ Wrote roll-up to {summary_path.relative_to(SUMMARY_DIR.parent)}")


def main() -> None:
    p = argparse.ArgumentParser(description="SkillScope offline pipeline")
    p.add_argument(
        "--role",
        default="data_analyst",
        choices=list(scraper.ROLE_KEYWORDS.keys()),
        help="Target role. See scraper.ROLE_KEYWORDS.",
    )
    p.add_argument(
        "--level",
        default="any",
        choices=[None, "new_grad", "any"],
        help=(
            "Experience level filter. Default 'any' skips level filtering "
            "(new-grad roles on Greenhouse are too rare to produce a demo-"
            "quality sample). Use 'new_grad' for strict 0-3 YOE filtering."
        ),
    )
    p.add_argument(
        "--sample",
        type=int,
        default=40,
        help=(
            "Max jobs to extract skills from (default: 40 — the demo sweet spot "
            "for stable top-10 skills). Fewer Groq calls, still statistically solid."
        ),
    )
    p.add_argument(
        "--companies",
        nargs="+",
        default=scraper.DEFAULT_COMPANIES,
        help=f"Greenhouse slugs. Default: the curated {len(scraper.DEFAULT_COMPANIES)}-company list.",
    )
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    level = None if args.level in (None, "any") else args.level
    run(args.role, args.sample, args.companies, level=level, seed=args.seed)


if __name__ == "__main__":
    main()
