"""The cabin window is a different aspect from the seven beach samples.

Regions are fractions of the window. The beach boxes stay in place so the
original replay still reads the same hand.
"""

from pathlib import Path

from PIL import Image

from hdpoker.layout import CABIN, WIDE, layout_for
from hdpoker.ocrutil import match_status
from hdpoker.replay import SAMPLE_ORDER, default_sample_dir
from hdpoker.vision import _clean_name, orient_table, read_image

ROOT = Path(__file__).resolve().parent.parent
CABIN_IMAGE = ROOT / "samples" / "current-window.png"


def _inside(rect) -> bool:
    return 0 <= rect.x <= 1 and 0 <= rect.y <= 1 and rect.w > 0 and rect.h > 0 and rect.x + rect.w <= 1.01 and rect.y + rect.h <= 1.01


def test_both_layouts_are_fractions_of_the_window():
    for layout in (WIDE, CABIN):
        rects = [
            layout.table,
            layout.blinds,
            layout.header_cards,
            layout.pot,
            layout.chat,
            layout.banner,
            layout.buttons,
            layout.felt,
            *layout.board_slots,
        ]
        for seat in layout.seats:
            rects.extend((seat.plate, seat.status, seat.cards, seat.shown, seat.button))
        assert all(_inside(rect) for rect in rects)
        assert len(layout.board_slots) == 5
        assert sum(seat.hero for seat in layout.seats) == 1


def test_aspect_ratio_picks_the_skin():
    wide = Image.open(default_sample_dir() / SAMPLE_ORDER[0])
    cabin = Image.open(CABIN_IMAGE)
    assert wide.size[0] / wide.size[1] >= 1.70
    assert cabin.size[0] / cabin.size[1] < 1.70
    assert layout_for(wide).name == "wide"
    assert layout_for(cabin).name == "cabin"
    # The same cabin UI stretched to 16:9 still uses the cabin plates.
    stretched = cabin.resize((1920, 1080))
    assert stretched.size[0] / stretched.size[1] >= 1.70
    assert layout_for(stretched).name == "cabin"


def test_ocr_fragments_are_not_seat_names():
    for fragment in ("mbit", "Fill", "ayout"):
        assert _clean_name(fragment) is None
    assert _clean_name("TDawn") == "TDawn"
    assert _clean_name("Tariq") == "Tariq"
    assert _clean_name("CoolPush54") == "CoolPush54"


def test_an_upside_down_bitblt_frame_is_turned_upright_before_reading():
    image = Image.open(CABIN_IMAGE)
    flipped = image.transpose(Image.FLIP_TOP_BOTTOM)
    assert orient_table(image).size == image.size
    assert orient_table(flipped).getpixel((image.width // 2, 20)) == orient_table(image).getpixel((image.width // 2, 20))
    reading = read_image(flipped)
    assert reading.table_name == "[Standard] The Reef #1"
    assert (reading.small_blind, reading.big_blind) == (250, 500)
    assert reading.board == []
    assert reading.hole_cards == ["Jc", "3h"]
    assert any(seat.name == "TDawn" for seat in reading.seats)


def test_im_back_is_not_an_action_word():
    assert match_status("I'M BACK") is None
    assert match_status("IM BACK") is None
    assert match_status("ALL IN!") == "ALL IN"
    assert match_status("PRE-FLOP") is None


def test_cabin_window_reads_the_table_cards_and_bets():
    reading = read_image(Image.open(CABIN_IMAGE))
    assert reading.table_name == "[Standard] The Reef #1"
    assert (reading.small_blind, reading.big_blind) == (250, 500)
    assert reading.board == []
    # The jack pip is black and club-shaped. The three is a red heart.
    assert reading.hole_cards == ["Jc", "3h"]
    hero = next(seat for seat in reading.seats if seat.name == "TDawn")
    assert reading.hero_seat == hero.index
    assert reading.hero_options == []
    assert "PRE-FLOP" not in " ".join(seat.status or "" for seat in reading.seats)

    names = {seat.name: seat for seat in reading.seats if seat.name}
    assert "TDawn" in names
    assert names["TDawn"].bet_bb == 1
    assert names["TDawn"].stack_bb == 280
    assert "Tariq" in names
    assert names["Tariq"].bet_bb == 0.5

    cool = next(seat for seat in reading.seats if seat.name and seat.name.startswith("CoolPush"))
    assert reading.button_seat == cool.index
    all_in = next(seat for seat in reading.seats if seat.status == "ALL IN")
    assert all_in.bet_bb == 100
    assert {0.5, 1.0, 100.0} <= {seat.bet_bb for seat in reading.seats if seat.bet_bb is not None}
    assert len(names) == 6
