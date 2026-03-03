"""Tests for reverse_image_search_bot.utils.tags."""

from reverse_image_search_bot.utils.tags import a, b, code, hidden_a, i, pre, tag, title


class TestTag:
    def test_basic_tag(self):
        assert tag("b", "hello") == "<b >hello</b>"

    def test_tag_with_attrs(self):
        assert tag("a", "click", {"href": "https://example.com"}) == '<a href="https://example.com">click</a>'

    def test_multiple_attrs(self):
        result = tag("div", "text", {"class": "foo", "id": "bar"})
        assert result == '<div class="foo" id="bar">text</div>'


class TestShortcuts:
    def test_bold(self):
        assert b("text") == "<b >text</b>"

    def test_italic(self):
        assert i("text") == "<i >text</i>"

    def test_pre(self):
        assert pre("text") == "<pre >text</pre>"

    def test_code(self):
        assert code("text") == "<code >text</code>"

    def test_anchor(self):
        assert a("click", "https://example.com") == '<a href="https://example.com">click</a>'

    def test_hidden_anchor(self):
        assert hidden_a("https://example.com") == '<a href="https://example.com">\u200b</a>'

    def test_title(self):
        assert title("Name") == "<b >Name:</b> "
