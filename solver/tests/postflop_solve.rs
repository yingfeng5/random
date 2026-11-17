//! River, turn, flop, and multiway checks for the combo DCFR solver.
//!
//! The river toy is a pot-sized bet that a person can price by hand:
//! nuts bet, air bluffs half the time, the bluff-catcher calls half the time.

use gto_solver::card::{parse_board, Card, Combo};
use gto_solver::eval::evaluate;
use gto_solver::payoff::settle;
use gto_solver::position::Position;
use gto_solver::postflop::{solve_postflop, PostflopConfig, Spot, SpotPlayer};
use gto_solver::range::parse_range;

fn player(pos: Position, stack: i32, invested: i32, range: &str, board: &[Card]) -> SpotPlayer {
    SpotPlayer {
        position: pos,
        stack,
        invested,
        combos: parse_range(range, board).unwrap(),
    }
}

fn freq(node_actions: &[String], strategy: &[f64], label: &str) -> f64 {
    let i = node_actions.iter().position(|a| a == label).expect(label);
    strategy[i]
}

#[test]
fn river_toy_matches_the_hand_solution() {
    // Board pairs deuces. KsKd is kings-up (always wins). QcJc is deuces with
    // a queen kicker (always loses to Ah9h). Pot 100, stacks 100, one pot-sized
    // bet, which is an all-in. Equilibrium: bluff 1/2, call 1/2, nuts always bet.
    // Chip EV is profit including the 50 each has already put in:
    //   nuts +100, air -50, bluff-catcher -25.
    let board = parse_board("Kh7d2c2s3d").unwrap();
    let spot = Spot {
        board: board.clone(),
        players: vec![
            player(Position::Sb, 100, 50, "KsKd,QcJc", &board),
            player(Position::Bb, 100, 50, "Ah9h", &board),
        ],
    };
    let cfg = PostflopConfig {
        iterations: 600,
        bet_fractions: vec![1.0],
        include_all_in: false,
        max_agg: 1,
        chance_samples: None,
        seed: 1,
    };
    let sol = solve_postflop(&spot, &cfg).unwrap();
    assert!(
        (sol.ev_weighted_sum).abs() < 3.0,
        "sum {}",
        sol.ev_weighted_sum
    );

    let oop = &sol.players[0];
    let ip = &sol.players[1];
    let nuts = oop.combos.iter().find(|c| c.combo == "KsKd").unwrap();
    let air = oop.combos.iter().find(|c| c.combo == "QcJc").unwrap();
    let catcher = &ip.combos[0];
    assert!((nuts.ev - 100.0).abs() < 8.0, "nuts ev {}", nuts.ev);
    assert!((air.ev - -50.0).abs() < 8.0, "air ev {}", air.ev);
    assert!(
        (catcher.ev - -25.0).abs() < 8.0,
        "catcher ev {}",
        catcher.ev
    );

    let root = sol.nodes.iter().find(|n| n.history.is_empty()).unwrap();
    assert_eq!(root.player, "SB");
    let nuts_s = root.combos.iter().find(|c| c.combo == "KsKd").unwrap();
    let air_s = root.combos.iter().find(|c| c.combo == "QcJc").unwrap();
    let bet = freq(&root.actions, &nuts_s.strategy, "allin");
    let bluff = freq(&root.actions, &air_s.strategy, "allin");
    assert!(bet > 0.9, "nuts bet {bet}");
    assert!((bluff - 0.5).abs() < 0.08, "bluff {bluff}");

    let face = sol.nodes.iter().find(|n| n.history == ["allin"]).unwrap();
    assert_eq!(face.player, "BB");
    let call = freq(&face.actions, &face.combos[0].strategy, "call");
    assert!((call - 0.5).abs() < 0.08, "call {call}");
}

