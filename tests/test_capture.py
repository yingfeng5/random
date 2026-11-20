"""Capture writes two files and does not import Win32 on Linux."""

import sys
from datetime import datetime
from pathlib import Path

from PIL import Image

from hdpoker.capture import format_accepted, readings_agree, run, write_hand
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


def test_accepted_line_names_board_hole_and_close():
    reading = Reading(board=["8c", "Th", "6s"], hole_cards=["Qh", "Jd"])
    assert format_accepted(reading, closed=False) == "board 8c Th 6s | hole Qh Jd | hand open"
    assert format_accepted(Reading(), closed=True) == "board - | hole - | hand closed"


def test_ctrl_c_writes_the_open_hand_and_prints_the_reading(tmp_path: Path, capsys, monkeypatch):
    first = Reading(board=["8c", "Th", "6s"], hole_cards=["Qh", "Jd"])
    images = [object(), object(), object()]

    def grab():
        if not images:
            raise KeyboardInterrupt
        return images.pop(0)

    monkeypatch.setattr("hdpoker.capture.read_image", lambda _image: first)
    count = run(tmp_path, interval=0, grab=grab)
    output = capsys.readouterr().out
    assert "board 8c Th 6s | hole Qh Jd | hand open" in output
    assert count == 1
    assert len(list(tmp_path.glob("*.json"))) == 1
    assert len(list(tmp_path.glob("*.txt"))) == 1
    assert list(tmp_path.glob("*.png")) == []


def test_stable_reading_that_ends_a_hand_prints_closed(tmp_path: Path, capsys, monkeypatch):
    opened = Reading(board=["8c"], hole_cards=["Qh", "Jd"])
    ended = Reading(board=[], hole_cards=["As", "Kd"])
    sequence = [opened, opened, ended, ended]
    monkeypatch.setattr("hdpoker.capture.read_image", lambda _image: sequence.pop(0))

    def grab():
        return Image.new("RGB", (2, 2))

    count = run(tmp_path, interval=0, grab=grab, frames=3)
    output = capsys.readouterr().out
    assert "board 8c | hole Qh Jd | hand open" in output
    assert "board - | hole As Kd | hand closed" in output
    assert count == 2
    assert list(tmp_path.glob("*.png")) == []


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
