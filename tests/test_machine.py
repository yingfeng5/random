"""State machine tests. They build readings in memory and open no images."""

from hdpoker.machine import HandMachine
from hdpoker.reading import Reading, SeatReading


def _seat(index, name, status=None, bet=None, stack=100, sitting=False, shown=None):
    text = None if bet is None else f"{bet:g} BB"
    return SeatReading(
        index=index,
        name=name,
        stack_bb=stack,
        stack_text=f"{stack:g} BB",
        status="SITTING OUT" if sitting else status,
        bet_bb=bet,
        bet_text=text,
        shown_cards=list(shown or []),
    )


def _reading(board, seats, hole=("Qh", "Jd"), pot=None, chat=None, banner=None, button=0):
    return Reading(
        table_name="[Standard] The Reef #2",
        small_blind=250,
        big_blind=500,
        hero_seat=0,
        hole_cards=list(hole),
        board=list(board),
        pot_bb=pot,
        pot_text=None if pot is None else f"{pot:g} BB",
        seats=seats,
        button_seat=button,
        chat_lines=list(chat or []),
        banner=banner,
    )


def _play(readings):
    machine = HandMachine()
    done = []
    for reading in readings:
        done.extend(machine.feed(reading))
    done.append(machine.close())
    return done[-1]


def test_check_then_bet_is_two_actions_not_two_checks():
    hero = "TDawn"
    first = _reading(
        ["8c", "Th", "6s"],
        [_seat(0, hero, "CHECK"), _seat(1, "Kiwigirl")],
        pot=4,
    )
    second = _reading(
        ["8c", "Th", "6s"],
        [_seat(0, hero, "BET", bet=5), _seat(1, "Kiwigirl")],
        pot=4,
    )
    hand = _play([first, second])
    flop = next(street for street in hand.streets if street.name == "flop")
    types = [action.type for action in flop.actions]
    assert types == ["check", "bet"]
    assert flop.actions[1].amount_bb == 5


def test_same_check_on_the_same_street_is_not_repeated():
    reading = _reading(["8c", "Th", "6s"], [_seat(0, "TDawn", "CHECK")], pot=4)
    hand = _play([reading, reading])
    flop = next(street for street in hand.streets if street.name == "flop")
    assert [action.type for action in flop.actions] == ["check"]


def test_waiting_and_sitting_out_are_not_actions():
    reading = _reading(
        [],
        [
            _seat(0, "TDawn", "WAITING"),
            _seat(1, "george123", sitting=True, stack=100),
            _seat(2, "Kiwigirl", "CHECK"),
        ],
    )
    hand = _play([reading])
    preflop = hand.streets[0]
    assert all(action.player != "george123" for action in preflop.actions)
    assert all(action.type != "waiting" for action in preflop.actions)
    assert [action.type for action in preflop.actions] == ["check"]
    george = next(seat for seat in hand.seats if seat.name == "george123")
    assert george.sitting_out
    assert george.position is None


def test_post_is_only_the_blinds():
    reading = _reading(
        [],
        [
            _seat(0, "TDawn", bet=1),
            _seat(1, "Insomnia3", bet=0.5),
            _seat(2, "george123", "CALL", bet=1),
            _seat(3, "Kiwigirl", bet=2),
        ],
        button=3,
    )
    hand = _play([reading])
    posts = [action for action in hand.streets[0].actions if action.type == "post"]
    assert sorted(action.amount_bb for action in posts) == [0.5, 1]
    assert all(action.player != "Kiwigirl" for action in posts)
    calls = [action for action in hand.streets[0].actions if action.type == "call"]
    assert len(calls) == 1
    assert calls[0].amount_bb == 1
    assert not any(action.amount_bb == 2 for action in hand.streets[0].actions)


def test_raise_amount_is_the_street_total():
    pre = _reading([], [_seat(0, "TDawn", bet=1), _seat(1, "Villain", bet=0.5)])
    flop = _reading(["8c", "Th", "6s"], [_seat(0, "TDawn", "RAISE", bet=9), _seat(1, "Villain")], pot=4)
    hand = _play([pre, flop])
    street = next(item for item in hand.streets if item.name == "flop")
    assert street.actions[0].type == "raise"
    assert street.actions[0].amount_bb == 9