#[test]
fn three_players_on_the_river_are_actually_solved() {
    // SB has the nuts, BB beats BTN and loses to SB, BTN loses to both.
    // Calling the nuts' all-in is strictly losing. DCFR has to find that;
    // a flat 50/50 strategy does not.
    let board = parse_board("Kh7d2c2s3d").unwrap();
    let spot = Spot {
        board: board.clone(),
        players: vec![
            player(Position::Sb, 100, 100, "KsKd", &board),
            player(Position::Bb, 100, 100, "Ah9d", &board),
            player(Position::Btn, 100, 100, "6h5h", &board),
        ],
    };
    let cfg = PostflopConfig {
        iterations: 400,
        bet_fractions: vec![1.0],
        include_all_in: false,
        max_agg: 1,
        chance_samples: None,
        seed: 2,
    };
    let sol = solve_postflop(&spot, &cfg).unwrap();
    assert!(
        sol.ev_weighted_sum.abs() < 5.0,
        "sum {}",
        sol.ev_weighted_sum
    );
    let sb = sol.players.iter().find(|p| p.position == "SB").unwrap();
    let bb = sol.players.iter().find(|p| p.position == "BB").unwrap();
    let btn = sol.players.iter().find(|p| p.position == "BTN").unwrap();
    assert!(
        sb.combos[0].ev > bb.combos[0].ev,
        "nuts should out-earn the ace"
    );
    assert!(
        bb.combos[0].ev > btn.combos[0].ev,
        "ace should out-earn six-high"
    );

    let face = sol
        .nodes
        .iter()
        .find(|n| n.player == "BB" && n.history == ["allin"])
        .expect("BB response to the shove");
    let fold = freq(&face.actions, &face.combos[0].strategy, "fold");
    assert!(
        fold > 0.85,
        "drawing dead fold {fold}, actions {:?}",
        face.actions
    );
    let sum: f64 = face.combos[0].strategy.iter().sum();
    assert!((sum - 1.0).abs() < 1e-6);
    // Not a flat policy.
    let max = face.combos[0]
        .strategy
        .iter()
        .cloned()
        .fold(0.0_f64, f64::max);
    assert!(max > 0.85);
}

#[test]
fn suited_combos_of_the_same_class_are_not_bucketed() {
    // 9h8h is the nut-ish flush. 9c8c is the same class (98s) and loses to
    // deuces. A bucketed solver would give them one strategy.
    let board = parse_board("AhKhQh2c3d").unwrap();
    let spot = Spot {
        board: board.clone(),
        players: vec![
            player(Position::Sb, 100, 50, "9h8h,9c8c", &board),
            player(Position::Bb, 100, 50, "2d2h", &board),
        ],
    };
    let cfg = PostflopConfig {
        iterations: 500,
        bet_fractions: vec![1.0],
        include_all_in: false,
        max_agg: 1,
        chance_samples: None,
        seed: 3,
    };
    let sol = solve_postflop(&spot, &cfg).unwrap();
    let root = sol.nodes.iter().find(|n| n.history.is_empty()).unwrap();
    let flush = root.combos.iter().find(|c| c.combo == "9h8h").unwrap();
    let off = root.combos.iter().find(|c| c.combo == "9c8c").unwrap();
    let flush_bet = freq(&root.actions, &flush.strategy, "allin");
    let off_bet = freq(&root.actions, &off.strategy, "allin");
    assert!(flush_bet > 0.9, "flush bet {flush_bet}");
    assert!(
        flush_bet > off_bet + 0.25,
        "same class diverged: flush {flush_bet} off {off_bet}"
    );
    let flush_ev = sol.players[0]
        .combos
        .iter()
        .find(|c| c.combo == "9h8h")
        .unwrap()
        .ev;
    let off_ev = sol.players[0]
        .combos
        .iter()
        .find(|c| c.combo == "9c8c")
        .unwrap()
        .ev;
    assert!(flush_ev > off_ev + 40.0, "ev {flush_ev} vs {off_ev}");
}

