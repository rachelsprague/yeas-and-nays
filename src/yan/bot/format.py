"""Format a vote as a post, following the STYLE.md template:

    {Chamber} {result verb} {official title or nominee + position}
    {Yea} Yea · {Nay} Nay{ · Present}{ · Not Voting}{ · Vice President voted {position} to break the tie}
    D {Yea}–{Nay}{ · I {Yea}–{Nay}} · R {Yea}–{Nay}
    Voted against party majority: {Name (P-ST)}, …   (only when 1 to 5 members)
    {link}
"""

import re

from yan.bot.rules import RECONSIDERED, Decision, headline_title, measure_label, outcome
from yan.config import SITE_URL

MAX_GRAPHEMES = 300
MAX_NAMES = 5
MIN_TITLE = 20
ELLIPSIS = "…"
CLOSERS = {"(": ")", "“": "”", "‘": "’"}
# a, in, on, by, with and or count only in lowercase: "Part A" and "Portland, OR" end a name.
SMALL_WORD_END = re.compile(r"\s[\"“‘']?(?:of|to|the|and|for|(?-i:a|in|on|by|with|or))$", flags=re.IGNORECASE)


class PostTooLong(ValueError):
    pass


def headline(vote: dict, decision: Decision, title: str) -> str:
    chamber = vote["chamber"].capitalize()
    passed = outcome(vote)
    measure = measure_label(vote)
    # No official title: cite the measure alone, not an empty pair of quotes.
    if measure and not title:
        cited = measure
    else:
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
    if decision.kind == "expulsion":
        return f"{chamber} {'agrees to' if passed else 'rejects'} {cited}"
    if decision.kind == "nomination":
        return f"{chamber} {'confirms' if passed else 'rejects'} {title}"
    if decision.kind == "cloture":
        return f"{chamber} {'invokes cloture on' if passed else 'fails to invoke cloture on'} {title}"
    raise ValueError(f"no headline for vote kind {decision.kind!r}")


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


def vote_page_url(vote: dict) -> str:
    """Our page for the vote, which links the official record (STYLE.md).
    Same route as the site's vote pages in site/_plugins/yan_data.rb."""
    return f"{SITE_URL}/votes/{vote['congress']}/{vote['chamber']}/{vote['session']}/{vote['roll_number']}/"


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
    fixed = "\n" + "\n".join(lines + ([names] if names else []) + [display_url(vote_page_url(vote))])

    # Only the title is shortened; the tally, party lines, names, and link stay whole.
    text = headline(vote, decision, title) + fixed
    if grapheme_length(text) <= max_length:
        return text
    # A trailing ", Upon Reconsideration" goes first, so it is never cut mid-word.
    if title.endswith(RECONSIDERED):
        title = title[:-len(RECONSIDERED)]
        text = headline(vote, decision, title) + fixed
        if grapheme_length(text) <= max_length:
            return text
    keep = len(title) - (grapheme_length(text) - max_length) - len(ELLIPSIS)
    # A cut inside a quoted name or parentheses ("“Fairness…", "(the Housing…")
    # gets its closing marks back, which need more characters, so it may take
    # a shorter cut.
    for length in range(keep, MIN_TITLE - 1, -1):
        short = cut_title(title, length)
        text = headline(vote, decision, short + ELLIPSIS + closing_marks(short)) + fixed
        if grapheme_length(text) <= max_length:
            return text
    raise PostTooLong(f"{vote['vote_id']}: cannot fit post in {max_length} characters")


def closing_marks(text: str) -> str:
    """The marks that close each parenthesis or quote text opens and leaves
    open, innermost first. A straight double quote opens or closes by turn.
    A closing mark closes the latest open mark it matches, even past marks
    opened inside it and left open (“a (b ” c leaves only the parenthesis
    open); a stray closing mark is ignored. A ’ between two letters or
    digits is an apostrophe ("Children’s", "1990’s"), not a closing quote."""
    open_marks = []
    for i, char in enumerate(text):
        if char == '"':
            if '"' in open_marks:
                close(open_marks, char)
            else:
                open_marks.append(char)
        elif char in CLOSERS:
            open_marks.append(CLOSERS[char])
        elif char == "’" and text[i - 1:i].isalnum() and text[i + 1:i + 2].isalnum():
            continue
        elif char in open_marks:
            close(open_marks, char)
    return "".join(reversed(open_marks))


def close(open_marks: list[str], mark: str) -> None:
    """Remove the latest occurrence of mark from open_marks."""
    del open_marks[len(open_marks) - 1 - open_marks[::-1].index(mark)]


def ends_word(rest: str) -> bool:
    """Whether a cut before rest falls at the end of a word: before a space, or
    before punctuation that ends one ("(the Housing Act)", "?", ”).

    A period doesn't count: a cut never falls just before one that ends the
    title (the ellipsis needs that space), and mid-title most periods end an
    abbreviation ("H.R. 1", "St. Louis"), so the whole word is dropped instead."""
    return bool(re.match(r"[,;:)?!”’\"']*(\s|$)", rest))


def cut_title(title: str, keep: int) -> str:
    """The first keep characters of title, cut back to the end of a word so
    no word or bill number is left half-written, unless that leaves too
    little of the title. No trailing punctuation; the caller adds the ellipsis."""
    short = title[:keep]
    at_boundary = ends_word(title[keep:])
    if not at_boundary and " " in short:
        by_word = short.rsplit(" ", 1)[0].rstrip(" ,;:")
        if len(by_word) >= MIN_TITLE:
            short = by_word
    whole_words = at_boundary or short != title[:keep]
    # A cut that ends on a whole small word ("Secretary of…", 'as "The…') reads
    # as broken, and so does one just after a period, which mostly ends an
    # abbreviation ("of H.R.") but can end a sentence ("Code of 1986."). Drop
    # such words, one at a time since each can bare another ("U.S.C. and"),
    # as long as enough title remains.
    short = short.rstrip(" ,;:")
    while True:
        if short.endswith(".") and " " in short:
            trimmed = short.rsplit(" ", 1)[0]
        elif whole_words:
            trimmed = SMALL_WORD_END.sub("", short)
        else:
            break
        trimmed = trimmed.rstrip(" ,;:")
        if trimmed == short or len(trimmed) < MIN_TITLE:
            break
        short, whole_words = trimmed, True
    return short.rstrip(" ,;:")
