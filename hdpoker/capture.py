"""Watch the HD Poker window and write a hand when it ends.

Only the current frame and the previous frame are kept, in memory. Screenshots
are not written. A hand is written as ``hands/<time>_<n>.json`` and ``.txt``
when the board clears and the hole cards change, or when the loop stops.

The Win32 grabber is imported only on Windows.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

from hdpoker.machine import HandMachine
from hdpoker.reading import Reading
from hdpoker.schema import Hand
from hdpoker.vision import read_image


def readings_agree(first: Reading, second: Reading) -> bool:
    return first.signature() == second.signature()


def format_accepted(reading: Reading, closed: bool) -> str:
    """One line for a stable reading: board, hole cards, and if that reading ended a hand."""
    board = " ".join(reading.board) if reading.board else "-"
    hole = " ".join(reading.hole_cards) if reading.hole_cards else "-"
    state = "closed" if closed else "open"
    return f"board {board} | hole {hole} | hand {state}"


def write_hand(directory: Path, hand: Hand, when: datetime, number: int) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    stem = directory / f"{when.strftime('%Y%m%d_%H%M%S')}_{number}"
    json_path = stem.with_suffix(".json")
    text_path = stem.with_suffix(".txt")
    json_path.write_text(json.dumps(hand.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    text_path.write_text(hand.to_chinese(), encoding="utf-8")
    return json_path, text_path


def grab_frame():
    if sys.platform != "win32":
        raise RuntimeError("HD Poker window capture only runs on Windows")
    from hdpoker.win32cap import capture_window

    return capture_window()


def run(hands_dir: Path, interval: float = 0.5, grab=None, frames: int | None = None) -> int:
    """Capture until ``frames`` grabs, or until interrupted.

    ``grab`` returns a PIL image. The default grabber is the Windows window.
    Two consecutive identical readings are required before the state machine
    moves. A reading that matches the last accepted one does not move it again.
    """
    if grab is None:
        grab = grab_frame
    machine = HandMachine()
    written = 0
    previous_image = None
    last_signature = None
    seen = 0
    reported_failure = False
    try:
        while frames is None or seen < frames:
            current_image = grab()
            seen += 1
            if previous_image is None:
                previous_image = current_image
                time.sleep(interval)
                continue
            try:
                previous_reading = read_image(previous_image)
                current_reading = read_image(current_image)
            except Exception as exc:
                # One bad read must not end the session. The reason is printed once.
                if not reported_failure:
                    print(exc, file=sys.stderr, flush=True)
                    reported_failure = True
                print("ocr failed, skipped frame", flush=True)
                previous_image = current_image
                if frames is not None and seen >= frames:
                    break
                time.sleep(interval)
                continue
            # Drop anything older than these two frames. Nothing is written to disk.
            if readings_agree(previous_reading, current_reading):
                signature = current_reading.signature()
                if signature != last_signature:
                    closed_hands = machine.feed(current_reading)
                    for hand in closed_hands:
                        written += 1
                        write_hand(hands_dir, hand, datetime.now(), written)
                    print(format_accepted(current_reading, closed=bool(closed_hands)), flush=True)
                    last_signature = signature
            previous_image = current_image
            if frames is not None and seen >= frames:
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        pass
    if machine.hand is not None:
        written += 1
        write_hand(hands_dir, machine.close(), datetime.now(), written)
    return written


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Capture an HD Poker hand from the window.")
    parser.add_argument("--hands", type=Path, default=Path("hands"))
    parser.add_argument("--interval", type=float, default=0.5)
    args = parser.parse_args()
    count = run(args.hands, interval=args.interval)
    print(f"wrote {count} hand(s) under {args.hands}", flush=True)


if __name__ == "__main__":
    main()
