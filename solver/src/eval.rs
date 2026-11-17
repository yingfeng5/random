//! 5/6/7-card hand evaluator.
//!
//! Higher `HandRank` wins. Ranks pack the category and kickers, so ordinary
//! integer comparison is the poker comparison. No lookup tables: every
//! category is detected from rank counts and suit masks, and tests cover the
//! category order, wheels, and 7-card "best five" cases.

use crate::card::Card;

/// Higher is better. Category lives in the top bits, then five kickers.
#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Debug, Hash)]
pub struct HandRank(pub u32);

pub const HIGH_CARD: u32 = 0;
pub const PAIR: u32 = 1;
pub const TWO_PAIR: u32 = 2;
pub const TRIPS: u32 = 3;
pub const STRAIGHT: u32 = 4;
pub const FLUSH: u32 = 5;
pub const FULL_HOUSE: u32 = 6;
pub const QUADS: u32 = 7;
pub const STRAIGHT_FLUSH: u32 = 8;

impl HandRank {
    pub fn category(self) -> u32 {
        self.0 >> 20
    }
}

fn pack(cat: u32, k: [u32; 5]) -> HandRank {
    let mut v = cat << 20;
    for (i, kick) in k.iter().enumerate() {
        v |= kick << (16 - 4 * i);
    }
    HandRank(v)
}

/// High card of the best straight in `mask`, or `None`.
/// Wheel (A-2-3-4-5) returns the five's rank (3), so it loses to six-high.
fn straight_high(mask: u16) -> Option<u32> {
    for high in (4..13).rev() {
        let bits = 0b1_1111u16 << (high - 4);
        if mask & bits == bits {
            return Some(high as u32);
        }
    }
    // A,2,3,4,5 = bit 12 and bits 0..3.
    const WHEEL: u16 = 0b1_0000_0000_1111;
    if mask & WHEEL == WHEEL {
        Some(3)
    } else {
        None
    }
}

fn top_bits(mask: u16, n: usize) -> [u32; 5] {
    let mut out = [0u32; 5];
    let mut found = 0;
    for r in (0..13).rev() {
        if mask & (1u16 << r) != 0 {
            out[found] = r as u32;
            found += 1;
            if found == n {
                break;
            }
        }
    }
    out
}

/// Best 5-card rank inside a 5, 6, or 7 card set.
pub fn evaluate(cards: &[Card]) -> HandRank {
    assert!(
        (5..=7).contains(&cards.len()),
        "evaluator takes 5 to 7 cards, got {}",
        cards.len()
    );
    let mut rank_count = [0u8; 13];
    let mut suit_count = [0u8; 4];
    let mut suit_mask = [0u16; 4];
    let mut rank_mask = 0u16;
    for card in cards {
        let r = card.rank() as usize;
        let s = card.suit() as usize;
        rank_count[r] += 1;
        suit_count[s] += 1;
        suit_mask[s] |= 1u16 << r;
        rank_mask |= 1u16 << r;
    }

    let flush_mask = (0..4).find(|&s| suit_count[s] >= 5).map(|s| suit_mask[s]);
    if let Some(mask) = flush_mask {
        if let Some(high) = straight_high(mask) {
            return pack(STRAIGHT_FLUSH, [high, 0, 0, 0, 0]);
        }
    }

    let mut quads: Option<u32> = None;
    let mut trips: Vec<u32> = Vec::new();
    let mut pairs: Vec<u32> = Vec::new();
    let mut singles: Vec<u32> = Vec::new();
    for r in (0..13).rev() {
        match rank_count[r] {
            4 => quads = Some(r as u32),
            3 => trips.push(r as u32),
            2 => pairs.push(r as u32),
            1 => singles.push(r as u32),
            _ => {}
        }
    }

    if let Some(q) = quads {
        let kicker = trips
            .first()
            .copied()
            .or_else(|| pairs.first().copied())
            .or_else(|| singles.first().copied())
            .unwrap_or(0);
        return pack(QUADS, [q, kicker, 0, 0, 0]);
    }

    if !trips.is_empty() && (trips.len() >= 2 || !pairs.is_empty()) {
        let trip = trips[0];
        let pair = if trips.len() >= 2 { trips[1] } else { pairs[0] };
        return pack(FULL_HOUSE, [trip, pair, 0, 0, 0]);
    }

    if let Some(mask) = flush_mask {
        return pack(FLUSH, top_bits(mask, 5));
    }

    if let Some(high) = straight_high(rank_mask) {
        return pack(STRAIGHT, [high, 0, 0, 0, 0]);
    }

    if let Some(&trip) = trips.first() {
        let k1 = singles.first().copied().unwrap_or(0);
        let k2 = singles.get(1).copied().unwrap_or(0);
        return pack(TRIPS, [trip, k1, k2, 0, 0]);
    }

    if pairs.len() >= 2 {
        // Three pairs in seven cards: the kicker is the higher of the third
        // pair-rank and any singleton.
        let mut kickers = singles.clone();
        if pairs.len() > 2 {
            kickers.push(pairs[2]);
        }
        kickers.sort_unstable_by(|a, b| b.cmp(a));
        let k = kickers.first().copied().unwrap_or(0);
        return pack(TWO_PAIR, [pairs[0], pairs[1], k, 0, 0]);
    }

    if let Some(&pair) = pairs.first() {
        return pack(
            PAIR,
            [
                pair,
                singles.first().copied().unwrap_or(0),
                singles.get(1).copied().unwrap_or(0),
                singles.get(2).copied().unwrap_or(0),
                0,
            ],
        );
    }

    pack(
        HIGH_CARD,
        [
            singles.first().copied().unwrap_or(0),
            singles.get(1).copied().unwrap_or(0),
            singles.get(2).copied().unwrap_or(0),
            singles.get(3).copied().unwrap_or(0),
            singles.get(4).copied().unwrap_or(0),
        ],
    )
}

