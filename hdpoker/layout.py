"""Fractions of a 6-max HD Poker window.

Two skins are calibrated. The beach samples are about 2210 by 1230 (aspect
about 1.80) with the hero on the left. The airplane-cabin window is about
2560 by 1600 (aspect about 1.60) with the hero at bottom center. Boxes are
fractions of whatever window is captured. ``layout_for`` picks the skin from
the aspect ratio. The module-level rects stay the wide beach layout so the
sample templates keep cropping the same pixels.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    def crop(self, image):
        width, height = image.size
        left = max(0, int(self.x * width))
        top = max(0, int(self.y * height))
        right = min(width, int((self.x + self.w) * width))
        bottom = min(height, int((self.y + self.h) * height))
        if right <= left or bottom <= top:
            return image.crop((0, 0, 1, 1))
        return image.crop((left, top, right, bottom))

    def center(self) -> tuple[float, float]:
        return (self.x + self.w / 2, self.y + self.h / 2)

    def contains(self, x: float, y: float) -> bool:
        return self.x <= x <= self.x + self.w and self.y <= y <= self.y + self.h


@dataclass(frozen=True)
class SeatLayout:
    index: int
    hero: bool
    plate: Rect
    status: Rect
    cards: Rect
    shown: Rect
    bet_anchor: tuple[float, float]
    button: Rect


@dataclass(frozen=True)
class Layout:
    name: str
    table: Rect
    blinds: Rect
    header_cards: Rect
    pot: Rect
    chat: Rect
    banner: Rect
    buttons: Rect
    felt: Rect
    board_slots: tuple[Rect, ...]
    seats: tuple[SeatLayout, ...]

    def hero(self) -> SeatLayout:
        for seat in self.seats:
            if seat.hero:
                return seat
        return self.seats[0]


# Beach / reef samples. Seat 0 is the hero on the left, then clockwise.
WIDE = Layout(
    "wide",
    Rect(0.07, 0.118, 0.20, 0.045),
    Rect(0.08, 0.142, 0.12, 0.038),
    Rect(0.455, 0.025, 0.12, 0.095),
    Rect(0.518, 0.638, 0.072, 0.062),
    Rect(0.008, 0.825, 0.26, 0.145),
    Rect(0.38, 0.445, 0.26, 0.08),
    Rect(0.70, 0.78, 0.29, 0.21),
    Rect(0.28, 0.48, 0.46, 0.32),
    (
        Rect(0.412, 0.560, 0.038, 0.090),
        Rect(0.447, 0.560, 0.038, 0.090),
        Rect(0.482, 0.560, 0.038, 0.090),
        Rect(0.517, 0.560, 0.038, 0.090),
        Rect(0.552, 0.560, 0.038, 0.090),
    ),
    (
        SeatLayout(
            0,
            True,
            Rect(0.218, 0.355, 0.092, 0.062),
            Rect(0.216, 0.404, 0.096, 0.046),
            Rect(0.205, 0.292, 0.130, 0.075),
            Rect(0.10, 0.42, 0.18, 0.22),
            (0.36, 0.62),
            Rect(0.300, 0.360, 0.045, 0.060),
        ),
        SeatLayout(
            1,
            False,
            Rect(0.305, 0.262, 0.088, 0.070),
            Rect(0.308, 0.316, 0.084, 0.046),
            Rect(0.300, 0.300, 0.150, 0.140),
            Rect(0.300, 0.300, 0.150, 0.140),
            (0.40, 0.54),
            Rect(0.385, 0.270, 0.045, 0.060),
        ),
        SeatLayout(
            2,
            False,
            Rect(0.392, 0.232, 0.090, 0.062),
            Rect(0.392, 0.278, 0.078, 0.042),
            Rect(0.400, 0.300, 0.130, 0.130),
            Rect(0.400, 0.300, 0.130, 0.130),
            (0.48, 0.50),
            Rect(0.470, 0.240, 0.045, 0.055),
        ),
        SeatLayout(
            3,
            False,
            Rect(0.500, 0.300, 0.090, 0.070),
            Rect(0.500, 0.355, 0.090, 0.045),
            Rect(0.500, 0.340, 0.140, 0.130),
            Rect(0.500, 0.340, 0.140, 0.130),
            (0.55, 0.52),
            Rect(0.580, 0.310, 0.045, 0.055),
        ),
        SeatLayout(
            4,
            False,
            Rect(0.705, 0.350, 0.085, 0.075),
            Rect(0.708, 0.405, 0.090, 0.055),
            Rect(0.680, 0.420, 0.160, 0.180),
            Rect(0.680, 0.420, 0.160, 0.180),
            (0.64, 0.58),
            Rect(0.768, 0.368, 0.050, 0.070),
        ),
        SeatLayout(
            5,
            False,
            Rect(0.462, 0.798, 0.090, 0.062),
            Rect(0.462, 0.848, 0.090, 0.050),
            Rect(0.430, 0.630, 0.160, 0.160),
            Rect(0.430, 0.630, 0.160, 0.160),
            (0.50, 0.70),
            Rect(0.540, 0.800, 0.050, 0.060),
        ),
    ),
)

# Airplane cabin. Seat 0 is the hero at bottom center, then clockwise:
# bottom-left, left, top, right, bottom-right.
CABIN = Layout(
    "cabin",
    Rect(0.055, 0.060, 0.250, 0.030),
    Rect(0.055, 0.088, 0.160, 0.032),
    Rect(0.468, 0.000, 0.058, 0.052),
    Rect(0.455, 0.600, 0.100, 0.048),
    Rect(0.004, 0.855, 0.300, 0.130),
    Rect(0.360, 0.455, 0.280, 0.080),
    Rect(0.780, 0.880, 0.210, 0.110),
    Rect(0.280, 0.548, 0.420, 0.200),
    (
        Rect(0.418, 0.518, 0.034, 0.082),
        Rect(0.454, 0.518, 0.034, 0.082),
        Rect(0.490, 0.518, 0.034, 0.082),
        Rect(0.526, 0.518, 0.034, 0.082),
        Rect(0.562, 0.518, 0.034, 0.082),
    ),
    (
        SeatLayout(
            0,
            True,
            Rect(0.448, 0.798, 0.112, 0.072),
            Rect(0.448, 0.872, 0.112, 0.036),
            Rect(0.458, 0.692, 0.090, 0.078),
            Rect(0.458, 0.692, 0.090, 0.078),
            (0.533, 0.670),
            Rect(0.548, 0.805, 0.036, 0.046),
        ),
        SeatLayout(
            1,
            False,
            Rect(0.262, 0.768, 0.150, 0.062),
            Rect(0.275, 0.828, 0.130, 0.042),
            Rect(0.285, 0.690, 0.090, 0.075),
            Rect(0.285, 0.690, 0.090, 0.075),
            (0.383, 0.664),
            Rect(0.400, 0.775, 0.036, 0.046),
        ),
        SeatLayout(
            2,
            False,
            Rect(0.150, 0.322, 0.125, 0.062),
            Rect(0.160, 0.388, 0.105, 0.036),
            Rect(0.165, 0.255, 0.090, 0.065),
            Rect(0.165, 0.255, 0.090, 0.065),
            (0.300, 0.470),
            Rect(0.262, 0.330, 0.036, 0.046),
        ),
        SeatLayout(
            3,
            False,
            Rect(0.538, 0.198, 0.125, 0.058),
            Rect(0.548, 0.256, 0.105, 0.034),
            Rect(0.550, 0.145, 0.090, 0.055),
            Rect(0.550, 0.145, 0.090, 0.055),
            (0.500, 0.340),
            Rect(0.652, 0.205, 0.036, 0.046),
        ),
        SeatLayout(
            4,
            False,
            Rect(0.738, 0.322, 0.120, 0.068),
            Rect(0.748, 0.392, 0.100, 0.036),
            Rect(0.755, 0.255, 0.090, 0.065),
            Rect(0.755, 0.255, 0.090, 0.065),
            (0.680, 0.480),
            Rect(0.808, 0.350, 0.036, 0.042),
        ),
        SeatLayout(
            5,
            False,
            Rect(0.618, 0.762, 0.130, 0.078),
            Rect(0.630, 0.842, 0.105, 0.036),
            Rect(0.640, 0.690, 0.085, 0.070),
            Rect(0.640, 0.690, 0.085, 0.070),
            (0.612, 0.666),
            Rect(0.740, 0.770, 0.036, 0.046),
        ),
    ),
)

# Names kept for the beach templates and any caller that still imports them.
TABLE = WIDE.table
BLINDS = WIDE.blinds
HEADER_CARDS = WIDE.header_cards
POT = WIDE.pot
CHAT = WIDE.chat
BANNER = WIDE.banner
BUTTONS = WIDE.buttons
FELT = WIDE.felt
BOARD_SLOTS = WIDE.board_slots
SEATS = WIDE.seats


def layout_for(image) -> Layout:
    """Pick the calibrated skin from the window's aspect ratio.

    Wide beach samples are about 1.80. The cabin window is about 1.60.
    A window at least 1.70 wide uses the beach boxes.
    """
    _width, height = image.size
    if not height:
        return WIDE
    if (_width / height) >= 1.70:
        return WIDE
    return CABIN


def hero_seat() -> SeatLayout:
    return WIDE.hero()
