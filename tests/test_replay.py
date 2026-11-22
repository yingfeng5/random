"""Replay the seven screenshots. Images are required here; the state machine tests are not."""

from hdpoker.replay import compare_to_plan, replay
from hdpoker.schema import ACTION_TYPES


def test_replay_reads_the_sample_hand_without_inventing_the_river():
    hand = replay()
    assert hand.version == 1
    for street in hand.streets:
        for action in street.actions:
            assert action.type in ACTION_TYPES
    text = hand.to_chinese()
    assert "建议" not in text
    assert "HIGH CARD" not in text
    assert "ONE PAIR" not in text
    assert "PRE-FLOP" not in text

    flop = next(street for street in hand.streets if street.name == "flop")
    turn = next(street for street in hand.streets if street.name == "turn")
    river = next(street for street in hand.streets if street.name == "river")
    assert flop.cards == ["8c", "Th", "6s"]
    assert turn.cards == ["Js"] or turn.cards == ["Jh"] or turn.cards[0].startswith("J")
    assert river.cards[-1].startswith("4")
    assert not any(action.type in {"bet", "raise", "call", "allin"} and action.amount_bb is not None for action in river.actions)
    assert any(action.type == "unknown" and action.amount_bb is None for action in river.actions)

    rows = dict((fact, (expected, got)) for fact, expected, got in compare_to_plan(hand))
    # The river bets are not reconstructed from the pot.
    assert "unknown" in rows["river bets"][1]
    assert hand.showdown is not None
    assert hand.showdown.amount_text == "24.00K"
    assert hand.showdown.hand_text == "顺子"
