"""Format a vote as a post, following the STYLE.md template:

    {Chamber} {result verb} {official title or nominee + position}
    {Yea} Yea · {Nay} Nay{ · Present}{ · Not Voting}{ · Vice President voted {position} to break the tie}
    D {Yea}–{Nay}{ · I {Yea}–{Nay}} · R {Yea}–{Nay}
    Voted against party majority: {Name (P-ST)}, …   (only when 1 to 5 members)
    {link}
"""

import re

from yan.bot.rules import Decision, measure_label, outcome

MAX_GRAPHEMES = 300
MAX_NAMES = 5
MIN_TITLE = 20
ELLIPSIS = "…"


class PostTooLong(ValueError):
    pass


def headline(vote: dict, decision: Decision, title: str) -> str:
    chamber = vote["chamber"].capitalize()
    passed = outcome(vote)
    measure = measure_label(vote)
    cited = f'{measure}, "{title}"' if measure else f'"{title}"'

    if decision.kind == "passage":
        return f"{chamber} {'passes' if passed else 'fails'} {cited}"
    if decision.kind == "veto_override":
        overridden = passed or "Overridden" in (vote["result"] or "")
        return f"{chamber} {'overrides veto of' if overridden else 'sustains veto of'} {cited}"
    if decision.kind == "conference_report":
        return f"{chamber} {'agrees to' if passed else 'rejects'} conference report on {cited}"
    if decision.kind == "disposing_motion":
        return f"{chamber} {'agrees to' if passed else 'rejects'} motion to {decision.motion} {cited}"
    if decision.kind == "nomination":
        return f"{chamber} {'confirms' if passed else 'rejects'} {title}"
    if decision.kind == "cloture":
        return f"{chamber} {'invokes cloture on' if passed else 'fails to invoke cloture on'} {title}"
    raise ValueError(f"no headline for vote kind {decision.kind!r}")


def headline_title(vote: dict, decision: Decision) -> str:
    """The official title or nominee + position that goes in the headline."""
    title = vote.get("measure_title") or ""
    if decision.kind == "nomination":
        # Official form: "Peter Hegseth, of Tennessee, to be Secretary of Defense"
        m = re.fullmatch(r"(.+?), of [^,]+, to be (.+)", title)
        return f"{m.group(1)} as {m.group(2)}" if m else title
    if decision.kind == "cloture":
        # Official forms vary: "Motion to Invoke Cloture: Motion to Proceed to S. 5",
        # "... Cloture on the Motion to Proceed: H.R. 7008", "... Cloture Re: Amdt. No. 4308",
        # "Upon Reconsideration, Motion to Invoke Cloture ...". All become the most
        # common form, "Motion to Proceed to {measure}", with reconsideration last
        # as the Senate also writes it ("..., Upon Reconsideration").
        stripped = vote.get("vote_title") or ""
        reconsidered = re.match(r"^Upon Reconsideration[,:]\s*", stripped)
        if reconsidered:
            stripped = stripped[reconsidered.end():]
        stripped = re.sub(r"^Motion to Invoke Cloture(?::\s*|\s+Re:\s*|\s+on\s+)(?:the\s+)?", "", stripped)
        stripped = re.sub(r"^Motion to Proceed(?::\s*|\s+to\s+)", "Motion to Proceed to ", stripped,
                          flags=re.IGNORECASE)
        if reconsidered and not stripped.endswith("Upon Reconsideration"):
            stripped += ", Upon Reconsideration"
        return stripped or title
    return title


def tally_line(vote: dict, positions: dict[str, str]) -> str:
    # House recorded votes use Aye/No; yea-and-nay votes use Yea/Nay. Use what was recorded.
    yes_word, no_word = ("Aye", "No") if "Aye" in positions.values() else ("Yea", "Nay")
    parts = [f"{vote['yea_count']} {yes_word}", f"{vote['nay_count']} {no_word}"]
    if vote.get("present_count"):
        parts.append(f"{vote['present_count']} Present")
    if vote.get("not_voting_count"):
        parts.append(f"{vote['not_voting_count']} Not Voting")
    if vote.get("tie_breaker_by") and vote.get("tie_breaker_vote"):
        parts.append(f"Vice President voted {vote['tie_breaker_vote']} to break the tie")
    return " · ".join(parts)


def party_line(party_totals: dict[str, dict[str, int]]) -> str:
    """Yea–Nay per party, by party on the vote date, parties in alphabetical
    order. D and R always appear; I only when an independent voted Yea or Nay."""
    def counts(party):
        totals = party_totals.get(party, {})
        return totals.get("yes", 0), totals.get("no", 0)

    parts = []
    for party in ("D", "I", "R"):
        yes, no = counts(party)
        if party != "I" or yes or no:
            parts.append(f"{party} {yes}–{no}")
    return " · ".join(parts)


def party_break_line(labels: list[str], max_names: int = MAX_NAMES) -> str | None:
    """Names of members who voted against their party majority, only when
    there are between 1 and max_names of them; otherwise no line."""
    if not labels or len(labels) > max_names:
        return None
    return f"Voted against party majority: {', '.join(labels)}"


def display_url(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", url)


def grapheme_length(text: str) -> int:
    # Bluesky counts graphemes. Code points are never fewer than graphemes,
    # so counting code points keeps us safely under the limit.
    return len(text)


def format_post(vote_doc: dict, decision: Decision, max_length: int = MAX_GRAPHEMES) -> str:
    vote = vote_doc["vote"]
    title = headline_title(vote, decision)
    names = party_break_line([m["member_label"] for m in vote_doc["against_party_majority"]])
    lines = [tally_line(vote, vote_doc["positions"]), party_line(vote_doc["party_totals"])]
    fixed = "\n" + "\n".join(lines + ([names] if names else []) + [display_url(vote["source_url"])])

    # Only the title is shortened; the tally, party lines, names, and link stay whole.
    text = headline(vote, decision, title) + fixed
    if grapheme_length(text) <= max_length:
        return text
    keep = len(title) - (grapheme_length(text) - max_length) - len(ELLIPSIS)
    if keep >= MIN_TITLE:
        return headline(vote, decision, title[:keep].rstrip(" ,;:") + ELLIPSIS) + fixed
    raise PostTooLong(f"{vote['vote_id']}: cannot fit post in {max_length} characters")
