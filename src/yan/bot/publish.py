"""Publish posts to Bluesky. Only used when the bot runs with --publish
(BOT_PUBLISH=true in GitHub Actions); dry runs never import the SDK or read
credentials.

Credentials come from the BLUESKY_HANDLE and BLUESKY_APP_PASSWORD environment
variables (GitHub Actions secrets). They are never printed.
"""

import os

from yan.bot.card import LinkCard

POSTED_FEED_LIMIT = 100


class MissingCredentials(RuntimeError):
    pass


def _failed(action: str, exc: Exception) -> RuntimeError:
    """An error naming only the exception type and HTTP status. The SDK's own
    message can echo inputs or response bodies into public Actions logs."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return RuntimeError(f"Bluesky {action} failed ({type(exc).__name__}{f', HTTP {status}' if status else ''})")


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
            raise _failed("login", exc) from None

    def recent_links(self) -> set[str]:
        """Link lines (the last line) of the account's recent posts, so a vote
        already posted isn't posted again even if state wasn't saved."""
        try:
            feed = self._client.get_author_feed(actor=self._handle, limit=POSTED_FEED_LIMIT)
        except Exception as exc:
            raise _failed("feed read", exc) from None
        return {item.post.record.text.rsplit("\n", 1)[-1] for item in feed.feed}

    def post(self, text: str, url: str, card: LinkCard | None = None) -> None:
        """Post text whose last line is the display form of url, linked to url,
        with card (if any) as the post's link card."""
        from atproto import client_utils

        body, link_text = text.rsplit("\n", 1)
        builder = client_utils.TextBuilder().text(body + "\n").link(link_text, url)
        extra = {"embed": self._embed(card)} if card else {}
        try:
            self._client.send_post(builder, langs=["en"], **extra)
        except Exception as exc:
            raise _failed("post", exc) from None

    def _embed(self, card: LinkCard):
        """An external embed for card. A thumbnail that fails to upload is
        left off rather than holding the post."""
        from atproto import models

        thumb = None
        if card.thumb:
            try:
                thumb = self._client.upload_blob(card.thumb).blob
            except Exception as exc:
                print(f"::warning::{_failed('thumbnail upload', exc)}; posting the card without it")
        return models.AppBskyEmbedExternal.Main(external=models.AppBskyEmbedExternal.External(
            uri=card.uri, title=card.title, description=card.description, thumb=thumb))
