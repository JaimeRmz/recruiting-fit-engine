# Recruiting Fit Engine

**The recruiting edge is mostly access. This narrows the gap.**

Live: https://recruiting-fit-engine.vercel.app
API: https://recruiting-fit-engine-api.onrender.com

Getting recruited runs on things money buys — club dues, showcase travel, an
editor to cut your highlights. I built three tools that hand some of that
back to the player. Two of them are the real thing, tested against real data
until I trusted them. The third is an assistant built on top.

I'm Jaime Ramirez — CS student at University of Houston-Clear Lake, and
founder/head coach of JRGK Performance, a goalkeeper training academy here in
Houston. This project comes directly from coaching: I've watched talented
kids lose recruiting opportunities to access, not ability, and I wanted to
build something that actually chips away at that instead of just talking
about it.

## What's here

### 1. Comparator — real players like you
Pick a position, a home state, a squad. See real college soccer players who
share that profile, and the real programs they play for.

**No score. No prediction.** That was a deliberate call, not something I
skipped. I built a predictor first and killed it — see
[`fit_match_finding.md`](fit_match_finding.md) for the full story on why.

- Backed by 2,062 real players I scraped from 43 NCAA/NAIA rosters, across
  two different athletics-site templates (WMT Digital, Sidearm Sports).
- Falls back to a labeled regional match if a state doesn't have enough
  players at a given position — it never just comes back empty.
- Outreach Assistant's "browse all programs" mode runs on a second, bigger
  but lower-rigor dataset: 2,244 programs from Wikipedia (D1/D2/D3) and
  NCSA's sport-specific lists (D3/NAIA). That's a program directory — school,
  division, conference where it's available — not a scraped roster, and I
  haven't verified it the way I verified the 43-school set.

### 2. Moment-Finder — find the moments worth reviewing
Upload raw match footage. The pipeline flags candidate timestamps — motion
spikes and hard scene cuts — so you can jump straight to them instead of
scrubbing a whole match.

**What it is:** a candidate-finder for human review.
**What it's not:** an event classifier. It doesn't know what a goal, a
tackle, or a foul looks like. It ranks by motion magnitude, which is a proxy
for "something happened," not "this mattered" — a dead-ball restart can
outrank a real attacking sequence.

Real limitations I found while testing this, not hypothetical ones:
- False positives cluster into three patterns: dead-ball restarts (players
  bunching up for a corner), pre-game warmup, and hard camera zooms.
- On tripod/single-camera footage, the scene-cut signal never fires — there
  are no replay cuts for it to catch, so motion is the only usable signal.
- On broadcast footage with replays, a goal usually throws off two
  correlated signals close together — celebration motion, then a replay-
  angle scene cut. That's the "confirmed by both signals" case, and it's why
  it ranks higher by design.
- I manually spot-checked candidates against a real 59-minute club match and
  against a curated highlight reel — every one I checked, top-ranked to
  bottom-ranked, was either real action or a clearly identifiable false
  positive. Never just noise. That said, this was a manual spot-check, not a
  formal recall number. I built `eval_recall.py` to measure that properly,
  but I ran out of time to hand-label a full set before submitting. That's a
  real gap and I'd rather say so than fake a number.

Engineering worth knowing about:
- Frame-differencing with camera-pan compensation (phase correlation), not
  dense optical flow — chosen for speed, since a 90-minute match needed to
  analyze in minutes, not hours. Known limitation: the pan compensation is
  translation-only, so a hard camera zoom can still read as motion.
- Every upload gets pre-downscaled to 640px wide before any analysis runs.
  This exists because the deployed API OOM-crashed repeatedly on a real
  1080p upload before I caught it — peak memory went from 2.6GB down to
  ~170MB on the same 4K test file once this was fixed.
- Runs as an async background job (submit, then poll for status) instead of
  a synchronous request. I added this after finding Render's shared CPU runs
  the pipeline about 4.7x slower than my own machine, which made a
  synchronous request impractical at real match-segment lengths.

### 3. Outreach Assistant (optional) — draft the first email
Every recruiting guide I found while researching this says the same thing:
passive profile-browsing doesn't get you seen — direct outreach to a coach
does. And knowing how to actually write that outreach is exactly the kind of
insider knowledge a first-generation recruiting family usually doesn't have.
Comparator and Moment-Finder both hand you real material — a real program, a
real clip — but stop one step short of the thing you actually have to do
with it. This closes that gap.

