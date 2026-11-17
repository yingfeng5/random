//! Range text used by the postflop form.
//!
//! Accepted tokens, separated by commas or whitespace:
//! `AhKd`, `AhKd:0.5`, `AA`, `AKs`, `AKo`, `TT+`, `77-99`, `ATs+`, `A5s-A2s`.
//! A weight on a class is applied to every combo of that class. Combos that
//! use a board card are dropped.

use crate::card::{class_id, class_label, combos_by_class, Card, Combo, N_CLASSES};

#[derive(Clone, Debug)]
pub struct WeightedCombo {
    pub combo: Combo,
    pub weight: f64,
}

pub fn parse_range(text: &str, board: &[Card]) -> Result<Vec<WeightedCombo>, String> {
    let mut acc = vec![0.0f64; 1326];
    let combos = crate::card::all_combos();
    // Direct index: lo*52+hi. 52*52 is tiny and avoids a search per combo.
    let mut direct = vec![usize::MAX; 52 * 52];
    for (i, combo) in combos.iter().enumerate() {
        direct[combo.lo.index() * 52 + combo.hi.index()] = i;
    }
    let by_class = combos_by_class();

    if text.trim().is_empty() {
        return Err("range is empty".into());
    }
    for raw in text.split(|c: char| c == ',' || c.is_whitespace()) {
        let tok = raw.trim();
        if tok.is_empty() {
            continue;
        }
        let (body, weight) = split_weight(tok)?;
        apply_token(body, weight, &by_class, &direct, &mut acc)?;
    }

    let mut out = Vec::new();
    for (i, combo) in combos.iter().enumerate() {
        if acc[i] <= 0.0 {
            continue;
        }
        if board.iter().any(|c| combo.conflicts_card(*c)) {
            continue;
        }
        out.push(WeightedCombo {
            combo: *combo,
            weight: acc[i],
        });
    }
    if out.is_empty() {
        return Err("range has no combos left after removing board cards".into());
    }
    Ok(out)
}

fn split_weight(tok: &str) -> Result<(&str, f64), String> {
    if let Some((body, w)) = tok.split_once(':') {
        let weight: f64 = w.parse().map_err(|_| format!("bad weight in '{tok}'"))?;
        if !(weight > 0.0) || !weight.is_finite() {
            return Err(format!("weight in '{tok}' must be positive"));
        }
        Ok((body, weight))
    } else {
        Ok((tok, 1.0))
    }
}

fn apply_token(
    body: &str,
    weight: f64,
    by_class: &[Vec<Combo>],
    direct: &[usize],
    acc: &mut [f64],
) -> Result<(), String> {
    let upper = body.to_ascii_uppercase();
    if let Some(combo) = parse_combo_token(body) {
        let idx = direct[combo.lo.index() * 52 + combo.hi.index()];
        acc[idx] += weight;
        return Ok(());
    }
    if let Some((a, b)) = upper.split_once('-') {
        let ids = expand_span(a, b)?;
        for id in ids {
            add_class(id, weight, by_class, direct, acc);
        }
        return Ok(());
    }
    if let Some(prefix) = upper.strip_suffix('+') {
        let ids = expand_plus(prefix)?;
        for id in ids {
            add_class(id, weight, by_class, direct, acc);
        }
        return Ok(());
    }
    if let Some(id) = parse_class_token(&upper) {
        add_class(id, weight, by_class, direct, acc);
        return Ok(());
    }
    Err(format!("cannot parse range token '{body}'"))
}

fn add_class(id: usize, weight: f64, by_class: &[Vec<Combo>], direct: &[usize], acc: &mut [f64]) {
    for combo in &by_class[id] {
        let idx = direct[combo.lo.index() * 52 + combo.hi.index()];
        acc[idx] += weight;
    }
}

fn parse_combo_token(body: &str) -> Option<Combo> {
    if body.len() != 4 {
        return None;
    }
    let a = Card::parse(&body[0..2])?;
    let b = Card::parse(&body[2..4])?;
    Combo::new(a, b)
}

fn parse_class_token(upper: &str) -> Option<usize> {
    let chars: Vec<char> = upper.chars().collect();
    if chars.len() == 2 && chars[0] == chars[1] {
        let r = rank_char(chars[0])?;
        return Some(class_id(r, r, false));
    }
    if chars.len() == 3 {
        let r1 = rank_char(chars[0])?;
        let r2 = rank_char(chars[1])?;
        if r1 == r2 {
            return None;
        }
        let suited = match chars[2] {
            'S' => true,
            'O' => false,
            _ => return None,
        };
        return Some(class_id(r1, r2, suited));
    }
    None
}

fn rank_char(c: char) -> Option<u8> {
    b"23456789TJQKA"
        .iter()
        .position(|&r| r == c as u8)
        .map(|i| i as u8)
}

