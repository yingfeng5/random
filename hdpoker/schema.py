"""Hand-history structure and the Chinese text that mirrors it.

JSON version is 1. Action types are only check, bet, call, raise, allin,
fold, post, and unknown. ``post`` is a blind. ``unknown`` is not a guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

VERSION = 1

ACTION_TYPES = ("check", "bet", "call", "raise", "allin", "fold", "post", "unknown")

ACTION_ZH = {
    "check": "过牌",
    "bet": "下注",
    "call": "跟注",
    "raise": "加注",
    "allin": "全下",
    "fold": "弃牌",
    "post": "下盲",
    "unknown": "未知",
}

STREET_ZH = {
    "preflop": "翻牌前",
    "flop": "翻牌",
    "turn": "转牌",
    "river": "河牌",
}

POSITION_ZH = {
    "BTN": "按钮",
    "SB": "小盲",
    "BB": "大盲",
    "UTG": "枪口",
    "HJ": "劫持",
    "CO": "关煞",
}

SUIT_SYMBOL = {"c": "♣", "d": "♦", "h": "♥", "s": "♠"}
RANK_TEXT = {
    "A": "A",
    "K": "K",
    "Q": "Q",
    "J": "J",
    "T": "10",
    "9": "9",
    "8": "8",
    "7": "7",
    "6": "6",
    "5": "5",
    "4": "4",
    "3": "3",
    "2": "2",
}

HAND_ZH = {
    "high card": "高牌",
    "one pair": "一对",
    "two pair": "两对",
    "three of a kind": "三条",
    "straight": "顺子",
    "flush": "同花",
    "full house": "葫芦",
    "four of a kind": "四条",
    "straight flush": "同花顺",
    "royal flush": "皇家同花顺",
}


def card_text(card: str | None) -> str:
    if not card or card == "unknown":
        return "未知"
    if len(card) < 2 or card[-1] not in SUIT_SYMBOL:
        return "未知"
    rank, suit = card[:-1], card[-1]
    return f"{RANK_TEXT.get(rank, rank)}{SUIT_SYMBOL[suit]}"


def cards_text(cards: list[str] | None) -> str:
    if not cards:
        return "未知"
    return " ".join(card_text(card) for card in cards)


def format_bb(amount: float | None, original: str | None = None) -> str:
    if original:
        return original
    if amount is None:
        return "未知"
    text = f"{amount:.2f}".rstrip("0").rstrip(".")
    return f"{text} BB"


def chips_for(amount_bb: float | None, big_blind: int | None) -> int | None:
    if amount_bb is None or not big_blind:
        return None
    return int(round(amount_bb * big_blind))


@dataclass
class Action:
    type: str
    seat: int | None = None
    player: str | None = None
    amount_bb: float | None = None
    amount_text: str | None = None
    amount_chips: int | None = None

    def __post_init__(self) -> None:
        if self.type not in ACTION_TYPES:
            raise ValueError(f"action type {self.type!r} is not allowed")

    def to_dict(self) -> dict[str, Any]:
        return {
            "seat": self.seat,
            "player": self.player,
            "type": self.type,
            "amount_bb": self.amount_bb,
            "amount_text": self.amount_text,
            "amount_chips": self.amount_chips,
        }


@dataclass
class Street:
    name: str
    cards: list[str] = field(default_factory=list)
    pot_bb: float | None = None
    pot_text: str | None = None
    pot_chips: int | None = None
    actions: list[Action] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "cards": list(self.cards),
            "pot_bb": self.pot_bb,
            "pot_text": self.pot_text,
            "pot_chips": self.pot_chips,
            "actions": [action.to_dict() for action in self.actions],
        }


@dataclass
class Seat:
    seat: int
    name: str | None = None
    stack_bb: float | None = None
    stack_text: str | None = None
    stack_chips: int | None = None
    position: str | None = None
    sitting_out: bool = False
    shown_cards: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "seat": self.seat,
            "name": self.name,
            "stack_bb": self.stack_bb,
            "stack_text": self.stack_text,
            "stack_chips": self.stack_chips,
            "position": self.position,
            "sitting_out": self.sitting_out,
            "shown_cards": list(self.shown_cards),
        }


@dataclass
class Showdown:
    winner: str | None = None
    hand: str | None = None
    hand_text: str | None = None
    amount_text: str | None = None
    banner: str | None = None
    hero_note: str | None = None
    hero_start_bb: float | None = None
    hero_end_bb: float | None = None
    hero_net_bb: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "winner": self.winner,
            "hand": self.hand,
            "hand_text": self.hand_text,
            "amount_text": self.amount_text,
            "banner": self.banner,
            "hero_note": self.hero_note,
            "hero_start_bb": self.hero_start_bb,
            "hero_end_bb": self.hero_end_bb,
            "hero_net_bb": self.hero_net_bb,
        }


@dataclass
class Hand:
    table_name: str | None = None
    small_blind: int | None = None
    big_blind: int | None = None
    hero: str | None = None
    hole_cards: list[str] | None = None
    button_seat: int | None = None
    seats: list[Seat] = field(default_factory=list)
    streets: list[Street] = field(default_factory=list)
    showdown: Showdown | None = None
    version: int = VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "table": {
                "name": self.table_name,
                "small_blind": self.small_blind,
                "big_blind": self.big_blind,
            },
            "hero": {"name": self.hero, "hole_cards": self.hole_cards},
            "button_seat": self.button_seat,
            "seats": [seat.to_dict() for seat in self.seats],
            "streets": [street.to_dict() for street in self.streets],
            "showdown": None if self.showdown is None else self.showdown.to_dict(),
        }

    def to_chinese(self) -> str:
        return render_chinese(self)


def render_chinese(hand: Hand) -> str:
    """Chinese history whose facts are the same fields as the JSON."""
    lines: list[str] = []
    table = hand.table_name or "未知"
    if hand.small_blind and hand.big_blind:
        blinds = f"{hand.small_blind}/{hand.big_blind}"
    else:
        blinds = "未知"
    lines.append(f"桌：{table}，盲注 {blinds}")
    lines.append(f"你：{hand.hero or '未知'}，底牌 {cards_text(hand.hole_cards)}")

    button = _seat_by_index(hand, hand.button_seat)
    button_name = button.name if button and button.name else "未知"
    lines.append(f"按钮：{button_name}")

    occupied = [seat for seat in hand.seats if seat.name]
    if occupied:
        lines.append("座位（从按钮顺时针，暂离的人不占位置）：")
        for seat in _clockwise_from_button(hand):
            if not seat.name:
                continue
            bits = [seat.name]
            if seat.sitting_out:
                bits.append("暂离")
            elif seat.position:
                bits.append(POSITION_ZH.get(seat.position, seat.position))
            bits.append(_stack_phrase(seat))
            lines.append("  " + " ".join(bits))
    else:
        lines.append("座位：未知")

    lines.append("开始筹码：")
    wrote_stack = False
    for seat in hand.seats:
        if not seat.name or seat.sitting_out:
            continue
        if seat.stack_bb is None and not seat.stack_text:
            continue
        wrote_stack = True
        lines.append(f"  {seat.name} {_stack_phrase(seat)}")
    if not wrote_stack:
        lines.append("  未知")

    for street in hand.streets:
        lines.append(_street_heading(street))
        if not street.actions:
            lines.append("  （无）")
            continue
        for action in street.actions:
            lines.append("  " + _action_phrase(action))

    lines.append("摊牌：")
    showed = [seat for seat in hand.seats if seat.shown_cards]
    if not showed and hand.showdown is None:
        lines.append("  未知")
    else:
        for seat in hand.seats:
            if seat.shown_cards:
                who = seat.name or "未知"
                lines.append(f"  {who} 亮牌 {cards_text(seat.shown_cards)}")
        if hand.showdown is not None:
            show = hand.showdown
            winner = show.winner or "未知"
            hand_name = show.hand_text or "未知"
            amount = show.amount_text or "未知"
            lines.append(f"  {winner} 以{hand_name}赢下 {amount}")
            if show.hero_note:
                lines.append(f"  {show.hero_note}")
            if show.hero_net_bb is not None:
                lines.append(f"  你的净输赢 {format_bb(show.hero_net_bb)}")
            elif show.hero_start_bb is not None or show.hero_end_bb is not None:
                lines.append("  你的净输赢 未知")
    return "\n".join(lines) + "\n"


def _stack_phrase(seat: Seat) -> str:
    text = format_bb(seat.stack_bb, seat.stack_text)
    if seat.stack_chips is not None:
        return f"{text}（{seat.stack_chips:,}）"
    return text


def _street_heading(street: Street) -> str:
    title = STREET_ZH.get(street.name, street.name)
    if street.name == "preflop":
        return f"{title}："
    cards = cards_text(street.cards) if street.cards else "未知"
    pot = format_bb(street.pot_bb, street.pot_text)
    return f"{title}：{cards}，底池 {pot}"


def _action_phrase(action: Action) -> str:
    verb = ACTION_ZH[action.type]
    who = action.player or "未知"
    if action.type == "unknown" and action.player is None:
        return "未知"
    if action.type in {"check", "fold"} and (action.amount_bb is None or action.amount_bb == 0):
        return f"{who} {verb}"
    amount = format_bb(action.amount_bb, action.amount_text)
    if action.type == "unknown" and action.amount_bb is None and not action.amount_text:
        return f"{who} {verb}" if action.player else "未知"
    return f"{who} {verb} {amount}"


def _seat_by_index(hand: Hand, index: int | None) -> Seat | None:
    if index is None:
        return None
    for seat in hand.seats:
        if seat.seat == index:
            return seat
    return None


def _clockwise_from_button(hand: Hand) -> list[Seat]:
    if not hand.seats:
        return []
    ordered = sorted(hand.seats, key=lambda seat: seat.seat)
    if hand.button_seat is None:
        return ordered
    start = 0
    for i, seat in enumerate(ordered):
        if seat.seat == hand.button_seat:
            start = i
            break
    return ordered[start:] + ordered[:start]


def hand_name_zh(english: str | None) -> str | None:
    if not english:
        return None
    key = " ".join(english.strip().lower().split())
    return HAND_ZH.get(key)


def banner_hero_note(banner: str | None) -> str | None:
    """Turn the showdown banner into a result sentence. Not a betting tip.

    The sampled banner is ``STRAIGHT BEAT YOUR ONE PAIR``, which is recorded
    as 「你的一对输给顺子」. Other ``X BEAT YOUR Y`` banners are translated
    the same way. The hand-strength bar is never used here.
    """
    if not banner:
        return None
    text = " ".join(banner.upper().split())
    if "BEAT YOUR" not in text:
        return None
    left, right = text.split("BEAT YOUR", 1)
    winner_hand = _hand_in_text(left)
    hero_hand = _hand_in_text(right)
    if not winner_hand or not hero_hand:
        return None
    return f"你的{hero_hand}输给{winner_hand}"


def _hand_in_text(text: str) -> str | None:
    folded = " ".join(text.upper().split())
    for english in (
        "STRAIGHT FLUSH",
        "ROYAL FLUSH",
        "FOUR OF A KIND",
        "FULL HOUSE",
        "THREE OF A KIND",
        "TWO PAIR",
        "ONE PAIR",
        "HIGH CARD",
        "STRAIGHT",
        "FLUSH",
    ):
        if english in folded:
            return hand_name_zh(english)
    return None


def positions_for(count: int) -> list[str]:
    """Clockwise positions starting at the button. Sitting out is already excluded."""
    if count <= 0:
        return []
    if count == 2:
        return ["BTN", "BB"]
    table = {
        3: ["BTN", "SB", "BB"],
        4: ["BTN", "SB", "BB", "UTG"],
        5: ["BTN", "SB", "BB", "UTG", "CO"],
        6: ["BTN", "SB", "BB", "UTG", "HJ", "CO"],
    }
    return table.get(count, ["BTN", "SB", "BB", "UTG", "HJ", "CO"][:count])


def sample_hand() -> Hand:
    """The hand as the plan describes it, not as the screenshots were read.

    JSON and the Chinese text are rendered from this same object.
    """
    big = 500
    seats = [
        Seat(0, "TDawn", 99, "99 BB", chips_for(99, big), "BB", False, ["Qh", "Qd"]),
        Seat(1, "Kiwigirl", None, None, None, "BTN", False, []),
        Seat(2, "Insomnia13", None, None, None, "SB", False, []),
        Seat(3, "george123", None, None, None, None, True, []),
    ]
    streets = [
        Street(
            "preflop",
            [],
            None,
            None,
            None,
            [
                Action("post", None, None, 0.5, "0.5 BB", chips_for(0.5, big)),
                Action("post", None, None, 1, "1 BB", chips_for(1, big)),
            ],
        ),
        Street(
            "flop",
            ["8c", "Th", "6s"],
            4,
            "4 BB",
            chips_for(4, big),
            [Action("check", 0, "TDawn", 0, "0 BB", 0)],
        ),
        Street(
            "turn",
            ["Js"],
            4,
            "4 BB",
            chips_for(4, big),
            [
                Action("check", 0, "TDawn", 0, "0 BB", 0),
                Action("check", 1, "Kiwigirl", 0, "0 BB", 0),
            ],
        ),
        Street(
            "river",
            ["4d"],
            48,
            "48 BB",
            chips_for(48, big),
            [Action("unknown")],
        ),
    ]
    showdown = Showdown(
        winner="Insomnia13",
        hand="straight",
        hand_text="顺子",
        amount_text="24.00K",
        banner="STRAIGHT BEAT YOUR ONE PAIR",
        hero_note="你的一对输给顺子",
    )
    return Hand(
        table_name="[Standard] The Reef #2",
        small_blind=250,
        big_blind=big,
        hero="TDawn",
        hole_cards=["Qh", "Qd"],
        button_seat=1,
        seats=seats,
        streets=streets,
        showdown=showdown,
    )
