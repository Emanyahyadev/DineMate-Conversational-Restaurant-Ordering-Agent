"""CI gate: turn a scorecard into a merge decision (EVAL_PLAN.md section 8).

    uv run python -m evals.gate results.json [--baseline base.json]

Exits non-zero when:
  1. any HARD KPI has a violation          (no threshold, no exceptions)
  2. any GATED KPI is below its target
  3. a GATED KPI regressed by > 2 points versus the baseline, even if above target
  4. a case that passed on the baseline now fails
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from evals.run import GATED, HARD

REGRESSION_TOLERANCE = 0.02


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("results")
    parser.add_argument("--baseline")
    args = parser.parse_args()

    current = json.loads(Path(args.results).read_text(encoding="utf-8"))
    baseline = (
        json.loads(Path(args.baseline).read_text(encoding="utf-8"))
        if args.baseline and Path(args.baseline).exists()
        else None
    )

    problems: list[str] = []

    # 1. Hard gates.
    for kpi in HARD:
        hits = current["hard_violations"].get(kpi, 0)
        if hits:
            problems.append(f"HARD GATE {kpi}: {hits} violation(s) - target is 0")

    # 2. Scored gates.
    for kpi, target in GATED.items():
        data = current["kpi"].get(kpi)
        if not data:
            continue
        if data["score"] < target:
            problems.append(
                f"{kpi}: {data['score']:.1%} is below the {target:.0%} target"
            )

    if baseline:
        # 3. Regression even while above target.
        for kpi, data in current["kpi"].items():
            was = baseline["kpi"].get(kpi)
            if not was:
                continue
            drop = was["score"] - data["score"]
            if drop > REGRESSION_TOLERANCE:
                problems.append(
                    f"{kpi} regressed {was['score']:.1%} -> {data['score']:.1%} "
                    f"(more than {REGRESSION_TOLERANCE:.0%})"
                )

        # 4. Per-case regression, independent of aggregates.
        was_passing = {r["id"] for r in baseline["results"] if r["passed"]}
        now_failing = {r["id"] for r in current["results"] if not r["passed"]}
        for case_id in sorted(was_passing & now_failing):
            problems.append(f"case {case_id} passed on the baseline and now fails")

    print()
    if problems:
        print("EVAL GATE: FAILED")
        for p in problems:
            print(f"  - {p}")
        print()
        return 1

    print(
        f"EVAL GATE: PASSED  ({current['passed']}/{current['cases']} cases, "
        "all hard gates clean)"
    )
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
