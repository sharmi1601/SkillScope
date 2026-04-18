"""
score_cli.py — Run the Gap Scorer end-to-end and print a human-readable report.

Usage:
    python -m src.score_cli --role data_analyst
    python -m src.score_cli --role data_analyst --profile data/example_profile.json
    python -m src.score_cli --role data_analyst --json         # JSON output for the backend later
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .gap_scorer import DATA_DIR, run
from .recommender import recommend_for_report
from .scheduler import generate_plan

# Cap long-term display so the terminal stays readable. The full list is still
# written to gap_report_*.json; only the printed view is truncated.
LONG_TERM_DISPLAY_CAP = 15


def _fmt_dims(dims: dict[str, float]) -> str:
    parts = [f"{k[:4]}={v:.2f}" for k, v in dims.items()]
    return " ".join(parts)


def _print_resources(recs: list[dict]) -> None:
    """Indented resource list under each skill."""
    for r in recs:
        title = r["title"]
        # Trim long titles so the terminal stays readable.
        if len(title) > 60:
            title = title[:57] + "…"
        print(f"    → [{r['platform']:<10}] {title}")
        print(f"              {r['url']}")


def _print_plan(plan: dict) -> None:
    """Pretty-print a week-by-week study plan."""
    print("\n=== Week-by-Week Study Plan ===")
    summary = plan.get("plan_summary", "")
    if summary:
        print(f"{summary}\n")
    print(f"Total weeks: {plan.get('total_weeks', '?')}  |  "
          f"Total hours: {plan.get('total_hours', '?')}")
    sani = plan.get("_sanitization", {})
    if sani:
        print(
            f"URL safety check → swapped: {sani.get('hallucinated_urls_swapped', 0)}, "
            f"removed: {sani.get('activities_removed', 0)}"
        )
    print()
    for wk in plan.get("weeks", []):
        header = (
            f"Week {wk.get('week_number', '?')}  "
            f"({wk.get('hours_planned', 0)}h)  —  {wk.get('focus', '')}"
        )
        print(header)
        print("-" * len(header))
        for act in wk.get("activities", []):
            title = act.get("title", "")
            if len(title) > 58:
                title = title[:55] + "…"
            print(
                f"  • [{act.get('skill', '')}] {title}  ({act.get('hours', 0)}h)"
            )
            print(f"        {act.get('url', '')}")
        print()


def main() -> None:
    p = argparse.ArgumentParser(description="SkillScope gap scorer + recommender")
    p.add_argument("--role", default="data_analyst")
    p.add_argument(
        "--profile",
        default=str(DATA_DIR / "example_profile.json"),
        help="Path to a profile JSON (defaults to the seed example).",
    )
    p.add_argument(
        "--no-resources",
        action="store_true",
        help="Skip the per-skill resource recommendations (score only).",
    )
    p.add_argument("--json", action="store_true", help="Emit JSON instead of a table.")
    p.add_argument(
        "--plan",
        action="store_true",
        help="Also generate a week-by-week study plan (uses one Groq call, cached).",
    )
    p.add_argument(
        "--force-plan",
        action="store_true",
        help="Regenerate the plan even if a cached one exists.",
    )
    args = p.parse_args()

    report = run(args.role, args.profile)

    # Load profile to pick up learning_style for the recommender.
    profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))
    user_style = profile.get("learning_style", "any")
    recs_by_skill: dict[str, list[dict]] = {}
    if not args.no_resources:
        recs_by_skill = recommend_for_report(report, user_style=user_style, k=3)

    plan = None
    if args.plan:
        if not recs_by_skill:
            # Plan needs resources to pick from; if user passed --no-resources,
            # fetch them quietly here instead of erroring out.
            recs_by_skill = recommend_for_report(report, user_style=user_style, k=3)
        plan = generate_plan(
            report,
            recs_by_skill,
            hours_per_week=profile.get("hours_per_week", 10),
            deadline_weeks=profile.get("deadline_weeks", 12),
            user_name=profile.get("name", "user"),
            role=args.role,
            force=args.force_plan,
        )

    if args.json:
        out = report.to_dict()
        out["recommendations"] = recs_by_skill
        if plan is not None:
            out["plan"] = plan
        print(json.dumps(out, indent=2))
        return

    print("\n=== SkillScope gap report ===")
    print(f"Role: {args.role}")
    print(f"Profile: {Path(args.profile).name}")
    print(f"Total hours needed (close gaps): {report.total_hours_close}")
    print(f"Feasible in deadline: {report.feasible_in_deadline}")

    print(f"\n── CLOSE GAPS ({len(report.close_gaps)}) ── quick wins worth learning now")
    for sg in report.close_gaps:
        print(f"  {sg.skill:<28} score={sg.total_score:.2f} | {sg.hours_to_learn}h | {sg.market_frequency_pct}% of jobs")
        print(f"    dims: {_fmt_dims(sg.dimensions)}")
        print(f"    why:  {sg.reasoning}")
        if recs_by_skill.get(sg.skill):
            _print_resources(recs_by_skill[sg.skill])

    print(f"\n── POLISH ({len(report.polish)}) ── you're most of the way there")
    for sg in report.polish:
        print(f"  {sg.skill:<28} score={sg.total_score:.2f} | {sg.hours_to_learn}h | adjacent: {', '.join(sg.user_has_adjacent)}")
        print(f"    why:  {sg.reasoning}")
        if recs_by_skill.get(sg.skill):
            _print_resources(recs_by_skill[sg.skill])

    total_lt = len(report.long_term)
    shown_lt = min(total_lt, LONG_TERM_DISPLAY_CAP)
    header = f"\n── LONG-TERM ({total_lt}) ── mark these on a longer runway"
    if total_lt > LONG_TERM_DISPLAY_CAP:
        header += f"  (showing top {shown_lt})"
    print(header)
    for sg in report.long_term[:LONG_TERM_DISPLAY_CAP]:
        print(f"  {sg.skill:<28} score={sg.total_score:.2f} | {sg.hours_to_learn}h")
        print(f"    why:  {sg.reasoning}")
    if total_lt > LONG_TERM_DISPLAY_CAP:
        print(f"  …and {total_lt - LONG_TERM_DISPLAY_CAP} more lower-priority skills "
              f"(see gap_report_{args.role}.json for the full list)")

    if plan is not None:
        _print_plan(plan)

    # Also write a machine-readable version next to the snapshot.
    out = DATA_DIR / f"gap_report_{args.role}.json"
    payload = report.to_dict()
    payload["recommendations"] = recs_by_skill
    if plan is not None:
        payload["plan"] = plan
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\n✓ Wrote machine-readable report to {out.relative_to(DATA_DIR.parent)}")


if __name__ == "__main__":
    main()