pub fn evaluate_named(cards: &[&str]) -> HandRank {
    let parsed: Vec<Card> = cards.iter().map(|c| Card::parse(c).unwrap()).collect();
    evaluate(&parsed)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cat(cards: &[&str]) -> u32 {
        evaluate_named(cards).category()
    }

    #[test]
    fn category_order() {
        let royal = evaluate_named(&["Ah", "Kh", "Qh", "Jh", "Th"]);
        let quads = evaluate_named(&["As", "Ad", "Ac", "Ah", "Kd"]);
        let boat = evaluate_named(&["As", "Ad", "Ac", "Kd", "Kh"]);
        let flush = evaluate_named(&["Ah", "Qh", "9h", "5h", "2h"]);
        let straight = evaluate_named(&["9c", "8d", "7h", "6s", "5c"]);
        let trips = evaluate_named(&["Qs", "Qd", "Qc", "9h", "2c"]);
        let two = evaluate_named(&["Js", "Jd", "8c", "8h", "3d"]);
        let pair = evaluate_named(&["Ts", "Td", "9c", "6h", "2d"]);
        let high = evaluate_named(&["As", "Qd", "9c", "6h", "2d"]);
        let ranks = [royal, quads, boat, flush, straight, trips, two, pair, high];
        for w in ranks.windows(2) {
            assert!(w[0] > w[1], "{:?} should beat {:?}", w[0], w[1]);
        }
        assert_eq!(royal.category(), STRAIGHT_FLUSH);
        assert_eq!(cat(&["As", "Ks", "Qs", "Js", "Ts"]), STRAIGHT_FLUSH);
    }

    #[test]
    fn wheel_is_the_lowest_straight_and_steel_wheel_counts() {
        let wheel = evaluate_named(&["Ac", "2d", "3h", "4s", "5c"]);
        let six = evaluate_named(&["2c", "3d", "4h", "5s", "6c"]);
        assert_eq!(wheel.category(), STRAIGHT);
        assert!(six > wheel);
        let steel = evaluate_named(&["Ah", "2h", "3h", "4h", "5h"]);
        assert_eq!(steel.category(), STRAIGHT_FLUSH);
        let six_flush = evaluate_named(&["2h", "3h", "4h", "5h", "6h"]);
        assert!(six_flush > steel);
        // Ace-high hearts that merely contain a wheel of mixed suits are a flush, not a straight flush.
        let flush = evaluate_named(&["Ah", "Kh", "3h", "4h", "5h", "2c", "9d"]);
        assert_eq!(flush.category(), FLUSH);
    }

    #[test]
    fn kickers_and_full_house_order() {
        let ak = evaluate_named(&["As", "Kd", "Qc", "Jh", "9d"]);
        let aq = evaluate_named(&["As", "Qd", "Jc", "9h", "8d"]);
        assert!(ak > aq);
        let aces_kings = evaluate_named(&["As", "Ad", "Ac", "Kh", "Kd"]);
        let aces_queens = evaluate_named(&["As", "Ad", "Ac", "Qh", "Qd"]);
        let kings_aces = evaluate_named(&["Ks", "Kd", "Kc", "Ah", "Ad"]);
        assert!(aces_kings > aces_queens);
        assert!(aces_queens > kings_aces);
        let aqj = evaluate_named(&["As", "Ad", "Kc", "Qh", "Jd"]);
        let aqt = evaluate_named(&["As", "Ad", "Kc", "Qh", "Td"]);
        assert!(aqj > aqt);
    }

    #[test]
    fn seven_cards_use_the_best_five() {
        // Three pairs: kings, nines, fours, and a deuce. The kicker is the third
        // pair's rank (a four), which beats kings and nines with a three kicker.
        let three_pair = evaluate_named(&["Ks", "Kd", "9c", "9h", "4s", "4d", "2c"]);
        let lower_pair = evaluate_named(&["Ks", "Kd", "9c", "9h", "3s", "3d", "2c"]);
        let singleton_four = evaluate_named(&["Ks", "Kd", "9c", "9h", "4s", "3d", "2c"]);
        assert_eq!(three_pair.category(), TWO_PAIR);
        assert_eq!(three_pair, singleton_four);
        assert!(three_pair > lower_pair);

        // Quads on board, ace kicker beats king kicker.
        let ace = evaluate_named(&["9s", "9d", "9c", "9h", "2s", "3d", "Ah"]);
        let king = evaluate_named(&["9s", "9d", "9c", "9h", "2s", "3d", "Kh"]);
        assert_eq!(ace.category(), QUADS);
        assert!(ace > king);

        // Board straight plays; both players tie.
        let a = evaluate_named(&["Ks", "Kd", "9c", "8d", "7h", "6s", "5c"]);
        let b = evaluate_named(&["As", "Qd", "9c", "8d", "7h", "6s", "5c"]);
        assert_eq!(a, b);
        assert_eq!(a.category(), STRAIGHT);

        // Flush uses five hearts, not a higher non-heart card.
        let flush = evaluate_named(&["Ah", "7h", "4h", "3h", "2h", "Kd", "Qs"]);
        assert_eq!(flush.category(), FLUSH);
        let better = evaluate_named(&["Ah", "Kh", "4h", "3h", "2h", "9d", "8s"]);
        assert!(better > flush);
    }

    #[test]
    fn identical_hands_tie() {
        let a = evaluate_named(&["As", "Kd", "Qc", "Jh", "9d"]);
        let b = evaluate_named(&["Ad", "Kc", "Qh", "Js", "9c"]);
        assert_eq!(a, b);
    }
}
