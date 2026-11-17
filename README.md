# 8-max NLHE study tool

A local solver for no-limit hold'em. Preflop is a precomputed 100bb eight-handed library. Postflop solves the spot you type, heads-up or multiway, with one strategy per combo. There is no hand bucketing and no neural net.

## Run

From the repository root, after the library file is in `solver/data/`:

```text
cargo run --release --manifest-path solver/Cargo.toml --bin gto-server -- --port 8080
```

Open http://127.0.0.1:8080 . The server binds to loopback only.

Rebuild the preflop library (this is the same DCFR the tests load, not a filled-in chart):

```text
cargo run --release --manifest-path solver/Cargo.toml --bin export-preflop -- --iterations 96 --boards 48 --out solver/data/preflop_100bb_8max.json
```

The file already in `solver/data/preflop_100bb_8max.json` is that command: 96 iterations, 48 showdown boards, seed `0xC0FFEE`.

`cargo test --manifest-path solver/Cargo.toml` runs the evaluator, the river toy, a 3-player solve, flop and turn check-downs, and the library checks.

## Preflop library

100bb, eight seats (UTG through BB), blinds 0.5bb and 1bb. Discounted CFR with α = 1.5, β = 0, γ = 2.

The shipped file records the iteration count that was actually run. The tree limits are:

- no limps
- open to 2.5bb only
- 3-bet to 7.5bb (3× the open)
- 4-bet is all-in, and only when at most three players remain
- no postflop betting: a called pot is awarded by check-down equity
- heads-up equity averages every non-conflicting combo pair on a fixed board sample
- multiway equity uses one representative combo per class, cycling with the board sample
- card removal between seats is not applied to betting reaches

Calling ranges are wider than a full postflop solve, because a called pot is won by equity alone. The frequencies are the DCFR output of this tree, not a chart copied from somewhere else.

## Postflop

Any street can be the root (3, 4, or 5 board cards). Two or more of the eight seats may still be in. Infosets are concrete combos. Bet sizes are 33% pot, 75% pot, pot, and all-in. Check, call, and fold are always offered when legal. The default raise cap is 3 bets or raises per street. Set chance samples on a wide flop; leave it empty and every remaining card is dealt.
