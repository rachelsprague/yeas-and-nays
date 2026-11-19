"""The link card under a post: title, description and thumbnail from our vote
page's Open Graph tags, the same card the Bluesky app builds when a URL is
pasted. Over the API nothing builds it, so the bot reads the page (already
checked live before posting) and the image itself.

A card is optional: any failure gives no card (or no thumbnail), never a
held post. Each failure prints an Actions warning.
"""

from dataclasses import dataclass
from html.parser import HTMLParser

# Bluesky's limit for an external embed's thumbnail blob.
MAX_THUMB_BYTES = 1_000_000


@dataclass(frozen=True)
class LinkCard:
    uri: str
    title: str
    description: str
    thumb: bytes | None = None


class _OpenGraph(HTMLParser):
    """og:* meta tags, first of each, as {"og:title": ...}. Attribute values
    come back with entities decoded ("Yeas &amp; Nays" -> "Yeas & Nays")."""

    def __init__(self):
        super().__init__()
        self.tags = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        prop, content = attrs.get("property"), attrs.get("content")
        if tag == "meta" and prop and prop.startswith("og:") and content is not None:
            self.tags.setdefault(prop, content.strip())


def open_graph(html: str) -> dict[str, str]:
    parser = _OpenGraph()
    parser.feed(html)
    return parser.tags


def fetch_card(url: str) -> LinkCard | None:
    """The card for our page at url, or None if the page or its tags can't be read."""
    import httpx

    page = _get(url)
    if page is None:
        return None
    tags = open_graph(page.text)
    title = tags.get("og:title")
    if not title:
        _warn(f"Link card for {url}: no og:title; posting without a card")
        return None
    return LinkCard(uri=url, title=title, description=tags.get("og:description", ""),
                    thumb=_thumb(tags.get("og:image"), httpx.URL(url).host))


def _thumb(image_url: str | None, host: str) -> bytes | None:
    """The image's bytes, if it's an image on our own host small enough to upload."""
    import httpx

    if not image_url:
        return None
    try:
        image_host = httpx.URL(image_url).host
    except httpx.InvalidURL:
        _warn(f"Link card image URL for {host} is malformed; posting the card without it")
        return None
    if image_host != host:
        _warn(f"Link card image {image_url} is not on {host}; posting the card without it")
        return None
    resp = _get(image_url)
    if resp is None:
        return None
    if not resp.headers.get("content-type", "").startswith("image/"):
        _warn(f"Link card image {image_url} is not an image; posting the card without it")
        return None
    if len(resp.content) > MAX_THUMB_BYTES:
        _warn(f"Link card image {image_url} is over {MAX_THUMB_BYTES} bytes; posting the card without it")
        return None
    return resp.content


def _get(url: str):
    """A 200 response from url on the same host, or None (with a warning)."""
    import httpx

    from yan.http import USER_AGENT

    try:
        resp = httpx.get(url, headers={"User-Agent": USER_AGENT}, timeout=30.0, follow_redirects=True)
    except httpx.HTTPError as exc:
        _warn(f"Link card fetch failed for {url}: {type(exc).__name__}")
        return None
    if resp.status_code != 200 or resp.url.host != httpx.URL(url).host:
        _warn(f"Link card fetch for {url}: HTTP {resp.status_code} from {resp.url.host}")
        return None
    return resp


def _warn(message: str) -> None:
    # Shows on the Actions run page, without failing the run.
    print(f"::warning::{message}")
