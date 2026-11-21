"""One screenshot in, one reading out.

Status words are taken from a fixed list. A light bar whose letters are not
in that list is ``UNKNOWN`` and is not turned into a bet. The hand-strength
bar (PRE-FLOP, HIGH CARD, ONE PAIR, and the rest) is not read.
"""

from __future__ import annotations

import re

import numpy as np
from PIL import Image, ImageEnhance

from hdpoker.cards import read_card, templates_ready, load_templates
from hdpoker.layout import Layout, Rect, SeatLayout, layout_for
from hdpoker.ocrutil import (
    match_status,
    ocr_image,
    ocr_tsv,
    parse_bb,
    parse_blinds,
    parse_name,
    white_mask,
)
from hdpoker.reading import ACTIONS, Reading, SeatReading, same_cards

_OPTION_WORDS = ("FOLD", "CHECK", "CALL", "BET", "ALL IN", "RAISE")
_STRENGTH = {
    "PRE-FLOP",
    "PREFLOP",
    "HIGH CARD",
    "ONE PAIR",
    "TWO PAIR",
    "THREE OF A KIND",
    "STRAIGHT",
    "FLUSH",
    "FULL HOUSE",
    "FOUR OF A KIND",
    "STRAIGHT FLUSH",
    "ROYAL FLUSH",
}


def read_image(image: Image.Image) -> Reading:
    if templates_ready():
        load_templates()
    rgb = image.convert("RGB")
    layout = layout_for(rgb)
    table_name = _table_name(rgb, layout)
    small_blind, big_blind = _blinds(rgb, layout)
    board = _board(rgb, layout)
    pot_bb, pot_text = _pot(rgb, layout)
    button = _button_seat(rgb, layout)
    chat = _chat(rgb, layout)
    banner = _banner(rgb, layout)
    options = _options(rgb, layout)
    hero = layout.hero()
    hero_index = hero.index
    header = _cards_in(layout.header_cards.crop(rgb), limit=2)
    hole_seat = _cards_in(hero.cards.crop(rgb), limit=2)
    hole = _reconcile_hole(header, hole_seat)
    seats = []
    bets = _bets(rgb, layout)
    # Shown cards are only read once the board is complete or the banner is up,
    # so live hole cards and the community cards are not treated as a showdown.
    read_shown = banner is not None or len(board) >= 5
    for seat_layout in layout.seats:
        seat = _seat(rgb, seat_layout, bets, layout.pot)
        if read_shown:
            zone = seat_layout.shown
            shown = _cards_in(zone.crop(rgb), limit=2)
            if shown and len(shown) >= 2:
                seat.shown_cards = shown[:2]
        seats.append(seat)
    return Reading(
        table_name=table_name,
        small_blind=small_blind,
        big_blind=big_blind,
        hero_seat=hero_index,
        hole_cards=hole,
        hole_cards_header=header,
        hole_cards_seat=hole_seat,
        board=board,
        pot_bb=pot_bb,
        pot_text=pot_text,
        seats=seats,
        button_seat=button,
        hero_to_act=_hero_to_act(options),
        hero_options=options,
        chat_lines=chat,
        banner=banner,
    )


def _boost(image: Image.Image, scale: int = 4) -> Image.Image:
    resized = image.resize((max(1, image.width * scale), max(1, image.height * scale)), Image.Resampling.LANCZOS)
    return ImageEnhance.Contrast(resized).enhance(1.7)


def _table_name(image: Image.Image, layout: Layout) -> str | None:
    text = ocr_image(_boost(layout.table.crop(image), 3), psm=6)
    folded = " ".join(text.split())
    if re.search(r"reef", folded, re.IGNORECASE) and re.search(r"#\s*2", folded):
        return "[Standard] The Reef #2"
    match = re.search(r"\[[^\]]+\]\s*.*?#\s*\d+", folded)
    if match:
        return " ".join(match.group(0).split())
    match = re.search(r"\[[^\]]+\].*", folded)
    return match.group(0).strip() if match else None


