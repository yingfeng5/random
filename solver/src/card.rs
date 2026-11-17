//! Cards, combos, and the 169 canonical preflop hand classes.
//!
//! A class (AA, AKs, AKo, …) is the suit-isomorphism used for the preflop
//! library. Postflop play never groups combos into classes or buckets.

use serde::{Deserialize, Serialize};
use std::fmt;

/// 0..51. Rank is `index / 4` (0 = deuce … 12 = ace). Suit is `index % 4`.
#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Debug, Serialize, Deserialize)]
pub struct Card(pub u8);

pub const RANK_CHARS: &[u8] = b"23456789TJQKA";
pub const SUIT_CHARS: &[u8] = b"cdhs";

impl Card {
    pub fn new(rank: u8, suit: u8) -> Self {
        debug_assert!(rank < 13 && suit < 4);
        Card(rank * 4 + suit)
    }

    pub fn rank(self) -> u8 {
        self.0 / 4
    }

    pub fn suit(self) -> u8 {
        self.0 % 4
    }

    pub fn index(self) -> usize {
        self.0 as usize
    }

    pub fn parse(text: &str) -> Option<Self> {
        let b = text.as_bytes();
        if b.len() != 2 {
            return None;
        }
        let rank = RANK_CHARS
            .iter()
            .position(|&c| c == b[0] || c == b[0].to_ascii_uppercase())?;
        let suit = SUIT_CHARS
            .iter()
            .position(|&c| c == b[1] || c == b[1].to_ascii_lowercase())?;
        Some(Card::new(rank as u8, suit as u8))
    }
}

impl fmt::Display for Card {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "{}{}",
            RANK_CHARS[self.rank() as usize] as char,
            SUIT_CHARS[self.suit() as usize] as char
        )
    }
}

/// Two hole cards, stored with the lower card index first.
#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Debug)]
pub struct Combo {
    pub lo: Card,
    pub hi: Card,
}

impl Combo {
    pub fn new(a: Card, b: Card) -> Option<Self> {
        if a == b {
            return None;
        }
        if a.0 < b.0 {
            Some(Combo { lo: a, hi: b })
        } else {
            Some(Combo { lo: b, hi: a })
        }
    }

    pub fn cards(self) -> [Card; 2] {
        [self.lo, self.hi]
    }

    pub fn conflicts_card(self, card: Card) -> bool {
        self.lo == card || self.hi == card
    }

    pub fn conflicts_combo(self, other: Combo) -> bool {
        self.lo == other.lo || self.lo == other.hi || self.hi == other.lo || self.hi == other.hi
    }

    pub fn suited(self) -> bool {
        self.lo.suit() == self.hi.suit()
    }

    pub fn class_id(self) -> usize {
        class_id(self.lo.rank(), self.hi.rank(), self.suited())
    }

    /// "AhKd"
    pub fn label(self) -> String {
        let a = self.hi;
        let b = self.lo;
        // Show the higher rank first; suits follow the card.
        if a.rank() != b.rank() {
            format!("{a}{b}")
        } else if a.suit() > b.suit() {
            format!("{a}{b}")
        } else {
            format!("{b}{a}")
        }
    }
}

impl fmt::Display for Combo {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.label())
    }
}

pub const N_CLASSES: usize = 169;
pub const N_COMBOS: usize = 1326;

/// Pairs use 0..13 (deuce pair = 0 … aces = 12).
/// Suited unmatched pairs use 13..91, offsuit 91..169, in (hi, lo) order
/// with hi running 1..12 and lo running 0..hi.
pub fn class_id(r1: u8, r2: u8, suited: bool) -> usize {
    if r1 == r2 {
        return r1 as usize;
    }
    let (hi, lo) = if r1 > r2 { (r1, r2) } else { (r2, r1) };
    let mut k = 0usize;
    for hi2 in 1..13u8 {
        for lo2 in 0..hi2 {
            if hi2 == hi && lo2 == lo {
                return if suited { 13 + k } else { 13 + 78 + k };
            }
            k += 1;
        }
    }
    unreachable!("rank pair out of range");
}

