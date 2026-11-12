"""Format a vote as a post, following the STYLE.md template:

    {Chamber} {result verb} {official title or nominee + position}
    {Yea} Yea · {Nay} Nay{ · Present}{ · Not Voting}{ · Vice President voted {position} to break the tie}
    Voted against party majority: {Name (P-ST)}, … and {N} others
    {link}
"""

import re

from yan.bot.rules import Decision, measure_label, outcome

MAX_GRAPHEMES = 300
MAX_NAMES = 5
# Shortest a title is cut to before listing fewer names.
MIN_TITLE = 60
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
        # Official forms: "Motion to Invoke Cloture: Motion to Proceed to S. 5",
        # "Motion to Invoke Cloture on the Motion to Proceed to H.R. 9340"
        stripped = re.sub(r"^Motion to Invoke Cloture(?::\s*|\s+on\s+)", "", vote.get("vote_title") or "")
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


def party_break_line(labels: list[str], max_names: int = MAX_NAMES) -> str | None:
    if not labels:
        return None
    shown, rest = labels[:max_names], len(labels) - max_names
    names = ", ".join(shown)
    if rest > 0:
        names += f" and {rest} other{'s' if rest != 1 else ''}"
    return f"Voted against party majority: {names}"


def display_url(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", url)


def grapheme_length(text: str) -> int:
    # Bluesky counts graphemes. Code points are never fewer than graphemes,
    # so counting code points keeps us safely under the limit.
    return len(text)


def format_post(vote_doc: dict, decision: Decision, max_length: int = MAX_GRAPHEMES) -> str:
    vote = vote_doc["vote"]
    title = headline_title(vote, decision)
    labels = [m["member_label"] for m in vote_doc["against_party_majority"]]
    tally = tally_line(vote, vote_doc["positions"])
    link = display_url(vote["source_url"])

    # Shorten until it fits, never touching the tally or link: first the title
    # (down to MIN_TITLE), then the number of names listed (the "and N others"
    # count keeps the total), then the title further.
    for min_title in (MIN_TITLE, 20):
        for max_names in range(MAX_NAMES, 0, -1):
            names = party_break_line(labels, max_names)
            fixed = "\n" + "\n".join([tally] + ([names] if names else []) + [link])
            text = headline(vote, decision, title) + fixed
            if grapheme_length(text) <= max_length:
                return text
            keep = len(title) - (grapheme_length(text) - max_length) - len(ELLIPSIS)
            if keep >= min_title:
                text = headline(vote, decision, title[:keep].rstrip(" ,;:") + ELLIPSIS) + fixed
                if grapheme_length(text) <= max_length:
                    return text
    raise PostTooLong(f"{vote['vote_id']}: cannot fit post in {max_length} characters")