def _blinds(image: Image.Image, layout: Layout) -> tuple[int | None, int | None]:
    crop = layout.blinds.crop(image)
    parsed = parse_blinds(ocr_image(_boost(crop), psm=6))
    if parsed[0] is not None:
        return parsed
    # White stakes on a tan header. A contrast boost smears this skin.
    array = np.asarray(crop.convert("L"), dtype=np.int16)
    mask = Image.fromarray(np.where(array > 200, 0, 255).astype(np.uint8))
    scaled = mask.resize((max(1, mask.width * 5), max(1, mask.height * 5)), Image.Resampling.NEAREST)
    return parse_blinds(ocr_image(scaled.convert("RGB"), psm=7, whitelist="0123456789/ "))


def _board(image: Image.Image, layout: Layout) -> list[str]:
    cards = []
    for slot in layout.board_slots:
        crop = slot.crop(image)
        if not _card_present(crop):
            break
        cards.append(read_card(crop))
    return cards


def _card_present(crop: Image.Image) -> bool:
    array = np.asarray(crop.convert("RGB"), dtype=np.int16)
    if array.size == 0:
        return False
    top = array[: max(1, array.shape[0] // 2)]
    luminance = top.mean(axis=2)
    return float((luminance > 180).mean()) > 0.10


def _cards_in(zone: Image.Image, limit: int) -> list[str] | None:
    array = np.asarray(zone.convert("RGB"), dtype=np.int16)
    if array.size == 0:
        return None
    luminance = array.mean(axis=2)
    white = luminance > 188
    boxes = _boxes(white)
    faces = []
    for left, top, right, bottom in boxes:
        width = right - left
        height = bottom - top
        if width < 14 or height < 22:
            continue
        ratio = height / max(1, width)
        if ratio < 0.9 or ratio > 2.2:
            continue
        faces.append((left, top, right, bottom))
    faces = _drop_outer_boxes(faces)
    if not faces:
        return None
    faces = faces[:limit]
    return [read_card(zone.crop(box)) for box in faces]


def _drop_outer_boxes(boxes: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    """A white blob that wraps two cards is not itself a card."""
    kept = []
    for box in boxes:
        left, top, right, bottom = box
        contains = False
        for other in boxes:
            if other == box:
                continue
            cx = (other[0] + other[2]) / 2
            cy = (other[1] + other[3]) / 2
            if left < cx < right and top < cy < bottom:
                contains = True
                break
        if not contains:
            kept.append(box)
    return kept


def _boxes(mask: np.ndarray) -> list[tuple[int, int, int, int]]:
    height, width = mask.shape
    seen = np.zeros((height, width), dtype=bool)
    found = []
    coords = np.argwhere(mask)
    for y, x in coords.tolist():
        if seen[y, x]:
            continue
        stack = [(y, x)]
        seen[y, x] = True
        miny = maxy = y
        minx = maxx = x
        area = 0
        while stack:
            cy, cx = stack.pop()
            area += 1
            miny, maxy = min(miny, cy), max(maxy, cy)
            minx, maxx = min(minx, cx), max(maxx, cx)
            for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                if 0 <= ny < height and 0 <= nx < width and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        if area >= 70:
            found.append((minx, miny, maxx + 1, maxy + 1, area))
    found.sort(key=lambda item: item[0])
    return [(a, b, c, d) for a, b, c, d, _area in found]


def _pair_known(cards: list[str] | None) -> bool:
    return bool(cards) and len(cards) == 2 and all(card and card != "unknown" for card in cards)


def _reconcile_hole(header: list[str] | None, seat: list[str] | None) -> list[str] | None:
    header_known = _pair_known(header)
    seat_known = _pair_known(seat)
    if header_known and seat_known:
        if same_cards(header, seat):
            return list(header)
        return ["unknown", "unknown"]
    # A source that did not read is not a disagreement.
    if header_known:
        return list(header)
    if seat_known:
        return list(seat)
    return None


def _pot(image: Image.Image, layout: Layout) -> tuple[float | None, str | None]:
    crop = layout.pot.crop(image)
    mask = white_mask(crop, minimum=175)
    scaled = mask.resize((max(1, mask.width * 6), max(1, mask.height * 6)), Image.Resampling.NEAREST)
    text = ocr_image(scaled.convert("RGB"), psm=6, whitelist="0123456789.MAINPOTBB ")
    if "POT" not in text.upper():
        return None, None
    return parse_bb(text)


def _seat(
    image: Image.Image,
    layout: SeatLayout,
    bets: list[tuple[float, str, float, float]],
    pot: Rect,
) -> SeatReading:
    plate = layout.plate.crop(image)
    name = _name(plate)
    stack_bb, stack_text = _stack(plate)
    status = _status(image, layout)
    bet_bb, bet_text = _nearest_bet(layout.bet_anchor, bets, pot)
    return SeatReading(
        index=layout.index,
        name=name,
        stack_bb=stack_bb,
        stack_text=stack_text,
        status=status,
        bet_bb=bet_bb,
        bet_text=bet_text,
        timer=_timer(plate),
    )


def _name(plate: Image.Image) -> str | None:
    width, height = plate.size
    # Stop at the white stack line. A fixed fraction clips a tall name or
    # swallows the chips on a short plate.
    bottom = _name_bottom(plate)
    line = plate.crop((int(width * 0.10), int(height * 0.02), int(width * 0.98), int(height * bottom)))
    green = _read_name_line(line)
    bright = _read_bright_name(line)
    color = _read_plate_color(plate)
    return _choose_name(green, bright, color)


def _name_bottom(plate: Image.Image) -> float:
    array = np.asarray(plate.convert("L"), dtype=np.int16)
    height, width = array.shape
    if height < 8:
        return 0.50
    body = array[:, int(width * 0.28) : int(width * 0.88)]
    fraction = (body > 185).mean(axis=1)
    baseline = float(np.median(fraction))
    start = None
    run = 0
    for y in range(int(height * 0.32), int(height * 0.86)):
        if fraction[y] > baseline + 0.08:
            run += 1
            if run >= 4:
                start = y - 3
                break
        else:
            run = 0
    if start is None:
        return 0.55
    return min(0.64, max(0.40, (start - 1) / height))


def _choose_name(green: str | None, bright: str | None, color: str | None) -> str | None:
    candidates = [name for name in (green, bright, color) if name]
    if not candidates:
        return None
    if green:
        # "pweetBet17" and "SweetBet17" are the same name. Keep the capital.
        for other in candidates:
            if other.lower()[1:] == green.lower()[1:] and other[0].isupper() and not green[0].isupper():
                return other
        chosen = green
        for other in candidates:
            low = other.lower()
            base = green.lower()
            if (low.startswith(base) or base.startswith(low)) and abs(len(other) - len(green)) <= 3:
                if len(other) > len(chosen):
                    chosen = other
        return chosen
    candidates.sort(key=lambda item: (item[0].isupper(), item[-1].isdigit(), len(item)), reverse=True)
    return candidates[0]


def _read_plate_color(plate: Image.Image) -> str | None:
    scaled = plate.resize((max(1, plate.width * 4), max(1, plate.height * 4)), Image.Resampling.LANCZOS)
    scaled = ImageEnhance.Contrast(scaled).enhance(2.0)
    text = ocr_image(scaled, psm=6)
    return _clean_name(parse_name(text))


def _read_name_line(line: Image.Image) -> str | None:
    scaled = line.resize((max(1, line.width * 6), max(1, line.height * 6)), Image.Resampling.LANCZOS)
    array = np.asarray(scaled.convert("RGB"), dtype=np.int16)
    red, green, blue = array[:, :, 0], array[:, :, 1], array[:, :, 2]
    mask = (green > 120) & (green > red + 18) & (green > blue + 8)
    bw = Image.fromarray(np.where(mask, 0, 255).astype(np.uint8))
    text = ocr_image(
        bw.convert("RGB"),
        psm=7,
        whitelist="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
    )
    return _clean_name(parse_name(text))


def _read_bright_name(line: Image.Image) -> str | None:
    """Hero names are light green on a green plate, so a relative green mask misses them."""
    scaled = line.resize((max(1, line.width * 6), max(1, line.height * 6)), Image.Resampling.LANCZOS)
    array = np.asarray(scaled.convert("L"), dtype=np.int16)
    if array.size == 0:
        return None
    cutoff = float(np.percentile(array, 70))
    bw = Image.fromarray(np.where(array > cutoff, 0, 255).astype(np.uint8))
    text = ocr_image(
        bw.convert("RGB"),
        psm=7,
        whitelist="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
    )
    return _clean_name(parse_name(text))


def _clean_name(name: str | None) -> str | None:
    if not name or len(name) < 4:
        return None
    # Tesseract reads the vertical stroke of "1" as "l" in names like george123.
    return re.sub(r"l(?=\d)", "1", name)


def _stack(plate: Image.Image) -> tuple[float | None, str | None]:
    width, height = plate.size
    # Several crops and thresholds. A clipped line reads "280" as "750" or
    # "40" once; the value that comes back more than once is the stack.
    bands = (
        plate.crop((int(width * 0.15), int(height * 0.46), int(width * 0.92), int(height * 0.80))),
        plate.crop((int(width * 0.15), int(height * 0.38), int(width * 0.92), int(height * 0.72))),
    )
    votes: dict[float, int] = {}
    for band in bands:
        array = np.asarray(band.convert("L"), dtype=np.int16)
        for minimum in (155, 165, 175):
            mask = Image.fromarray(np.where(array > minimum, 0, 255).astype(np.uint8))
            scaled = mask.resize((max(1, mask.width * 5), max(28, mask.height * 5)), Image.Resampling.NEAREST)
            text = ocr_image(scaled.convert("RGB"), psm=7, whitelist="0123456789.BB ")
            value, _label = parse_bb(text)
            if value is None or value > 5000:
                continue
            votes[value] = votes.get(value, 0) + 1
    if not votes:
        return None, None
    value = max(votes, key=lambda item: (votes[item], -item))
    text_out = f"{value:.2f}".rstrip("0").rstrip(".") + " BB"
    return value, text_out


def _status(image: Image.Image, layout: SeatLayout) -> str | None:
    area = layout.status.crop(image)
    width, height = area.size
    if width < 4 or height < 4:
        return None
    hits: dict[str, int] = {}
    saw_bar = False
    saw_letters = False
    steps = 5
    for step in range(steps):
        top = int(step / steps * height * 0.55)
        bottom = min(height, top + max(8, int(height * 0.62)))
        strip = area.crop((0, top, width, bottom))
        if _label_bar(strip):
            saw_bar = True
        for minimum in (200, 170):
            mask = white_mask(strip, minimum=minimum)
            if _ink_fraction(mask) < 0.004:
                continue
            text = ocr_image(
                mask.resize((mask.width * 6, max(24, mask.height * 6)), Image.Resampling.LANCZOS),
                psm=7,
                whitelist="ABCDEFGHIJKLMNOPQRSTUVWXYZ ",
            )
            status = match_status(text)
            if status:
                hits[status] = hits.get(status, 0) + 1
            letters = [ch for ch in text if ch.isalpha()]
            # "EEE" is a window frame. A label has more than one letter shape.
            if len(letters) >= 3 and len(set(letters)) >= 2:
                saw_letters = True
        dark = _dark_on_bright(strip)
        if dark:
            hits[dark] = hits.get(dark, 0) + 1
    if hits:
        return max(hits, key=lambda word: (hits[word], len(word)))
    # A label bar whose letters are not in the vocabulary stays unknown.
    # The cabin window is a bright flat region with no letters, so it is not one.
    if saw_bar and saw_letters:
        return "UNKNOWN"
    return None


def _ink_fraction(mask: Image.Image) -> float:
    array = np.asarray(mask, dtype=np.uint8)
    if array.size == 0:
        return 0.0
    return float((array < 128).mean())


def _dark_on_bright(strip: Image.Image) -> str | None:
    """Black letters on a yellow ALL IN bar. Light-blue labels use white text."""
    array = np.asarray(strip.convert("RGB"), dtype=np.int16)
    if array.size == 0:
        return None
    red, green, blue = array[:, :, 0], array[:, :, 1], array[:, :, 2]
    yellow = (red > 170) & (green > 130) & (blue < 140) & ((red.astype(int) - blue) > 40)
    if float(yellow.mean()) < 0.35:
        return None
    luminance = (red + green + blue) / 3
    dark = luminance < 90
    if float(dark.mean()) < 0.01:
        return None
    mask = Image.fromarray(np.where(dark, 0, 255).astype(np.uint8))
    text = ocr_image(
        mask.resize((mask.width * 6, max(24, mask.height * 6)), Image.Resampling.LANCZOS),
        psm=7,
        whitelist="ABCDEFGHIJKLMNOPQRSTUVWXYZ ",
    )
    return match_status(text)


def _label_bar(strip: Image.Image) -> bool:
    array = np.asarray(strip.convert("RGB"), dtype=np.int16)
    red, green, blue = array[:, :, 0], array[:, :, 1], array[:, :, 2]
    luminance = (red + green + blue) / 3
    chroma = np.maximum(np.maximum(red, green), blue) - np.minimum(np.minimum(red, green), blue)
    light = (luminance > 150) & (luminance < 215) & (chroma < 60) & ((red - blue) < 40)
    return float(light.mean()) > 0.35


def _timer(plate: Image.Image) -> bool:
    """A bright bar across the stack. Used only to mark whose turn it is."""
    array = np.asarray(plate.convert("RGB"), dtype=np.int16)
    red, green, blue = array[:, :, 0], array[:, :, 1], array[:, :, 2]
    # The hero plate is green all the time, so a flat green fill is not a timer.
    hot = (red > 180) & (green > 80) & (green < 180) & (blue < 80)
    return float(hot.mean()) > 0.04


def _bets(image: Image.Image, layout: Layout) -> list[tuple[float, str, float, float]]:
    felt = layout.felt
    crop = _boost(felt.crop(image), 2)
    rows = ocr_tsv(crop, psm=11)
    found = []
    for row in rows:
        amount, original = parse_bb(row["text"])
        if amount is None:
            # "0.5" on one word and "BB" on the next is handled below.
            continue
        x = (row["left"] + row["width"] / 2) / crop.width
        y = (row["top"] + row["height"] / 2) / crop.height
        found.append((amount, original or "", felt.x + x * felt.w, felt.y + y * felt.h))
    # Join a number word with a nearby BB word.
    numbers = []
    bbs = []
    for row in rows:
        text = row["text"].replace(",", "")
        center_x = felt.x + ((row["left"] + row["width"] / 2) / crop.width) * felt.w
        center_y = felt.y + ((row["top"] + row["height"] / 2) / crop.height) * felt.h
        if re.fullmatch(r"\d+(?:\.\d+)?", text):
            numbers.append((float(text), center_x, center_y))
        elif text.upper() == "BB":
            bbs.append((center_x, center_y))
    for value, x, y in numbers:
        for bx, by in bbs:
            if abs(bx - x) < 0.03 and abs(by - y) < 0.02:
                original = f"{value:.2f}".rstrip("0").rstrip(".") + " BB"
                if not any(abs(item[2] - x) < 0.01 and abs(item[3] - y) < 0.01 for item in found):
                    found.append((value, original, x, y))
                break
    for amount, original, x, y in _bet_pills(image, felt):
        if not any(abs(item[2] - x) < 0.015 and abs(item[3] - y) < 0.015 for item in found):
            found.append((amount, original, x, y))
    return found


def _bet_pills(image: Image.Image, felt: Rect) -> list[tuple[float, str, float, float]]:
    """Read a small dark chip label when the whole-felt pass misses it."""
    crop = felt.crop(image)
    array = np.asarray(crop.convert("RGB"), dtype=np.int16)
    if array.size == 0:
        return []
    red, green, blue = array[:, :, 0], array[:, :, 1], array[:, :, 2]
    luminance = (red + green + blue) / 3
    chroma = np.maximum(np.maximum(red, green), blue) - np.minimum(np.minimum(red, green), blue)
    dark = (luminance < 85) & (chroma < 55)
    found = []
    width, height = image.size
    for left, top, right, bottom in _boxes(dark):
        box_w = (right - left) / width
        box_h = (bottom - top) / height
        if not (0.012 < box_w < 0.08 and 0.008 < box_h < 0.055):
            continue
        if box_h <= 0 or not 1.15 <= (box_w / box_h) <= 5.5:
            continue
        pill = crop.crop((left, top, right, bottom))
        mask = white_mask(pill, minimum=160)
        scaled = mask.resize((max(1, mask.width * 4), max(1, mask.height * 4)), Image.Resampling.NEAREST)
        text = ocr_image(scaled.convert("RGB"), psm=7, whitelist="0123456789.BB ")
        amount, original = parse_bb(text)
        if amount is None:
            continue
        x = felt.x + ((left + right) / 2) / crop.width * felt.w
        y = felt.y + ((top + bottom) / 2) / crop.height * felt.h
        found.append((amount, original or "", x, y))
    return found


def _nearest_bet(
    anchor: tuple[float, float],
    bets: list[tuple[float, str, float, float]],
    pot: Rect,
) -> tuple[float | None, str | None]:
    best = None
    best_distance = 0.07
    pot_box = (pot.x, pot.y, pot.x + pot.w, pot.y + pot.h)
    for amount, original, x, y in bets:
        if pot_box[0] <= x <= pot_box[2] and pot_box[1] <= y <= pot_box[3]:
            continue
        distance = ((x - anchor[0]) ** 2 + (y - anchor[1]) ** 2) ** 0.5
        if distance < best_distance:
            best_distance = distance
            best = (amount, original)
    if best is None:
        return None, None
    return best


def _button_seat(image: Image.Image, layout: Layout) -> int | None:
    array = np.asarray(image.convert("RGB"), dtype=np.int16)
    height, width = array.shape[:2]
    red, green, blue = array[:, :, 0], array[:, :, 1], array[:, :, 2]
    teal = (red < 130) & (green > 90) & (blue > 150) & (blue > red + 40) & (green > red)
    # Ignore the window chrome.
    teal[: int(0.18 * height), :] = False
    teal[int(0.86 * height) :, :] = False
    boxes = _boxes(teal)
    if not boxes:
        return None
    # Prefer a small disc, not a huge UI panel.
    candidates = []
    for left, top, right, bottom in boxes:
        area = (right - left) * (bottom - top)
        if area < 40 or area > 4000:
            continue
        if right - left > 80 or bottom - top > 80:
            continue
        candidates.append(((left + right) / 2 / width, (top + bottom) / 2 / height, area))
    if not candidates:
        return None
    best_seat = None
    best_distance = 0.08
    for cx, cy, _area in candidates:
        for seat_layout in layout.seats:
            bx, by = seat_layout.button.center()
            distance = ((cx - bx) ** 2 + (cy - by) ** 2) ** 0.5
            if distance < best_distance:
                best_distance = distance
                best_seat = seat_layout.index
    return best_seat


def _chat(image: Image.Image, layout: Layout) -> list[str]:
    text = ocr_image(_boost(layout.chat.crop(image), 3), psm=6)
    lines = []
    for raw in text.splitlines() if "\n" in text else [text]:
        pass
    # tesseract returns spaces; split on the Kendra tag.
    chunks = re.split(r"\[+\s*Kendra\s*\]+", text, flags=re.IGNORECASE)
    for chunk in chunks:
        line = " ".join(chunk.split())
        line = line.strip(" |-:")
        if not line or "HIT ENTER" in line.upper() or "CHAT" == line.upper():
            continue
        if len(line) < 8:
            continue
        lines.append(line)
    return lines


def _banner(image: Image.Image, layout: Layout) -> str | None:
    text = ocr_image(_boost(layout.banner.crop(image), 3), psm=6).upper()
    text = " ".join(text.split())
    if "BEAT YOUR" not in text and "STRAIGHT" not in text:
        return None
    # Drop strength-bar words that are not this banner. The banner is the
    # sentence in the middle of the table, already isolated by BANNER.
    if any(word in text for word in ("BEAT YOUR", "WINNER")):
        return text
    if "STRAIGHT" in text and "PAIR" in text:
        return text
    return None


def _options(image: Image.Image, layout: Layout) -> list[str]:
    text = ocr_image(_boost(layout.buttons.crop(image), 2), psm=6).upper()
    # The sit-back control is not a betting action.
    text = text.replace("I'M BACK", " ").replace("IM BACK", " ").replace("I AM BACK", " ")
    found = []
    for word in _OPTION_WORDS:
        if word in text:
            found.append(word)
    return found


def _hero_to_act(options: list[str]) -> bool:
    # The bet-sizing panel is up only on the hero's turn. CHECK/FOLD presets
    # are also up when it is not. BET or ALL IN in that corner means the turn.
    return "BET" in options or "ALL IN" in options


def _strength_ignored(text: str) -> bool:
    """Present so a caller can see these words are deliberately dropped."""
    return " ".join(text.upper().split()) in _STRENGTH
