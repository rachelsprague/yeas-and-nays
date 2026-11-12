"""Parse everything under data/raw/ and write Parquet tables to data/staged/."""

import logging

import pyarrow as pa
import pyarrow.parquet as pq

from yan.config import RAW_DIR, STAGED_DIR
from yan.measures import parse_measure
from yan.stage import house, legislators, senate

log = logging.getLogger(__name__)

# Explicit schemas so an empty table (e.g. no votes yet) still has columns.
STRING_COLUMNS = {
    "house_votes": [
        "source_file", "congress", "session", "rollcall_num", "legis_num", "vote_question",
        "vote_type", "vote_result", "action_date", "action_time_etz", "vote_desc",
        "amendment_num", "amendment_author", "yea_total", "nay_total", "present_total",
        "not_voting_total", "bill_type", "bill_number",
    ],
    "house_positions": [
        "source_file", "congress", "session", "rollcall_num", "bioguide_id", "name",
        "party", "state", "vote",
    ],
    "senate_votes": [
        "source_file", "congress", "session", "vote_number", "vote_date", "modify_date",
        "vote_question_text", "vote_document_text", "vote_result_text", "question",
        "vote_title", "majority_requirement", "vote_result", "document_type",
        "document_number", "document_name", "document_title", "document_short_title",
        "amendment_number", "amendment_purpose", "yeas", "nays", "present", "absent",
        "tie_breaker_by_whom", "tie_breaker_vote", "bill_type", "bill_number",
    ],
    "senate_positions": [
        "source_file", "congress", "session", "vote_number", "lis_member_id", "member_full",
        "first_name", "last_name", "party", "state", "vote_cast",
    ],
    "legislator_terms": [
        "bioguide_id", "term_type", "term_start", "term_end", "state", "party", "caucus",
    ],
    "legislator_party_affiliations": [
        "bioguide_id", "term_start", "affiliation_start", "affiliation_end", "party", "caucus",
    ],
}
SCHEMAS = {name: pa.schema([(c, pa.string()) for c in cols]) for name, cols in STRING_COLUMNS.items()}
SCHEMAS["legislator_terms"] = SCHEMAS["legislator_terms"].append(pa.field("district", pa.int64()))
SCHEMAS["legislators"] = pa.schema([
    ("bioguide_id", pa.string()), ("lis_id", pa.string()), ("first_name", pa.string()),
    ("last_name", pa.string()), ("official_full_name", pa.string()), ("is_current", pa.bool_()),
])


def write(name: str, rows: list[dict]) -> None:
    STAGED_DIR.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows, schema=SCHEMAS[name])
    pq.write_table(table, STAGED_DIR / f"{name}.parquet")
    log.info("staged %s: %d rows", name, table.num_rows)


def with_bill(votes: list[dict], measure_field: str) -> list[dict]:
    """Add the Congress.gov bill type and number parsed from the recorded measure number
    (null for nominations and other non-bill questions). The recorded value is kept too."""
    for vote in votes:
        vote["bill_type"], vote["bill_number"] = parse_measure(vote[measure_field]) or (None, None)
    return votes


def run() -> None:
    h_votes, h_positions = house.parse_dir(RAW_DIR / "house")
    write("house_votes", with_bill(h_votes, "legis_num"))
    write("house_positions", h_positions)

    s_votes, s_positions = senate.parse_dir(RAW_DIR / "senate")
    write("senate_votes", with_bill(s_votes, "document_name"))
    write("senate_positions", s_positions)

    people, terms, affiliations = legislators.parse_dir(RAW_DIR / "legislators")
    write("legislators", people)
    write("legislator_terms", terms)
    write("legislator_party_affiliations", affiliations)
