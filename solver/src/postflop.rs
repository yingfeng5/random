//! Postflop DCFR on concrete combos.
//!
//! Any street can be the root: a 3-card board deals the turn and the river,
//! a 4-card board deals the river, a 5-card board has no chance nodes.
//! Two or more players may still be in. Infosets are keyed by the public
//! history and store a separate strategy for every combo in the acting
//! player's range — combos are never bucketed.
//!
//! Bet sizes are a pot fraction (33%, 75%, 100% by default) plus all-in.
//! Check, call, and fold are offered whenever they are legal. A raise cap
//! limits how many bets and raises a street may contain.

use crate::card::{deck_without, Card, Combo};
use crate::dcfr::{dcfr_discounts, Infoset, Rng};
use crate::eval::evaluate;
use crate::payoff::settle;
use crate::position::{postflop_order, Position, BB_CHIPS};
use crate::range::{parse_range, WeightedCombo};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Clone, Debug)]
pub struct SpotPlayer {
    pub position: Position,
    /// Chips still behind, not counting `invested`.
    pub stack: i32,
    /// Chips already in the pot.
    pub invested: i32,
    pub combos: Vec<WeightedCombo>,
}

#[derive(Clone, Debug)]
pub struct Spot {
    pub board: Vec<Card>,
    pub players: Vec<SpotPlayer>,
}

#[derive(Clone, Debug)]
pub struct PostflopConfig {
    pub iterations: u32,
    /// Pot fractions for bets and raises. Empty means check / call / fold only.
    pub bet_fractions: Vec<f64>,
    pub include_all_in: bool,
    /// Maximum bets plus raises on one street.
    pub max_agg: u8,
    /// `None` deals every remaining card. `Some(k)` samples k cards at each
    /// chance node (unbiased public-chance estimate) so a wide flop can finish.
    pub chance_samples: Option<usize>,
    pub seed: u64,
}

