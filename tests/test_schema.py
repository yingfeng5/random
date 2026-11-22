"""The sample hand's JSON and Chinese text describe the same facts."""

from hdpoker.schema import ACTION_TYPES, sample_hand

STRENGTH_WORDS = ("HIGH CARD", "ONE PAIR", "PRE-FLOP", "牌力")


def test_version_and_action_types():
    hand = sample_hand()
    payload = hand.to_dict()
    assert payload["version"] == 1
    for street in payload["streets"]:
        for action in street["actions"]:
            assert action["type"] in ACTION_TYPES


def test_chinese_matches_json_fields():
    hand = sample_hand()
    text = hand.to_chinese()
    assert "[Standard] The Reef #2" in text
    assert "250/500" in text
    assert "TDawn" in text
    assert "Q♥" in text and "Q♦" in text
    assert "8♣" in text and "10♥" in text and "6♠" in text
    assert "J♠" in text
    assert "4♦" in text
    assert "过牌" in text
    assert "Kiwigirl" in text
    assert "24.00K" in text
    assert "顺子" in text
    assert "你的一对输给顺子" in text
    assert "未知" in text
    # george123 is sitting out, so the action lines do not include him.
    action_lines = [line for line in text.splitlines() if line.startswith("  ") and "过牌" in line or "下盲" in line or line.strip() == "未知"]
    assert all("george123" not in line for line in action_lines)
    assert "暂离" in text


def test_text_does_not_advise_or_record_the_strength_bar():
    text = sample_hand().to_chinese()
    assert "建议" not in text
    for word in STRENGTH_WORDS:
        assert word not in text


def test_river_unknown_has_no_invented_amount():
    river = next(street for street in sample_hand().streets if street.name == "river")
    assert len(river.actions) == 1
    assert river.actions[0].type == "unknown"
    assert river.actions[0].amount_bb is None
    assert river.actions[0].player is None
