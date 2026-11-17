//! The shipped 100bb library must be a real DCFR run: every seat, 169 classes,
//! and a strategy that folds trash from UTG while opening aces.

use gto_solver::preflop::load_library;

fn library() -> gto_solver::preflop::PreflopLibrary {
    let path = concat!(env!("CARGO_MANIFEST_DIR"), "/data/preflop_100bb_8max.json");
    load_library(path).expect("shipped library")
}

#[test]
fn shipped_library_is_a_real_eight_max_solve() {
    let lib = library();
    assert!(lib.iterations >= 64, "iterations {}", lib.iterations);
    assert_eq!(lib.algorithm, "DCFR");
    assert_eq!(lib.hands.len(), 169);
    assert_eq!(lib.limits.open_bb, 2.5);
    assert_eq!(lib.limits.three_bet_bb, 7.5);
    assert!(lib.limits.no_limps);
    assert_eq!(lib.limits.four_bet_max_players_remaining, 3);

    let mut seats = std::collections::BTreeSet::new();
    for node in &lib.nodes {
        seats.insert(node.player.clone());
        let n_act = node.actions.len();
        assert_eq!(node.strategy_bp.len(), 169 * n_act, "{}", node.history);
        assert!(n_act >= 1);
        for hand in 0..169 {
            let sum: u32 = node.strategy_bp[hand * n_act..(hand + 1) * n_act]
                .iter()
                .map(|&b| b as u32)
                .sum();
            assert_eq!(sum, 10_000, "{} {}", node.player, lib.hands[hand]);
        }
    }
    for seat in ["UTG", "UTG+1", "MP", "HJ", "CO", "BTN", "SB", "BB"] {
        assert!(seats.contains(seat), "missing {seat}");
    }

    let utg = lib.node("UTG", "").expect("UTG RFI");
    let btn = lib.node("BTN", "fffff").expect("BTN RFI");
    let bb = lib.node("BB", "fffffof").expect("BB versus BTN open");
    let aa = lib.hands.iter().position(|h| h == "AA").unwrap();
    let trash = lib.hands.iter().position(|h| h == "72o").unwrap();

    let utg_aa = lib.probs(utg, aa);
    let utg_trash = lib.probs(utg, trash);
    let open = utg.actions.iter().position(|a| a == "open").unwrap();
    assert!(utg_aa[open] > 0.95, "UTG AA open {}", utg_aa[open]);
    assert!(utg_trash[open] < 0.08, "UTG 72o open {}", utg_trash[open]);

    let btn_open = btn.actions.iter().position(|a| a == "open").unwrap();
    let wide = |node: &gto_solver::preflop::PreflopNode, action: usize| -> usize {
        let n = node.actions.len();
        (0..169)
            .filter(|&h| node.strategy_bp[h * n + action] > 5_000)
            .count()
    };
    let utg_wide = wide(utg, open);
    let btn_wide = wide(btn, btn_open);
    assert!(
        btn_wide > utg_wide + 8,
        "BTN opens {btn_wide} hands above 50%, UTG {utg_wide}"
    );

    let mut mean = 0.0;
    for hand in 0..169 {
        mean += lib.probs(utg, hand)[open];
    }
    mean /= 169.0;
    let mut var = 0.0;
    for hand in 0..169 {
        let d = lib.probs(utg, hand)[open] - mean;
        var += d * d;
    }
    let std = (var / 169.0).sqrt();
    assert!(std > 0.2, "UTG open std {std} looks flat");

    let three = bb.actions.iter().position(|a| a == "3bet").unwrap();
    assert!(
        lib.probs(bb, aa)[three] > 0.9,
        "BB AA 3-bet {}",
        lib.probs(bb, aa)[three]
    );
    // UTG and BTN are not the same chart pasted twice.
    let utg_vec: Vec<_> = (0..169).map(|h| lib.probs(utg, h)[open]).collect();
    let btn_vec: Vec<_> = (0..169).map(|h| lib.probs(btn, h)[btn_open]).collect();
    let gap: f64 = utg_vec
        .iter()
        .zip(&btn_vec)
        .map(|(a, b)| (a - b).abs())
        .sum();
    assert!(gap > 5.0, "position gap {gap}");
}
