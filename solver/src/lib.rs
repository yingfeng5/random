//! Eight-max no-limit hold'em study solver.
//!
//! Postflop trees keep every combo as its own infoset (no hand buckets) and
//! abstract only bet sizes. Preflop is a discounted-CFR library over the 169
//! suit-isomorphism classes at 100bb, because an eight-handed tree is not
//! something the page should build on each click.

pub mod api;
pub mod card;
pub mod dcfr;
pub mod eval;
pub mod payoff;
pub mod position;
pub mod postflop;
pub mod preflop;
pub mod range;

pub use card::{Card, Combo};
pub use position::{Position, BB_CHIPS, SB_CHIPS};
pub use postflop::{solve_postflop, PostflopConfig, PostflopSolution, Spot, SpotPlayer};
pub use preflop::{load_library, PreflopLibrary};
