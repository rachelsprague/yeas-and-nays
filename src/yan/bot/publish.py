"""Publish posts to Bluesky. Only used when the bot runs with --publish
(BOT_PUBLISH=true in GitHub Actions); dry runs never import the SDK or read
credentials.

Credentials come from the BLUESKY_HANDLE and BLUESKY_APP_PASSWORD environment
variables (GitHub Actions secrets). They are never printed.
"""

import os

POSTED_FEED_LIMIT = 100


class MissingCredentials(RuntimeError):
    pass


class BlueskyPublisher:
    def __init__(self, client=None):
        handle = os.environ.get("BLUESKY_HANDLE")
        password = os.environ.get("BLUESKY_APP_PASSWORD")
        if not handle or not password:
            raise MissingCredentials("BLUESKY_HANDLE and BLUESKY_APP_PASSWORD must be set to publish")
        if client is None:
            from atproto import Client

            client = Client()
        self._client = client
        self._handle = handle
        try:
            self._client.login(handle, password)
        except Exception as exc:
            # Re-raise without the SDK's message or request details, which can echo inputs.
            raise RuntimeError(f"Bluesky login failed ({type(exc).__name__})") from None

    def recent_links(self) -> set[str]:
        """Link lines (the last line) of the account's recent posts, so a vote
        already posted isn't posted again even if state wasn't saved."""
        feed = self._client.get_author_feed(actor=self._handle, limit=POSTED_FEED_LIMIT)
        return {item.post.record.text.rsplit("\n", 1)[-1] for item in feed.feed}

    def post(self, text: str, url: str) -> None:
        """Post text whose last line is the display form of url, linked to url."""
        from atproto import client_utils

        body, link_text = text.rsplit("\n", 1)
        builder = client_utils.TextBuilder().text(body + "\n").link(link_text, url)
        self._client.send_post(builder, langs=["en"])
