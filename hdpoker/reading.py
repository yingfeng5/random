"""One stable frame, before it is turned into a hand history.

The state machine consumes only these objects, so tests can build them
without opening an image.
"""

from __future__ import annotations

from dataclasses import dataclass, field


ACTIONS = ("CHECK", "BET", "CALL", "RAISE", "ALL IN", "FOLD")
NOT_ACTIONS = ("WAITING", "SITTING OUT")
STATUS_WORDS = ACTIONS + NOT_ACTIONS

ACTION_TYPE = {
    "CHECK": "check",
    "BET": "bet",
    "CALL": "call",
    "RAISE": "raise",
    "ALL IN": "allin",
    "FOLD": "fold",
}


@dataclass
class SeatReading:
    index: int
    name: str | None = None
    stack_bb: float | None = None
    stack_text: str | None = None
    status: str | None = None
    bet_bb: float | None = None
    bet_text: str | None = None
    timer: bool = False
    shown_cards: list[str] = field(default_factory=list)

    @property
    def is_action(self) -> bool:
        return self.status in ACTIONS

    @property
    def sitting_out(self) -> bool:
        return self.status == "SITTING OUT"


@dataclass
class Reading:
    table_name: str | None = None
    small_blind: int | None = None
    big_blind: int | None = None
    hero_seat: int | None = None
    hole_cards: list[str] | None = None
    hole_cards_header: list[str] | None = None
    hole_cards_seat: list[str] | None = None
    board: list[str] = field(default_factory=list)
    pot_bb: float | None = None
    pot_text: str | None = None
    seats: list[SeatReading] = field(default_factory=list)
    button_seat: int | None = None
    hero_to_act: bool = False
    hero_options: list[str] = field(default_factory=list)
    chat_lines: list[str] = field(default_factory=list)
    banner: str | None = None

    def seat(self, index: int) -> SeatReading | None:
        for seat in self.seats:
            if seat.index == index:
                return seat
        return None

    def signature(self) -> tuple:
        """Fields that must agree on two frames before a reading is accepted."""
        seats = tuple(
            (
                seat.index,
                seat.name,
                seat.stack_bb,
                seat.status,
                seat.bet_bb,
                seat.timer,
                tuple(seat.shown_cards),
            )
            for seat in self.seats
        )
        return (
            self.table_name,
            self.small_blind,
            self.big_blind,
            tuple(self.hole_cards or []),
            tuple(self.board),
            self.pot_bb,
            seats,
            self.button_seat,
            tuple(self.chat_lines),
            self.banner,
        )


def same_cards(left: list[str] | None, right: list[str] | None) -> bool:
    if not left or not right:
        return False
    if any(card == "unknown" for card in left + right):
        return False
    return list(left) == list(right) or list(left) == list(reversed(right))
