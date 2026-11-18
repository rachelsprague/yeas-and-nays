"""Link card images for vote pages: one 1200x630 PNG per vote, at
site/assets/cards/{vote_id}.png, which the vote page's og:image points to.

    Yeas & Nays                         HOUSE · ROLL CALL 325 · NOV. 17, 2026
    ─────────────────────────────────────────────────────────────────────────
    H.R. 9600
    “Common Sense 250 Act”

    Motion to Suspend the Rules and Pass
    Passed   365 Yea · 36 Nay · 32 Not Voting
    ███████████████████████████████████████████████████████████▓▓▓▓▓▓░░░░░

The title is the page heading's (measure title, else the Senate's vote title,
else the question), the measure title in quotes as in bot posts. A vote with
no Yea or Nay (a quorum call) or one tallied by candidate (a Speaker
election) gets no card; its page keeps the brand card. The cards are built
for each site deploy and never committed.
"""

import datetime as dt
import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from yan.config import OUT_DIR, REPO_ROOT

log = logging.getLogger(__name__)

CARDS_DIR = REPO_ROOT / "site" / "assets" / "cards"
FONTS = Path(__file__).parent / "fonts"

WIDTH, HEIGHT, MARGIN = 1200, 630, 70
PAPER, INK, AUBERGINE, MUTED, RULE = "#F2EFE6", "#1C1C1C", "#5A3463", "#5B5752", "#D9D3C4"
TITLE_SIZES = (78, 68, 58, 50)
TITLE_LINES = 3
TITLE_TOP = 194  # below the measure label
ELLIPSIS = "…"

AP_MONTHS = ["Jan.", "Feb.", "March", "April", "May", "June", "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."]
CHAMBERS = {"house": "House", "senate": "Senate"}


@dataclass(frozen=True)
class Card:
    meta: str  # "HOUSE · ROLL CALL 325 · NOV. 17, 2026"
    label: str | None  # "H.R. 9600"
    title: str  # "“Common Sense 250 Act”"
    question: str  # "Motion to Suspend the Rules and Pass"
    result: str  # "Passed"
    tally: str  # "365 Yea · 36 Nay · 32 Not Voting"
    counts: tuple[int, int, int]  # yes, no, and present + not voting, for the bar


def position_kind(raw: str) -> str:
    """Mirrors transform/macros/normalize_position.sql (and the site's position_kind)."""
    if raw in ("Yea", "Aye", "Guilty"):
        return "yes"
    if raw in ("Nay", "No", "Not Guilty"):
        return "no"
    if raw.startswith("Present"):
        return "present"
    if raw == "Not Voting":
        return "not_voting"
    return "other"


