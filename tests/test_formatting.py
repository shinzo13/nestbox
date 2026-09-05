from nestbox.bot.formatting import escape_md, human_duration, split_message


def test_escape_md_escapes_specials():
    assert escape_md("a-b.c!") == "a\\-b\\.c\\!"


def test_split_message_keeps_short_text():
    assert split_message("hi") == ["hi"]


def test_split_message_breaks_on_paragraph():
    text = "a" * 100 + "\n\n" + "b" * 100
    chunks = split_message(text, limit=150)
    assert len(chunks) == 2
    assert chunks[0] == "a" * 100
    assert chunks[1] == "b" * 100


def test_split_message_respects_limit():
    text = "word " * 500
    for chunk in split_message(text, limit=200):
        assert len(chunk) <= 200


def test_human_duration():
    assert human_duration(None) == ""
    assert human_duration(4200) == "4s"
    assert human_duration(125000) == "2m05s"