def test_fold_with_no_chips_is_zero():
    reading = _reading(["8c", "Th", "6s"], [_seat(0, "TDawn", "FOLD")], pot=4)
    hand = _play([reading])
    flop = next(street for street in hand.streets if street.name == "flop")
    assert flop.actions[0].type == "fold"
    assert flop.actions[0].amount_bb == 0


def test_pot_jump_without_a_label_stays_unknown():
    turn = _reading(["8c", "Th", "6s", "Js"], [_seat(0, "TDawn", "CHECK"), _seat(1, "Kiwigirl", "CHECK")], pot=4)
    river = _reading(
        ["8c", "Th", "6s", "Js", "4d"],
        [_seat(0, "TDawn"), _seat(1, "Kiwigirl")],
        pot=48,
        banner="STRAIGHT BEAT YOUR ONE PAIR",
        chat=["Insomnia3 won 24.00K with a Straight"],
    )
    # The chat line is new only if it was not the baseline. Seed an older line.
    opener = _reading([], [_seat(0, "TDawn", bet=1), _seat(1, "Kiwigirl", bet=0.5)], chat=["Kiwigirl won 4,250 with Two Pair"])
    hand = _play([opener, turn, river])
    river_street = next(street for street in hand.streets if street.name == "river")
    assert river_street.cards == ["4d"]
    assert river_street.pot_bb == 48
    assert any(action.type == "unknown" and action.amount_bb is None for action in river_street.actions)
    assert not any(action.type in {"bet", "raise", "call", "allin"} for action in river_street.actions)
    assert hand.showdown is not None
    assert hand.showdown.winner == "Insomnia3"
    assert hand.showdown.hand_text == "顺子"
    assert hand.showdown.amount_text == "24.00K"
    assert hand.showdown.hero_note == "你的一对输给顺子"
    text = hand.to_chinese()
    assert "建议" not in text
    assert "ONE PAIR" not in text


def test_old_chat_is_not_this_hand():
    first = _reading([], [_seat(0, "TDawn", bet=1)], chat=["george123 won 25K with a Straight"])
    later = _reading(["8c", "Th", "6s"], [_seat(0, "TDawn", "CHECK")], pot=4, chat=["george123 won 25K with a Straight"])
    hand = _play([first, later])
    assert hand.showdown is None or hand.showdown.winner is None


def test_hole_cards_that_disagree_become_unknown():
    first = _reading([], [_seat(0, "TDawn")], hole=("Qh", "Jd"))
    second = _reading(["8c", "Th", "6s"], [_seat(0, "TDawn")], hole=("As", "Kd"), pot=4)
    hand = _play([first, second])
    assert hand.hole_cards == ["unknown", "unknown"]


def test_hand_ends_when_the_board_clears_and_the_hole_cards_change():
    machine = HandMachine()
    machine.feed(_reading(["8c", "Th", "6s"], [_seat(0, "TDawn", "CHECK", stack=99)], pot=4, hole=("Qh", "Jd")))
    done = machine.feed(_reading([], [_seat(0, "TDawn", stack=84)], hole=("As", "Kd")))
    assert len(done) == 1
    assert done[0].hole_cards == ["Qh", "Jd"]
    assert machine.hand is not None
    assert machine.hand.hole_cards == ["As", "Kd"]


def test_unreadable_label_is_unknown_not_a_guess():
    reading = _reading(["8c", "Th", "6s"], [_seat(0, "TDawn", "UNKNOWN", bet=20)], pot=24)
    hand = _play([reading])
    flop = next(street for street in hand.streets if street.name == "flop")
    assert flop.actions[0].type == "unknown"
    assert flop.actions[0].amount_bb is None


def test_sitting_out_player_does_not_take_a_position():
    reading = _reading(
        [],
        [
            _seat(0, "TDawn", bet=1),
            _seat(1, "george123", sitting=True),
            _seat(4, "Kiwigirl"),
            _seat(5, "Insomnia3", bet=0.5),
        ],
        button=4,
    )
    hand = _play([reading])
    positions = {seat.name: seat.position for seat in hand.seats}
    assert positions["Kiwigirl"] == "BTN"
    assert positions["Insomnia3"] == "SB"
    assert positions["TDawn"] == "BB"
    assert positions["george123"] is None
