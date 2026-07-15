# Equity finding: hometown income vs. program division

**Hypothesis tested.** Higher-division soccer programs recruit from wealthier hometowns. Roster hometowns were linked to Census ACS 5-year (2023) place-level median household income (`B19013_001E`) and compared across D1/D2/D3/NAIA.

## Headline

**The hypothesis is not supported, and the headline result does not survive a regional control.**

1. **The ordering is not the prestige ladder.** Program-level medians run D3 ($118,408) > D1 ($100,749) > D2 ($86,110) > NAIA ($72,416) -- **D3, not D1, recruits from the wealthiest hometowns.** A simple 'higher division = more money' story predicts D1 > D2 > D3 > NAIA and is immediately contradicted.

2. **The raw difference is significant** at the program level: H=13.62, p=0.0035, epsilon-squared=0.287 (large effect, n=41 programs).

3. **But it mostly dissolves once you control for region.** Scoring each hometown against *its own state's* median income and re-running the same test gives p=0.0523, epsilon-squared=0.127 -- **no longer significant**. Roughly half the raw effect was cost-of-living geography, not athletics: the D3 programs here sit in NY/VA/PA (expensive states), the NAIA programs in MI/IL/IN (cheaper ones).

## What actually survives

The robust pattern is not about *division tiers* -- it is about college soccer as a whole. Every division except NAIA recruits from towns meaningfully **above** their own state's median income:

| division | programs | median hometown income | income relative to state median |
|---|---|---|---|
| D1 | 18 | $100,749 | 1.18x |
| D2 | 9 | $86,110 | 1.07x |
| D3 | 8 | $118,408 | 1.23x |
| NAIA | 6 | $72,416 | 0.97x |

A ratio of 1.00 means a program's typical recruit comes from a town at exactly its state's median income. D1 (1.18x) and D3 (1.23x) draw from towns roughly a fifth richer than their states' median; NAIA (0.97x) is the only division recruiting at parity with the general population. **That contrast -- NAIA vs. everyone else -- is the real signal here, and it is not a story about competitive tier.**

## Per-player distribution (raw income)

| division | players | median | Q1 | Q3 |
|---|---|---|---|---|
| D1 | 536 | $103,698 | $77,171 | $138,569 |
| D2 | 301 | $82,424 | $66,981 | $111,742 |
| D3 | 290 | $111,582 | $79,713 | $152,398 |
| NAIA | 235 | $75,235 | $65,526 | $104,920 |

## Pairwise (school-level, raw income, Bonferroni-corrected)

| comparison | median difference | adjusted p |
|---|---|---|
| D1 vs D2 | $+14,638 | 0.253 |
| D1 vs D3 | $-17,659 | 0.480 |
| D1 vs NAIA | $+28,333 | 0.153 |
| D2 vs D3 | $-32,297 | 0.009 \* |
| D2 vs NAIA | $+13,695 | 0.868 |
| D3 vs NAIA | $+45,992 | 0.176 |

Only **D2 vs D3** survives correction. Note what that contrast actually is: selective private Northeast colleges versus Sunbelt D2 programs. It is an *institution-type* difference, not a *competitive-tier* difference. D1 vs D2 and D1 vs D3 are both null.

## A plausible mechanism (untested here)

D3 offers **no athletic scholarships**. A D3 roster spot therefore selects, in part, for families who can absorb full private-college tuition -- which would push D3 hometown income up independent of athletic level. That mechanism fits the data better than a prestige ladder does, but this study cannot confirm it: it would need financial-aid data, not roster data.

## Caveats -- read before citing any number above

1. **Differential missingness, and it is not random.** 82.6% of unique US hometowns matched a Census place; 66.1% of all 2062 players carry an income value. 414 players (20%) are international and hold `null` by design -- but international share *varies by division* (D2 32%, D1 21%, NAIA 18%, D3 4%). So the analysis runs on ~59% of D2's roster versus ~86% of D3's. The excluded group is correlated with both the predictor and the outcome, because international recruiting is itself a marker of program resources. This is the single weakest point in the design.
2. **Ambiguity.** 17 hometowns matched multiple same-name places within one state and were dropped rather than guessed; 143 matched no Census place at all (unincorporated areas, neighborhoods like 'West Roxbury', townships). Unmatched places skew toward affluent unincorporated suburbs (Gladwyne PA, Chevy Chase MD, Palos Verdes CA), which likely biases the matched sample *downward* -- against the very effect being tested.
3. **Ecological fallacy -- the deepest problem.** `B19013_001E` is the median income of a player's *hometown*, not of the player's *household*. A recruit from Bakersfield is not a Bakersfield-median earner. Club soccer runs to thousands of dollars a season, so within any town the players who reach a college roster are plausibly drawn from its upper income tail. This measure cannot see that -- and it is precisely the mechanism an equity claim would rest on. Town income is a weak proxy for geographic sorting, not a measure of player wealth.
4. **Clustering / pseudo-replication.** The 2062 players are not independent: they cluster into 43 recruiting pipelines. The player-level test (p=7.2e-20) treats teammates as independent draws and is inflated by roughly the average roster size; it is reported for reference only and should not be cited. The program-level test is the honest one, and its effective sample size is 41, not 1362.
5. **Underpowered at the program level.** 41 programs split across four divisions leaves 6-18 per group. The region-adjusted test (p=0.0523) sits close enough to 0.05 that it should be read as 'undetermined at this sample size', not as a clean null. More programs would genuinely help here -- unlike in the fit-match experiment, where more data would not have moved the ceiling.

## Bottom line

**The equity hypothesis as operationalized here is not supported.** The raw division difference is significant (p=0.0035) but is largely a regional cost-of-living artifact: adjusting each hometown against its own state's median drops it to p=0.0523, below the conventional threshold. And the raw ordering contradicts the hypothesis anyway -- **D3, not D1, recruits from the wealthiest hometowns**, which points at scholarship structure rather than competitive tier.

The one durable observation: **college soccer recruits from above-median towns across the board** (D1 1.18x, D3 1.23x, D2 1.07x their state medians), with NAIA at parity (0.97x). If there is an income barrier in this sport, it looks like a barrier to *playing college soccer at all* rather than a barrier that sorts players between divisions.

This is a **null-to-inconclusive result for the stated hypothesis** and should be written up as one. Town-of-origin median income is too coarse an instrument to settle the question (caveat 3); a real test needs household income, financial-aid, or club-fee data.
