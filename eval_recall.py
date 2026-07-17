"""
Measure Moment-Finder recall against hand-labeled real moments.

Recall is the metric that matters for a review queue: how many moments a human
would want landed within reach. Precision is not optimized -- a false positive
costs a few seconds to skip, a false negative is a real moment never surfaced.

LABEL FORMAT
    A CSV with a header row `timestamp,description`, then one row per notable
    moment. `timestamp` is mm:ss (e.g. 6:31), mm:ss.ss (6:31.80), h:mm:ss, or plain
    seconds (391.8). `description` is free text -- what the moment is. Lines
    starting with `#` are ignored. See data/moment_labels_template.csv.

USAGE
    python eval_recall.py <video.mp4> <labels.csv> [--tolerance 3] [--percentile 92]

Writes moment_finder_evaluation.md next to this script.
"""
import argparse
import csv
import os

from moment_finder import find_moments

OUT_MD = "moment_finder_evaluation.md"


def parse_timestamp(s):
    """'6:31' / '06:31.80' / '1:02:03' / '391.8' -> seconds (float)."""
    s = s.strip()
    if ":" in s:
        sec = 0.0
        for part in s.split(":"):
            sec = sec * 60 + float(part)
        return sec
    return float(s)


def load_labels(csv_path):
    """Return [(seconds, description), ...] from the label CSV."""
    labels = []
    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.reader(fh):
            if not row or not row[0].strip() or row[0].lstrip().startswith("#"):
                continue
            if row[0].strip().lower() in ("timestamp", "time"):  # header
                continue
            try:
                sec = parse_timestamp(row[0])
            except ValueError:
                print(f"  skipping unparseable timestamp: {row[0]!r}")
                continue
            desc = row[1].strip() if len(row) > 1 else ""
            labels.append((sec, desc))
    return labels


def compute_recall(candidate_times, labels, tolerance):
    """
    Match each labeled moment to the nearest candidate within `tolerance` seconds.

    Returns per_label [(sec, desc, hit_bool, nearest_gap)], and the set of candidate
    indices that matched at least one label (the "useful" candidates).
    """
    per_label = []
    matched_candidates = set()
    for sec, desc in labels:
        best_i, best_gap = None, None
        for i, c in enumerate(candidate_times):
            gap = abs(c - sec)
            if best_gap is None or gap < best_gap:
                best_i, best_gap = i, gap
        hit = best_gap is not None and best_gap <= tolerance
        if hit:
            matched_candidates.add(best_i)
        per_label.append((sec, desc, hit, best_gap))
    return per_label, matched_candidates


def fmt_ts(sec):
    m, s = divmod(sec, 60)
    return f"{int(m):02d}:{s:05.2f}"


def evaluate(video, labels_csv, tolerance=3.0, percentile=92.0):
    labels = load_labels(labels_csv)
    if not labels:
        raise SystemExit(f"No labels found in {labels_csv}.")

    print(f"labels: {len(labels)} hand-marked moments")
    print(f"running find_moments on {video} (percentile={percentile}) ...")
    cands = find_moments(video, motion_percentile=percentile, write_clips=False)
    cand_times = [c.time for c in cands]
    print(f"candidates: {len(cand_times)}")

    per_label, matched = compute_recall(cand_times, labels, tolerance)
    hits = sum(1 for _, _, hit, _ in per_label if hit)
    recall = hits / len(labels)
    n_cand = len(cand_times)
    extra = n_cand - len(matched)
    extra_frac = extra / n_cand if n_cand else 0.0

    print(f"\nrecall: {hits}/{len(labels)} = {recall:.0%} (within +/-{tolerance:.0f}s)")
    print(f"candidates matching a labeled moment: {len(matched)}/{n_cand}")

    write_markdown(video, labels_csv, tolerance, percentile, per_label,
                   n_cand, hits, recall, len(matched), extra, extra_frac)
    print(f"wrote {OUT_MD}")


