//! 100bb eight-max preflop library.
//!
//! The tree is the real betting order with a documented action abstraction:
//! no limps, open to 2.5bb, 3-bet to 7.5bb (3×), 4-bet is all-in and only
//! when at most three players are still in. There is no postflop betting.
//! A showdown pays the pot by check-down equity.
//!
//! Heads-up pots use a combo-averaged equity matrix (conflicting combos
//! removed). Three or more players use one representative combo of each
//! class, a board from a fixed sample, and an exact independent-hand
//! contest on that board. The representative and the board both cycle, so
//! the average over iterations is a real sampled DCFR solve, not a table
//! of hardcoded frequencies. Card removal between the eight seats is not
//! applied in the betting reaches; that limit is recorded in the file.

use crate::card::{all_combos, class_combo_count, class_label, Combo, N_CLASSES, N_COMBOS};
use crate::dcfr::{dcfr_discounts, Infoset, Rng};
use crate::eval::evaluate;
use crate::position::{Position, BB_CHIPS, POSITIONS, SB_CHIPS};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

pub const OPEN_CHIPS: i32 = 250;
pub const THREE_BET_CHIPS: i32 = 750;
pub const STACK_CHIPS: i32 = 10_000;
/// 4-bet (all-in) is offered only when this many players, or fewer, remain.
pub const FOUR_BET_MAX_LIVE: usize = 3;
pub const DCFR_ALPHA: f64 = 1.5;
pub const DCFR_BETA: f64 = 0.0;
pub const DCFR_GAMMA: f64 = 2.0;

