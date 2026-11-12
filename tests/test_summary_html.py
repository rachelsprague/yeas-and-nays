from yan.export.summary_html import clean


def test_keeps_formatting_tags_and_drops_everything_else():
    raw = ('<p><strong>Act of 2025</strong><em></em></p><p class="x">This bill&nbsp;does '
           '<a href="https://example.com">things</a>.</p><ul><li>One</li></ul>')
    assert clean(raw) == "<p><strong>Act of 2025</strong></p><p>This bill does things.</p><ul><li>One</li></ul>"


def test_escapes_text_and_strips_scripts():
    assert clean("<p>A &lt;b&gt; tag &amp; more</p><script>alert(1)</script>") == "<p>A &lt;b&gt; tag &amp; more</p>"
    assert clean('<p onclick="x()">Hi</p><img src=x onerror=alert(1)>') == "<p>Hi</p>"


def test_empty():
    assert clean(None) is None
    assert clean("<p></p>") == "<p></p>"
