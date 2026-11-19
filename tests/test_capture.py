"""Capture writes two files and does not import Win32 on Linux."""

import sys
from datetime import datetime
from pathlib import Path

from hdpoker.capture import readings_agree, write_hand
from hdpoker.reading import Reading
from hdpoker.schema import sample_hand


def test_capture_module_does_not_import_win32():
    assert "hdpoker.win32cap" not in sys.modules
    import hdpoker.capture  # noqa: F401

    assert "hdpoker.win32cap" not in sys.modules
    assert "win32gui" not in sys.modules


def test_write_hand_writes_json_and_text_only(tmp_path: Path):
    json_path, text_path = write_hand(tmp_path, sample_hand(), datetime(2026, 11, 19, 17, 45, 30), 1)
    assert json_path.name == "20261119_174530_1.json"
    assert text_path.name == "20261119_174530_1.txt"
    assert json_path.read_text(encoding="utf-8").startswith("{")
    assert "TDawn" in text_path.read_text(encoding="utf-8")
    assert list(tmp_path.iterdir()) == [json_path, text_path] or set(tmp_path.iterdir()) == {json_path, text_path}


def test_unchanged_readings_agree():
    reading = Reading(table_name="reef", board=["8c"])
    assert readings_agree(reading, Reading(table_name="reef", board=["8c"]))
    assert not readings_agree(reading, Reading(table_name="reef", board=["8c", "Th"]))


def test_grab_frame_refuses_off_windows():
    from hdpoker.capture import grab_frame

    if sys.platform == "win32":
        return
    try:
        grab_frame()
    except RuntimeError as exc:
        assert "Windows" in str(exc)
    else:
        raise AssertionError("grab_frame should refuse")
    assert "hdpoker.win32cap" not in sys.modules