pub fn class_label(id: usize) -> String {
    if id < 13 {
        let c = RANK_CHARS[id] as char;
        return format!("{c}{c}");
    }
    let suited = id < 13 + 78;
    let mut k = if suited { id - 13 } else { id - 13 - 78 };
    for hi in 1..13u8 {
        for lo in 0..hi {
            if k == 0 {
                let a = RANK_CHARS[hi as usize] as char;
                let b = RANK_CHARS[lo as usize] as char;
                return if suited {
                    format!("{a}{b}s")
                } else {
                    format!("{a}{b}o")
                };
            }
            k -= 1;
        }
    }
    unreachable!("class id {id}");
}

pub fn class_combo_count(id: usize) -> usize {
    if id < 13 {
        6
    } else if id < 13 + 78 {
        4
    } else {
        12
    }
}

/// Every combo, indexed 0..1326, lower card index first.
pub fn all_combos() -> Vec<Combo> {
    let mut out = Vec::with_capacity(N_COMBOS);
    for i in 0..52u8 {
        for j in (i + 1)..52u8 {
            out.push(Combo {
                lo: Card(i),
                hi: Card(j),
            });
        }
    }
    debug_assert_eq!(out.len(), N_COMBOS);
    out
}

pub fn combos_by_class() -> Vec<Vec<Combo>> {
    let mut out = vec![Vec::new(); N_CLASSES];
    for combo in all_combos() {
        out[combo.class_id()].push(combo);
    }
    out
}

pub fn parse_board(text: &str) -> Result<Vec<Card>, String> {
    let trimmed = text.trim();
    if trimmed.is_empty() {
        return Ok(Vec::new());
    }
    let mut raw = Vec::new();
    if trimmed.contains(|c: char| c == ',' || c == ' ' || c == '/') {
        for tok in trimmed.split(|c: char| c == ',' || c.is_whitespace() || c == '/') {
            if tok.is_empty() {
                continue;
            }
            raw.push(tok.to_string());
        }
    } else if trimmed.len() % 2 == 0 {
        let b = trimmed.as_bytes();
        let mut i = 0;
        while i < b.len() {
            raw.push(std::str::from_utf8(&b[i..i + 2]).unwrap().to_string());
            i += 2;
        }
    } else {
        return Err(format!("cannot parse board '{text}'"));
    }
    let mut cards = Vec::new();
    for tok in raw {
        let card = Card::parse(&tok).ok_or_else(|| format!("bad card '{tok}'"))?;
        if cards.contains(&card) {
            return Err(format!("duplicate card {card}"));
        }
        cards.push(card);
    }
    if !matches!(cards.len(), 0 | 3 | 4 | 5) {
        return Err("board must be empty, a flop (3), a turn (4), or a river (5)".into());
    }
    Ok(cards)
}

pub fn deck_without(dead: &[Card]) -> Vec<Card> {
    let mut dead_set = [false; 52];
    for c in dead {
        dead_set[c.index()] = true;
    }
    (0..52u8)
        .filter(|&i| !dead_set[i as usize])
        .map(Card)
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_and_prints_cards() {
        let a = Card::parse("Ah").unwrap();
        assert_eq!(a.rank(), 12);
        assert_eq!(a.suit(), 2);
        assert_eq!(a.to_string(), "Ah");
        assert_eq!(Card::parse("Td").unwrap().rank(), 8);
        assert!(Card::parse("Ax").is_none());
    }

    #[test]
    fn one_six_nine_classes_cover_the_deck() {
        let combos = all_combos();
        assert_eq!(combos.len(), 1326);
        let grouped = combos_by_class();
        assert_eq!(grouped.len(), 169);
        let mut sum = 0;
        for (id, list) in grouped.iter().enumerate() {
            assert_eq!(list.len(), class_combo_count(id), "{}", class_label(id));
            sum += list.len();
            for combo in list {
                assert_eq!(combo.class_id(), id);
            }
        }
        assert_eq!(sum, 1326);
        assert_eq!(class_label(class_id(12, 12, false)), "AA");
        assert_eq!(class_label(class_id(12, 11, true)), "AKs");
        assert_eq!(class_label(class_id(12, 11, false)), "AKo");
        assert_eq!(class_label(class_id(0, 0, false)), "22");
        assert_eq!(class_label(class_id(8, 2, true)), "T4s");
    }

    #[test]
    fn board_parser_accepts_compact_and_spaced() {
        let b = parse_board("Kh7d2c").unwrap();
        assert_eq!(b.len(), 3);
        assert!(parse_board("Kh Kh 2c").is_err());
        assert!(parse_board("Kh7d").is_err());
        assert!(parse_board("").unwrap().is_empty());
    }
}
