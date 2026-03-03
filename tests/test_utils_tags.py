"""Tests for reverse_image_search_bot.utils.tags."""

from reverse_image_search_bot.utils.tags import a, b, code, hidden_a, i, pre, tag, title


class TestTag:
    def test_basic_tag(self):
        assert tag("b", "hello") == "<b >hello</b>"

    def test_tag_with_attrs(self):
        result = tag("a", "click", {"href": "https://example.com"})
        assert 'href="https://example.com"' in result
        assert ">click</a>" in result

    def test_multiple_attrs(self):
        result = tag("div", "text", {"class": "foo", "id": "bar"})
        assert 'class="foo"' in result
        assert 'id="bar"' in result


class TestShortcuts:
    def test_bold(self):
        assert "<b" in b("text")
        assert "text</b>" in b("text")

    def test_italic(self):
        assert "<i" in i("text")
        assert "text</i>" in i("text")

    def test_pre(self):
        assert "<pre" in pre("text")
        assert "text</pre>" in pre("text")

    def test_code(self):
        assert "<code" in code("text")
        assert "text</code>" in code("text")

    def test_anchor(self):
        result = a("click", "https://example.com")
        assert 'href="https://example.com"' in result
        assert ">click</a>" in result

    def test_hidden_anchor(self):
        result = hidden_a("https://example.com")
        assert 'href="https://example.com"' in result
        assert "\u200b" in result  # zero-width space, not empty
        assert "</a>" in result

    def test_title(self):
        result = title("Name")
        assert "<b" in result
        assert "Name:" in result
