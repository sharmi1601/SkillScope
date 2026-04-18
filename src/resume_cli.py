"""
resume_cli.py — Parse a resume file into a SkillScope profile JSON.

Usage:
    python -m src.resume_cli --resume my_resume.pdf --role data_analyst
    python -m src.resume_cli --resume my_resume.docx --role data_analyst \\
        --name sharmi --hours 10 --weeks 12 --style video

The resulting profile is written to data/profile_{slug}.json and is
immediately usable by score_cli:

    python -m src.score_cli --role data_analyst \\
        --profile data/profile_sharmi.json --plan
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from .gap_scorer import DATA_DIR
from .resume_parser import parse_resume


VALID_ROLES = {"data_analyst", "data_engineer", "data_scientist", "ml_engineer"}
VALID_STYLES = {"video", "reading", "hands_on", "any"}


def _slugify(s: str) -> str:
    """Turn a name into a safe filename stem: 'Sharmi D.' -> 'sharmi_d'."""
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "user"


def _print_profile_summary(profile: dict, out_path: Path) -> None:
    print("\n=== Resume parsed ===")
    print(f"Name:           {profile.get('name')}")
    print(f"Target role:    {profile.get('target_role')}")
    print(
        f"Schedule:       {profile.get('hours_per_week')}h/week × "
        f"{profile.get('deadline_weeks')} weeks  (style: {profile.get('learning_style')})"
    )

    skills = profile.get("skills", [])
    strong = [s["name"] for s in skills if s.get("confidence") == "strong"]
    basic = [s["name"] for s in skills if s.get("confidence") == "basic"]
    print(f"\nSkills extracted: {len(skills)}")
    if strong:
        print(f"  strong: {', '.join(strong)}")
    if basic:
        print(f"  basic:  {', '.join(basic)}")

    exps = profile.get("experiences", [])
    if exps:
        print(f"\nExperience ({len(exps)}):")
        for e in exps:
            yrs = e.get("years", "?")
            print(f"  • {e.get('title', '?')} @ {e.get('company', '?')} ({yrs}y)")

    projs = profile.get("projects", [])
    if projs:
        print(f"\nProjects ({len(projs)}):")
        for p in projs:
            tech = ", ".join(p.get("tech", []))
            print(f"  • {p.get('name', '?')}  [{tech}]")

    edus = profile.get("education", [])
    if edus:
        print(f"\nEducation ({len(edus)}):")
        for ed in edus:
            print(f"  • {ed.get('degree', '?')}, {ed.get('field', '?')}")

    print(f"\n✓ Wrote profile to {out_path.relative_to(DATA_DIR.parent)}")
    print("\nNext step — run the gap report against this profile:")
    print(
        f"  python -m src.score_cli --role {profile.get('target_role')} "
        f"--profile {out_path.relative_to(DATA_DIR.parent).as_posix()} --plan"
    )


def main() -> None:
    p = argparse.ArgumentParser(
        description="Parse a resume (PDF/DOCX/TXT) into a SkillScope profile JSON."
    )
    p.add_argument("--resume", required=True, help="Path to the resume file.")
    p.add_argument(
        "--role",
        required=True,
        choices=sorted(VALID_ROLES),
        help="Target role to score against.",
    )
    p.add_argument(
        "--name",
        default=None,
        help="Override the candidate name (otherwise taken from the resume).",
    )
    p.add_argument(
        "--hours",
        type=int,
        default=10,
        help="Hours per week the candidate can study (default: 10).",
    )
    p.add_argument(
        "--weeks",
        type=int,
        default=12,
        help="Deadline in weeks (default: 12).",
    )
    p.add_argument(
        "--style",
        choices=sorted(VALID_STYLES),
        default="any",
        help="Preferred learning style for the recommender (default: any).",
    )
    p.add_argument(
        "--out",
        default=None,
        help="Override the output path (default: data/profile_{name}.json).",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Print the profile JSON to stdout instead of a human summary.",
    )
    args = p.parse_args()

    resume_path = Path(args.resume).expanduser().resolve()
    if not resume_path.exists():
        p.error(f"Resume file not found: {resume_path}")

    profile = parse_resume(
        path=resume_path,
        target_role=args.role,
        name=args.name,
        hours_per_week=args.hours,
        deadline_weeks=args.weeks,
        learning_style=args.style,
    )

    # Pick an output path. Prefer --out; else derive from name.
    if args.out:
        out_path = Path(args.out).expanduser().resolve()
    else:
        slug = _slugify(str(profile.get("name") or "user"))
        out_path = DATA_DIR / f"profile_{slug}.json"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(profile, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(profile, indent=2))
        return

    _print_profile_summary(profile, out_path)


if __name__ == "__main__":
    main()