Pick a program (from a Comparator result or by browsing the full national
list), answer a few optional questions about yourself, and get a draft
first-contact email.

**The safeguard, and I tested it hard:** the model is instructed to never
invent a coach's name, email address, or contact-period date. Anything you
didn't give it shows up as a bracketed placeholder — things like
`[Coach's name — check the athletics staff directory]`. There's also a
static disclaimer (not AI-generated) reminding you to verify contact details
yourself, and that a non-response is often about NCAA contact-period timing,
not disinterest.

I didn't just assume this safeguard would hold — I tested it adversarially,
across three rounds. The cheaper model (Haiku) reliably avoided inventing
facts, but it also kept dropping facts I *did* give it — genericizing away a
specific reason a player gave for being interested in a program, even when
the prompt explicitly told it not to. Switching to a bigger model (Sonnet)
plus a worked example in the prompt fixed that, while keeping the
no-invention behavior intact across every test I ran.

## Why two features are "validated" and one is an "assistant"

That distinction is intentional, not me hedging. Comparator and Moment-Finder
only ever show real data — a real roster row, a real timestamp in your own
footage. Neither one predicts or scores anything about the person using it.
Outreach Assistant is a different kind of thing: it's a language model
writing prose. It's useful, and I stress-tested it against the one failure
mode that would make it actively harmful — inventing facts — but it's not the
same category of tool as the other two, and I'd rather be upfront about that
than call all three equally "validated."

## What I tried and killed

Two features got built, tested rigorously, and thrown out, because the data
didn't back them up:

- **A division-fit predictor** (XGBoost, guessing D1/D2/D3/NAIA from a
  player's position/height/hometown) — full writeup in
  `fit_match_finding.md`. I found two real data leaks: one where a website
  quirk was masquerading as signal, and one where the effective sample size
  was 43 schools, not 2,062 players. What real signal survived was
  statistically real but way too weak to act on.
- **An income-equity index** (matching hometown to Census median income) —
  full writeup in `data/equity_finding.md`. Looked like a strong result at
  first, until I controlled for region of the country, at which point it
  dropped out of significance at this sample size. What does survive — D3
  programs recruiting from wealthier-than-average towns even after that
  control — points to something genuinely interesting (D3 doesn't offer
  athletic scholarships), but this dataset can't confirm that. I'd need
  financial-aid data for that, not rosters.

Neither of these shipped. I wrote both up in full because finding and
killing a bad idea is as much a part of this project as what actually made
it into the app.

## Architecture

- **Backend:** FastAPI (Python), deployed on Render. XGBoost (evaluation
  only — not in the deployed API), OpenCV + PySceneDetect (Moment-Finder),
  Anthropic API (Outreach Assistant).
- **Frontend:** React + Vite, deployed on Vercel. No component framework
  beyond React itself, custom CSS design system.
- **Data:** `data/program_roster_master.csv` (the 43-school scrape,
  Comparator's source of truth), `data/all_programs.csv` (the 2,244-program
  national directory, Outreach Assistant's "browse all" source).

## Known limitations, as of submission

- Moment-Finder's upload cap (20 min / 500MB) is about Render's shared-CPU
  speed, not a ceiling on the actual pipeline — I validated it locally on a
  full 59-minute match with no issues.
- The async job store is in-memory and single-process. A mid-job server
  restart loses that job. Fine for a demo, would need real persistence for
  production.
- `all_programs.csv`'s D3/NAIA rows have no conference data — the only
  sport-specific source I found for those divisions doesn't publish it.
- Moment-Finder's recall hasn't been formally measured against a
  hand-labeled set yet, though I did manually spot-check it against real
  footage (above). `eval_recall.py` is built and ready for that — I just
  ran out of time.

## Running it locally

```bash
# Backend
pip install -r requirements.txt
python check_deps.py   # confirms cv2/ffmpeg work on your machine
uvicorn main:app --reload
# needs env vars: API_SECRET_KEY, ANTHROPIC_API_KEY (Outreach Assistant only)

# Frontend
cd frontend
npm install
npm run dev
# needs frontend/.env.local: VITE_API_KEY=<same value as API_SECRET_KEY>
```
