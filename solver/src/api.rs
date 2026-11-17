//! JSON boundary between the web page and the postflop solver.
//!
//! Chips are the solver's unit (100 chips = 1bb). The page speaks in big blinds.

use crate::card::parse_board;
use crate::position::{postflop_order, Position, BB_CHIPS};
use crate::postflop::{solve_postflop, PostflopConfig, PostflopSolution, Spot, SpotPlayer};
use crate::range::parse_range;
use serde::{Deserialize, Serialize};
use serde_json::json;

#[derive(Debug, Deserialize)]
pub struct SolveRequest {
    pub board: String,
    pub pot_bb: f64,
    #[serde(default = "default_iterations")]
    pub iterations: u32,
    #[serde(default = "default_fractions")]
    pub bet_fractions: Vec<f64>,
    #[serde(default = "default_true")]
    pub include_all_in: bool,
    #[serde(default = "default_agg")]
    pub max_agg: u8,
    pub chance_samples: Option<usize>,
    pub players: Vec<SeatRequest>,
}

#[derive(Debug, Deserialize)]
pub struct SeatRequest {
    pub position: String,
    pub stack_bb: f64,
    pub range: String,
    pub invested_bb: Option<f64>,
}

fn default_iterations() -> u32 {
    200
}
fn default_fractions() -> Vec<f64> {
    vec![0.33, 0.75, 1.0]
}
fn default_true() -> bool {
    true
}
fn default_agg() -> u8 {
    3
}

#[derive(Serialize)]
struct SolveResponse {
    iterations: u32,
    chance: String,
    max_agg: u8,
    bet_fractions: Vec<f64>,
    ev_weighted_sum_bb: f64,
    players: Vec<PlayerOut>,
    nodes: Vec<NodeOut>,
}

#[derive(Serialize)]
struct PlayerOut {
    position: String,
    combos: Vec<ComboOut>,
}

#[derive(Serialize)]
struct ComboOut {
    combo: String,
    weight: f64,
    ev_bb: f64,
}

#[derive(Serialize)]
struct NodeOut {
    player: String,
    history: Vec<String>,
    actions: Vec<String>,
    combos: Vec<LineOut>,
}

#[derive(Serialize)]
struct LineOut {
    combo: String,
    weight: f64,
    strategy: Vec<f64>,
}

pub fn solve_request(body: &str) -> Result<String, String> {
    let req: SolveRequest = serde_json::from_str(body).map_err(|e| format!("bad json: {e}"))?;
    let spot = spot_from_request(&req)?;
    let cfg = PostflopConfig {
        iterations: req.iterations,
        bet_fractions: req.bet_fractions.clone(),
        include_all_in: req.include_all_in,
        max_agg: req.max_agg,
        chance_samples: req.chance_samples,
        seed: 1,
    };
    let sol = solve_postflop(&spot, &cfg)?;
    Ok(serde_json::to_string(&to_response(&sol)).map_err(|e| e.to_string())?)
}