def write_markdown(video, labels_csv, tol, pct, per_label, n_cand, hits, recall,
                   matched, extra, extra_frac):
    n = len(per_label)
    missed = [(s, d, g) for s, d, hit, g in per_label if not hit]

    lines = [
        "# Moment-Finder evaluation: recall on hand-labeled footage",
        "",
        f"- **Footage:** `{os.path.basename(video)}`",
        f"- **Ground truth:** `{os.path.basename(labels_csv)}` "
        f"({n} hand-labeled notable moments)",
        f"- **Match tolerance:** a labeled moment counts as *caught* if a candidate "
        f"lands within +/-{tol:.0f}s of it.",
        f"- **Detector setting:** {pct:.0f}th-percentile motion threshold (default).",
        "",
        "## Headline",
        "",
        f"**Recall: {hits} of {n} labeled moments caught = {recall:.0%}.** "
        f"The tool surfaced **{n_cand} candidates** total; **{matched}** of them "
        f"landed on a labeled moment, and **{extra}** ({extra_frac:.0%}) are extra "
        "clips a human skips past.",
        "",
        "## What these numbers mean (and don't)",
        "",
        "This is a **recall-focused review tool, not a precision classifier**, and "
        "the numbers should be read that way:",
        "",
        f"- **Recall ({recall:.0%}) is the number that matters.** A missed real "
        "moment is the actual cost -- it never reaches the editor's eye. Recall is "
        "what this tool is built to protect.",
        f"- **The {extra_frac:.0%} of candidates that are \"extra\" is by design, "
        "not a defect.** Precision is intentionally left low: a false positive "
        "costs a few seconds to skip, so the tool errs toward surfacing more rather "
        "than risk dropping a real moment. Calling this \"low precision\" misreads "
        "the goal.",
        "- The tool still does **no event recognition** -- it does not know a "
        "candidate is a goal, a save, or a throw-in. A human makes every keep/skip "
        "call. These numbers measure how much scrubbing it saves, not judgment it "
        "replaces.",
        "",
        "## Per-moment detail",
        "",
        "| labeled moment | description | caught? | nearest candidate |",
        "|---|---|---|---|",
    ]
    for sec, desc, hit, gap in per_label:
        gaptxt = f"{gap:.1f}s away" if gap is not None else "none"
        lines.append(f"| {fmt_ts(sec)} | {desc or '-'} | "
                     f"{'yes' if hit else '**MISSED**'} | {gaptxt} |")

    if missed:
        lines += ["", "## Missed moments (recall failures -- the real cost)", ""]
        for sec, desc, gap in missed:
            near = f"nearest candidate {gap:.1f}s away" if gap is not None else "no candidates"
            lines.append(f"- **{fmt_ts(sec)}** {desc or ''} ({near}, outside the "
                         f"+/-{tol:.0f}s window)")
    else:
        lines += ["", "_Every labeled moment was caught within tolerance._"]

    lines += [
        "",
        "## Honest caveats",
        "",
        f"- **Single footage sample.** This is one video ({n} moments); it is an "
        "indication, not a benchmark. Recall on other camera setups (broadcast vs. "
        "sideline tripod vs. phone) will differ.",
        "- **Labels are one person's judgment** of what counts as notable. A "
        "different labeler would draw the line differently, especially on marginal "
        "moments.",
        f"- **Tolerance is a choice.** At +/-{tol:.0f}s a candidate 'catches' a "
        "moment; a stricter window would lower recall. The clip window "
        "(4.5s before / 5s after) is wider than the tolerance, so a caught moment "
        "is actually visible in its clip.",
        "",
    ]
    with open(OUT_MD, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("labels", help="CSV of hand-labeled moments (timestamp,description)")
    ap.add_argument("--tolerance", type=float, default=3.0,
                    help="seconds; a candidate within this of a label counts (default 3)")
    ap.add_argument("--percentile", type=float, default=92.0,
                    help="motion threshold percentile (default 92, matches the API)")
    a = ap.parse_args()
    evaluate(a.video, a.labels, a.tolerance, a.percentile)
