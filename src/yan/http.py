"""HTTP client shared by the ingesters: identifies itself and paces requests.
Also the bot's same-host fetch of our own pages."""

import logging
import time

import httpx

log = logging.getLogger(__name__)

USER_AGENT = "yeas-and-nays-data (+https://yeasandnaysdata.com)"
REQUEST_DELAY_SECONDS = 0.25
# senate.gov intermittently answers 403 when throttling; retry those along
# with the usual rate-limit and server errors, backing off each time.
RETRY_STATUSES = {403, 429, 500, 502, 503, 504}
RETRY_BACKOFF_SECONDS = [5, 15, 45, 120]


class Client:
    def __init__(self, delay: float = REQUEST_DELAY_SECONDS, transport: httpx.BaseTransport | None = None):
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=30.0,
            follow_redirects=True,
            transport=transport or httpx.HTTPTransport(retries=3),
        )
        self._delay = delay
        self._last_request = 0.0

    def get(self, url: str, headers: dict | None = None) -> httpx.Response:
        """GET with pacing and retries.

        Requests with extra headers (an API key) never follow redirects: httpx
        forwards custom headers to the redirect target, even on another host.
        A redirect on such a request raises instead.
        """
        for backoff in [*RETRY_BACKOFF_SECONDS, None]:
            resp = self._get_once(url, headers)
            if headers and resp.is_redirect:
                raise httpx.HTTPStatusError(
                    f"HTTP {resp.status_code} redirect for {url}; not following a request with credentials",
                    request=resp.request, response=resp,
                )
            if resp.status_code not in RETRY_STATUSES or backoff is None:
                return resp
            log.warning("HTTP %d for %s; retrying in %ds", resp.status_code, url, backoff)
            time.sleep(backoff)

    def _get_once(self, url: str, headers: dict | None = None) -> httpx.Response:
        wait = self._delay - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        try:
            return self._client.get(url, headers=headers, follow_redirects=not headers)
        finally:
            self._last_request = time.monotonic()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


MAX_REDIRECTS = 5


def get_on_host(url: str) -> httpx.Response:
    """GET url, following redirects only while each one stays on url's host.

    A redirect to another host, or from https to http, comes back unfollowed
    (its Location names where it pointed), so a lapsed domain's parking page is
    never requested. Checking only the final host would still fetch it, and any
    redirects it chains to. Raises httpx.TooManyRedirects after MAX_REDIRECTS
    hops, and httpx.RemoteProtocolError on a malformed Location, as httpx's own
    redirect handling does.
    """
    host = httpx.URL(url).host
    for _ in range(MAX_REDIRECTS + 1):
        resp = httpx.get(url, headers={"User-Agent": USER_AGENT}, timeout=30.0, follow_redirects=False)
        if not resp.has_redirect_location:
            return resp
        try:
            target = redirect_target(resp)
        except httpx.InvalidURL as exc:
            raise httpx.RemoteProtocolError(f"Malformed redirect Location: {exc}", request=resp.request) from exc
        downgrade = resp.request.url.scheme == "https" and target.scheme != "https"
        if target.host != host or downgrade:
            return resp
        url = str(target)
    raise httpx.TooManyRedirects(f"More than {MAX_REDIRECTS} redirects", request=resp.request)


def redirect_target(resp: httpx.Response) -> httpx.URL:
    """Where a redirect response points, with a relative Location resolved.
    Safe on a redirect get_on_host returned: it already parsed the Location."""
    return resp.request.url.join(resp.headers["location"])


def write_atomic(path, content: bytes) -> None:
    """Write via a temp file so an interrupted run never leaves a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(content)
    tmp.replace(path)
