"""Turn stable readings into one hand.

Actions come only from a status label that changed to CHECK, BET, CALL,
RAISE, ALL IN, or FOLD. WAITING and SITTING OUT are not actions. ``post`` is
only the 0.5 BB and 1 BB blinds at the start, and only when that seat has no
action label. A pot that grows without a label is ``unknown``; the difference
is not dealt out to players.
"""

from __future__ import annotations

from hdpoker.reading import ACTION_TYPE, ACTIONS, Reading, same_cards
from hdpoker.schema import (
    Action,
    Hand,
    Seat,
    Showdown,
    Street,
    banner_hero_note,
    chips_for,
    hand_name_zh,
    positions_for,
)

_STREETS = ("preflop", "flop", "turn", "river")
_BLIND_AMOUNTS = (0.5, 1.0)
_WIN_MARK = " won "


class HandMachine:
    def __init__(self) -> None:
        self.hand: Hand | None = None
        self._previous: Reading | None = None
        self._recorded: dict[int, str] = {}
        self._blinds_posted = False
        self._baseline_chat: set[str] | None = None
        self._showdown_open = False
        self._hero_start: float | None = None
        self._hero_end: float | None = None

    def feed(self, reading: Reading) -> list[Hand]:
        finished: list[Hand] = []
        if self.hand is not None and _hand_ended(self.hand, self._previous, reading):
            finished.append(self.close())
        if self.hand is None:
            self._start(reading)
        else:
            self._apply(reading)
        self._previous = reading
        return finished

    def close(self) -> Hand:
        if self.hand is None:
            self.hand = Hand()
        self._finish_showdown()
        hand = self.hand
        self.hand = None
        self._previous = None
        self._recorded = {}
        self._blinds_posted = False
        self._baseline_chat = None
        self._showdown_open = False
        self._hero_start = None
        self._hero_end = None
        return hand

    def _start(self, reading: Reading) -> None:
        self.hand = Hand(
            table_name=reading.table_name,
            small_blind=reading.small_blind,
            big_blind=reading.big_blind,
            hero=_hero_name(reading),
            hole_cards=_copy_cards(reading.hole_cards),
        )
        self._ensure_streets()
        self._sync_seats(reading, lock_start=True)
        # The first stable frame may already be past preflop.
        for index in range(1, _street_index(reading) + 1):
            self._open_one(_STREETS[index], reading, is_latest=index == _street_index(reading))
        self._apply(reading)

    def _apply(self, reading: Reading) -> None:
        assert self.hand is not None
        if reading.table_name and not self.hand.table_name:
            self.hand.table_name = reading.table_name
        if reading.small_blind and not self.hand.small_blind:
            self.hand.small_blind = reading.small_blind
        if reading.big_blind and not self.hand.big_blind:
            self.hand.big_blind = reading.big_blind
        if reading.hole_cards and _cards_known(reading.hole_cards):
            if not _cards_known(self.hand.hole_cards):
                self.hand.hole_cards = list(reading.hole_cards)
            elif not same_cards(self.hand.hole_cards, reading.hole_cards):
                self.hand.hole_cards = ["unknown", "unknown"]
        if not self.hand.hero:
            self.hand.hero = _hero_name(reading)
        self._sync_seats(reading, lock_start=False)
        self._note_chat(reading)
        if self._previous is not None and _street_index(reading) > _street_index(self._previous):
            self._settle(self._previous)
            self._open_streets(reading)
            self._record_changes(self._previous, reading)
            self._note_unexplained_pot(self._previous, reading)
        else:
            if not self.hand.streets:
                self._ensure_streets()
            self._posts(reading)
            previous = self._previous
            self._record_changes(previous, reading)
        self._maybe_showdown(reading)

    def _ensure_streets(self) -> None:
        assert self.hand is not None
        if not self.hand.streets:
            self.hand.streets.append(Street("preflop"))

    def _current(self) -> Street:
        assert self.hand is not None
        self._ensure_streets()
        return self.hand.streets[-1]

    def _open_streets(self, reading: Reading) -> None:
        assert self.hand is not None and self._previous is not None
        for index in range(_street_index(self._previous) + 1, _street_index(reading) + 1):
            self._open_one(_STREETS[index], reading, is_latest=index == _street_index(reading))

    def _open_one(self, name: str, reading: Reading, is_latest: bool) -> None:
        assert self.hand is not None
        street = next((item for item in self.hand.streets if item.name == name), None)
        if street is None:
            street = Street(name)
            self.hand.streets.append(street)
        if name == "flop" and len(reading.board) >= 3:
            street.cards = list(reading.board[:3])
        elif name == "turn" and len(reading.board) >= 4:
            street.cards = [reading.board[3]]
        elif name == "river" and len(reading.board) >= 5:
            street.cards = [reading.board[4]]
        if is_latest and reading.pot_bb is not None:
            street.pot_bb = reading.pot_bb
            street.pot_text = reading.pot_text or _bb_text(reading.pot_bb)
            street.pot_chips = chips_for(reading.pot_bb, self.hand.big_blind)
        self._recorded = {}

    def _settle(self, previous: Reading) -> None:
        """Write action labels from the street that is ending, if they were missed."""
        for seat in previous.seats:
            if seat.status in ACTIONS and self._recorded.get(seat.index) != seat.status:
                self._write_action(seat, previous)

    def _record_changes(self, previous: Reading | None, reading: Reading) -> None:
        old = {seat.index: seat for seat in previous.seats} if previous else {}
        for seat in reading.seats:
            if seat.status == "UNKNOWN":
                before = old.get(seat.index)
                previous_status = before.status if before else None
                if previous_status != "UNKNOWN" and self._recorded.get(seat.index) != "UNKNOWN":
                    self._write_action(seat, reading)
                continue
            if seat.status not in ACTIONS:
                continue
            before = old.get(seat.index)
            previous_status = before.status if before else None
            if previous_status == seat.status:
                continue
            if self._recorded.get(seat.index) == seat.status and previous_status in (None, "WAITING", seat.status):
                continue
            self._write_action(seat, reading)

    def _write_action(self, seat, reading: Reading) -> None:
        assert self.hand is not None
        if seat.sitting_out or seat.status == "SITTING OUT":
            return
        action_type = ACTION_TYPE.get(seat.status or "")
        if seat.status == "UNKNOWN":
            action_type = "unknown"
        if action_type is None:
            return
        amount = seat.bet_bb
        amount_text = seat.bet_text
        if action_type in {"check", "fold"} and amount is None:
            amount = 0
            amount_text = "0 BB"
        if action_type == "unknown":
            # An unreadable label is not a amount we are willing to invent.
            amount = None
            amount_text = None
        action = Action(
            type=action_type,
            seat=seat.index,
            player=seat.name,
            amount_bb=amount,
            amount_text=amount_text if amount is not None else None,
            amount_chips=chips_for(amount, self.hand.big_blind) if amount is not None else None,
        )
        self._current().actions.append(action)
        if seat.status in ACTIONS or seat.status == "UNKNOWN":
            self._recorded[seat.index] = seat.status

    def _posts(self, reading: Reading) -> None:
        """Blinds only: 0.5 BB and 1 BB in front, and only with no action label."""
        if self._blinds_posted or reading.board:
            return
        assert self.hand is not None
        street = self._current()
        if street.name != "preflop":
            return
        for seat in reading.seats:
            if seat.status in ACTIONS or seat.status == "SITTING OUT":
                continue
            if seat.bet_bb not in _BLIND_AMOUNTS:
                continue
            street.actions.append(
                Action(
                    type="post",
                    seat=seat.index,
                    player=seat.name,
                    amount_bb=seat.bet_bb,
                    amount_text=seat.bet_text or _bb_text(seat.bet_bb),
                    amount_chips=chips_for(seat.bet_bb, self.hand.big_blind),
                )
            )
        self._blinds_posted = True

    def _note_unexplained_pot(self, previous: Reading, reading: Reading) -> None:
        """A bigger pot with no bet, call, raise, or all-in label stays unknown."""
        if previous.pot_bb is None or reading.pot_bb is None:
            # The river can be the first frame that shows a real pot. A large
            # pot with no bet, call, or raise label is still unknown.
            if reading.pot_bb is None or len(reading.board) < 5 or reading.pot_bb < 8:
                return
            last_known = _last_pot(self.hand)
            if last_known is not None and reading.pot_bb <= last_known + 0.25:
                return
        else:
            last_known = previous.pot_bb
            if reading.pot_bb <= last_known + 0.25:
                return
        street = self._current()
        saw_money = any(action.type in {"bet", "call", "raise", "allin"} for action in street.actions)
        if saw_money:
            return
        if any(action.type == "unknown" and action.player is None for action in street.actions):
            return
        street.actions.append(Action(type="unknown"))

    def _sync_seats(self, reading: Reading, lock_start: bool) -> None:
        assert self.hand is not None
        by_index = {seat.seat: seat for seat in self.hand.seats}
        for source in reading.seats:
            seat = by_index.get(source.index)
            if seat is None:
                seat = Seat(seat=source.index)
                self.hand.seats.append(seat)
                by_index[source.index] = seat
            if source.name and not seat.name:
                seat.name = source.name
            if source.sitting_out:
                seat.sitting_out = True
            if source.stack_bb is not None and seat.stack_bb is None:
                seat.stack_bb = source.stack_bb
                seat.stack_text = source.stack_text or _bb_text(source.stack_bb)
                seat.stack_chips = chips_for(source.stack_bb, self.hand.big_blind or reading.big_blind)
            if source.shown_cards and _cards_known(source.shown_cards):
                seat.shown_cards = list(source.shown_cards)
            if source.index == reading.hero_seat and source.stack_bb is not None:
                if self._hero_start is None:
                    self._hero_start = source.stack_bb
                self._hero_end = source.stack_bb
        if reading.button_seat is not None and self.hand.button_seat is None:
            self.hand.button_seat = reading.button_seat
        self._assign_positions()
        if lock_start:
            pass

    def _assign_positions(self) -> None:
        assert self.hand is not None
        if self.hand.button_seat is None:
            return
        ordered = sorted(self.hand.seats, key=lambda seat: seat.seat)
        start = 0
        for index, seat in enumerate(ordered):
            if seat.seat == self.hand.button_seat:
                start = index
                break
        clockwise = ordered[start:] + ordered[:start]
        playing = [seat for seat in clockwise if seat.name and not seat.sitting_out]
        names = positions_for(len(playing))
        playing_ids = {seat.seat for seat in playing}
        for seat in self.hand.seats:
            if seat.seat not in playing_ids:
                seat.position = None
        for seat, position in zip(playing, names):
            seat.position = position

    def _note_chat(self, reading: Reading) -> None:
        normalized = [_norm_line(line) for line in reading.chat_lines if line.strip()]
        if self._baseline_chat is None:
            # Lines already on screen when the hand starts are older hands.
            self._baseline_chat = set(normalized)
            return
        for line in normalized:
            if line in self._baseline_chat or not line:
                continue
            self._baseline_chat.add(line)
            parsed = _parse_win(line)
            if parsed and self.hand is not None:
                self._showdown_open = True
                show = self._showdown()
                winner, amount, hand_name = parsed
                show.winner = winner
                show.amount_text = amount
                show.hand = hand_name
                show.hand_text = hand_name_zh(hand_name) or hand_name

    def _maybe_showdown(self, reading: Reading) -> None:
        shown = any(_cards_known(seat.shown_cards) for seat in reading.seats)
        if shown or reading.banner:
            self._showdown_open = True
        if not self._showdown_open:
            return
        show = self._showdown()
        if reading.banner and not show.banner:
            show.banner = " ".join(reading.banner.upper().split())
            note = banner_hero_note(show.banner)
            if note:
                show.hero_note = note
        for source in reading.seats:
            if _cards_known(source.shown_cards):
                seat = next(seat for seat in self.hand.seats if seat.seat == source.index)  # type: ignore[union-attr]
                seat.shown_cards = list(source.shown_cards)

    def _showdown(self) -> Showdown:
        assert self.hand is not None
        if self.hand.showdown is None:
            self.hand.showdown = Showdown()
        return self.hand.showdown

    def _finish_showdown(self) -> None:
        if self.hand is None:
            return
        if self.hand.showdown is None and not any(seat.shown_cards for seat in self.hand.seats):
            return
        show = self._showdown()
        show.hero_start_bb = self._hero_start
        show.hero_end_bb = self._hero_end
        if self._hero_start is not None and self._hero_end is not None:
            net = round(self._hero_end - self._hero_start, 2)
            show.hero_net_bb = int(net) if net == int(net) else net


