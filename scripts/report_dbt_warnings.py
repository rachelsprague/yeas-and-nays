"""Show dbt's test warnings on the Actions run page.

A warning doesn't fail `dbt build`, so on its own it only reaches the step's
log. This prints one Actions warning annotation per test that warned and, when
GITHUB_STEP_SUMMARY is set, lists them all in the run's summary (GitHub shows
at most 10 warning annotations per step). Standard library only:

    python3 -I scripts/report_dbt_warnings.py <run_results.json>
"""

import json
import os
import sys
from pathlib import Path


def warnings(results: dict) -> list[str]:
    """One line per test that warned, "name: dbt's message", sorted by name."""
    lines = []
    for result in results["results"]:
        if result["status"] != "warn":
            continue
        # "test.<project>.<name>", with a hash after the name of a generic test.
        name = result["unique_id"].split(".")[2]
        # One line each: a line break would end the annotation or the list item.
        message = " ".join((result.get("message") or "warned").split())
        lines.append(f"{name}: {message}")
    return sorted(lines)


def annotation(line: str) -> str:
    return "::warning title=dbt test::" + line.replace("%", "%25")


def main(path: str) -> None:
    lines = warnings(json.loads(Path(path).read_text()))
    for line in lines:
        print(annotation(line))
    if not lines:
        print("No dbt warnings.")
        return
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a") as f:
            f.write("### dbt warnings\n\n")
            f.writelines(f"- `{line}`\n" for line in lines)


if __name__ == "__main__":
    main(sys.argv[1])
