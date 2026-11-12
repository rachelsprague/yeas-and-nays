"""Reduce a CRS summary's HTML to a small allowlist of text tags before it's published.

Congress.gov summaries are plain formatted text (paragraphs, lists, bold and
italic). Any other tag is dropped but its text kept; all attributes are
dropped; text is re-escaped. The site inserts the result as HTML.
"""

from html import escape
from html.parser import HTMLParser

ALLOWED = {"p", "ul", "ol", "li", "strong", "em", "b", "i", "br", "sub", "sup"}
VOID = {"br"}
DROP_CONTENT = {"script", "style"}


class _Sanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in DROP_CONTENT:
            self.skip += 1
        elif tag in ALLOWED and not self.skip:
            self.out.append(f"<{tag}>")

    def handle_endtag(self, tag):
        if tag in DROP_CONTENT:
            self.skip = max(0, self.skip - 1)
        elif tag in ALLOWED and tag not in VOID and not self.skip:
            self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(escape(data.replace("\xa0", " "), quote=False))


def clean(html: str | None) -> str | None:
    if not html:
        return None
    parser = _Sanitizer()
    parser.feed(html)
    parser.close()
    text = "".join(parser.out)
    # Drop empty inline wrappers CRS sometimes leaves behind, e.g. <em></em>.
    for tag in ("em", "strong", "b", "i"):
        text = text.replace(f"<{tag}></{tag}>", "")
    return text.strip() or None
