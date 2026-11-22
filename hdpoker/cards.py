"""Card ranks and suits by matching corner glyphs cropped from the samples.

A glyph that does not match a template stays ``unknown``. The hand-strength
bar is not a card and is not read here.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
RANK_DIR = TEMPLATE_DIR / "ranks"
SUIT_DIR = TEMPLATE_DIR / "suits"
RANK_HEIGHT = 32
SUIT_SIZE = 32
MIN_SCORE = 0.55

_RANKS: dict[str, np.ndarray] | None = None
_SUITS: dict[str, np.ndarray] | None = None


def templates_ready() -> bool:
    return RANK_DIR.is_dir() and any(RANK_DIR.glob("*.png")) and SUIT_DIR.is_dir() and any(SUIT_DIR.glob("*.png"))


def load_templates() -> None:
    global _RANKS, _SUITS
    _RANKS = {path.stem: _load_glyph(path) for path in sorted(RANK_DIR.glob("*.png"))}
    _SUITS = {path.stem: _load_glyph(path) for path in sorted(SUIT_DIR.glob("*.png"))}


def _load_glyph(path: Path) -> np.ndarray:
    image = Image.open(path).convert("L")
    array = np.asarray(image, dtype=np.float32)
    return array < 128


_OCR_RANK = {
    "A": "A",
    "K": "K",
    "Q": "Q",
    "J": "J",
    "T": "T",
    "10": "T",
    "9": "9",
    "8": "8",
    "7": "7",
    "6": "6",
    "5": "5",
    "4": "4",
    "3": "3",
    "2": "2",
}


def read_card(image: Image.Image) -> str:
    """Read one card face. Returns ``unknown`` when the glyph does not match."""
    if _RANKS is None or _SUITS is None:
        if not templates_ready():
            return "unknown"
        load_templates()
    assert _RANKS is not None and _SUITS is not None
    trimmed = trim_to_face(image)
    if trimmed is None:
        return "unknown"
    rank_glyph, suit_glyph, color = extract_glyphs(trimmed)
    rank = _match(rank_glyph, _RANKS, canvas=(48, RANK_HEIGHT))
    if rank is None:
        rank = _ocr_rank(rank_glyph)
    if rank is None:
        rank = _ocr_rank_face(trimmed)
    suit = _match_suit(suit_glyph, color)
    if rank is None or suit is None:
        return "unknown"
    return f"{rank}{suit}"


def _ocr_rank_face(image: Image.Image) -> str | None:
    """Read a large index when the corner glyph is too small to match."""
    width, height = image.size
    if width < 8 or height < 12:
        return None
    top = image.crop((0, 0, max(1, int(width * 0.8)), max(1, int(height * 0.62))))
    array = np.asarray(top.convert("RGB"), dtype=np.int16)
    red, green, blue = array[:, :, 0], array[:, :, 1], array[:, :, 2]
    ink = ((red < 105) & (green < 105) & (blue < 105)) | (
        (red > 95) & (red > green + 22) & (red > blue + 22) & (green < 170) & (blue < 170)
    )
    if int(ink.sum()) < 8:
        return None
    mask = Image.fromarray(np.where(ink, 0, 255).astype(np.uint8))
    mask = mask.resize((max(16, mask.width * 8), max(16, mask.height * 8)), Image.Resampling.NEAREST)
    from hdpoker.ocrutil import ocr_image

    text = ocr_image(mask.convert("RGB"), psm=10, whitelist="AJKQT2345678910")
    token = "".join(ch for ch in text if ch.isalnum())
    return _OCR_RANK.get(token)


def _ocr_rank(glyph: np.ndarray | None) -> str | None:
    """Read a rank the template missed. Only a single rank character is accepted."""
    if glyph is None or glyph.size < 8:
        return None
    from hdpoker.ocrutil import ocr_image

    image = Image.fromarray(np.where(glyph, 0, 255).astype(np.uint8))
    height = 80
    width = max(16, int(round(image.width * height / max(1, image.height))))
    image = image.resize((width, height), Image.Resampling.NEAREST)
    canvas = Image.new("L", (width + 40, height + 40), 255)
    canvas.paste(image, (20, 20))
    text = ocr_image(canvas.convert("RGB"), psm=10, whitelist="AJKQT2345678910")
    token = "".join(ch for ch in text if ch.isalnum())
    return _OCR_RANK.get(token)


def trim_to_face(image: Image.Image) -> Image.Image | None:
    array = np.asarray(image.convert("RGB"), dtype=np.int16)
    red, green, blue = array[:, :, 0], array[:, :, 1], array[:, :, 2]
    luminance = array.mean(axis=2)
    # The showdown glow is cyan. A card face is white, so the channels stay close.
    white = (luminance > 170) & (np.abs(red - green) < 32) & (np.abs(red - blue) < 40)
    ys, xs = np.where(white)
    if len(ys) < 25:
        return None
    left, right = int(xs.min()), int(xs.max()) + 1
    top, bottom = int(ys.min()), int(ys.max()) + 1
    if right - left < 8 or bottom - top < 12:
        return None
    return image.crop((left, top, right, bottom))


def extract_glyphs(image: Image.Image) -> tuple[np.ndarray | None, np.ndarray | None, str]:
    array = np.asarray(image.convert("RGB"), dtype=np.int16)
    height, width = array.shape[:2]
    red, green, blue = array[:, :, 0], array[:, :, 1], array[:, :, 2]
    black = (red < 105) & (green < 105) & (blue < 105) & (np.abs(red - green) < 45)
    red_ink = (red > 95) & (red > green + 22) & (red > blue + 22) & (green < 170) & (blue < 170)
    ink = black | red_ink

    # The rank sits in the upper-left. "10" is wide, so the window is most of
    # the left side and stops before the corner pip.
    rank_window = ink[: max(4, int(height * 0.46)), : max(4, int(width * 0.74))]
    rank = _bbox(rank_window)
    suit_glyph = _largest_component(ink[int(height * 0.40) :, :])
    if suit_glyph is None:
        color = "red" if int(red_ink.sum()) > int(black.sum()) else "black"
    else:
        lower_red = int(red_ink[int(height * 0.40) :, :].sum())
        lower_black = int(black[int(height * 0.40) :, :].sum())
        color = "red" if lower_red > lower_black else "black"
    return rank, suit_glyph, color


def _largest_component(ink: np.ndarray) -> np.ndarray | None:
    height, width = ink.shape
    if height == 0 or width == 0:
        return None
    seen = np.zeros_like(ink, dtype=bool)
    best = None
    best_area = 0
    ys, xs = np.where(ink)
    for y, x in zip(ys.tolist(), xs.tolist()):
        if seen[y, x]:
            continue
        stack = [(y, x)]
        seen[y, x] = True
        cells = []
        while stack:
            cy, cx = stack.pop()
            cells.append((cy, cx))
            for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                if 0 <= ny < height and 0 <= nx < width and ink[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        if len(cells) > best_area:
            best_area = len(cells)
            best = cells
    if not best or best_area < 8:
        return None
    rows = [cell[0] for cell in best]
    cols = [cell[1] for cell in best]
    glyph = np.zeros((max(rows) - min(rows) + 1, max(cols) - min(cols) + 1), dtype=bool)
    top, left = min(rows), min(cols)
    for y, x in best:
        glyph[y - top, x - left] = True
    return glyph


def _split_rank_and_suit(ink: np.ndarray) -> tuple[np.ndarray | None, np.ndarray | None]:
    columns = ink.any(axis=0)
    runs = _runs(columns)
    if not runs:
        return None, None
    # The pip sits to the right of the rank and is the narrower run.
    if len(runs) >= 2:
        left = runs[0][1] - runs[0][0]
        right = runs[-1][1] - runs[-1][0]
        if right < left * 0.85 and runs[-1][0] > ink.shape[1] * 0.35:
            # Every run except the last pip, so "10" stays one glyph.
            rank_box = (runs[0][0], runs[-2][1])
            return _clip_rows(ink, rank_box), _clip_rows(ink, runs[-1])
    return _clip_rows(ink, (runs[0][0], runs[-1][1])), None


def _clip_rows(ink: np.ndarray, x_span: tuple[int, int]) -> np.ndarray | None:
    piece = ink[:, x_span[0] : x_span[1]]
    return _bbox(piece)


def _bbox(ink: np.ndarray) -> np.ndarray | None:
    ys, xs = np.where(ink)
    if len(ys) < 6:
        return None
    return ink[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]


def _runs(flags: np.ndarray) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start = None
    for index, value in enumerate(flags):
        if value and start is None:
            start = index
        if not value and start is not None:
            if index - start >= 1:
                runs.append((start, index))
            start = None
    if start is not None:
        runs.append((start, len(flags)))
    # Merge runs separated by a one-pixel gap so a broken "8" stays one glyph
    # until the suit gap, which is wider, remains.
    merged: list[tuple[int, int]] = []
    for run in runs:
        if merged and run[0] - merged[-1][1] <= 2:
            merged[-1] = (merged[-1][0], run[1])
        else:
            merged.append(run)
    return merged


def _suit_color(array: np.ndarray, glyph: np.ndarray, from_big: bool) -> str:
    red, green, blue = array[:, :, 0], array[:, :, 1], array[:, :, 2]
    red_ink = (red > 140) & (green < 125) & (blue < 125) & (red > green + 35)
    black = (red < 90) & (green < 90) & (blue < 90)
    if from_big:
        region_red = red_ink[int(array.shape[0] * 0.34) :, int(array.shape[1] * 0.12) : int(array.shape[1] * 0.90)]
        region_black = black[int(array.shape[0] * 0.34) :, int(array.shape[1] * 0.12) : int(array.shape[1] * 0.90)]
        return "red" if int(region_red.sum()) > int(region_black.sum()) else "black"
    return "red" if int(red_ink.sum()) > int(black.sum()) else "black"


def _match(glyph: np.ndarray | None, templates: dict[str, np.ndarray], canvas: tuple[int, int]) -> str | None:
    if glyph is None or not templates:
        return None
    prepared = _normalize(glyph, canvas)
    best_name = None
    best_score = MIN_SCORE
    for name, template in templates.items():
        score = _score(prepared, _normalize(template, canvas))
        if score > best_score:
            best_score = score
            best_name = name
    return best_name


def _match_suit(glyph: np.ndarray | None, color: str) -> str | None:
    assert _SUITS is not None
    if glyph is None:
        return None
    allowed = {"h", "d"} if color == "red" else {"s", "c"}
    subset = {name: template for name, template in _SUITS.items() if name in allowed}
    if not subset:
        return None
    prepared = _normalize(glyph, (SUIT_SIZE, SUIT_SIZE))
    scores = {
        name: _score(prepared, _normalize(template, (SUIT_SIZE, SUIT_SIZE)))
        for name, template in subset.items()
    }
    best = max(scores, key=scores.get)
    # A small club and a small spade score almost the same, sometimes under the
    # usual cutoff. Clubs are wide across the top; spades come to a point.
    if color != "red" and "c" in scores and "s" in scores and abs(scores["c"] - scores["s"]) < 0.08:
        if max(scores["c"], scores["s"]) >= 0.40:
            top = float(prepared[:8].mean())
            return "c" if top >= 0.27 else "s"
    if scores[best] < MIN_SCORE:
        return None
    return best


def _normalize(glyph: np.ndarray, canvas: tuple[int, int]) -> np.ndarray:
    canvas_w, canvas_h = canvas
    height = max(1, glyph.shape[0])
    width = max(1, glyph.shape[1])
    scale = canvas_h / height
    resized_w = max(1, min(canvas_w, int(round(width * scale))))
    image = Image.fromarray(np.where(glyph, 0, 255).astype(np.uint8))
    image = image.resize((resized_w, canvas_h), Image.Resampling.BOX)
    array = np.asarray(image, dtype=np.float32) < 128
    plate = np.zeros((canvas_h, canvas_w), dtype=bool)
    left = (canvas_w - resized_w) // 2
    plate[:, left : left + resized_w] = array
    return plate


def _score(left: np.ndarray, right: np.ndarray) -> float:
    a = left.astype(np.float32)
    b = right.astype(np.float32)
    a -= a.mean()
    b -= b.mean()
    denom = float(np.sqrt((a * a).sum() * (b * b).sum()))
    if denom < 1e-6:
        return 0.0
    return float((a * b).sum() / denom)


def save_glyph(glyph: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.fromarray(np.where(glyph, 0, 255).astype(np.uint8))
    image.save(path)


def build_templates(sample_dir: Path, destinations: tuple[Path, Path] = (RANK_DIR, SUIT_DIR)) -> list[str]:
    """Crop labeled glyphs from the calibration screenshots and write templates.

    Labels were checked against the sample pixels (rank shape and red/black pip).
    """
    from hdpoker.layout import BOARD_SLOTS, SEATS

    rank_dir, suit_dir = destinations
    # file prefix, slot index, rank, suit
    board_labels = [
        ("98316dae", 0, "8", "c"),
        ("98316dae", 1, "T", "h"),
        ("98316dae", 2, "6", "s"),
        ("476d0a9d", 3, "J", "h"),
        ("d37c69ce", 4, "4", "d"),
    ]
    written: list[str] = []
    seen_ranks: set[str] = set()
    seen_suits: set[str] = set()
    for prefix, slot, rank, suit in board_labels:
        path = _find_sample(sample_dir, prefix)
        image = Image.open(path).convert("RGB")
        card = trim_to_face(BOARD_SLOTS[slot].crop(image))
        if card is None:
            continue
        rank_glyph, suit_glyph, _color = extract_glyphs(card)
        if rank_glyph is not None and rank not in seen_ranks:
            save_glyph(rank_glyph, rank_dir / f"{rank}.png")
            seen_ranks.add(rank)
            written.append(f"rank {rank}")
        if suit_glyph is not None and suit not in seen_suits:
            save_glyph(suit_glyph, suit_dir / f"{suit}.png")
            seen_suits.add(suit)
            written.append(f"suit {suit}")
    _add_showdown_glyphs(sample_dir, rank_dir, suit_dir, seen_ranks, seen_suits, written)
    _add_hero_queen(sample_dir, rank_dir, seen_ranks, written, SEATS[0].cards)
    return written


def _find_sample(sample_dir: Path, prefix: str) -> Path:
    matches = sorted(sample_dir.glob(f"{prefix}*.png"))
    if not matches:
        raise FileNotFoundError(prefix)
    return matches[0]


def _add_showdown_glyphs(sample_dir, rank_dir, suit_dir, seen_ranks, seen_suits, written) -> None:
    """7 and 5 are only on the showdown cards under the board."""
    path = _find_sample(sample_dir, "d37c69ce")
    image = Image.open(path).convert("RGB")
    width, height = image.size
    # The two winning cards sit just under the board, left of the pot label.
    zone = image.crop((int(0.44 * width), int(0.64 * height), int(0.58 * width), int(0.80 * height)))
    faces = _faces_in(zone)
    labels = ["7", "5"]
    suits = ["s", "h"]
    for face, rank, suit in zip(faces, labels, suits):
        rank_glyph, suit_glyph, _color = extract_glyphs(face)
        if rank_glyph is not None and rank not in seen_ranks:
            save_glyph(rank_glyph, rank_dir / f"{rank}.png")
            seen_ranks.add(rank)
            written.append(f"rank {rank}")
        if suit_glyph is not None and suit not in seen_suits:
            save_glyph(suit_glyph, suit_dir / f"{suit}.png")
            seen_suits.add(suit)
            written.append(f"suit {suit}")


def _add_hero_queen(sample_dir, rank_dir, seen_ranks, written, zone_rect) -> None:
    if "Q" in seen_ranks:
        return
    path = _find_sample(sample_dir, "8d28a795")
    image = Image.open(path).convert("RGB")
    zone = zone_rect.crop(image)
    faces = _faces_in(zone)
    if not faces:
        return
    rank_glyph, _suit, _color = extract_glyphs(faces[0])
    if rank_glyph is not None:
        save_glyph(rank_glyph, rank_dir / "Q.png")
        seen_ranks.add("Q")
        written.append("rank Q")


def _faces_in(zone: Image.Image) -> list[Image.Image]:
    array = np.asarray(zone.convert("RGB"), dtype=np.int16)
    luminance = array.mean(axis=2)
    white = luminance > 185
    boxes = _component_boxes(white, min_area=80, min_w=12, min_h=18)
    faces = []
    for left, top, right, bottom in boxes:
        if bottom - top < 18 or right - left < 12:
            continue
        ratio = (bottom - top) / max(1, right - left)
        if ratio < 0.8 or ratio > 2.4:
            continue
        faces.append(zone.crop((left, top, right, bottom)))
    return faces


def _component_boxes(mask: np.ndarray, min_area: int, min_w: int, min_h: int) -> list[tuple[int, int, int, int]]:
    height, width = mask.shape
    seen = np.zeros((height, width), dtype=bool)
    boxes = []
    ys, xs = np.where(mask)
    for y, x in zip(ys.tolist(), xs.tolist()):
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
                if ny < 0 or nx < 0 or ny >= height or nx >= width:
                    continue
                if seen[ny, nx] or not mask[ny, nx]:
                    continue
                seen[ny, nx] = True
                stack.append((ny, nx))
        if area >= min_area and (maxx - minx + 1) >= min_w and (maxy - miny + 1) >= min_h:
            boxes.append((minx, miny, maxx + 1, maxy + 1))
    boxes.sort(key=lambda box: box[0])
    return boxes