fn expand_plus(prefix: &str) -> Result<Vec<usize>, String> {
    let chars: Vec<char> = prefix.chars().collect();
    if chars.len() == 2 && chars[0] == chars[1] {
        let r = rank_char(chars[0]).ok_or_else(|| format!("bad pair '{prefix}+'"))?;
        return Ok((r..13).map(|rank| class_id(rank, rank, false)).collect());
    }
    if chars.len() == 3 {
        let hi = rank_char(chars[0]).ok_or_else(|| format!("bad class '{prefix}+'"))?;
        let lo = rank_char(chars[1]).ok_or_else(|| format!("bad class '{prefix}+'"))?;
        if hi == lo {
            return Err(format!("'{prefix}+' is not a pair plus"));
        }
        let suited = match chars[2] {
            'S' => true,
            'O' => false,
            _ => return Err(format!("bad class '{prefix}+'")),
        };
        let (hi, lo) = if hi > lo { (hi, lo) } else { (lo, hi) };
        let mut ids = Vec::new();
        // ATs+ means suited aces from the given kicker up to the ace.
        for k in lo..hi {
            ids.push(class_id(hi, k, suited));
        }
        Ok(ids)
    } else {
        Err(format!("bad plus-range '{prefix}+'"))
    }
}

fn expand_span(a: &str, b: &str) -> Result<Vec<usize>, String> {
    let id_a = parse_class_token(a).ok_or_else(|| format!("bad span endpoint '{a}'"))?;
    let id_b = parse_class_token(b).ok_or_else(|| format!("bad span endpoint '{b}'"))?;
    let la = class_label(id_a);
    let lb = class_label(id_b);
    let (ra, rb) = (la.chars().next().unwrap(), lb.chars().next().unwrap());
    let (ka, kb) = (la.chars().nth(1).unwrap(), lb.chars().nth(1).unwrap());
    if la.ends_with('s') || la.ends_with('o') || lb.ends_with('s') || lb.ends_with('o') {
        if la.chars().last() != lb.chars().last() || ra != rb {
            return Err(format!(
                "span '{a}-{b}' must share a high card and suitedness"
            ));
        }
        let suited = la.ends_with('s');
        let hi = rank_char(ra).unwrap();
        let lo_a = rank_char(ka).unwrap();
        let lo_b = rank_char(kb).unwrap();
        let (start, end) = if lo_a < lo_b {
            (lo_a, lo_b)
        } else {
            (lo_b, lo_a)
        };
        return Ok((start..=end).map(|lo| class_id(hi, lo, suited)).collect());
    }
    // Pair span: 99-77 or 77-99.
    if ra == ka && rb == kb {
        let r1 = rank_char(ra).unwrap();
        let r2 = rank_char(rb).unwrap();
        let (start, end) = if r1 < r2 { (r1, r2) } else { (r2, r1) };
        return Ok((start..=end).map(|r| class_id(r, r, false)).collect());
    }
    Err(format!("cannot parse span '{a}-{b}'"))
}

/// Normalize weights into a reach distribution that sums to 1.
pub fn reaches(combos: &[WeightedCombo]) -> Vec<f64> {
    let sum: f64 = combos.iter().map(|c| c.weight).sum();
    if sum <= 0.0 {
        return vec![0.0; combos.len()];
    }
    combos.iter().map(|c| c.weight / sum).collect()
}

pub fn class_names() -> Vec<String> {
    (0..N_CLASSES).map(class_label).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_classes_pluses_and_exact_combos() {
        let board = [
            Card::parse("Ah").unwrap(),
            Card::parse("7d").unwrap(),
            Card::parse("2c").unwrap(),
        ];
        let range = parse_range("AA, AKs, A5s+, TT+, 77-99, KdQh:2", &board).unwrap();
        let labels: Vec<_> = range.iter().map(|c| c.combo.label()).collect();
        // AhAx combos are blocked by the ace of hearts on board. AdAc remains.
        assert!(labels
            .iter()
            .any(|l| l.contains('A') && l.matches('A').count() == 2));
        assert!(!range.iter().any(|c| c.combo.conflicts_card(board[0])));
        // A5s+ is A5s,A6s,A7s,A8s,A9s,ATs,AJs,AQs,AKs — AKs also listed, weight stacks.
        let aks = range
            .iter()
            .find(|c| c.combo.class_id() == class_id(12, 11, true));
        assert!(aks.unwrap().weight >= 2.0);
        // KdQh has weight 2.
        assert!(range
            .iter()
            .any(|c| c.combo.label() == "KdQh" && (c.weight - 2.0).abs() < 1e-9));
        // TT+ includes JJ+QQ+KK+AA but AA partly blocked. TT itself is present.
        assert!(range
            .iter()
            .any(|c| c.combo.class_id() == class_id(8, 8, false)));
        let _ = labels;
    }
}
