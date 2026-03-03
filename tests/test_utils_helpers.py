"""Tests for reverse_image_search_bot.utils.helpers."""

from reverse_image_search_bot.utils.helpers import chunks, safe_get, tagify


class TestChunks:
    def test_even_split(self):
        assert list(chunks([1, 2, 3, 4], 2)) == [[1, 2], [3, 4]]

    def test_uneven_split(self):
        assert list(chunks([1, 2, 3, 4, 5], 2)) == [[1, 2], [3, 4], [5]]

    def test_single_chunk(self):
        assert list(chunks([1, 2, 3], 10)) == [[1, 2, 3]]

    def test_empty_list(self):
        assert list(chunks([], 3)) == []

    def test_chunk_size_one(self):
        assert list(chunks([1, 2, 3], 1)) == [[1], [2], [3]]


class TestTagify:
    def test_string_input(self):
        assert tagify("cat dog") == {"#cat", "#dog"}

    def test_list_input(self):
        assert tagify(["Action", "Comedy"]) == {"#action", "#comedy"}

    def test_list_input_with_duplicates(self):
        assert tagify(["Action", "Action", "Comedy"]) == {"#action", "#comedy"}

    def test_set_input(self):
        assert tagify({"Romance"}) == {"#romance"}

    def test_spaces_become_underscores(self):
        assert tagify(["Slice of Life"]) == {"#slice_of_life"}

    def test_special_chars_replaced(self):
        assert tagify("rock&roll") == {"#rock_roll"}

    def test_empty_input(self):
        assert tagify("") == set()
        assert tagify([]) == set()

    def test_digit_start_filtered(self):
        assert tagify("123numeric valid") == {"#valid"}


class TestSafeGet:
    def setup_method(self):
        self.data = {
            "foo": "bar",
            "hello": {
                "world": "jeff",
                "animal": [
                    {"type": "cat", "sound": "meow", "ja": "neko"},
                    {"type": "shark", "sound": "a", "de": "hai"},
                ],
            },
        }

    def test_simple_key(self):
        assert safe_get(self.data, "foo") == "bar"

    def test_nested_key(self):
        assert safe_get(self.data, "hello.world") == "jeff"

    def test_list_index(self):
        result = safe_get(self.data, "hello.animal.[0]")
        assert result == {"type": "cat", "sound": "meow", "ja": "neko"}

    def test_list_key_value_match(self):
        result = safe_get(self.data, "hello.animal.[type=cat]")
        assert result == {"type": "cat", "sound": "meow", "ja": "neko"}

    def test_list_key_value_nested(self):
        assert safe_get(self.data, "hello.animal.[type=shark].sound") == "a"

    def test_list_key_exists(self):
        result = safe_get(self.data, "hello.animal.[de]")
        assert result == {"type": "shark", "sound": "a", "de": "hai"}

    def test_missing_key_default(self):
        assert safe_get(self.data, "nonexistent") is None
        assert safe_get(self.data, "nonexistent", "fallback") == "fallback"

    def test_deep_missing(self):
        assert safe_get(self.data, "hello.missing.deep") is None

    def test_none_value_default(self):
        data = {"key": None}
        assert safe_get(data, "key") is None
        assert safe_get(data, "key", "default", none_to_default=True) == "default"
        assert safe_get(data, "key", "default", none_to_default=False) is None