const N: usize = N_CLASSES;
const SEATS: usize = 8;

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PreflopLimits {
    pub no_limps: bool,
    pub open_bb: f64,
    pub three_bet_bb: f64,
    pub four_bet: String,
    pub four_bet_max_players_remaining: usize,
    pub showdown: String,
    pub card_removal: String,
    pub boards: usize,
    pub seed: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PreflopNode {
    pub player: String,
    pub history: String,
    pub actions: Vec<String>,
    /// Basis points, row-major: hand class, then action. Each row sums to 10_000.
    pub strategy_bp: Vec<u16>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PreflopLibrary {
    pub schema: u32,
    pub game: String,
    pub table: String,
    pub stack_bb: u32,
    pub big_blind_chips: i32,
    pub algorithm: String,
    pub alpha: f64,
    pub beta: f64,
    pub gamma: f64,
    pub iterations: u32,
    pub limits: PreflopLimits,
    pub hands: Vec<String>,
    pub nodes: Vec<PreflopNode>,
}

impl PreflopLibrary {
    pub fn node(&self, player: &str, history: &str) -> Option<&PreflopNode> {
        self.nodes
            .iter()
            .find(|n| n.player == player && n.history == history)
    }

    /// Strategy for one class as probabilities that sum to 1.
    pub fn probs(&self, node: &PreflopNode, class_id: usize) -> Vec<f64> {
        let n_act = node.actions.len();
        let row = &node.strategy_bp[class_id * n_act..(class_id + 1) * n_act];
        row.iter().map(|&b| b as f64 / 10_000.0).collect()
    }

    pub fn rfi_nodes(&self) -> Vec<&PreflopNode> {
        // First-in: every player before this one folded, or the empty history for UTG.
        let mut out = Vec::new();
        for (i, pos) in POSITIONS.iter().enumerate() {
            if *pos == Position::Bb {
                continue;
            }
            let history = "f".repeat(i);
            if let Some(node) = self.node(&pos.to_string(), &history) {
                if node.actions.iter().any(|a| a == "open") {
                    out.push(node);
                }
            }
        }
        out
    }
}

pub fn load_library(path: &str) -> Result<PreflopLibrary, String> {
    let text = std::fs::read_to_string(path).map_err(|e| format!("reading {path}: {e}"))?;
    let lib: PreflopLibrary =
        serde_json::from_str(&text).map_err(|e| format!("parsing {path}: {e}"))?;
    if lib.hands.len() != N_CLASSES {
        return Err(format!("expected 169 hands, found {}", lib.hands.len()));
    }
    if lib.nodes.is_empty() {
        return Err("library has no nodes".into());
    }
    Ok(lib)
}

pub fn save_library(path: &str, lib: &PreflopLibrary) -> Result<(), String> {
    if let Some(parent) = std::path::Path::new(path).parent() {
        if !parent.as_os_str().is_empty() {
            std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
    }
    let text = serde_json::to_string(lib).map_err(|e| e.to_string())?;
    std::fs::write(path, text).map_err(|e| e.to_string())
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Act {
    Fold,
    Check,
    Call,
    Open,
    Three,
    Jam,
}

impl Act {
    fn label(self) -> &'static str {
        match self {
            Act::Fold => "fold",
            Act::Check => "check",
            Act::Call => "call",
            Act::Open => "open",
            Act::Three => "3bet",
            Act::Jam => "allin",
        }
    }

    fn ch(self) -> char {
        match self {
            Act::Fold => 'f',
            Act::Check => 'x',
            Act::Call => 'c',
            Act::Open => 'o',
            Act::Three => 't',
            Act::Jam => 'j',
        }
    }
}

#[derive(Clone)]
struct PState {
    street: [i32; SEATS],
    stack: [i32; SEATS],
    folded: [bool; SEATS],
    need: [bool; SEATS],
    current_bet: i32,
    raises: u8,
    pot: i32,
    to_act: usize,
    history: String,
}

struct EquityModel {
    hu: Vec<f64>,
    /// Flat `boards * 1326` hand ranks.
    ranks: Vec<u32>,
    boards: Vec<[u8; 5]>,
    class_combos: Vec<Vec<usize>>,
    combo_lo: Vec<u8>,
    combo_hi: Vec<u8>,
}

pub struct PreflopParams {
    pub iterations: u32,
    pub boards: usize,
    pub seed: u64,
}

impl Default for PreflopParams {
    fn default() -> Self {
        Self {
            iterations: 96,
            boards: 48,
            seed: 0xC0FFEE,
        }
    }
}

pub fn solve_preflop(params: &PreflopParams) -> PreflopLibrary {
    let model = EquityModel::build(params.boards.max(1), params.seed);
    let mut infos: HashMap<(u8, String), Infoset> = HashMap::new();
    let mut reach = initial_reach();
    let iterations = params.iterations.max(1);
    for t in 1..=iterations {
        let (pos, neg, strat) = dcfr_discounts(t);
        for info in infos.values_mut() {
            info.discount(pos, neg, strat);
        }
        let board_i = (t as usize - 1) % model.boards.len();
        let rep = t as usize - 1;
        let root = root_state();
        walk(&root, &mut reach, &mut infos, &model, board_i, rep, true);
    }
    library_from(params, &model, &infos)
}

pub struct TreeStats {
    pub decisions: usize,
    pub fold_terminals: usize,
    pub showdowns: usize,
    pub multiway_showdowns: usize,
}

pub fn tree_stats() -> TreeStats {
    let mut stats = TreeStats {
        decisions: 0,
        fold_terminals: 0,
        showdowns: 0,
        multiway_showdowns: 0,
    };
    fn rec(state: &PState, stats: &mut TreeStats) {
        let live = live_players(state);
        if live.len() == 1 {
            stats.fold_terminals += 1;
            return;
        }
        if next_actor(state).is_none() {
            stats.showdowns += 1;
            if live.len() >= 3 {
                stats.multiway_showdowns += 1;
            }
            return;
        }
        let actor = next_actor(state).unwrap();
        stats.decisions += 1;
        for action in legal(state, actor) {
            rec(&apply(state, actor, action), stats);
        }
    }
    rec(&root_state(), &mut stats);
    stats
}

fn library_from(
    params: &PreflopParams,
    model: &EquityModel,
    infos: &HashMap<(u8, String), Infoset>,
) -> PreflopLibrary {
    let mut nodes: Vec<PreflopNode> = infos
        .iter()
        .map(|((player, history), info)| {
            let mut bp = Vec::with_capacity(N * info.n_actions());
            for hand in 0..N {
                bp.extend(to_bp(&info.average(hand)));
            }
            PreflopNode {
                player: POSITIONS[*player as usize].to_string(),
                history: history.clone(),
                actions: info.action_labels.clone(),
                strategy_bp: bp,
            }
        })
        .collect();
    nodes.sort_by(|a, b| a.history.cmp(&b.history).then(a.player.cmp(&b.player)));
    PreflopLibrary {
        schema: 1,
        game: "NLHE".into(),
        table: "8-max".into(),
        stack_bb: 100,
        big_blind_chips: BB_CHIPS,
        algorithm: "DCFR".into(),
        alpha: DCFR_ALPHA,
        beta: DCFR_BETA,
        gamma: DCFR_GAMMA,
        iterations: params.iterations,
        limits: PreflopLimits {
            no_limps: true,
            open_bb: OPEN_CHIPS as f64 / BB_CHIPS as f64,
            three_bet_bb: THREE_BET_CHIPS as f64 / BB_CHIPS as f64,
            four_bet: "all-in".into(),
            four_bet_max_players_remaining: FOUR_BET_MAX_LIVE,
            showdown: "check-down equity only; the preflop tree does not deal a flop or bet postflop".into(),
            card_removal: "ignored between seats in the betting reaches; heads-up equity drops conflicting combos; multiway equity uses one cycled combo per class".into(),
            boards: model.boards.len(),
            seed: params.seed,
        },
        hands: (0..N).map(class_label).collect(),
        nodes,
    }
}

fn walk(
    state: &PState,
    reach: &mut [[f64; N]; SEATS],
    infos: &mut HashMap<(u8, String), Infoset>,
    model: &EquityModel,
    board_i: usize,
    rep: usize,
    train: bool,
) -> [[f64; N]; SEATS] {
    let live = live_players(state);
    if live.len() == 1 {
        return flat_profit(state, live[0]);
    }
    let Some(actor) = next_actor(state) else {
        return showdown_ev(state, reach, model, board_i, rep);
    };
    let actions = legal(state, actor);
    let labels: Vec<String> = actions.iter().map(|a| a.label().to_string()).collect();
    let key = (actor as u8, state.history.clone());
    infos
        .entry(key.clone())
        .or_insert_with(|| Infoset::new(N, labels));
    let n_act = actions.len();
    let mut strat = vec![vec![0.0; n_act]; N];
    {
        let info = &infos[&key];
        for hand in 0..N {
            strat[hand] = if train {
                info.current(hand)
            } else {
                info.average(hand)
            };
        }
    }
    let mass: f64 = reach[actor].iter().sum();
    let mut p_act = vec![0.0; n_act];
    if mass > 1e-15 {
        for hand in 0..N {
            for a in 0..n_act {
                p_act[a] += reach[actor][hand] * strat[hand][a];
            }
        }
        for v in &mut p_act {
            *v /= mass;
        }
    } else {
        for hand in 0..N {
            for a in 0..n_act {
                p_act[a] += strat[hand][a];
            }
        }
        for v in &mut p_act {
            *v /= N as f64;
        }
    }

    let saved = reach[actor];
    let mut child_ev: Vec<[[f64; N]; SEATS]> = Vec::with_capacity(n_act);
    for (ai, action) in actions.iter().enumerate() {
        for hand in 0..N {
            reach[actor][hand] = saved[hand] * strat[hand][ai];
        }
        let child = apply(state, actor, *action);
        child_ev.push(walk(&child, reach, infos, model, board_i, rep, train));
    }
    reach[actor] = saved;

    let mut out = [[0.0; N]; SEATS];
    for seat in 0..SEATS {
        if seat == actor {
            for hand in 0..N {
                let mut ev = 0.0;
                for a in 0..n_act {
                    ev += strat[hand][a] * child_ev[a][seat][hand];
                }
                out[seat][hand] = ev;
            }
        } else {
            for hand in 0..N {
                let mut ev = 0.0;
                for a in 0..n_act {
                    ev += p_act[a] * child_ev[a][seat][hand];
                }
                out[seat][hand] = ev;
            }
        }
    }
    if train {
        let info = infos.get_mut(&key).expect("infoset inserted");
        for hand in 0..N {
            for a in 0..n_act {
                info.add_strategy(hand, a, saved[hand] * strat[hand][a]);
                let regret = child_ev[a][actor][hand] - out[actor][hand];
                info.add_regret(hand, a, regret);
            }
        }
    }
    out
}

fn showdown_ev(
    state: &PState,
    reach: &[[f64; N]; SEATS],
    model: &EquityModel,
    board_i: usize,
    rep: usize,
) -> [[f64; N]; SEATS] {
    let live = live_players(state);
    let mut out = [[0.0; N]; SEATS];
    for seat in 0..SEATS {
        if state.folded[seat] {
            let loss = -state.street[seat] as f64;
            out[seat] = [loss; N];
        }
    }
    if live.len() == 2 {
        let a = live[0];
        let b = live[1];
        for hand in 0..N {
            let eq_a = model.hu_vs_range(hand, &reach[b]);
            let eq_b = model.hu_vs_range(hand, &reach[a]);
            out[a][hand] = eq_a * state.pot as f64 - state.street[a] as f64;
            out[b][hand] = eq_b * state.pot as f64 - state.street[b] as f64;
        }
        return out;
    }
    let ranks = model.class_ranks(board_i, rep);
    let eqs = multiway_equity(&ranks, reach, &live);
    for (k, &seat) in live.iter().enumerate() {
        for hand in 0..N {
            out[seat][hand] = eqs[k][hand] * state.pot as f64 - state.street[seat] as f64;
        }
    }
    out
}

fn flat_profit(state: &PState, winner: usize) -> [[f64; N]; SEATS] {
    let mut out = [[0.0; N]; SEATS];
    for seat in 0..SEATS {
        let profit = if seat == winner {
            (state.pot - state.street[seat]) as f64
        } else {
            -state.street[seat] as f64
        };
        out[seat] = [profit; N];
    }
    out
}

fn initial_reach() -> [[f64; N]; SEATS] {
    let mut row = [0.0; N];
    let mut sum = 0.0;
    for c in 0..N {
        let w = class_combo_count(c) as f64;
        row[c] = w;
        sum += w;
    }
    for w in &mut row {
        *w /= sum;
    }
    [row; SEATS]
}

fn root_state() -> PState {
    let mut street = [0; SEATS];
    let mut stack = [STACK_CHIPS; SEATS];
    street[Position::Sb.index()] = SB_CHIPS;
    street[Position::Bb.index()] = BB_CHIPS;
    stack[Position::Sb.index()] = STACK_CHIPS - SB_CHIPS;
    stack[Position::Bb.index()] = STACK_CHIPS - BB_CHIPS;
    PState {
        street,
        stack,
        folded: [false; SEATS],
        need: [true; SEATS],
        current_bet: BB_CHIPS,
        raises: 0,
        pot: SB_CHIPS + BB_CHIPS,
        to_act: 0,
        history: String::new(),
    }
}

fn live_players(state: &PState) -> Vec<usize> {
    (0..SEATS).filter(|&i| !state.folded[i]).collect()
}

fn next_actor(state: &PState) -> Option<usize> {
    if live_players(state).len() <= 1 {
        return None;
    }
    for k in 0..SEATS {
        let i = (state.to_act + k) % SEATS;
        if state.need[i] && !state.folded[i] && state.stack[i] > 0 {
            return Some(i);
        }
    }
    None
}

fn legal(state: &PState, player: usize) -> Vec<Act> {
    let to_call = state.current_bet - state.street[player];
    let mut actions = Vec::new();
    if to_call <= 0 {
        actions.push(Act::Check);
        return actions;
    }
    let unopened = state.raises == 0;
    actions.push(Act::Fold);
    if !unopened {
        actions.push(Act::Call);
    }
    if state.raises == 0 && state.stack[player] + state.street[player] >= OPEN_CHIPS {
        actions.push(Act::Open);
    } else if state.raises == 1 && state.stack[player] + state.street[player] >= THREE_BET_CHIPS {
        actions.push(Act::Three);
    } else if state.raises == 2
        && live_players(state).len() <= FOUR_BET_MAX_LIVE
        && state.stack[player] > to_call
    {
        actions.push(Act::Jam);
    }
    actions
}

fn apply(state: &PState, player: usize, action: Act) -> PState {
    let mut n = state.clone();
    n.history.push(action.ch());
    match action {
        Act::Fold => {
            n.folded[player] = true;
            n.need[player] = false;
        }
        Act::Check => {
            n.need[player] = false;
        }
        Act::Call => {
            let add = n.current_bet - n.street[player];
            n.street[player] += add;
            n.stack[player] -= add;
            n.pot += add;
            n.need[player] = false;
        }
        Act::Open => put_to(&mut n, player, OPEN_CHIPS, 1),
        Act::Three => put_to(&mut n, player, THREE_BET_CHIPS, 2),
        Act::Jam => {
            let to = n.street[player] + n.stack[player];
            put_to(&mut n, player, to, 3);
        }
    }
    n.to_act = (player + 1) % SEATS;
    n
}

fn put_to(state: &mut PState, player: usize, to: i32, raises: u8) {
    let add = to - state.street[player];
    state.street[player] = to;
    state.stack[player] -= add;
    state.pot += add;
    state.current_bet = to;
    state.raises = raises;
    for i in 0..SEATS {
        state.need[i] = i != player && !state.folded[i] && state.stack[i] > 0;
    }
}

fn to_bp(probs: &[f64]) -> Vec<u16> {
    let mut bp: Vec<i32> = probs
        .iter()
        .map(|p| (p * 10_000.0).round() as i32)
        .collect();
    let sum: i32 = bp.iter().sum();
    let drift = 10_000 - sum;
    if drift != 0 {
        let i = bp
            .iter()
            .enumerate()
            .max_by_key(|(_, v)| *v)
            .map(|(i, _)| i)
            .unwrap_or(0);
        bp[i] += drift;
    }
    bp.into_iter().map(|v| v.clamp(0, 10_000) as u16).collect()
}

impl EquityModel {
    fn build(n_boards: usize, seed: u64) -> Self {
        let combos = all_combos();
        let mut class_combos = vec![Vec::new(); N];
        let mut combo_lo = Vec::with_capacity(N_COMBOS);
        let mut combo_hi = Vec::with_capacity(N_COMBOS);
        for (i, combo) in combos.iter().enumerate() {
            class_combos[combo.class_id()].push(i);
            combo_lo.push(combo.lo.0);
            combo_hi.push(combo.hi.0);
        }
        let boards = sample_boards(n_boards, seed);
        let mut ranks = vec![0u32; boards.len() * N_COMBOS];
        let mut hu_num = vec![0.0f64; N * N];
        let mut hu_den = vec![0.0f64; N * N];
        for (b, board) in boards.iter().enumerate() {
            let dead = board_mask(board);
            for (i, combo) in combos.iter().enumerate() {
                if dead[combo.lo.index()] || dead[combo.hi.index()] {
                    ranks[b * N_COMBOS + i] = 0;
                    continue;
                }
                let cards = [
                    combo.lo,
                    combo.hi,
                    crate::card::Card(board[0]),
                    crate::card::Card(board[1]),
                    crate::card::Card(board[2]),
                    crate::card::Card(board[3]),
                    crate::card::Card(board[4]),
                ];
                ranks[b * N_COMBOS + i] = evaluate(&cards).0;
            }
            for a in 0..N {
                for c in a..N {
                    let (num, den) = class_pair_share(
                        &class_combos[a],
                        &class_combos[c],
                        &combos,
                        &ranks[b * N_COMBOS..(b + 1) * N_COMBOS],
                        &dead,
                    );
                    if den > 0.0 {
                        hu_num[a * N + c] += num;
                        hu_den[a * N + c] += den;
                        if a != c {
                            hu_num[c * N + a] += den - num;
                            hu_den[c * N + a] += den;
                        }
                    }
                }
            }
        }
        let mut hu = vec![0.5; N * N];
        for i in 0..N * N {
            if hu_den[i] > 0.0 {
                hu[i] = hu_num[i] / hu_den[i];
            }
        }
        Self {
            hu,
            ranks,
            boards,
            class_combos,
            combo_lo,
            combo_hi,
        }
    }

    fn hu_vs_range(&self, class_id: usize, opp: &[f64; N]) -> f64 {
        let mut num = 0.0;
        let mut den = 0.0;
        for j in 0..N {
            let w = opp[j];
            if w <= 0.0 {
                continue;
            }
            den += w;
            num += w * self.hu[class_id * N + j];
        }
        if den <= 0.0 {
            0.5
        } else {
            num / den
        }
    }

    fn class_ranks(&self, board_i: usize, rep: usize) -> [u32; N] {
        let dead = board_mask(&self.boards[board_i]);
        let base = board_i * N_COMBOS;
        let mut out = [0u32; N];
        for class in 0..N {
            let list = &self.class_combos[class];
            let mut count = 0usize;
            for &i in list {
                if !dead[self.combo_lo[i] as usize] && !dead[self.combo_hi[i] as usize] {
                    count += 1;
                }
            }
            if count == 0 {
                continue;
            }
            let pick = rep % count;
            let mut seen = 0usize;
            for &i in list {
                if dead[self.combo_lo[i] as usize] || dead[self.combo_hi[i] as usize] {
                    continue;
                }
                if seen == pick {
                    out[class] = self.ranks[base + i];
                    break;
                }
                seen += 1;
            }
        }
        out
    }
}

fn class_pair_share(
    a: &[usize],
    b: &[usize],
    combos: &[Combo],
    ranks: &[u32],
    dead: &[bool; 52],
) -> (f64, f64) {
    let mut num = 0.0;
    let mut den = 0.0;
    for &ia in a {
        if dead[combos[ia].lo.index()] || dead[combos[ia].hi.index()] {
            continue;
        }
        for &ib in b {
            if ia == ib {
                continue;
            }
            if dead[combos[ib].lo.index()] || dead[combos[ib].hi.index()] {
                continue;
            }
            if combos[ia].conflicts_combo(combos[ib]) {
                continue;
            }
            den += 1.0;
            if ranks[ia] > ranks[ib] {
                num += 1.0;
            } else if ranks[ia] == ranks[ib] {
                num += 0.5;
            }
        }
    }
    (num, den)
}

fn board_mask(board: &[u8; 5]) -> [bool; 52] {
    let mut dead = [false; 52];
    for c in board {
        dead[*c as usize] = true;
    }
    dead
}

fn sample_boards(n: usize, seed: u64) -> Vec<[u8; 5]> {
    let mut rng = Rng::new(seed);
    let mut boards = Vec::with_capacity(n);
    let mut guard = 0;
    while boards.len() < n && guard < n * 50 {
        guard += 1;
        let mut deck: Vec<u8> = (0..52).collect();
        for i in 0..5 {
            let j = i + rng.index(52 - i);
            deck.swap(i, j);
        }
        let board = [deck[0], deck[1], deck[2], deck[3], deck[4]];
        if !boards.contains(&board) {
            boards.push(board);
        }
    }
    boards
}

/// Equity of each live seat's classes. Hands are treated as independent;
/// `ranks[class]` is the strength of that class's representative combo.
fn multiway_equity(ranks: &[u32; N], reach: &[[f64; N]; SEATS], live: &[usize]) -> Vec<[f64; N]> {
    let dists: Vec<RankDist> = live
        .iter()
        .map(|&s| RankDist::from_reach(ranks, &reach[s]))
        .collect();
    let mut out = vec![[0.0; N]; live.len()];
    for (h, &seat) in live.iter().enumerate() {
        let _ = seat;
        let opps: Vec<&RankDist> = dists
            .iter()
            .enumerate()
            .filter(|(i, _)| *i != h)
            .map(|(_, d)| d)
            .collect();
        for class in 0..N {
            out[h][class] = contest_equity(ranks[class], &opps);
        }
    }
    out
}

struct RankDist {
    ranks: Vec<u32>,
    prefix: Vec<f64>,
    weight_at: Vec<f64>,
    total: f64,
}

impl RankDist {
    fn from_reach(ranks: &[u32; N], reach: &[f64; N]) -> Self {
        let mut items: Vec<(u32, f64)> = Vec::new();
        for c in 0..N {
            if reach[c] > 1e-15 && ranks[c] > 0 {
                items.push((ranks[c], reach[c]));
            }
        }
        items.sort_by_key(|i| i.0);
        let mut merged_r = Vec::new();
        let mut merged_w = Vec::new();
        for (r, w) in items {
            if merged_r.last() == Some(&r) {
                *merged_w.last_mut().unwrap() += w;
            } else {
                merged_r.push(r);
                merged_w.push(w);
            }
        }
        let mut prefix = Vec::with_capacity(merged_r.len() + 1);
        prefix.push(0.0);
        let mut run = 0.0;
        for w in &merged_w {
            run += *w;
            prefix.push(run);
        }
        Self {
            total: run,
            ranks: merged_r,
            weight_at: merged_w,
            prefix,
        }
    }

    fn lt_eq(&self, rank: u32) -> (f64, f64) {
        if self.total <= 0.0 {
            return (1.0, 0.0);
        }
        let i = self.ranks.partition_point(|&r| r < rank);
        let plt = self.prefix[i] / self.total;
        let peq = if i < self.ranks.len() && self.ranks[i] == rank {
            self.weight_at[i] / self.total
        } else {
            0.0
        };
        (plt, peq)
    }
}

fn contest_equity(hero: u32, opps: &[&RankDist]) -> f64 {
    if hero == 0 {
        return 0.0;
    }
    let n = opps.len();
    if n == 0 {
        return 1.0;
    }
    let mut dp = vec![0.0; n + 1];
    dp[0] = 1.0;
    let mut considered = 0;
    for opp in opps {
        let (plt, peq) = opp.lt_eq(hero);
        let mut next = vec![0.0; n + 1];
        for t in 0..=considered {
            next[t] += dp[t] * plt;
            next[t + 1] += dp[t] * peq;
        }
        dp = next;
        considered += 1;
    }
    let mut eq = 0.0;
    for t in 0..=n {
        eq += dp[t] / (t as f64 + 1.0);
    }
    eq
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tree_matches_the_documented_abstraction() {
        let stats = tree_stats();
        assert!(stats.decisions > 5_000, "decisions {}", stats.decisions);
        assert!(stats.multiway_showdowns > 1_000);
        // Structural spots a study page has to be able to open.
        fn has(history: &str, player: Position, want: &[&str]) -> bool {
            let mut state = root_state();
            for ch in history.chars() {
                let actor = next_actor(&state).expect("history left the tree");
                let action = legal(&state, actor)
                    .into_iter()
                    .find(|a| a.ch() == ch)
                    .unwrap_or_else(|| {
                        panic!(
                            "no action {ch} at {} for {}",
                            state.history, POSITIONS[actor]
                        )
                    });
                state = apply(&state, actor, action);
            }
            let actor = next_actor(&state).expect("node missing");
            assert_eq!(POSITIONS[actor], player, "history {history}");
            let labels: Vec<_> = legal(&state, actor).iter().map(|a| a.label()).collect();
            for w in want {
                assert!(
                    labels.contains(w),
                    "{history} labels {labels:?} missing {w}"
                );
            }
            true
        }
        assert!(has("", Position::Utg, &["fold", "open"]));
        assert!(has("fffff", Position::Btn, &["fold", "open"]));
        assert!(has("fffffof", Position::Bb, &["fold", "call", "3bet"]));
        // BTN open, SB fold, BB 3-bet: BTN is heads-up and may 4-bet all-in.
        assert!(has("fffffoft", Position::Btn, &["fold", "call", "allin"]));
        // UTG open, HJ 3-bet, three folds: BB is one of three left and may jam.
        assert!(has("offtfff", Position::Bb, &["fold", "call", "allin"]));
        // Right after HJ 3-bets, four or more players remain, so CO cannot jam.
        let mut state = root_state();
        for ch in "offt".chars() {
            let actor = next_actor(&state).unwrap();
            let action = legal(&state, actor)
                .into_iter()
                .find(|a| a.ch() == ch)
                .unwrap();
            state = apply(&state, actor, action);
        }
        let actor = next_actor(&state).unwrap();
        assert_eq!(POSITIONS[actor], Position::Co);
        let labels: Vec<_> = legal(&state, actor).iter().map(|a| a.label()).collect();
        assert!(!labels.contains(&"allin"), "{labels:?}");
        let _ = stats;
    }

    #[test]
    fn heads_up_equity_respects_hand_order() {
        let model = EquityModel::build(12, 1);
        let aa = class_id_label("AA");
        let kk = class_id_label("KK");
        let trash = class_id_label("72o");
        let aa_vs_trash = model.hu[aa * N + trash];
        let trash_vs_aa = model.hu[trash * N + aa];
        let aa_vs_aa = model.hu[aa * N + aa];
        assert!(aa_vs_trash > 0.80, "AA vs 72o {aa_vs_trash}");
        assert!((aa_vs_trash + trash_vs_aa - 1.0).abs() < 1e-9);
        assert!((aa_vs_aa - 0.5).abs() < 0.05, "AA vs AA {aa_vs_aa}");
        assert!(model.hu[aa * N + kk] > model.hu[kk * N + aa]);
    }

    #[test]
    fn multiway_contest_splits_ties_and_pays_the_nuts() {
        let mut ranks = [1u32; N];
        ranks[0] = 100;
        ranks[1] = 50;
        ranks[2] = 50;
        let mut reach = [[0.0; N]; SEATS];
        reach[0][0] = 1.0;
        reach[1][1] = 1.0;
        reach[2][2] = 1.0;
        let eqs = multiway_equity(&ranks, &reach, &[0, 1, 2]);
        assert!((eqs[0][0] - 1.0).abs() < 1e-9);
        assert!(eqs[1][1].abs() < 1e-9);
        assert!(eqs[2][2].abs() < 1e-9);
        // Two-way tie for the best hand, third player worse.
        ranks[0] = 80;
        ranks[1] = 80;
        ranks[2] = 10;
        let eqs = multiway_equity(&ranks, &reach, &[0, 1, 2]);
        assert!((eqs[0][0] - 0.5).abs() < 1e-9, "{}", eqs[0][0]);
        assert!((eqs[1][1] - 0.5).abs() < 1e-9);
        assert!(eqs[2][2].abs() < 1e-9);
    }

    #[test]
    fn short_dcfr_is_not_a_flat_strategy() {
        // Two iterations of the real 8-max tree. Too few to read as a strategy,
        // enough to prove regrets move off uniform for AA versus 72o.
        let params = PreflopParams {
            iterations: 2,
            boards: 4,
            seed: 2,
        };
        let lib = solve_preflop(&params);
        let utg = lib.node("UTG", "").expect("UTG RFI");
        let aa = class_id_label("AA");
        let trash = class_id_label("72o");
        let aa_p = lib.probs(utg, aa);
        let trash_p = lib.probs(utg, trash);
        let open = utg.actions.iter().position(|a| a == "open").unwrap();
        assert!(
            aa_p[open] > trash_p[open] + 0.05,
            "AA open {} vs 72o open {}",
            aa_p[open],
            trash_p[open]
        );
    }

    fn class_id_label(label: &str) -> usize {
        (0..N).find(|&i| class_label(i) == label).expect(label)
    }
}
