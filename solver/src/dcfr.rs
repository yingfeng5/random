//! Discounted Counterfactual Regret Minimization.
//!
//! Regret tables are indexed by concrete combo (postflop) or by canonical
//! class (preflop). Nothing in here groups hands into equity buckets.
//!
//! Parameters are the standard DCFR triple from Brown & Sandholm (2019):
//! α = 1.5, β = 0, γ = 2. On iteration `t` (1-based) accumulated positive
//! regrets are multiplied by `t^α / (t^α + 1)`, negative regrets by
//! `t^β / (t^β + 1)` which is 1/2 when β = 0, and the average-strategy
//! accumulator is multiplied by `(t / (t + 1))^γ` before this iteration's
//! strategy is added at weight 1.

#[derive(Clone, Debug)]
pub struct Infoset {
    n_actions: usize,
    n_hands: usize,
    pub action_labels: Vec<String>,
    regrets: Vec<f64>,
    strat_sum: Vec<f64>,
}

impl Infoset {
    pub fn new(n_hands: usize, action_labels: Vec<String>) -> Self {
        let n_actions = action_labels.len();
        Self {
            n_actions,
            n_hands,
            action_labels,
            regrets: vec![0.0; n_hands * n_actions],
            strat_sum: vec![0.0; n_hands * n_actions],
        }
    }

    pub fn n_actions(&self) -> usize {
        self.n_actions
    }

    pub fn n_hands(&self) -> usize {
        self.n_hands
    }

    fn idx(&self, hand: usize, action: usize) -> usize {
        hand * self.n_actions + action
    }

    pub fn current(&self, hand: usize) -> Vec<f64> {
        regret_match(&self.regrets[self.idx(hand, 0)..self.idx(hand, 0) + self.n_actions])
    }

    pub fn average(&self, hand: usize) -> Vec<f64> {
        let slice = &self.strat_sum[self.idx(hand, 0)..self.idx(hand, 0) + self.n_actions];
        let sum: f64 = slice.iter().map(|v| v.max(0.0)).sum();
        if sum <= 1e-12 {
            return vec![1.0 / self.n_actions as f64; self.n_actions];
        }
        slice.iter().map(|v| v.max(0.0) / sum).collect()
    }

    pub fn add_regret(&mut self, hand: usize, action: usize, amount: f64) {
        let i = hand * self.n_actions + action;
        self.regrets[i] += amount;
    }

    pub fn add_strategy(&mut self, hand: usize, action: usize, amount: f64) {
        let i = hand * self.n_actions + action;
        self.strat_sum[i] += amount;
    }

    pub fn discount(&mut self, pos: f64, neg: f64, strat: f64) {
        for r in &mut self.regrets {
            if *r > 0.0 {
                *r *= pos;
            } else if *r < 0.0 {
                *r *= neg;
            }
        }
        for s in &mut self.strat_sum {
            *s *= strat;
        }
    }
}

pub fn regret_match(regrets: &[f64]) -> Vec<f64> {
    let n = regrets.len();
    let mut pos = vec![0.0; n];
    let mut sum = 0.0;
    for (a, r) in regrets.iter().enumerate() {
        let v = r.max(0.0);
        pos[a] = v;
        sum += v;
    }
    if sum <= 1e-12 {
        return vec![1.0 / n as f64; n];
    }
    for v in &mut pos {
        *v /= sum;
    }
    pos
}

/// Positive-regret discount, negative-regret discount, average-strategy discount.
pub fn dcfr_discounts(iteration: u32) -> (f64, f64, f64) {
    let t = iteration.max(1) as f64;
    let pos = t.powf(1.5) / (t.powf(1.5) + 1.0);
    let neg = t.powf(0.0) / (t.powf(0.0) + 1.0);
    let strat = (t / (t + 1.0)).powf(2.0);
    (pos, neg, strat)
}

/// Tiny deterministic generator for chance sampling. Not used on the river,
/// where there is no undealt card.
#[derive(Clone, Debug)]
pub struct Rng(u64);

impl Rng {
    pub fn new(seed: u64) -> Self {
        Self(seed | 1)
    }

    pub fn next_u64(&mut self) -> u64 {
        let mut x = self.0;
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        self.0 = x;
        x
    }

    pub fn index(&mut self, n: usize) -> usize {
        debug_assert!(n > 0);
        (self.next_u64() as usize) % n
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn regret_matching_and_discount_signs() {
        let s = regret_match(&[2.0, -1.0, 2.0]);
        assert!((s[0] - 0.5).abs() < 1e-9);
        assert!(s[1].abs() < 1e-9);
        assert!((s[2] - 0.5).abs() < 1e-9);
        let (pos, neg, strat) = dcfr_discounts(1);
        assert!((neg - 0.5).abs() < 1e-12);
        assert!(pos < 1.0 && pos > 0.0);
        assert!((strat - 0.25).abs() < 1e-12);
        let mut info = Infoset::new(1, vec!["a".into(), "b".into()]);
        info.add_regret(0, 0, 4.0);
        info.add_regret(0, 1, -4.0);
        info.add_strategy(0, 0, 10.0);
        let (pos, neg, strat) = dcfr_discounts(4);
        info.discount(pos, neg, strat);
        assert!((info.regrets[0] - 4.0 * pos).abs() < 1e-9);
        assert!((info.regrets[1] - -4.0 * neg).abs() < 1e-9);
        assert!((info.strat_sum[0] - 10.0 * strat).abs() < 1e-9);
    }
}
