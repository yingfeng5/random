//! Showdown settlement, including side pots when stacks differ.
//!
//! Payoffs are net profit: chips awarded minus chips invested. With no rake
//! they sum to zero. An odd chip in a split layer goes to the earliest
//! winner in the `invested` order (postflop action order when callers use it).

/// `ranks[i]` is ignored when `folded[i]` is set. Higher rank wins a layer.
pub fn settle(invested: &[i32], folded: &[bool], ranks: &[u32]) -> Vec<i32> {
    let n = invested.len();
    debug_assert_eq!(n, folded.len());
    debug_assert_eq!(n, ranks.len());
    let mut won = vec![0i32; n];
    let mut levels: Vec<i32> = invested.to_vec();
    levels.sort_unstable();
    levels.dedup();
    let mut prev = 0i32;
    for level in levels {
        if level <= prev {
            continue;
        }
        let layer = level - prev;
        let contributors: Vec<usize> = (0..n).filter(|&i| invested[i] >= level).collect();
        let pot = layer * contributors.len() as i32;
        let eligible: Vec<usize> = contributors.into_iter().filter(|&i| !folded[i]).collect();
        if !eligible.is_empty() && pot > 0 {
            let best = eligible.iter().map(|&i| ranks[i]).max().unwrap_or(0);
            let winners: Vec<usize> = eligible.into_iter().filter(|&i| ranks[i] == best).collect();
            let share = pot / winners.len() as i32;
            let mut extra = pot - share * winners.len() as i32;
            for w in winners {
                won[w] += share;
                if extra > 0 {
                    won[w] += 1;
                    extra -= 1;
                }
            }
        }
        prev = level;
    }
    (0..n).map(|i| won[i] - invested[i]).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn heads_up_showdown_and_fold() {
        // Each put in 50, hero wins the 100 pot.
        let profit = settle(&[50, 50], &[false, false], &[10, 3]);
        assert_eq!(profit, vec![50, -50]);
        let folded = settle(&[50, 50], &[false, true], &[0, 99]);
        assert_eq!(folded, vec![50, -50]);
        let split = settle(&[50, 50], &[false, false], &[7, 7]);
        assert_eq!(split, vec![0, 0]);
    }

    #[test]
    fn side_pot_pays_the_short_stack_only_the_main() {
        // Short stack 100 in, two others 300. Short stack has the best hand,
        // the next stack the second best.
        let profit = settle(&[100, 300, 300], &[false, false, false], &[30, 20, 10]);
        // Main 300 to seat 0 (profit 200). Side 400 to seat 1 (profit 100).
        // Seat 2 loses 300.
        assert_eq!(profit, vec![200, 100, -300]);
        assert_eq!(profit.iter().sum::<i32>(), 0);
    }

    #[test]
    fn odd_chip_goes_to_the_earliest_winner() {
        let profit = settle(&[5, 5, 5], &[false, false, false], &[4, 4, 1]);
        // Pot 15, two-way split, one odd chip to seat 0.
        assert_eq!(profit, vec![3, 2, -5]);
        assert_eq!(profit.iter().sum::<i32>(), 0);
    }

    #[test]
    fn folded_player_still_contributes_chips() {
        let profit = settle(&[100, 100, 50], &[false, false, true], &[5, 9, 100]);
        // Seat 2 folded a 50 blind. Remaining pot 250 is won by seat 1.
        assert_eq!(profit, vec![-100, 150, -50]);
        assert_eq!(profit.iter().sum::<i32>(), 0);
    }
}
