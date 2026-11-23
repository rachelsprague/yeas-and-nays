import json

import httpx
import pytest

from yan.http import Client
from yan.ingest import legislators

YAML = """\
- id:
    bioguide: X000001
  name:
    last: Examplé
  terms:
  - type: rep
    start: '2025-01-03'
    end: 2027-01-03
    state: 'NO'
    district: 3
"""


def client(responses) -> tuple[Client, list[str]]:
    """A client answering from `responses` (file name -> (status, text)), YAML for the rest."""
    urls = []

    def handler(request):
        urls.append(str(request.url))
        status, text = responses.get(request.url.path.rsplit("/", 1)[1], (200, YAML))
        return httpx.Response(status, content=text.encode())

    return Client(delay=0, transport=httpx.MockTransport(handler)), urls


@pytest.fixture(autouse=True)
def raw_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(legislators, "RAW_DIR", tmp_path)
    return tmp_path / "legislators"


def test_saves_each_yaml_file_as_json(raw_dir):
    c, urls = client({})
    legislators.ingest(c)

    assert urls == [f"{legislators.BASE_URL}/{name}.yaml" for name in legislators.FILES]
    assert sorted(p.name for p in raw_dir.iterdir()) == [
        "legislators-current.json", "legislators-historical.json", "legislators-social-media.json"]
    # An unquoted date is saved as the text a quoted one would be.
    assert json.loads((raw_dir / "legislators-current.json").read_text()) == [{
        "id": {"bioguide": "X000001"},
        "name": {"last": "Examplé"},
        "terms": [{"type": "rep", "start": "2025-01-03", "end": "2027-01-03", "state": "NO", "district": 3}],
    }]


@pytest.mark.parametrize("text", ["", "[]", "id: X000001", "404: Not Found", "- id: [unclosed"])
def test_a_file_that_is_not_a_list_of_entries_fails_and_keeps_the_last_one(raw_dir, text):
    raw_dir.mkdir()
    saved = raw_dir / "legislators-current.json"
    saved.write_text("[1]")
    c, _ = client({"legislators-current.yaml": (200, text)})
    with pytest.raises(ValueError, match="legislators-current"):
        legislators.ingest(c)
    assert saved.read_text() == "[1]"


def test_an_http_error_fails(raw_dir):
    c, _ = client({"legislators-current.yaml": (404, "404: Not Found")})
    with pytest.raises(httpx.HTTPStatusError):
        legislators.ingest(c)
    assert not raw_dir.exists()
