"""Which votes get posted, per the STYLE.md post rules.

Each vote gets a Decision: a vote kind (which also picks the post headline),
or a skip with the reason. Anything not matched by a posting rule is skipped
("Unsure? Default to skip"); every vote still appears on the site.
"""

import re
from dataclasses import dataclass

# Measure types whose passage is posted: bills and joint/concurrent resolutions.
# Simple resolutions (H.Res., S.Res.) are not in the posting list.
POSTED_MEASURE = re.compile(r"^(H\.R\.|S\.|H\.J\.Res\.|S\.J\.Res\.|H\.Con\.Res\.|S\.Con\.Res\.) ")

_HOUSE_MEASURE_PREFIXES = {
    "H R": "H.R.",
    "H RES": "H.Res.",
    "H J RES": "H.J.Res.",
    "H CON RES": "H.Con.Res.",
    "S": "S.",
    "S RES": "S.Res.",
    "S J RES": "S.J.Res.",
    "S CON RES": "S.Con.Res.",
}


def measure_label(vote: dict) -> str | None:
    """Measure number in the conventional citation form, e.g. "H RES 1655" -> "H.Res. 1655"."""
    number = vote.get("measure_number")
    if not number:
        return None
    if vote["chamber"] == "house":
        m = re.fullmatch(r"([A-Z ]+?) (\d+)", number)
        if m and m.group(1) in _HOUSE_MEASURE_PREFIXES:
            return f"{_HOUSE_MEASURE_PREFIXES[m.group(1)]} {m.group(2)}"
    return number


def outcome(vote: dict) -> bool | None:
    """True if the question was decided in the affirmative, False if not, None if unrecognized."""
    result = vote["result"] or ""
    if re.search(r"(Not Sustained|Failed|Rejected|Defeated)$", result):
        return False
    if re.search(r"(Passed|Agreed to|Confirmed|Sustained|Well Taken)$", result):
        return True
    return None


@dataclass(frozen=True)
class Decision:
    post: bool
    kind: str  # passage | veto_override | nomination | cloture | conference_report | disposing_motion | skip
    reason: str
    motion: str | None = None  # table / refer / postpone, for disposing motions


def skip(reason: str) -> Decision:
    return Decision(False, "skip", reason)


def decide(vote: dict) -> Decision:
    question = vote["question"] or ""
    title = vote.get("measure_title") or ""
    measure = measure_label(vote) or ""
    passed = outcome(vote)

    if vote.get("yea_count") is None:
        return skip("not a yea/nay vote (quorum call or Speaker election)")
    if re.search(r"(?i)providing for (the )?consideration", title):
        return skip("rule (H.Res. providing for consideration)")

    if vote["chamber"] == "house":
        return _decide_house(vote, question, measure, passed)
    return _decide_senate(vote, question, measure, passed)


def _decide_house(vote, question, measure, passed) -> Decision:
    if question.startswith("Passage, Objections of the President"):
        return Decision(True, "veto_override", "veto override")
    if question == "On Agreeing to the Conference Report":
        return Decision(True, "conference_report", "conference report")
    if question.startswith("On Motion to Suspend the Rules"):
        if passed:
            return Decision(True, "passage", "suspension vote that passed")
        return skip("suspension vote that did not pass")
    if question == "On Passage" or question.startswith("On Agreeing to the Resolution"):
        if POSTED_MEASURE.match(measure):
            return Decision(True, "passage", "passage of a bill or joint/concurrent resolution")
        return skip("simple resolution (not in the posting list)")
    if m := re.fullmatch(r"On Motion to (Table|Refer|Postpone(?: Consideration)?)", question):
        return _disposing_motion(vote, m.group(1), measure, passed)
    return skip(f"procedural or amendment vote: {question}")


def _decide_senate(vote, question, measure, passed) -> Decision:
    vote_title = vote.get("vote_title") or ""
    if question.startswith(("On the Cloture Motion", "On Cloture on")):
        return Decision(True, "cloture", "cloture")
    if question.startswith("On the Nomination"):
        return Decision(True, "nomination", "nomination")
    if re.match(r"On (Overriding the Veto|the Veto Message)|.*Objections of the President", question):
        return Decision(True, "veto_override", "veto override")
    if question.startswith("On the Conference Report"):
        return Decision(True, "conference_report", "conference report")
    if question.startswith(("On Passage of the Bill", "On the Joint Resolution", "On the Concurrent Resolution")):
        if POSTED_MEASURE.match(measure):
            return Decision(True, "passage", "passage of a bill or joint/concurrent resolution")
        return skip(f"passage vote on an unrecognized measure type: {measure}")
    if m := re.match(r"On the Motion to (Table|Refer|Postpone)", question):
        # The Senate's vote title names what is being tabled: the measure
        # itself, or an amendment, motion, point of order, or appeal.
        target = re.sub(r"^.*?Motion to (Table|Refer|Postpone)\b:?\s*", "", vote_title, flags=re.I)
        if vote.get("amendment_number") or re.search(r"(?i)amdt|motion|point of order|appeal", target):
            return skip(f"motion to {m.group(1).lower()} an amendment, motion, or point of order")
        return _disposing_motion(vote, m.group(1), measure, passed)
    return skip(f"procedural or amendment vote: {question}")


def _disposing_motion(vote, motion, measure, passed) -> Decision:
    """STYLE.md exception: a motion to table/refer/postpone that ends floor
    consideration of a measure is posted. Only an agreed-to motion ends
    consideration; a rejected one leaves the measure pending."""
    motion = motion.split()[0].lower()
    if vote.get("amendment_number") or not measure:
        return skip(f"motion to {motion} not directed at a measure")
    if not passed:
        return skip(f"motion to {motion} {measure} not agreed to (measure still pending)")
    return Decision(True, "disposing_motion", f"motion to {motion} that disposes of {measure}", motion=motion)
