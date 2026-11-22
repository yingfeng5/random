"""Watch the HD Poker window and write a hand when it ends.

Only the current frame and the previous frame are kept, in memory. A hand is
written as ``hands/<time>_<n>.json`` and ``.txt`` when the next deal starts,
or when the loop stops. If that hand still has an unknown card or no hero,
one png of the frame that showed the problem is written beside the json.

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


def repeated_deal_change(
    previous: Reading,
    current: Reading,
    last_board_count: int,
    last_button: int | None,
) -> bool:
    """A board-count or button change seen on two frames in a row.

    Other OCR fields may flicker. The deal still advances when the board
    count, or the dealer seat, is the same on both frames and different from
    the last reading that was accepted.
    """
    if len(previous.board) == len(current.board) and len(current.board) != last_board_count:
        return True
    return (
        previous.button_seat is not None
        and current.button_seat is not None
        and previous.button_seat == current.button_seat
        and current.button_seat != last_button
    )


def format_accepted(reading: Reading, closed: bool) -> str:
    """One line for a stable reading: board, hole cards, and if that reading ended a hand."""
    board = " ".join(reading.board) if reading.board else "-"
    hole = " ".join(reading.hole_cards) if reading.hole_cards else "-"
    state = "closed" if closed else "open"
    return f"board {board} | hole {hole} | hand {state}"


def hand_needs_frame(hand: Hand) -> bool:
    """True when a live frame would show an unknown card or a missing hero."""
    if not hand.hero:
        return True
    cards = list(hand.hole_cards or [])
    for street in hand.streets:
        cards.extend(street.cards)
    for seat in hand.seats:
        cards.extend(seat.shown_cards)
    return any(card == "unknown" for card in cards)


def reading_needs_frame(reading: Reading) -> bool:
    if reading.hero_seat is None:
        return True
    cards = list(reading.board) + list(reading.hole_cards or [])
    return any(card == "unknown" for card in cards)


def write_hand(
    directory: Path,
    hand: Hand,
    when: datetime,
    number: int,
    image=None,
) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    stem = directory / f"{when.strftime('%Y%m%d_%H%M%S')}_{number}"
    json_path = stem.with_suffix(".json")
    text_path = stem.with_suffix(".txt")
    json_path.write_text(json.dumps(hand.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    text_path.write_text(hand.to_chinese(), encoding="utf-8")
    if image is not None and hasattr(image, "save") and hand_needs_frame(hand):
        image.save(stem.with_suffix(".png"))
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
    last_board_count: int | None = None
    last_button: int | None = None
    problem_image = None
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
            # Names and stacks may flicker. The first deal is accepted when the
            # board count is the same on both frames. After that, a new board
            # count or a new dealer seat, seen twice, becomes the next reading.
            if last_board_count is None:
                deal_changed = len(previous_reading.board) == len(current_reading.board)
            else:
                deal_changed = repeated_deal_change(
                    previous_reading, current_reading, last_board_count, last_button
                )
            if readings_agree(previous_reading, current_reading) or deal_changed:
                signature = current_reading.signature()
                if signature != last_signature or deal_changed:
                    closed_hands = machine.feed(current_reading)
                    for hand in closed_hands:
                        written += 1
                        write_hand(hands_dir, hand, datetime.now(), written, problem_image)
                        problem_image = None
                    print(format_accepted(current_reading, closed=bool(closed_hands)), flush=True)
                    last_signature = signature
                    last_board_count = len(current_reading.board)
                    last_button = current_reading.button_seat
                    if reading_needs_frame(current_reading) and hasattr(current_image, "save"):
                        problem_image = current_image
            previous_image = current_image
            if frames is not None and seen >= frames:
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        pass
    if machine.hand is not None:
        written += 1
        write_hand(hands_dir, machine.close(), datetime.now(), written, problem_image)
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