fn spot_from_request(req: &SolveRequest) -> Result<Spot, String> {
    if req.players.len() < 2 || req.players.len() > 8 {
        return Err("send 2 to 8 players still in the hand".into());
    }
    if !(req.pot_bb.is_finite() && req.pot_bb >= 0.0) {
        return Err("pot must be a non-negative number of big blinds".into());
    }
    let board = parse_board(&req.board)?;
    let pot_chips = bb_to_chips(req.pot_bb);
    let mut parsed = Vec::new();
    for seat in &req.players {
        let position = Position::parse(&seat.position)
            .ok_or_else(|| format!("unknown position '{}'", seat.position))?;
        if !(seat.stack_bb.is_finite() && seat.stack_bb >= 0.0) {
            return Err(format!("{position} stack must be non-negative"));
        }
        let combos = parse_range(&seat.range, &board)?;
        let invested = seat.invested_bb.map(bb_to_chips);
        parsed.push((position, bb_to_chips(seat.stack_bb), invested, combos));
    }
    let invested = if parsed.iter().all(|p| p.2.is_some()) {
        parsed.iter().map(|p| p.2.unwrap()).collect::<Vec<_>>()
    } else if parsed.iter().any(|p| p.2.is_some()) {
        return Err(
            "either every seat has invested_bb, or none do (the pot is split evenly)".into(),
        );
    } else {
        split_pot(pot_chips, &parsed.iter().map(|p| p.0).collect::<Vec<_>>())
    };
    if invested.iter().sum::<i32>() != pot_chips && parsed.iter().all(|p| p.2.is_some()) {
        // Allow a one-chip rounding gap when the caller names investments.
        let sum = invested.iter().sum::<i32>();
        if (sum - pot_chips).abs() > req.players.len() as i32 {
            return Err(format!(
                "invested chips {sum} do not add up to the pot {pot_chips}"
            ));
        }
    }
    let players = parsed
        .into_iter()
        .enumerate()
        .map(|(i, (position, stack, _, combos))| SpotPlayer {
            position,
            stack,
            invested: invested[i],
            combos,
        })
        .collect();
    Ok(Spot { board, players })
}

fn split_pot(pot: i32, seats: &[Position]) -> Vec<i32> {
    let n = seats.len() as i32;
    let base = pot / n;
    let mut extra = pot - base * n;
    let order = postflop_order(seats);
    let mut extra_for = vec![0; seats.len()];
    for pos in order {
        if extra <= 0 {
            break;
        }
        let idx = seats.iter().position(|s| *s == pos).unwrap();
        extra_for[idx] += 1;
        extra -= 1;
    }
    extra_for.into_iter().map(|e| base + e).collect()
}

fn bb_to_chips(bb: f64) -> i32 {
    (bb * BB_CHIPS as f64).round() as i32
}

fn to_response(sol: &PostflopSolution) -> SolveResponse {
    let bb = BB_CHIPS as f64;
    SolveResponse {
        iterations: sol.iterations,
        chance: sol.chance.clone(),
        max_agg: sol.max_agg,
        bet_fractions: sol.bet_fractions.clone(),
        ev_weighted_sum_bb: sol.ev_weighted_sum / bb,
        players: sol
            .players
            .iter()
            .map(|p| PlayerOut {
                position: p.position.clone(),
                combos: p
                    .combos
                    .iter()
                    .map(|c| ComboOut {
                        combo: c.combo.clone(),
                        weight: c.weight,
                        ev_bb: c.ev / bb,
                    })
                    .collect(),
            })
            .collect(),
        nodes: sol
            .nodes
            .iter()
            .map(|n| NodeOut {
                player: n.player.clone(),
                history: n.history.clone(),
                actions: n.actions.clone(),
                combos: n
                    .combos
                    .iter()
                    .map(|c| LineOut {
                        combo: c.combo.clone(),
                        weight: c.weight,
                        strategy: c.strategy.clone(),
                    })
                    .collect(),
            })
            .collect(),
    }
}

pub fn error_json(message: &str) -> String {
    json!({ "error": message }).to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn request_solves_a_three_player_river() {
        let body = r#"{
            "board": "Kh7d2c2s3d",
            "pot_bb": 3,
            "iterations": 80,
            "bet_fractions": [1.0],
            "include_all_in": false,
            "max_agg": 1,
            "players": [
                {"position": "SB", "stack_bb": 1, "range": "KsKd"},
                {"position": "BB", "stack_bb": 1, "range": "Ah9d"},
                {"position": "BTN", "stack_bb": 1, "range": "6h5h"}
            ]
        }"#;
        let text = solve_request(body).unwrap();
        let v: serde_json::Value = serde_json::from_str(&text).unwrap();
        assert_eq!(v["players"].as_array().unwrap().len(), 3);
        assert!(v["ev_weighted_sum_bb"].as_f64().unwrap().abs() < 0.15);
        let nodes = v["nodes"].as_array().unwrap();
        assert!(nodes.iter().any(|n| n["player"] == "SB"));
    }
}