def ap_date(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return f"{AP_MONTHS[d.month - 1]} {d.day}, {d.year}"


def card_text(vote: dict, doc: dict) -> Card | None:
    """What a vote's card says, or None for a vote that gets no card."""
    positions = list(doc["positions"].values())
    kinds = [position_kind(p) for p in positions]
    counts = {k: kinds.count(k) for k in ("yes", "no", "present", "not_voting", "other")}
    if counts["other"] or not (counts["yes"] or counts["no"]):
        return None

    # The words the vote recorded, as on the vote page: Yea/Nay, Aye/No or Guilty/Not Guilty.
    yes = next((w for w in ("Aye", "Guilty") if w in positions), "Yea")
    no = {"Aye": "No", "Guilty": "Not Guilty"}.get(yes, "Nay")
    tally = [f"{counts['yes']} {yes}", f"{counts['no']} {no}"]
    if counts["present"]:
        tally.append(f"{counts['present']} Present")
    if counts["not_voting"]:
        tally.append(f"{counts['not_voting']} Not Voting")

    question = vote["question"]
    title = vote.get("measure_title") or vote.get("vote_title") or question
    if vote.get("measure_title"):
        title = f"“{title}”"
    meta = "  ·  ".join([CHAMBERS[vote["chamber"]], f"Roll call {vote['roll_number']}", ap_date(vote["vote_date"])])
    return Card(
        meta=meta.upper(),
        label=vote.get("measure_label"),
        title=title,
        question=question.removeprefix("On the ").removeprefix("On "),
        result=vote["result"],
        tally="  ·  ".join(tally),
        counts=(counts["yes"], counts["no"], counts["present"] + counts["not_voting"]),
    )


@lru_cache(maxsize=None)
def serif(size: int, weight: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(FONTS / "Newsreader.ttf", size)
    font.set_variation_by_axes([weight, min(72, size)])  # axes: weight, optical size
    return font


@lru_cache(maxsize=None)
def sans(size: int, weight: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(FONTS / "IBMPlexSans.ttf", size)
    font.set_variation_by_axes([weight, 100])  # axes: weight, width
    return font


def wrap(text: str, fits) -> list[str]:
    """Greedy word wrap: each line as long as `fits(line)` allows."""
    lines: list[str] = []
    for word in text.split():
        if lines and fits(f"{lines[-1]} {word}"):
            lines[-1] = f"{lines[-1]} {word}"
        else:
            lines.append(word)
    return lines


def fit_title(title: str, measure, width: int, height: int) -> tuple[int, list[str]]:
    """The largest title size whose lines fit `height` (at most TITLE_LINES);
    at the smallest size, the last line that fits ends in an ellipsis."""
    for size in TITLE_SIZES:
        line_height = round(size * 1.12)
        max_lines = min(TITLE_LINES, height // line_height)
        lines = wrap(title, lambda t: measure(t, size) <= width)
        if len(lines) <= max_lines:
            return size, lines
    lines = lines[:max_lines]
    closer = "”" if title.endswith("”") else ""
    last = lines[-1]
    while " " in last and measure(last + ELLIPSIS + closer, size) > width:
        last = last.rsplit(" ", 1)[0]
    lines[-1] = last.rstrip(",;:") + ELLIPSIS + closer
    return size, lines


def render(card: Card) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    d = ImageDraw.Draw(img)
    right = WIDTH - MARGIN

    # Top row: a small wordmark, then chamber, roll call and date on the right.
    x = MARGIN
    for part, color in (("Yeas ", INK), ("&", AUBERGINE), (" Nays", INK)):
        d.text((x, 52), part, font=serif(38, 600), fill=color)
        x += d.textlength(part, font=serif(38, 600))
    d.text((right, 90), card.meta, font=sans(21, 500), fill=MUTED, anchor="rs")
    d.line((MARGIN, 116, right, 116), fill=RULE, width=2)

    # Bottom block, from the bar up: result and tally on one baseline, the question above.
    bar_top, bar_height = 550, 14
    baseline = bar_top - 30
    question_baseline = baseline - 70
    result_font = next((serif(s, 600) for s in (58, 50, 42)
                        if d.textlength(card.result, font=serif(s, 600)) <= (right - MARGIN) * 0.6), serif(36, 600))
    d.text((MARGIN, baseline), card.result, font=result_font, fill=AUBERGINE, anchor="ls")
    tally_x = MARGIN + d.textlength(card.result, font=result_font) + 28
    tally_font = next((sans(s, 500) for s in (30, 26, 22, 18)
                       if tally_x + d.textlength(card.tally, font=sans(s, 500)) <= right), sans(18, 500))
    d.text((tally_x, baseline), card.tally, font=tally_font, fill=INK, anchor="ls")
    d.text((MARGIN, question_baseline), card.question, font=sans(22, 400), fill=MUTED, anchor="ls")

    total = sum(card.counts)
    x = MARGIN
    for n, color in zip(card.counts, (AUBERGINE, INK, RULE)):
        w = round((right - MARGIN) * n / total)
        if w:
            d.rectangle((x, bar_top, x + w - 1, bar_top + bar_height - 1), fill=color)
        x += w

    # Measure label and title, in the space left above the question.
    y = 150
    if card.label:
        d.text((MARGIN, y), card.label, font=sans(26, 600), fill=AUBERGINE)
    y = TITLE_TOP
    size, lines = fit_title(card.title, lambda t, s: d.textlength(t, font=serif(s, 500)),
                            right - MARGIN, question_baseline - 44 - y)
    for line in lines:
        d.text((MARGIN, y), line, font=serif(size, 500), fill=INK)
        y += round(size * 1.12)
    return img


def run(out_dir: Path = CARDS_DIR) -> int:
    """Write a card for every vote that gets one; returns how many were written."""
    out_dir.mkdir(parents=True, exist_ok=True)
    votes = json.loads((OUT_DIR / "votes.json").read_text())["votes"]
    written = 0
    for vote in votes:
        doc = json.loads((OUT_DIR / "votes" / f"{vote['vote_id']}.json").read_text())
        dest = out_dir / f"{vote['vote_id']}.png"
        card = card_text(vote, doc)
        if card is None:
            dest.unlink(missing_ok=True)
            continue
        # 32 colors keep the text smooth at about a third of the full-color size.
        render(card).quantize(32, method=Image.Quantize.FASTOCTREE).save(dest)
        written += 1
    log.info("wrote %d link cards to %s", written, out_dir)
    return written
