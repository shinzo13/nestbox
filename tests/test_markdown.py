from nestbox.bot.markdown import to_telegram_markdown


def test_plain_text_is_escaped():
    assert to_telegram_markdown("a-b.") == "a\\-b\\."


def test_code_fence_keeps_content_raw():
    result = to_telegram_markdown("before\n```python\nx = 1 - 2\n```\nafter")
    assert "```python\nx = 1 - 2\n```" in result
    assert result.startswith("before")


def test_inline_code_not_escaped_inside():
    assert to_telegram_markdown("run `a-b` now") == "run `a-b` now"


def test_bold_becomes_single_star():
    assert to_telegram_markdown("**loud**") == "*loud*"


def test_heading_becomes_bold():
    assert to_telegram_markdown("## title!") == "*title\\!*"


def test_bullets_use_dot():
    assert to_telegram_markdown("- one\n- two") == "• one\n• two"


def test_link_preserved():
    assert to_telegram_markdown("[docs](https://x.io/a_b)") == "[docs](https://x.io/a_b)"


def test_backtick_inside_fence_escaped():
    result = to_telegram_markdown("```\nsay `hi`\n```")
    assert "\\`hi\\`" in result
