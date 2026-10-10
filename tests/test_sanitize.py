from __future__ import annotations

import pytest

from dejabuilt.sanitize import ELLIPSIS, clean, markdown


class TestClean:
    def test_plain_text_is_unchanged(self) -> None:
        assert clean("A tidy description") == "A tidy description"

    @pytest.mark.parametrize("value", [None, 12, ["x"], {"a": 1}])
    def test_non_strings_become_empty(self, value: object) -> None:
        assert clean(value) == ""

    def test_newlines_and_tabs_collapse_to_single_spaces(self) -> None:
        assert clean("line one\n\nline\ttwo   end") == "line one line two end"

    def test_terminal_escape_sequences_lose_their_control_byte(self) -> None:
        cleaned = clean("safe\x1b[2J\x1b[31mred\x07")
        assert "\x1b" not in cleaned
        assert "\x07" not in cleaned

    def test_invisible_direction_and_zero_width_marks_are_removed(self) -> None:
        assert clean("ab‮cd​⁦ef") == "abcdef"

    def test_long_text_is_cut_with_an_ellipsis(self) -> None:
        cleaned = clean("x" * 500, limit=50)
        assert len(cleaned) == 50
        assert cleaned.endswith(ELLIPSIS)

    def test_text_at_the_limit_is_not_cut(self) -> None:
        assert clean("x" * 50, limit=50) == "x" * 50

    def test_non_ascii_text_survives(self) -> None:
        assert clean("déjà vu 日本語 🚀") == "déjà vu 日本語 🚀"


class TestMarkdown:
    def test_table_and_link_syntax_is_escaped(self) -> None:
        assert markdown("a|b [x](y)") == "a\\|b \\[x\\]\\(y\\)"

    def test_html_is_neutralised(self) -> None:
        escaped = markdown('<img src=x onerror="alert(1)">')
        assert "<" not in escaped
        assert ">" not in escaped
        assert escaped.startswith("&lt;img")

    def test_ampersand_is_escaped_first(self) -> None:
        assert markdown("a & <b>") == "a &amp; &lt;b&gt;"

    def test_emphasis_headings_and_code_are_escaped(self) -> None:
        assert markdown("# *bold* `code` _x_") == "\\# \\*bold\\* \\`code\\` \\_x\\_"

    def test_backslash_is_escaped(self) -> None:
        assert markdown("a\\b") == "a\\\\b"
