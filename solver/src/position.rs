//! Eight-handed seats, blind posting, and who acts next.

use serde::{Deserialize, Serialize};
use std::fmt;

/// 100 chips = 1 big blind. The small blind is half a big blind.
pub const BB_CHIPS: i32 = 100;
pub const SB_CHIPS: i32 = 50;
pub const DEFAULT_STACK_BB: i32 = 100;

#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Debug, Serialize, Deserialize)]
pub enum Position {
    Utg = 0,
    Utg1 = 1,
    Mp = 2,
    Hj = 3,
    Co = 4,
    Btn = 5,
    Sb = 6,
    Bb = 7,
}

pub const POSITIONS: [Position; 8] = [
    Position::Utg,
    Position::Utg1,
    Position::Mp,
    Position::Hj,
    Position::Co,
    Position::Btn,
    Position::Sb,
    Position::Bb,
];

impl Position {
    pub fn index(self) -> usize {
        self as usize
    }

    pub fn parse(text: &str) -> Option<Self> {
        match text.trim().to_ascii_uppercase().as_str() {
            "UTG" => Some(Position::Utg),
            "UTG+1" | "UTG1" => Some(Position::Utg1),
            "MP" | "LJ" => Some(Position::Mp),
            "HJ" => Some(Position::Hj),
            "CO" => Some(Position::Co),
            "BTN" | "BU" | "BUTTON" => Some(Position::Btn),
            "SB" => Some(Position::Sb),
            "BB" => Some(Position::Bb),
            _ => None,
        }
    }

    /// Chips this seat posts before cards are dealt. Non-blinds post nothing.
    pub fn blind(self) -> i32 {
        match self {
            Position::Sb => SB_CHIPS,
            Position::Bb => BB_CHIPS,
            _ => 0,
        }
    }
}

impl fmt::Display for Position {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Position::Utg => "UTG",
            Position::Utg1 => "UTG+1",
            Position::Mp => "MP",
            Position::Hj => "HJ",
            Position::Co => "CO",
            Position::Btn => "BTN",
            Position::Sb => "SB",
            Position::Bb => "BB",
        })
    }
}

/// Preflop action runs from UTG to the big blind.
pub fn preflop_order() -> [Position; 8] {
    POSITIONS
}

/// Postflop action starts with the first live seat left of the button
/// (small blind when it is still in) and ends with the button.
pub fn postflop_order(live: &[Position]) -> Vec<Position> {
    let order = [
        Position::Sb,
        Position::Bb,
        Position::Utg,
        Position::Utg1,
        Position::Mp,
        Position::Hj,
        Position::Co,
        Position::Btn,
    ];
    order.into_iter().filter(|p| live.contains(p)).collect()
}

/// Starting chips behind after posting, for a `stack_bb` buy-in.
pub fn stack_behind(position: Position, stack_bb: i32) -> i32 {
    stack_bb * BB_CHIPS - position.blind()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn eight_seats_and_blind_amounts() {
        assert_eq!(POSITIONS.len(), 8);
        assert_eq!(Position::Sb.blind(), 50);
        assert_eq!(Position::Bb.blind(), 100);
        assert_eq!(Position::Utg.blind(), 0);
        assert_eq!(Position::Btn.blind(), 0);
        let posted: i32 = POSITIONS.iter().map(|p| p.blind()).sum();
        assert_eq!(posted, 150);
        assert_eq!(stack_behind(Position::Sb, 100), 9_950);
        assert_eq!(stack_behind(Position::Bb, 100), 9_900);
        assert_eq!(stack_behind(Position::Utg, 100), 10_000);
    }

    #[test]
    fn action_order() {
        let pre: Vec<_> = preflop_order().iter().map(|p| p.to_string()).collect();
        assert_eq!(pre, ["UTG", "UTG+1", "MP", "HJ", "CO", "BTN", "SB", "BB"]);
        let full = postflop_order(&POSITIONS);
        assert_eq!(full.first().copied(), Some(Position::Sb));
        assert_eq!(full.last().copied(), Some(Position::Btn));
        // Folded small blind: the big blind acts first, button still last.
        let live = [Position::Bb, Position::Btn, Position::Co];
        let order = postflop_order(&live);
        assert_eq!(order, vec![Position::Bb, Position::Co, Position::Btn]);
        assert_eq!(Position::parse("UTG+1"), Some(Position::Utg1));
        assert_eq!(Position::parse("bu"), Some(Position::Btn));
    }
}
