from pathlib import Path

from nestbox.core.journal import Journal


def make(tmp_path: Path) -> Journal:
    folder = tmp_path / "journal"
    folder.mkdir()
    return Journal(folder)


def test_pending_is_what_the_summary_has_not_seen(tmp_path):
    journal = make(tmp_path)
    day = journal.folder / "2026-09-07.md"
    day.write_text("yesterday", encoding="utf-8")
    assert journal.pending() == [day]

    journal.write_summary("folded")
    assert journal.pending() == []

    fresh = journal.folder / "2026-09-08.md"
    fresh.write_text("today", encoding="utf-8")
    assert journal.pending() == [fresh]


def test_summary_is_not_a_day_file(tmp_path):
    journal = make(tmp_path)
    journal.write_summary("folded")
    assert journal.days() == []


def test_recent_carries_summary_and_unfolded_days(tmp_path):
    journal = make(tmp_path)
    journal.write_summary("who i am")
    (journal.folder / "2026-09-08.md").write_text("new", encoding="utf-8")
    text = journal.recent()
    assert "who i am" in text and "new" in text


def test_cuts_are_announced_not_silent(tmp_path):
    journal = make(tmp_path)
    journal.write_summary("s" * 100)
    (journal.folder / "2026-09-08.md").write_text("d" * 100, encoding="utf-8")
    text = journal.recent(summary_limit=50, tail_limit=50)
    assert "50 chars cut from the end" in text
    assert "50 chars cut from the start" in text
