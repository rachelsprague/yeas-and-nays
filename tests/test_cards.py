import json

from PIL import Image

from yan import cards
from yan.cards import card_text, fit_title, render


def vote(**overrides):
    v = {
        "vote_id": "h119-2-0325", "chamber": "house", "congress": 119, "session": 2, "roll_number": 325,
        "vote_date": "2026-11-17", "question": "On Motion to Suspend the Rules and Pass", "result": "Passed",
        "measure_label": "H.R. 9600", "measure_title": "Example Act", "vote_title": None,
    }
    return {**v, **overrides}


def doc(*positions):
    """A vote file whose members voted these positions, in order."""
    return {"positions": {f"M{i:06d}": p for i, p in enumerate(positions)}}


def test_card_text_house_vote():
    card = card_text(vote(), doc(*["Yea"] * 3, "Nay", "Not Voting"))
    assert card.meta == "HOUSE  ·  ROLL CALL 325  ·  NOV. 17, 2026"
    assert card.label == "H.R. 9600"
    assert card.title == "“Example Act”"
    assert card.question == "Motion to Suspend the Rules and Pass"
    assert card.result == "Passed"
    assert card.tally == "3 Yea  ·  1 Nay  ·  1 Not Voting"
    assert card.counts == (3, 1, 1)


def test_card_text_uses_the_words_recorded():
    # House recorded votes are Aye/No; Present counts with Not Voting in the bar.
    card = card_text(vote(), doc("Aye", "No", "Present", "Not Voting"))
    assert card.tally == "1 Aye  ·  1 No  ·  1 Present  ·  1 Not Voting"
    assert card.counts == (1, 1, 2)
    assert card_text(vote(), doc("Guilty", "Not Guilty")).tally == "1 Guilty  ·  1 Not Guilty"


def test_card_text_title_falls_back_like_the_heading():
    # The Senate's vote title, then the question; only the measure title is quoted.
    senate = vote(chamber="senate", vote_date="2025-09-02", measure_title=None, measure_label=None,
                  vote_title="Motion to Invoke Cloture: Motion to Proceed to S. 5",
                  question="On the Cloture Motion S. 5", result="Cloture Motion Agreed to")
    card = card_text(senate, doc("Yea", "Nay"))
    assert card.title == "Motion to Invoke Cloture: Motion to Proceed to S. 5"
    assert card.label is None
    assert card.question == "Cloture Motion S. 5"
    assert card.meta == "SENATE  ·  ROLL CALL 325  ·  SEPT. 2, 2025"
    assert card_text(vote(measure_title="", vote_title=""), doc("Yea")).title == "On Motion to Suspend the Rules and Pass"


def test_no_card_without_yea_or_nay():
    # A quorum call has no Yea or Nay; a Speaker election is tallied by candidate.
    assert card_text(vote(question="Call by States"), doc("Present", "Not Voting")) is None
    assert card_text(vote(question="Election of the Speaker"), doc("Smith", "Jones", "Present")) is None


def test_fit_title_shrinks_then_truncates():
    measure = lambda text, size: len(text) * size // 2  # noqa: E731
    size, lines = fit_title("“Short Act”", measure, 1000, 400)
    assert (size, lines) == (cards.TITLE_SIZES[0], ["“Short Act”"])

    # More than 3 lines at the first size: a smaller size, every word kept.
    words = "“" + " ".join(["word"] * 18) + "”"
    size, lines = fit_title(words, measure, 1000, 400)
    assert size < cards.TITLE_SIZES[0] and len(lines) <= 3
    assert " ".join(lines) == words

    # Too long at every size: three lines, the last ending in an ellipsis inside the quote.
    size, lines = fit_title("“" + " ".join(["word,"] * 80) + "”", measure, 1000, 400)
    assert size == cards.TITLE_SIZES[-1] and len(lines) == 3
    assert lines[-1].endswith("word…”")
    assert all(measure(line, size) <= 1000 for line in lines)


def test_fit_title_lines_fit_the_height():
    measure = lambda text, size: len(text) * size // 2  # noqa: E731
    size, lines = fit_title(" ".join(["word"] * 40), measure, 1000, 120)
    assert len(lines) * round(size * 1.12) <= 120
    assert lines[-1].endswith("…")


def test_render_size():
    img = render(card_text(vote(measure_title="A bill " * 40), doc("Yea", "Nay")))
    assert img.size == (1200, 630)


def test_run_writes_cards_and_removes_stale(tmp_path, monkeypatch):
    out = tmp_path / "out"
    (out / "votes").mkdir(parents=True)
    votes = [vote(), vote(vote_id="h119-2-0326", roll_number=326, question="Call by States")]
    (out / "votes.json").write_text(json.dumps({"votes": votes}))
    (out / "votes" / "h119-2-0325.json").write_text(json.dumps(doc("Yea", "Nay")))
    (out / "votes" / "h119-2-0326.json").write_text(json.dumps(doc("Present")))
    monkeypatch.setattr(cards, "OUT_DIR", out)
    dest = tmp_path / "cards"
    dest.mkdir()
    (dest / "h119-2-0326.png").write_bytes(b"stale")

    assert cards.run(dest) == 1
    assert sorted(p.name for p in dest.iterdir()) == ["h119-2-0325.png"]
    assert Image.open(dest / "h119-2-0325.png").size == (1200, 630)