def _hand_ended(hand: Hand, previous: Reading | None, reading: Reading) -> bool:
    if previous is None or not previous.board:
        return False
    if reading.board:
        return False
    old_cards = hand.hole_cards
    new_cards = reading.hole_cards
    if not _cards_known(old_cards) or not _cards_known(new_cards):
        return False
    return not same_cards(old_cards, new_cards)


def _street_index(reading: Reading) -> int:
    count = len(reading.board)
    if count >= 5:
        return 3
    if count == 4:
        return 2
    if count >= 3:
        return 1
    return 0


def _hero_name(reading: Reading) -> str | None:
    if reading.hero_seat is None:
        return None
    seat = reading.seat(reading.hero_seat)
    return seat.name if seat else None


def _copy_cards(cards: list[str] | None) -> list[str] | None:
    if not cards:
        return None
    return list(cards)


def _cards_known(cards: list[str] | None) -> bool:
    return bool(cards) and all(card and card != "unknown" for card in cards)


def _bb_text(amount: float | None) -> str | None:
    if amount is None:
        return None
    text = f"{amount:.2f}".rstrip("0").rstrip(".")
    return f"{text} BB"


def _last_pot(hand: Hand | None) -> float | None:
    if hand is None:
        return None
    for street in reversed(hand.streets):
        if street.pot_bb is not None:
            return street.pot_bb
    return None


