import httpx
import pytest

from yan.http import MAX_REDIRECTS, Client, get_on_host, redirect_target


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


def fake_hops(monkeypatch, locations):
    """httpx.get answers a redirect to locations[url] when it has one, else 200.
    Returns the URLs requested."""
    seen = []

    def fake_get(url, **kwargs):
        assert kwargs["follow_redirects"] is False
        seen.append(url)
        location = locations.get(url)
        return httpx.Response(302 if location else 200, headers={"location": location} if location else {},
                              request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    return seen


def test_get_on_host_follows_same_host_redirects_one_hop_at_a_time(monkeypatch):
    seen = fake_hops(monkeypatch, {"http://a.test/old": "https://a.test/new", "https://a.test/new": "/newer"})
    resp = get_on_host("http://a.test/old")
    assert resp.status_code == 200
    assert seen == ["http://a.test/old", "https://a.test/new", "https://a.test/newer"]


def test_get_on_host_stops_at_a_redirect_off_the_host(monkeypatch):
    seen = fake_hops(monkeypatch, {"https://a.test/": "https://a.test/moved",
                                   "https://a.test/moved": "https://parked.test/lander"})
    resp = get_on_host("https://a.test/")
    assert resp.is_redirect and redirect_target(resp).host == "parked.test"
    assert seen == ["https://a.test/", "https://a.test/moved"]


def test_get_on_host_gives_up_on_a_redirect_loop(monkeypatch):
    seen = fake_hops(monkeypatch, {"https://a.test/1": "/2", "https://a.test/2": "/1"})
    with pytest.raises(httpx.TooManyRedirects):
        get_on_host("https://a.test/1")
    assert len(seen) == MAX_REDIRECTS + 1
