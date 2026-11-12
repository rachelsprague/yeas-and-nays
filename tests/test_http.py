import httpx
import pytest

from yan.http import Client


def redirecting_transport(seen):
    def handler(request):
        seen.append(request)
        if request.url.host == "api.congress.gov":
            return httpx.Response(302, headers={"Location": "https://elsewhere.example/page"})
        return httpx.Response(200, text="ok")

    return httpx.MockTransport(handler)


def test_keyed_request_does_not_follow_redirect():
    seen = []
    with Client(delay=0, transport=redirecting_transport(seen)) as client:
        with pytest.raises(httpx.HTTPStatusError, match="redirect"):
            client.get("https://api.congress.gov/v3/bill", headers={"X-Api-Key": "test-key"})
    assert [r.url.host for r in seen] == ["api.congress.gov"]


def test_unkeyed_request_follows_redirect():
    seen = []
    with Client(delay=0, transport=redirecting_transport(seen)) as client:
        resp = client.get("https://api.congress.gov/v3/bill")
    assert resp.text == "ok"
    assert [r.url.host for r in seen] == ["api.congress.gov", "elsewhere.example"]
    assert "x-api-key" not in seen[1].headers
