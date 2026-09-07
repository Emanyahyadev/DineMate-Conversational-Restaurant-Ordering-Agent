"""Run the golden set and compute the accuracy KPIs.

    uv run python -m evals.run                # all cases
    uv run python -m evals.run --filter CART  # one family
    uv run python -m evals.run --json out.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from evals.harness import CaseResult, load_cases, menu_names, run_case

# KPIS.md section 2. HARD gates have a target of zero violations.
HARD = ["A01", "A02", "A03", "A11"]
GATED = {"A04": 0.97, "A05": 0.98, "A06": 0.99, "A09": 0.95, "A10": 1.0, "A08a": 0.90}


def summarise(results: list[CaseResult]) -> dict:
    total = len(results)
    passed = sum(1 for r in results if r.passed)

    per_kpi: dict[str, dict[str, int]] = {}
    for r in results:
        for kpi in r.kpi:
            bucket = per_kpi.setdefault(kpi, {"cases": 0, "violations": 0})
            bucket["cases"] += 1
            if kpi in r.violations:
                bucket["violations"] += 1

    # A HARD violation anywhere counts, whether or not the case declared that KPI.
    hard_hits = {k: 0 for k in HARD}
    for r in results:
        for k in HARD:
            if k in r.violations:
                hard_hits[k] += 1

    scores = {}
    for kpi, bucket in sorted(per_kpi.items()):
        rate = 1.0 - (bucket["violations"] / bucket["cases"]) if bucket["cases"] else 1.0
        scores[kpi] = {
            "cases": bucket["cases"],
            "violations": bucket["violations"],
            "score": round(rate, 4),
        }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cases": total,
        "passed": passed,
        "failed": total - passed,
        "hard_violations": hard_hits,
        "kpi": scores,
        "results": [
            {
                "id": r.case_id,
                "title": r.title,
                "passed": r.passed,
                "us": r.us,
                "kpi": r.kpi,
                "violations": sorted(r.violations),
                "failures": r.failures,
            }
            for r in results
        ],
    }


def render(summary: dict) -> str:
    lines = [
        "",
        "=" * 72,
        f"  DineMate eval  -  {summary['passed']}/{summary['cases']} cases passed",
        "=" * 72,
        "",
        "  HARD GATES (target: 0 violations)",
    ]
    for kpi, hits in summary["hard_violations"].items():
        mark = "PASS" if hits == 0 else "FAIL"
        lines.append(f"    {kpi}  {hits} violation(s)   [{mark}]")

    lines += ["", "  SCORED KPIs"]
    for kpi, data in summary["kpi"].items():
        if kpi in summary["hard_violations"]:
            continue
        target = GATED.get(kpi)
        mark = "" if target is None else ("PASS" if data["score"] >= target else "FAIL")
        target_s = f" target {target:.0%}" if target else ""
        lines.append(
            f"    {kpi}  {data['score']:.1%} over {data['cases']} case(s){target_s}   [{mark}]"
        )

    failed = [r for r in summary["results"] if not r["passed"]]
    if failed:
        lines += ["", "  FAILURES"]
        for r in failed:
            lines.append(f"    {r['id']}  {r['title']}")
            for f in r["failures"]:
                lines.append(f"        - {f}")
    lines.append("")
    return "\n".join(lines)


async def main_async(args: argparse.Namespace) -> int:
    cases = load_cases(args.filter)
    if not cases:
        print("no cases matched")
        return 2

    names = await menu_names()
    results = [await run_case(case, names) for case in cases]
    summary = summarise(results)
    print(render(summary))

    if args.json:
        Path(args.json).write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"  wrote {args.json}")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the DineMate golden eval set")
    parser.add_argument("--filter", help="Only cases whose id contains this")
    parser.add_argument("--json", help="Write the scorecard here")
    parser.add_argument("--mode", default="recorded", choices=["recorded", "live"])
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
