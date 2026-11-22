"""Capture writes two files and does not import Win32 on Linux."""

import sys
from datetime import datetime
from pathlib import Path

from PIL import Image

from hdpoker.capture import format_accepted, readings_agree, run, write_hand
from hdpoker.reading import Reading, SeatReading
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


def _named(board, hole, button=0):
    return Reading(
        board=list(board),
        hole_cards=list(hole),
        hero_seat=0,
        button_seat=button,
        seats=[SeatReading(index=0, name="TDawn")],
    )


def test_flickering_fields_still_write_a_second_hand_when_the_board_clears(tmp_path: Path, monkeypatch):
    flop_a = Reading(
        board=["unknown", "unknown", "unknown"],
        hero_seat=0,
        button_seat=1,
        seats=[SeatReading(index=0, name="violets", stack_bb=100)],
    )
    flop_b = Reading(
        board=["unknown", "unknown", "unknown"],
        hero_seat=0,
        button_seat=1,
        seats=[SeatReading(index=0, name="violets", stack_bb=99)],
    )
    empty_a = Reading(
        board=[],
        hero_seat=0,
        button_seat=1,
        hole_cards=["Ah", "Kd"],
        seats=[SeatReading(index=0, name="violets", stack_bb=100)],
    )
    empty_b = Reading(
        board=[],
        hero_seat=0,
        button_seat=1,
        hole_cards=["Ah", "Kd"],
        seats=[SeatReading(index=0, name="violets", stack_bb=98)],
    )
    frames = [object(), object(), object(), object()]
    readings = {
        id(frames[0]): flop_a,
        id(frames[1]): flop_b,
        id(frames[2]): empty_a,
        id(frames[3]): empty_b,
    }
    monkeypatch.setattr("hdpoker.capture.read_image", lambda image: readings[id(image)])

    def grab():
        return frames.pop(0)

    count = run(tmp_path, interval=0, grab=grab, frames=4)
    assert count == 2
    assert len(list(tmp_path.glob("*.json"))) == 2
    assert len(list(tmp_path.glob("*.txt"))) == 2
    assert list(tmp_path.glob("*.png")) == []


def test_unknown_cards_save_one_frame_beside_the_hand(tmp_path: Path, monkeypatch):
    image = Image.new("RGB", (8, 8), (10, 20, 30))
    reading = Reading(
        board=["unknown", "unknown", "unknown"],
        hero_seat=0,
        seats=[SeatReading(index=0, name="violets")],
    )
    monkeypatch.setattr("hdpoker.capture.read_image", lambda _image: reading)
    count = run(tmp_path, interval=0, grab=lambda: image, frames=2)
    assert count == 1
    pngs = list(tmp_path.glob("*.png"))
    assert len(pngs) == 1
    assert pngs[0].with_suffix(".json").exists()


def test_stable_reading_that_ends_a_hand_prints_closed(tmp_path: Path, capsys, monkeypatch):
    opened = _named(["8c"], ["Qh", "Jd"])
    ended = _named([], ["As", "Kd"])
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


def test_tesseract_exit_does_not_skip_the_frame(tmp_path: Path, capsys, monkeypatch):
    """A tessdata failure used to raise and skip every grab. The frame is still read."""
    import subprocess

    import hdpoker.ocrutil as ocrutil

    ocrutil._failure_reported = False

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr='Please make sure the TESSDATA_PREFIX environment variable is set to your "tessdata" directory.\n',
        )

    monkeypatch.setattr(ocrutil.subprocess, "run", fake_run)
    count = run(tmp_path, interval=0, grab=lambda: Image.new("RGB", (160, 100), (30, 90, 40)), frames=3)
    captured = capsys.readouterr()
    assert captured.err.count("TESSDATA_PREFIX") == 1
    assert "board - | hole - | hand open" in captured.out
    assert "ocr failed, skipped frame" not in captured.out
    assert count == 1


def test_one_ocr_failure_does_not_stop_capture(tmp_path: Path, capsys, monkeypatch):
    reading = Reading(board=["8c"], hole_cards=["Qh", "Jd"])
    calls = {"n": 0}

    def read(_image):
        calls["n"] += 1
        if calls["n"] == 1:
            raise UnicodeDecodeError("gbk", b"\xff", 0, 1, "illegal multibyte sequence")
        return reading

    monkeypatch.setattr("hdpoker.capture.read_image", read)
    count = run(tmp_path, interval=0, grab=lambda: object(), frames=3)
    output = capsys.readouterr().out
    assert "ocr failed, skipped frame" in output
    assert "board 8c | hole Qh Jd | hand open" in output
    assert count == 1


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