#[test]
fn flop_and_turn_checkdowns_match_full_enumeration() {
    let cfg = PostflopConfig {
        iterations: 1,
        bet_fractions: vec![],
        include_all_in: false,
        max_agg: 1,
        chance_samples: None,
        seed: 1,
    };
    let flop = parse_board("Kh7d2c").unwrap();
    let flop_spot = Spot {
        board: flop.clone(),
        players: vec![
            player(Position::Btn, 1_000, 100, "AsAd", &flop),
            player(Position::Bb, 1_000, 100, "QsQd", &flop),
        ],
    };
    let sol = solve_postflop(&flop_spot, &cfg).unwrap();
    let expected = brute_runout(&flop, "AsAd", "QsQd", 200, 100, 100);
    let got = sol
        .players
        .iter()
        .find(|p| p.position == "BTN")
        .unwrap()
        .combos[0]
        .ev;
    assert!(
        (got - expected).abs() < 1e-6,
        "flop ev {got} expected {expected}"
    );
    assert!(sol.ev_weighted_sum.abs() < 1e-6);

    let turn = parse_board("Kh7d2c9s").unwrap();
    let turn_spot = Spot {
        board: turn.clone(),
        players: vec![
            player(Position::Co, 1_000, 80, "AsAd", &turn),
            player(Position::Btn, 1_000, 80, "QsQd", &turn),
            player(Position::Bb, 1_000, 80, "JsJd", &turn),
        ],
    };
    let sol = solve_postflop(&turn_spot, &cfg).unwrap();
    let expected = brute_three(&turn, "AsAd", "QsQd", "JsJd", 80);
    for (pos, exp) in expected {
        let got = sol
            .players
            .iter()
            .find(|p| p.position == pos)
            .unwrap()
            .combos[0]
            .ev;
        assert!((got - exp).abs() < 1e-6, "{pos} ev {got} expected {exp}");
    }
}

fn hand(board: &[Card], combo: &str) -> u32 {
    let mut cards = board.to_vec();
    let c = Combo::new(
        Card::parse(&combo[0..2]).unwrap(),
        Card::parse(&combo[2..4]).unwrap(),
    )
    .unwrap();
    cards.push(c.lo);
    cards.push(c.hi);
    evaluate(&cards).0
}

fn brute_runout(flop: &[Card], hero: &str, vill: &str, pot: i32, inv_h: i32, inv_v: i32) -> f64 {
    let mut num = 0.0;
    let mut den = 0.0;
    for turn in gto_solver::card::deck_without(flop) {
        if turn.to_string().len() == 0 {
            continue;
        }
        let hero_c = Combo::new(
            Card::parse(&hero[0..2]).unwrap(),
            Card::parse(&hero[2..4]).unwrap(),
        )
        .unwrap();
        let vill_c = Combo::new(
            Card::parse(&vill[0..2]).unwrap(),
            Card::parse(&vill[2..4]).unwrap(),
        )
        .unwrap();
        if hero_c.conflicts_card(turn) || vill_c.conflicts_card(turn) {
            continue;
        }
        let mut four = flop.to_vec();
        four.push(turn);
        for river in gto_solver::card::deck_without(&four) {
            if hero_c.conflicts_card(river) || vill_c.conflicts_card(river) {
                continue;
            }
            let mut five = four.clone();
            five.push(river);
            let ranks = [hand(&five, hero), hand(&five, vill)];
            let profit = settle(&[inv_h, inv_v], &[false, false], &ranks);
            // Pot may exceed inv_h+inv_v if we passed pot separately; here pot == sum.
            let _ = pot;
            num += profit[0] as f64;
            den += 1.0;
        }
    }
    num / den
}

fn brute_three(
    turn: &[Card],
    a: &str,
    b: &str,
    c: &str,
    invested: i32,
) -> Vec<(&'static str, f64)> {
    let combos = [
        Combo::new(
            Card::parse(&a[0..2]).unwrap(),
            Card::parse(&a[2..4]).unwrap(),
        )
        .unwrap(),
        Combo::new(
            Card::parse(&b[0..2]).unwrap(),
            Card::parse(&b[2..4]).unwrap(),
        )
        .unwrap(),
        Combo::new(
            Card::parse(&c[0..2]).unwrap(),
            Card::parse(&c[2..4]).unwrap(),
        )
        .unwrap(),
    ];
    let mut sums = [0.0; 3];
    let mut den = 0.0;
    for river in gto_solver::card::deck_without(turn) {
        if combos.iter().any(|combo| combo.conflicts_card(river)) {
            continue;
        }
        let mut five = turn.to_vec();
        five.push(river);
        let ranks = [hand(&five, a), hand(&five, b), hand(&five, c)];
        let profit = settle(
            &[invested, invested, invested],
            &[false, false, false],
            &ranks,
        );
        for i in 0..3 {
            sums[i] += profit[i] as f64;
        }
        den += 1.0;
    }
    // Postflop order of CO, BTN, BB is BB, CO, BTN — the solver returns that
    // order, but we look up by position name, so the pairing is by seat.
    vec![
        ("CO", sums[0] / den),
        ("BTN", sums[1] / den),
        ("BB", sums[2] / den),
    ]
}
