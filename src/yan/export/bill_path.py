"""A measure's path from introduction to law, for the vote page: each step on its
kind's track, how far the measure has gone (from the bill_milestones mart), and
which step this vote was taken at.

Tracks follow /how/bills/:

    bill, joint resolution  Introduced, Committee, Passed {first chamber}, Passed {second
                            chamber}, Differences resolved, To President, then Became law;
                            or Vetoed and Veto override; or Pocket vetoed
    constitutional amendment  the same through Passed {second chamber} (it goes to the
                            states, not the President)
    concurrent resolution   Introduced, Committee, Agreed to in each chamber
    simple resolution       Introduced, Committee, Agreed to in its chamber

Each step's status is one of:

    done         reached: dated when the milestone is recorded, undated when only a
                 later step shows it was reached
    failed       the chamber voted it down (and hasn't passed it since), or the
                 override failed
    skipped      not needed: both chambers passed the same text
    in_progress  differences being resolved, not yet sent to the President
    upcoming     not reached
"""

import datetime as dt
import re

CHAMBERS = {"house": "House", "senate": "Senate"}
CONSTITUTIONAL_AMENDMENT = re.compile(r"^Proposing an amendment to the Constitution", re.I)
OVERRIDE_QUESTION = re.compile(r"Objections of the President|^On (Overriding the Veto|the Veto Message)")
DIFFERENCES_QUESTION = re.compile(
    r"^On (the )?Motion to (Suspend the Rules and )?Concur|^On (Agreeing to )?the Conference Report|"
    r"^On Motion to Instruct Conferees")


def track(bill_type: str, title: str | None) -> str:
    if bill_type in ("hres", "sres"):
        return "simple"
    if bill_type in ("hconres", "sconres"):
        return "concurrent"
    if bill_type in ("hjres", "sjres") and CONSTITUTIONAL_AMENDMENT.match(title or ""):
        return "amendment"
    return "law"


def _date(value) -> str | None:
    if value is None:
        return None
    return value.isoformat() if isinstance(value, dt.date) else str(value)


def vote_path(vote: dict, milestones: dict[str, tuple]) -> dict | None:
    """The path of the vote's measure, or None for a vote on no measure. `milestones` maps
    each milestone the measure reached to its (first_date, last_date)."""
    bill_type = vote.get("bill_type")
    if not bill_type:
        return None
    kind = track(bill_type, vote.get("measure_title"))
    first = "house" if bill_type.startswith("h") else "senate"
    second = "senate" if first == "house" else "house"
    passed = "Passed" if kind in ("law", "amendment") else "Agreed to in"
    not_passed = "Failed in" if kind in ("law", "amendment") else "Not agreed to in"

    def dated(key, which=0):
        return milestones[key][which] if key in milestones else None

    steps = [
        {"key": "introduced", "label": "Introduced", "date": dated("introduced"), "anchor": "introduced"},
        {"key": "committee", "label": "Committee", "date": dated("committee"), "anchor": "committee"},
    ]
    chambers = [first] if kind == "simple" else [first, second]
    for i, chamber in enumerate(chambers):
        name = CHAMBERS[chamber]
        failed = dated(f"failed_{chamber}") if f"passed_{chamber}" not in milestones else None
        steps.append({
            "key": f"passed_{chamber}",
            "label": f"{not_passed} {name}" if failed else f"{passed} {name}",
            "date": failed or dated(f"passed_{chamber}"),
            "failed": bool(failed),
            "anchor": "first-chamber" if i == 0 else "second-chamber",
        })
    # The committee step is the first chamber's: a committee report or discharge after the
    # first chamber passed it (in the second chamber) doesn't date it.
    first_passed = dated(f"passed_{first}")
    if steps[1]["date"] and first_passed and steps[1]["date"] > first_passed:
        steps[1]["date"] = None

    if kind == "law":
        steps.append({"key": "differences", "label": "Differences resolved", "date": dated("differences", 1),
                      "anchor": "differences"})
        steps.append({"key": "presented", "label": "To President", "date": dated("presented"), "anchor": "president"})
        overrides = [m for m in milestones if m.startswith("override_")]
        if "pocket_vetoed" in milestones:
            steps.append({"key": "pocket_vetoed", "label": "Pocket vetoed", "date": dated("pocket_vetoed"),
                          "failed": True, "anchor": "president"})
        elif "vetoed" in milestones or overrides:
            override_failed = [dated(m) for m in overrides if "_failed_" in m]
            steps.append({"key": "vetoed", "label": "Vetoed", "date": dated("vetoed"), "failed": True,
                          "anchor": "president"})
            steps.append({
                "key": "override",
                "label": "Veto override failed" if override_failed and "became_law" not in milestones else "Veto override",
                "date": (min(override_failed) if override_failed and "became_law" not in milestones
                         else max((dated(m) for m in overrides if "_passed_" in m), default=None)),
                "failed": bool(override_failed) and "became_law" not in milestones,
                "anchor": "override",
            })
            if "became_law" in milestones:
                steps.append({"key": "became_law", "label": "Became law", "date": dated("became_law"),
                              "anchor": "president"})
        else:
            steps.append({"key": "became_law", "label": "Became law", "date": dated("became_law"),
                          "anchor": "president"})

    _set_statuses(steps)
    for step in steps:
        step["date"] = _date(step["date"])
    current = _current_step(vote, steps)
    for step in steps:
        step["current"] = step["key"] == current
    return {"track": kind, "steps": steps}


def _set_statuses(steps: list[dict]) -> None:
    """A step with a date is done (or failed); one with no date is done when a later step
    was reached, so a vote recorded before Congress.gov's action still moves the path along."""
    reached_later = False
    for step in reversed(steps):
        key = step["key"]
        if step.pop("failed", False):
            status = "failed"
        elif key == "differences":
            presented = any(s["status"] in ("done", "failed") for s in steps[steps.index(step) + 1:])
            if presented:
                status = "done" if step["date"] else "skipped"
            else:
                status = "in_progress" if step["date"] else "upcoming"
        elif step["date"] or reached_later or key == "introduced":
            # A measure with a vote on it was introduced, whether or not its date is in yet.
            status = "done"
        else:
            status = "upcoming"
        step["status"] = status
        if status in ("done", "failed", "skipped", "in_progress"):
            reached_later = True
    # A failed step ends the path: what comes after it wasn't reached.
    for i, step in enumerate(steps):
        if step["status"] == "failed" and step["key"].startswith("passed_"):
            for later in steps[i + 1:]:
                later["status"] = "upcoming"
            break


def _current_step(vote: dict, steps: list[dict]) -> str | None:
    """The step this vote was taken at: a veto override vote at the override; a vote on
    the other chamber's amendment or a conference report at resolving differences;
    otherwise, in its chamber, the passage step if that chamber hadn't passed the measure
    before the vote date; otherwise resolving differences once both had."""
    keys = {s["key"]: s for s in steps}
    question = vote.get("question") or ""
    if OVERRIDE_QUESTION.search(question) and "override" in keys:
        return "override"
    if DIFFERENCES_QUESTION.match(question) and "differences" in keys:
        return "differences"
    vote_date = _date(vote.get("vote_date"))
    passage = keys.get(f"passed_{vote.get('chamber')}")
    if passage and not (passage["status"] == "done" and passage["date"] and passage["date"] < vote_date):
        return passage["key"]
    if "differences" in keys and keys["differences"]["status"] in ("upcoming", "in_progress"):
        return "differences"
    return None
