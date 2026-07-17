# Fit-Match: a rejected experiment, and why

## The idea

Could a player's position, height, class year, gender, and hometown predict
which NCAA division they'd end up playing at? If it worked, it could tell an
underserved athlete something useful — "players with a profile like yours
typically play at this level."

I built it, tested it hard, and killed it. Here's that whole process, written
up in full, because a negative result you actually stress-tested tells you
more than a positive one you haven't.

## What I found

I trained an XGBoost multiclass classifier (predicting D1/D2/D3/NAIA) on
2,062 real players scraped from 43 schools. I ran four setups to separate
real signal from leakage:

| Setup | Description | Accuracy |
|---|---|---|
| A | Random train/test split, height included (the original spec) | 0.661 |
| B | Random split, height excluded | 0.523 |
| C | Held-out schools, height included | 0.549 |
| D | Held-out schools, height excluded (the honest one) | 0.424 |

Majority-class baseline (always guess the most common division): **0.364**.
I ran a permutation test — shuffled division labels across schools 30 times —
and got a null accuracy of **0.310 ± 0.039**, topping out at 0.377.

**Setup D (0.424) does beat the permutation ceiling (0.377), so the signal's
real — p < 0.033 — but it's only about a 6-point lift over just guessing the
most common division. That's not a usable predictor.**

## The two leaks that inflated Setup A

**1. `height` was a website quirk, not a real signal.** Only 12 of the 43
schools I scraped even publish a height column on their roster pages — and
every single one of those 12 is a D1 program. So `P(D1 | height is present)`
is basically 1.00. The model wasn't learning anything about the players, it
was picking up on which school's website happened to include a height field.
In Setup A, height-related features made up 88% of the model's total
importance.

**2. `division` is a school-level label, not a player-level one.** Every
player on a given roster shares that school's division. A random
train/test split puts teammates on both sides of the split, so the model can
partly just recognize the school from a player's profile and read the label
off it. The real, honest sample size here is 43 schools, not 2,062 rows.

## What the confusion matrix actually shows

Even in the honest setup, D1 and D2 are barely distinguishable — 223 D1
players got predicted as D2 — and NAIA recall drops to 0.27. NAIA players
just look like everyone else on these features. If you aggregate every
player at a school into one majority vote, you only get 24 of 43 schools'
actual division right.

## Why it fails, and what would actually fix it

Position, class year, gender, and hometown tell you who a player is, not how
good they are. Two identical 19-year-old midfielders from the same town in
New Jersey end up at different programs based on ability and performance —
and this dataset just doesn't have that. Roster pages tell you who made a
team, not the high school or club stats (goals, minutes, ratings) that
actually separate a D1 recruit from a D3 one.

**What it would take to bring this idea back:** a real performance signal —
club tier, minutes played, goals/assists, a recruiting service rating. Not
more schools, not more tuning. More rosters would only sharpen the small
geographic signal already there, and wouldn't touch the accuracy ceiling.

## What I built instead

Comparator, the feature that replaced this: give me a position and a
hometown, and I'll show you real players with that profile and where they
actually ended up playing — no score, no prediction, just the roster
reality. It's a smaller claim than a predictor would make, but it's a claim
the data can actually back up.
