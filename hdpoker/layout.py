"""Fractions of the 6-max HD Poker window, measured on the sample screenshots.

The samples are about 2210 by 1230, including the window title bar. A different
skin or a 9-max table needs new boxes. Seat 0 is the hero on the left; indexes
then run clockwise: upper-left, top, upper-right, right, bottom.
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


TABLE = Rect(0.07, 0.118, 0.20, 0.045)
BLINDS = Rect(0.08, 0.142, 0.12, 0.038)
HEADER_CARDS = Rect(0.455, 0.025, 0.12, 0.095)
POT = Rect(0.518, 0.638, 0.072, 0.062)
CHAT = Rect(0.008, 0.825, 0.26, 0.145)
BANNER = Rect(0.38, 0.445, 0.26, 0.08)
BUTTONS = Rect(0.70, 0.78, 0.29, 0.21)
FELT = Rect(0.28, 0.48, 0.46, 0.32)

# Five community-card slots. Empty felt scores near zero; a card scores higher.
BOARD_SLOTS = (
    Rect(0.412, 0.560, 0.038, 0.090),
    Rect(0.447, 0.560, 0.038, 0.090),
    Rect(0.482, 0.560, 0.038, 0.090),
    Rect(0.517, 0.560, 0.038, 0.090),
    Rect(0.552, 0.560, 0.038, 0.090),
)

SEATS = (
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
)


def hero_seat() -> SeatLayout:
    for seat in SEATS:
        if seat.hero:
            return seat
    return SEATS[0]