def _norm_line(line: str) -> str:
    return " ".join(line.replace("]", " ").replace("[", " ").split())


def _parse_win(line: str) -> tuple[str, str, str] | None:
    folded = line.lower()
    if " won " not in f" {folded} ":
        return None
    # "Insomnia3 won 24.00K with a Straight"
    marker = " won "
    index = folded.find(marker)
    if index < 0:
        return None
    name = line[:index].strip(" []")
    # Drop a leading Kendra tag if it survived normalization.
    if name.lower().startswith("kendra"):
        name = name.split(None, 1)[-1]
    rest = line[index + len(marker) :].strip()
    parts = rest.split()
    if len(parts) < 3 or parts[1].lower() != "with":
        # "won 24.00K with a Straight" -> amount, with, optional a, hand
        if " with " not in rest.lower():
            return None
    lower_rest = rest.lower()
    with_at = lower_rest.find(" with ")
    if with_at < 0:
        return None
    amount = rest[:with_at].strip().split()[0]
    after = rest[with_at + len(" with ") :]
    hand_name = _hand_word(after)
    name = " ".join(name.split())
    if not name or not amount or not hand_name:
        return None
    return name, amount, hand_name


def _hand_word(text: str) -> str | None:
    folded = text.lower()
    for english in (
        "straight flush",
        "royal flush",
        "four of a kind",
        "full house",
        "three of a kind",
        "two pair",
        "one pair",
        "high card",
        "straight",
        "flush",
    ):
        if english in folded:
            return english
