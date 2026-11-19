"""Replay the seven calibration screenshots in hand order.

Prints each reading and the hand the state machine built from them, then
compares that hand with the hand the plan expected. Differences stay
differences: a card the pictures do not show is not rewritten to match the plan.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

from hdpoker.machine import HandMachine
from hdpoker.schema import Hand, sample_hand
from hdpoker.vision import read_image

# Chronological order of the one recorded hand, not filename order.
SAMPLE_ORDER = (
    "8d28a795-93b4-490a-9cdb-0e2812c8c4c9.png",
    "98316dae-2c45-4bf8-95d0-392042558acd.png",
    "8ae4d648-890b-4edc-8a44-dcb2beb8af6e.png",
    "476d0a9d-387f-4dd8-9047-4c00a1a2283c.png",
    "e3829791-56d6-4e65-a771-61a125cfc6fb.png",
    "63bdf96c-ae5b-40eb-8512-04b51c91728b.png",
    "d37c69ce-e6f0-446e-be38-656bf1868a0f.png",
)


def default_sample_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "samples"


def replay(sample_dir: Path | None = None, order: tuple[str, ...] = SAMPLE_ORDER) -> Hand:
    directory = sample_dir or default_sample_dir()
    machine = HandMachine()
    for name in order:
        path = directory / name
        reading = read_image(Image.open(path))
        machine.feed(reading)
    return machine.close()


def format_reading(name: str, image_path: Path) -> str:
    reading = read_image(Image.open(image_path))
    seats = []
    for seat in reading.seats:
        if not seat.name and not seat.status and seat.bet_bb is None:
            continue
        seats.append(
            f"{seat.index}:{seat.name or '?'} {seat.stack_text or '-'} {seat.status or '-'} "
            f"bet={seat.bet_text or '-'} shown={seat.shown_cards or '-'}"
        )
    return "\n".join(
        [
            f"frame {name}",
            f"  table {reading.table_name} blinds {reading.small_blind}/{reading.big_blind}",
            f"  hole header={reading.hole_cards_header} seat={reading.hole_cards_seat} used={reading.hole_cards}",
            f"  board {reading.board} pot {reading.pot_text} button {reading.button_seat}",
            f"  banner {reading.banner}",
            f"  chat {reading.chat_lines}",
            "  seats " + " | ".join(seats),
        ]
    )


def compare_to_plan(actual: Hand) -> list[tuple[str, str, str]]:
    """Rows of (fact, expected, actual) for the plan's checklist."""
    expected = sample_hand()
    rows = [
        ("table", expected.table_name or "", actual.table_name or "unknown"),
        ("blinds", f"{expected.small_blind}/{expected.big_blind}", f"{actual.small_blind}/{actual.big_blind}"),
        ("hero", expected.hero or "", actual.hero or "unknown"),
        ("hole cards", " ".join(expected.hole_cards or []), " ".join(actual.hole_cards or []) or "unknown"),
        ("flop", " ".join(_street_cards(expected, "flop")), " ".join(_street_cards(actual, "flop")) or "unknown"),
        ("turn", " ".join(_street_cards(expected, "turn")), " ".join(_street_cards(actual, "turn")) or "unknown"),
        ("river", " ".join(_street_cards(expected, "river")), " ".join(_street_cards(actual, "river")) or "unknown"),
        ("flop pot", _pot(expected, "flop"), _pot(actual, "flop")),
        ("turn pot", _pot(expected, "turn"), _pot(actual, "turn")),
        ("river pot", _pot(expected, "river"), _pot(actual, "river")),
        ("TDawn flop", "check", _player_action(actual, "flop", actual.hero)),
        ("TDawn turn", "check", _player_action(actual, "turn", actual.hero)),
        ("Kiwigirl turn", "check", _player_action(actual, "turn", "Kiwigirl")),
        ("sitting out", "george123", ", ".join(seat.name or "?" for seat in actual.seats if seat.sitting_out) or "none"),
        ("winner", "Insomnia13", (actual.showdown.winner if actual.showdown else None) or "unknown"),
        ("winning hand", "顺子", (actual.showdown.hand_text if actual.showdown else None) or "unknown"),
        ("amount", "24.00K", (actual.showdown.amount_text if actual.showdown else None) or "unknown"),
        ("river bets", "unknown", _river_bets(actual)),
        ("banner note", "你的一对输给顺子", (actual.showdown.hero_note if actual.showdown else None) or "unknown"),
    ]
    return rows


def format_comparison(actual: Hand) -> str:
    lines = ["plan expected vs what the screenshots actually read:"]
    for fact, expect, got in compare_to_plan(actual):
        mark = "ok" if _same_enough(expect, got) else "diff"
        lines.append(f"  [{mark}] {fact}: expected {expect} | read {got}")
    return "\n".join(lines)


def _same_enough(expected: str, actual: str) -> bool:
    if expected == actual:
        return True
    # The nameplate reads Insomnia3; the plan wrote Insomnia13.
    if expected == "Insomnia13" and actual.lower().replace("1", "") == "insomnia3".replace("1", ""):
        return actual.lower().startswith("insomnia")
    return False


def _street_cards(hand: Hand, name: str) -> list[str]:
    for street in hand.streets:
        if street.name == name:
            return list(street.cards)
    return []


def _pot(hand: Hand, name: str) -> str:
    for street in hand.streets:
        if street.name == name:
            return street.pot_text or ("unknown" if street.pot_bb is None else str(street.pot_bb))
    return "unknown"


def _player_action(hand: Hand, street_name: str, player: str | None) -> str:
    if not player:
        return "unknown"
    found = []
    for street in hand.streets:
        if street.name != street_name:
            continue
        for action in street.actions:
            if action.player and action.player.lower() == player.lower():
                found.append(action.type)
    if not found:
        return "none"
    return ", ".join(found)


def _river_bets(hand: Hand) -> str:
    for street in hand.streets:
        if street.name != "river":
            continue
        if not street.actions:
            return "none"
        parts = []
        for action in street.actions:
            if action.type in {"bet", "raise", "call", "allin"} and action.amount_bb is not None:
                parts.append(f"{action.player or '?'} {action.type} {action.amount_bb}")
            elif action.type == "unknown":
                parts.append("unknown")
            else:
                parts.append(f"{action.player or '?'} {action.type}")
        return ", ".join(parts)
    return "none"


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay the HD Poker sample screenshots.")
    parser.add_argument("--samples", type=Path, default=None)
    args = parser.parse_args()
    directory = args.samples or default_sample_dir()
    machine = HandMachine()
    for name in SAMPLE_ORDER:
        path = directory / name
        print(format_reading(name, path))
        machine.feed(read_image(Image.open(path)))
        print()
    hand = machine.close()
    print(hand.to_chinese())
    print(format_comparison(hand))


if __name__ == "__main__":
    main()