impl Default for PostflopConfig {
    fn default() -> Self {
        Self {
            iterations: 200,
            bet_fractions: vec![0.33, 0.75, 1.0],
            include_all_in: true,
            max_agg: 3,
            chance_samples: None,
            seed: 1,
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ComboLine {
    pub combo: String,
    pub weight: f64,
    pub strategy: Vec<f64>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct StrategyNode {
    pub player: String,
    pub player_index: usize,
    /// Action labels that led here, not including the decision about to be made.
    pub history: Vec<String>,
    pub actions: Vec<String>,
    pub combos: Vec<ComboLine>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PlayerEv {
    pub position: String,
    pub combos: Vec<ComboEv>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ComboEv {
    pub combo: String,
    pub weight: f64,
    pub ev: f64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PostflopSolution {
    pub iterations: u32,
    pub chance: String,
    pub max_agg: u8,
    pub bet_fractions: Vec<f64>,
    pub players: Vec<PlayerEv>,
    /// Reach-weighted sum of combo EVs. A correct zero-sum solve lands on ~0.
    pub ev_weighted_sum: f64,
    /// Root decision, each player's "checked to" node, and the response to
    /// each root action.
    pub nodes: Vec<StrategyNode>,
}

#[derive(Clone, Debug)]
enum Action {
    Fold,
    Check,
    Call,
    Agg { to: i32, label: String },
}

impl Action {
    fn label(&self) -> String {
        match self {
            Action::Fold => "fold".into(),
            Action::Check => "check".into(),
            Action::Call => "call".into(),
            Action::Agg { label, .. } => label.clone(),
        }
    }

    fn code(&self) -> u32 {
        match self {
            Action::Fold => 1,
            Action::Check => 2,
            Action::Call => 3,
            Action::Agg { to, .. } => 0x1_0000 | (*to as u32),
        }
    }
}

#[derive(Clone)]
struct State {
    board: Vec<Card>,
    pot: i32,
    stacks: Vec<i32>,
    invested: Vec<i32>,
    street_put: Vec<i32>,
    folded: Vec<bool>,
    need: Vec<bool>,
    can_raise: Vec<bool>,
    acted: Vec<bool>,
    current_bet: i32,
    min_raise_inc: i32,
    agg: u8,
    history: Vec<u32>,
    history_labels: Vec<String>,
}

struct Values {
    ev: Vec<Vec<f64>>,
    den: Vec<Vec<f64>>,
}

#[derive(Hash, Eq, PartialEq, Clone)]
struct Key {
    player: u8,
    board: Vec<u8>,
    history: Vec<u32>,
}

struct Engine<'a> {
    combos: &'a [Vec<Combo>],
    fractions: &'a [f64],
    include_all_in: bool,
    max_agg: u8,
    chance_samples: Option<usize>,
    infos: HashMap<Key, Infoset>,
    train: bool,
    rng: Rng,
}

pub fn solve_postflop(spot: &Spot, cfg: &PostflopConfig) -> Result<PostflopSolution, String> {
    validate(spot, cfg)?;
    let players = order_players(&spot.players);
    let combos: Vec<Vec<Combo>> = players
        .iter()
        .map(|p| p.combos.iter().map(|c| c.combo).collect())
        .collect();
    let mut reach = Vec::new();
    for p in &players {
        let sum: f64 = p.combos.iter().map(|c| c.weight).sum();
        reach.push(p.combos.iter().map(|c| c.weight / sum).collect::<Vec<_>>());
    }
    let root = initial_state(&players, &spot.board);
    let mut engine = Engine {
        combos: &combos,
        fractions: &cfg.bet_fractions,
        include_all_in: cfg.include_all_in,
        max_agg: cfg.max_agg,
        chance_samples: cfg.chance_samples,
        infos: HashMap::new(),
        train: true,
        rng: Rng::new(cfg.seed),
    };
    let iters = cfg.iterations.max(1);
    for t in 1..=iters {
        let (pos, neg, strat) = dcfr_discounts(t);
        for info in engine.infos.values_mut() {
            info.discount(pos, neg, strat);
        }
        engine.walk(&root, &reach);
    }
    engine.train = false;
    let values = engine.walk(&root, &reach);
    Ok(package(
        cfg, &players, &combos, &reach, &values, &engine, &root,
    ))
}

fn validate(spot: &Spot, cfg: &PostflopConfig) -> Result<(), String> {
    let n = spot.players.len();
    if !(2..=8).contains(&n) {
        return Err("postflop spots need 2 to 8 players still in".into());
    }
    if !matches!(spot.board.len(), 3 | 4 | 5) {
        return Err("board must be a flop, turn, or river".into());
    }
    let mut seen = vec![false; 8];
    for p in &spot.players {
        if seen[p.position.index()] {
            return Err(format!("duplicate seat {}", p.position));
        }
        seen[p.position.index()] = true;
        if p.stack < 0 || p.invested < 0 {
            return Err("stacks and investments cannot be negative".into());
        }
        if p.combos.is_empty() {
            return Err(format!("{} has an empty range", p.position));
        }
    }
    if cfg.iterations == 0 {
        return Err("iterations must be at least 1".into());
    }
    for f in &cfg.bet_fractions {
        if !f.is_finite() || *f <= 0.0 {
            return Err("bet fractions must be positive".into());
        }
    }
    let product: u128 = spot
        .players
        .iter()
        .map(|p| p.combos.len() as u128)
        .product();
    // Flop and turn multiply this by the runout. The cap keeps a single
    // showdown enumerable; callers with wide multiway ranges must narrow them.
    if product > 4_000_000 {
        return Err(format!(
            "range product {product} is above 4,000,000 — narrow the ranges so each combo can be solved exactly"
        ));
    }
    Ok(())
}

fn order_players(players: &[SpotPlayer]) -> Vec<SpotPlayer> {
    let live: Vec<Position> = players.iter().map(|p| p.position).collect();
    postflop_order(&live)
        .into_iter()
        .map(|pos| {
            players
                .iter()
                .find(|p| p.position == pos)
                .expect("position was taken from this list")
                .clone()
        })
        .collect()
}

fn initial_state(players: &[SpotPlayer], board: &[Card]) -> State {
    let n = players.len();
    State {
        board: board.to_vec(),
        pot: players.iter().map(|p| p.invested).sum(),
        stacks: players.iter().map(|p| p.stack).collect(),
        invested: players.iter().map(|p| p.invested).collect(),
        street_put: vec![0; n],
        folded: vec![false; n],
        need: players.iter().map(|p| p.stack > 0).collect(),
        can_raise: players.iter().map(|p| p.stack > 0).collect(),
        acted: vec![false; n],
        current_bet: 0,
        min_raise_inc: BB_CHIPS,
        agg: 0,
        history: Vec::new(),
        history_labels: Vec::new(),
    }
}

fn package(
    cfg: &PostflopConfig,
    players: &[SpotPlayer],
    combos: &[Vec<Combo>],
    reach: &[Vec<f64>],
    values: &Values,
    engine: &Engine,
    root: &State,
) -> PostflopSolution {
    let mut ev_weighted_sum = 0.0;
    let mut out_players = Vec::new();
    for (p, player) in players.iter().enumerate() {
        let mut rows = Vec::new();
        for (i, combo) in combos[p].iter().enumerate() {
            let ev = values.ev[p][i];
            ev_weighted_sum += reach[p][i] * ev;
            rows.push(ComboEv {
                combo: combo.label(),
                weight: player.combos[i].weight,
                ev,
            });
        }
        out_players.push(PlayerEv {
            position: player.position.to_string(),
            combos: rows,
        });
    }
    let names: Vec<String> = players.iter().map(|p| p.position.to_string()).collect();
    let weights: Vec<Vec<f64>> = players
        .iter()
        .map(|p| p.combos.iter().map(|c| c.weight).collect())
        .collect();
    let mut nodes = Vec::new();
    collect_node(engine, root, &names, &weights, &mut nodes);
    // Checked-to nodes: each later player after a string of checks.
    let mut cursor = root.clone();
    for _ in 1..players.len() {
        let Some(actor) = next_actor(&cursor) else {
            break;
        };
        let actions = legal(&cursor, actor, engine);
        let Some(check) = actions.iter().find(|a| matches!(a, Action::Check)) else {
            break;
        };
        cursor = apply(&cursor, actor, check);
        collect_node(engine, &cursor, &names, &weights, &mut nodes);
    }
    // Two plies of responses so a third player facing a bet is visible.
    let mut frontier = vec![root.clone()];
    for _depth in 0..2 {
        let mut next = Vec::new();
        for state in &frontier {
            let Some(actor) = next_actor(state) else {
                continue;
            };
            for action in legal(state, actor, engine) {
                if matches!(action, Action::Check) {
                    continue;
                }
                let child = apply(state, actor, &action);
                if next_actor(&child).is_some() && alive(&child) >= 2 {
                    collect_node(engine, &child, &names, &weights, &mut nodes);
                    next.push(child);
                }
            }
        }
        frontier = next;
    }
    PostflopSolution {
        iterations: cfg.iterations,
        chance: match cfg.chance_samples {
            Some(k) => format!("sampled-{k}"),
            None => "exact".into(),
        },
        max_agg: cfg.max_agg,
        bet_fractions: cfg.bet_fractions.clone(),
        players: out_players,
        ev_weighted_sum,
        nodes,
    }
}

fn collect_node(
    engine: &Engine,
    state: &State,
    names: &[String],
    weights: &[Vec<f64>],
    out: &mut Vec<StrategyNode>,
) {
    let Some(actor) = next_actor(state) else {
        return;
    };
    let actions = legal(state, actor, engine);
    if actions.is_empty() {
        return;
    }
    let key = key_for(state, actor);
    let Some(info) = engine.infos.get(&key) else {
        return;
    };
    let combos = engine.combos[actor]
        .iter()
        .enumerate()
        .map(|(i, combo)| ComboLine {
            combo: combo.label(),
            weight: weights[actor][i],
            strategy: info.average(i),
        })
        .collect();
    let node = StrategyNode {
        player: names[actor].clone(),
        player_index: actor,
        history: state.history_labels.clone(),
        actions: actions.iter().map(Action::label).collect(),
        combos,
    };
    if out
        .iter()
        .any(|n| n.player_index == node.player_index && n.history == node.history)
    {
        return;
    }
    out.push(node);
}

impl Engine<'_> {
    fn walk(&mut self, state: &State, reach: &[Vec<f64>]) -> Values {
        if alive(state) <= 1 {
            let winner = (0..state.folded.len())
                .find(|&i| !state.folded[i])
                .unwrap_or(0);
            return terminal_fold(self.combos, state, winner);
        }
        if let Some(actor) = next_actor(state) {
            return self.decision(state, actor, reach);
        }
        if state.board.len() >= 5 {
            return self.showdown(state, reach);
        }
        self.chance(state, reach)
    }

    fn decision(&mut self, state: &State, actor: usize, reach: &[Vec<f64>]) -> Values {
        let actions = legal(state, actor, self);
        let n_actions = actions.len();
        let n_hands = self.combos[actor].len();
        let key = key_for(state, actor);
        self.infos
            .entry(key.clone())
            .or_insert_with(|| Infoset::new(n_hands, actions.iter().map(Action::label).collect()));
        let mut strat = vec![vec![0.0; n_actions]; n_hands];
        {
            let info = &self.infos[&key];
            for h in 0..n_hands {
                strat[h] = if self.train {
                    info.current(h)
                } else {
                    info.average(h)
                };
            }
        }
        let mass: f64 = reach[actor].iter().sum();
        let mut p_act = vec![0.0; n_actions];
        if mass > 1e-15 {
            for h in 0..n_hands {
                for a in 0..n_actions {
                    p_act[a] += reach[actor][h] * strat[h][a];
                }
            }
            for v in &mut p_act {
                *v /= mass;
            }
        } else {
            for h in 0..n_hands {
                for a in 0..n_actions {
                    p_act[a] += strat[h][a];
                }
            }
            for v in &mut p_act {
                *v /= n_hands as f64;
            }
        }

        let mut child_vals = Vec::with_capacity(n_actions);
        for (ai, action) in actions.iter().enumerate() {
            let mut child_reach = reach.to_vec();
            for h in 0..n_hands {
                child_reach[actor][h] = reach[actor][h] * strat[h][ai];
            }
            let child = apply(state, actor, action);
            child_vals.push(self.walk(&child, &child_reach));
        }

        let n = self.combos.len();
        let mut ev = Vec::with_capacity(n);
        let mut den = Vec::with_capacity(n);
        for p in 0..n {
            let nh = self.combos[p].len();
            let mut pev = vec![0.0; nh];
            let mut pden = vec![0.0; nh];
            if p == actor {
                for h in 0..nh {
                    for a in 0..n_actions {
                        pev[h] += strat[h][a] * child_vals[a].ev[p][h];
                        pden[h] += strat[h][a] * child_vals[a].den[p][h];
                    }
                }
            } else {
                for h in 0..nh {
                    for a in 0..n_actions {
                        pev[h] += p_act[a] * child_vals[a].ev[p][h];
                        pden[h] += p_act[a] * child_vals[a].den[p][h];
                    }
                }
            }
            ev.push(pev);
            den.push(pden);
        }

        if self.train {
            let info = self.infos.get_mut(&key).expect("infoset inserted above");
            for h in 0..n_hands {
                for a in 0..n_actions {
                    info.add_strategy(h, a, reach[actor][h] * strat[h][a]);
                    let regret = child_vals[a].ev[actor][h] - ev[actor][h];
                    info.add_regret(h, a, regret);
                }
            }
        }
        Values { ev, den }
    }

    fn chance(&mut self, state: &State, reach: &[Vec<f64>]) -> Values {
        let n = self.combos.len();
        let mut cards = deck_without(&state.board);
        if let Some(k) = self.chance_samples {
            if k < cards.len() {
                cards = sample_cards(&mut self.rng, cards, k.max(1));
            }
        }
        let mut acc_num: Vec<Vec<f64>> = self.combos.iter().map(|c| vec![0.0; c.len()]).collect();
        let mut acc_den: Vec<Vec<f64>> = self.combos.iter().map(|c| vec![0.0; c.len()]).collect();
        for card in cards {
            let mut child = state.clone();
            child.board.push(card);
            child.history.push(0x8000_0000 | card.index() as u32);
            let mut child_reach = reach.to_vec();
            for p in 0..n {
                for (i, combo) in self.combos[p].iter().enumerate() {
                    if combo.conflicts_card(card) {
                        child_reach[p][i] = 0.0;
                    }
                }
            }
            open_street(&mut child);
            let v = self.walk(&child, &child_reach);
            for p in 0..n {
                for c in 0..self.combos[p].len() {
                    if self.combos[p][c].conflicts_card(card) {
                        continue;
                    }
                    acc_num[p][c] += v.den[p][c] * v.ev[p][c];
                    acc_den[p][c] += v.den[p][c];
                }
            }
        }
        let mut ev = acc_num;
        for p in 0..n {
            for c in 0..ev[p].len() {
                if acc_den[p][c] > 0.0 {
                    ev[p][c] /= acc_den[p][c];
                } else {
                    ev[p][c] = 0.0;
                }
            }
        }
        Values { ev, den: acc_den }
    }

    fn showdown(&self, state: &State, reach: &[Vec<f64>]) -> Values {
        let n = self.combos.len();
        let mut ranks = Vec::with_capacity(n);
        for p in 0..n {
            let mut row = Vec::with_capacity(self.combos[p].len());
            for combo in &self.combos[p] {
                if combo_dead(*combo, &state.board) {
                    row.push(0);
                    continue;
                }
                let mut cards = Vec::with_capacity(state.board.len() + 2);
                cards.extend_from_slice(&state.board);
                cards.push(combo.lo);
                cards.push(combo.hi);
                row.push(evaluate(&cards).0);
            }
            ranks.push(row);
        }
        let mut num: Vec<Vec<f64>> = self.combos.iter().map(|c| vec![0.0; c.len()]).collect();
        let mut den: Vec<Vec<f64>> = self.combos.iter().map(|c| vec![0.0; c.len()]).collect();
        for hero in 0..n {
            if state.folded[hero] {
                let profit = -state.invested[hero] as f64;
                for c in 0..self.combos[hero].len() {
                    num[hero][c] = profit;
                    den[hero][c] = 1.0;
                }
                continue;
            }
            let opponents: Vec<usize> = (0..n).filter(|&p| p != hero && !state.folded[p]).collect();
            for (hi, combo) in self.combos[hero].iter().enumerate() {
                if combo_dead(*combo, &state.board) {
                    continue;
                }
                let mut blocked = [false; 52];
                for card in &state.board {
                    blocked[card.index()] = true;
                }
                blocked[combo.lo.index()] = true;
                blocked[combo.hi.index()] = true;
                let mut chosen = vec![0usize; opponents.len()];
                enumerate(
                    &opponents,
                    0,
                    1.0,
                    &mut blocked,
                    &mut chosen,
                    self.combos,
                    reach,
                    &ranks,
                    state,
                    hero,
                    hi,
                    &mut num[hero][hi],
                    &mut den[hero][hi],
                );
            }
        }
        for p in 0..n {
            for c in 0..num[p].len() {
                if den[p][c] > 0.0 {
                    num[p][c] /= den[p][c];
                }
            }
        }
        Values { ev: num, den }
    }
}

fn enumerate(
    opponents: &[usize],
    depth: usize,
    weight: f64,
    blocked: &mut [bool; 52],
    chosen: &mut [usize],
    combos: &[Vec<Combo>],
    reach: &[Vec<f64>],
    ranks: &[Vec<u32>],
    state: &State,
    hero: usize,
    hero_idx: usize,
    num: &mut f64,
    den: &mut f64,
) {
    if depth == opponents.len() {
        let n = state.invested.len();
        let mut hand_ranks = vec![0u32; n];
        hand_ranks[hero] = ranks[hero][hero_idx];
        for (k, &p) in opponents.iter().enumerate() {
            hand_ranks[p] = ranks[p][chosen[k]];
        }
        let profit = settle(&state.invested, &state.folded, &hand_ranks);
        *num += weight * profit[hero] as f64;
        *den += weight;
        return;
    }
    let p = opponents[depth];
    for (i, combo) in combos[p].iter().enumerate() {
        let w = reach[p][i];
        if w <= 1e-15 {
            continue;
        }
        if blocked[combo.lo.index()] || blocked[combo.hi.index()] {
            continue;
        }
        blocked[combo.lo.index()] = true;
        blocked[combo.hi.index()] = true;
        chosen[depth] = i;
        enumerate(
            opponents,
            depth + 1,
            weight * w,
            blocked,
            chosen,
            combos,
            reach,
            ranks,
            state,
            hero,
            hero_idx,
            num,
            den,
        );
        blocked[combo.lo.index()] = false;
        blocked[combo.hi.index()] = false;
    }
}

fn terminal_fold(combos: &[Vec<Combo>], state: &State, winner: usize) -> Values {
    let mut ev = Vec::new();
    let mut den = Vec::new();
    for p in 0..combos.len() {
        let profit = if p == winner {
            (state.pot - state.invested[p]) as f64
        } else {
            -state.invested[p] as f64
        };
        ev.push(vec![profit; combos[p].len()]);
        den.push(vec![1.0; combos[p].len()]);
    }
    Values { ev, den }
}

fn alive(state: &State) -> usize {
    state.folded.iter().filter(|f| !**f).count()
}

fn next_actor(state: &State) -> Option<usize> {
    if alive(state) <= 1 {
        return None;
    }
    let n = state.need.len();
    for i in 0..n {
        if state.need[i] && !state.folded[i] && state.stacks[i] > 0 {
            return Some(i);
        }
    }
    None
}

fn open_street(state: &mut State) {
    let n = state.stacks.len();
    state.street_put = vec![0; n];
    state.current_bet = 0;
    state.min_raise_inc = BB_CHIPS;
    state.agg = 0;
    for i in 0..n {
        let live = !state.folded[i] && state.stacks[i] > 0;
        state.need[i] = live;
        state.can_raise[i] = live;
        state.acted[i] = false;
    }
}

fn key_for(state: &State, player: usize) -> Key {
    Key {
        player: player as u8,
        board: state.board.iter().map(|c| c.0).collect(),
        history: state.history.clone(),
    }
}

fn combo_dead(combo: Combo, board: &[Card]) -> bool {
    board.iter().any(|c| combo.conflicts_card(*c))
}

fn legal(state: &State, player: usize, engine: &Engine) -> Vec<Action> {
    let to_call = state.current_bet - state.street_put[player];
    let mut actions = Vec::new();
    if to_call <= 0 {
        actions.push(Action::Check);
    } else {
        actions.push(Action::Fold);
        if state.stacks[player] > 0 {
            actions.push(Action::Call);
        }
    }
    let can_agg = state.can_raise[player]
        && state.stacks[player] > to_call.max(0)
        && state.agg < engine.max_agg
        && (engine.include_all_in || !engine.fractions.is_empty());
    if can_agg {
        for (to, label) in agg_sizes(state, player, engine) {
            actions.push(Action::Agg { to, label });
        }
    }
    actions
}

fn agg_sizes(state: &State, player: usize, engine: &Engine) -> Vec<(i32, String)> {
    let to_call = (state.current_bet - state.street_put[player]).max(0);
    let call_amt = to_call.min(state.stacks[player]);
    let pot_after = state.pot + call_amt;
    let street = state.street_put[player];
    let stack = state.stacks[player];
    let all_in_to = street + stack;
    let mut raw: Vec<(i32, String)> = Vec::new();
    for &frac in engine.fractions {
        let raise_by = ((frac * pot_after as f64).round() as i32).max(1);
        let mut total = street + call_amt + raise_by;
        if to_call == 0 && total - street < BB_CHIPS {
            total = street + BB_CHIPS;
        }
        if total > all_in_to {
            total = all_in_to;
        }
        let pct = (frac * 100.0).round() as i32;
        let label = if total >= all_in_to {
            "allin".into()
        } else if to_call == 0 {
            format!("bet_{pct}")
        } else {
            format!("raise_{pct}")
        };
        raw.push((total, label));
    }
    if engine.include_all_in && stack > to_call {
        raw.push((all_in_to, "allin".into()));
    }
    let mut out = Vec::new();
    for (total, label) in raw {
        if total <= state.current_bet {
            continue;
        }
        let inc = total - state.current_bet;
        let is_allin = total == all_in_to;
        if !is_allin && inc < state.min_raise_inc {
            continue;
        }
        if out.iter().any(|(t, _)| *t == total) {
            continue;
        }
        let label = if is_allin { "allin".to_string() } else { label };
        out.push((total, label));
    }
    out
}

fn apply(state: &State, player: usize, action: &Action) -> State {
    let mut n = state.clone();
    match action {
        Action::Fold => {
            n.folded[player] = true;
            n.need[player] = false;
            n.can_raise[player] = false;
            n.acted[player] = true;
        }
        Action::Check => {
            n.need[player] = false;
            n.can_raise[player] = false;
            n.acted[player] = true;
        }
        Action::Call => {
            let to_call = n.current_bet - n.street_put[player];
            let add = to_call.min(n.stacks[player]);
            n.street_put[player] += add;
            n.invested[player] += add;
            n.stacks[player] -= add;
            n.pot += add;
            n.need[player] = false;
            n.can_raise[player] = false;
            n.acted[player] = true;
        }
        Action::Agg { to, .. } => {
            let add = *to - n.street_put[player];
            let inc = *to - n.current_bet;
            let full = inc >= n.min_raise_inc;
            n.street_put[player] = *to;
            n.invested[player] += add;
            n.stacks[player] -= add;
            n.pot += add;
            n.current_bet = *to;
            n.agg = n.agg.saturating_add(1);
            n.need[player] = false;
            n.can_raise[player] = false;
            n.acted[player] = true;
            if full {
                n.min_raise_inc = inc;
                for i in 0..n.stacks.len() {
                    if i != player && !n.folded[i] && n.stacks[i] > 0 {
                        n.need[i] = true;
                        n.can_raise[i] = true;
                    }
                }
            } else {
                for i in 0..n.stacks.len() {
                    if i == player || n.folded[i] || n.stacks[i] == 0 {
                        continue;
                    }
                    if n.street_put[i] < n.current_bet {
                        n.need[i] = true;
                        n.can_raise[i] = !n.acted[i];
                    }
                }
            }
        }
    }
    n.history.push(action.code());
    n.history_labels.push(action.label());
    n
}

fn sample_cards(rng: &mut Rng, mut cards: Vec<Card>, k: usize) -> Vec<Card> {
    for i in 0..k {
        let j = i + rng.index(cards.len() - i);
        cards.swap(i, j);
    }
    cards.truncate(k);
    cards
}

/// Build a spot from text. Investments split the pot evenly (remainder to the
/// earliest postflop seat) when the caller does not pass per-seat investments.
pub fn spot_from_text(
    board: &str,
    pot_chips: i32,
    seats: &[(Position, i32, &str)],
) -> Result<Spot, String> {
    let board = crate::card::parse_board(board)?;
    if seats.len() < 2 {
        return Err("need at least two seats".into());
    }
    let n = seats.len() as i32;
    let base = pot_chips / n;
    let mut extra = pot_chips - base * n;
    let mut players = Vec::new();
    // Assign the odd chips in postflop order so the split is stable.
    let positions: Vec<Position> = seats.iter().map(|s| s.0).collect();
    let order = postflop_order(&positions);
    let mut extra_for = vec![0; seats.len()];
    for pos in order {
        if extra <= 0 {
            break;
        }
        let idx = seats.iter().position(|s| s.0 == pos).unwrap();
        extra_for[idx] += 1;
        extra -= 1;
    }
    for (i, (position, stack, range)) in seats.iter().enumerate() {
        let combos = parse_range(range, &board)?;
        players.push(SpotPlayer {
            position: *position,
            stack: *stack,
            invested: base + extra_for[i],
            combos,
        });
    }
    Ok(Spot { board, players })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::card::Card;

    fn seat(pos: Position, stack: i32, invested: i32, range: &str, board: &[Card]) -> SpotPlayer {
        SpotPlayer {
            position: pos,
            stack,
            invested,
            combos: parse_range(range, board).unwrap(),
        }
    }

    #[test]
    fn min_bet_and_pot_fractions_are_offered() {
        let board = crate::card::parse_board("Kh7d2c2s3d").unwrap();
        let players = vec![
            seat(Position::Sb, 10_000, 500, "AsKd", &board),
            seat(Position::Bb, 10_000, 500, "QcJc", &board),
        ];
        let state = initial_state(&order_players(&players), &board);
        let engine = Engine {
            combos: &[],
            fractions: &[0.33, 0.75, 1.0],
            include_all_in: true,
            max_agg: 3,
            chance_samples: None,
            infos: HashMap::new(),
            train: true,
            rng: Rng::new(1),
        };
        let labels: Vec<_> = legal(&state, 0, &engine)
            .iter()
            .map(Action::label)
            .collect();
        assert_eq!(labels[0], "check");
        assert!(labels.iter().any(|l| l == "bet_33"));
        assert!(labels.iter().any(|l| l == "bet_75"));
        assert!(labels.iter().any(|l| l == "bet_100"));
        assert!(labels.iter().any(|l| l == "allin"));
        assert!(!labels.iter().any(|l| l == "fold"));
    }

    #[test]
    fn short_all_in_does_not_reopen_the_bettor() {
        let board = crate::card::parse_board("Kh7d2c2s3d").unwrap();
        // SB has a real stack, BB is short. SB bets, BB jams short of a min-raise.
        // Pot 400. A 33% bet is 132. BB has 180 behind, so jamming raises by 48,
        // short of the 132 minimum raise. The original bettor may call, not reraise.
        let players = vec![
            seat(Position::Sb, 2_000, 200, "AsKd", &board),
            seat(Position::Bb, 180, 200, "QcJc", &board),
        ];
        let ordered = order_players(&players);
        let state = initial_state(&ordered, &board);
        let engine = Engine {
            combos: &[],
            fractions: &[0.33],
            include_all_in: true,
            max_agg: 3,
            chance_samples: None,
            infos: HashMap::new(),
            train: true,
            rng: Rng::new(1),
        };
        let bet = legal(&state, 0, &engine)
            .into_iter()
            .find(|a| matches!(a, Action::Agg { label, .. } if label == "bet_33"))
            .expect("33% bet");
        let after_bet = apply(&state, 0, &bet);
        // BB can jam; the jam is smaller than a full raise (pot bet was 200, BB has 150).
        let bb = next_actor(&after_bet).unwrap();
        assert_eq!(ordered[bb].position, Position::Bb);
        let jam = legal(&after_bet, bb, &engine)
            .into_iter()
            .find(|a| matches!(a, Action::Agg { label, .. } if label == "allin"))
            .expect("short jam");
        let after_jam = apply(&after_bet, bb, &jam);
        let sb = next_actor(&after_jam).expect("bettor must be allowed to call");
        assert_eq!(ordered[sb].position, Position::Sb);
        let labels: Vec<_> = legal(&after_jam, sb, &engine)
            .iter()
            .map(Action::label)
            .collect();
        assert!(labels.iter().any(|l| l == "call"));
        assert!(labels.iter().any(|l| l == "fold"));
        assert!(
            !labels
                .iter()
                .any(|l| l.starts_with("raise") || l == "allin" || l.starts_with("bet")),
            "short all-in does not let the original bettor raise again: {labels:?}"
        );
    }
}
