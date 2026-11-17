//! Build the 100bb 8-max preflop library.
//!
//! ```text
//! cargo run --release --bin export-preflop -- --iterations 96 --boards 48 --out data/preflop_100bb_8max.json
//! ```

use gto_solver::preflop::{save_library, solve_preflop, PreflopParams};
use std::env;
use std::time::Instant;

fn main() {
    let mut params = PreflopParams::default();
    let mut out = "data/preflop_100bb_8max.json".to_string();
    let args: Vec<String> = env::args().skip(1).collect();
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--iterations" => {
                params.iterations = parse_next(&args, &mut i, "iterations");
            }
            "--boards" => {
                params.boards = parse_next(&args, &mut i, "boards");
            }
            "--seed" => {
                params.seed = parse_next(&args, &mut i, "seed");
            }
            "--out" => {
                i += 1;
                out = args
                    .get(i)
                    .cloned()
                    .unwrap_or_else(|| die("missing --out path"));
                i += 1;
            }
            other => die(&format!("unknown argument {other}")),
        }
    }
    eprintln!(
        "solving 100bb 8-max preflop: {} DCFR iterations, {} showdown boards",
        params.iterations, params.boards
    );
    let started = Instant::now();
    let lib = solve_preflop(&params);
    eprintln!(
        "done in {:.1}s, {} decision nodes",
        started.elapsed().as_secs_f64(),
        lib.nodes.len()
    );
    save_library(&out, &lib).unwrap_or_else(|e| die(&e));
    eprintln!("wrote {out}");
}

fn parse_next<T: std::str::FromStr>(args: &[String], i: &mut usize, name: &str) -> T {
    *i += 1;
    let raw = args
        .get(*i)
        .unwrap_or_else(|| die(&format!("missing --{name} value")));
    *i += 1;
    raw.parse()
        .unwrap_or_else(|_| die(&format!("bad --{name} value '{raw}'")))
}

fn die(msg: &str) -> ! {
    eprintln!("{msg}");
    std::process::exit(1);
}
