"""
Scrape every roster in data/seed_roster_urls.csv into one master table.

Pipeline per URL:
    requests (real UA) -> HTML -> markdownify -> detect template -> parse -> normalize

Why the markdownify step: parser.py consumes *markdown* (parse_wmt matches `**12**`
and `[Name](url)`; parse_sidearm_table matches `| # | Full Name | ...`). requests
returns raw HTML, which matches neither. markdownify reconstructs the exact shapes
both parsers already expect, so parser.py is used unmodified.

Usage:
    python scrape_rosters.py            # full run
    python scrape_rosters.py --limit 5  # smoke test on first 5 URLs
"""
import argparse
import re
import sys
import time
from collections import Counter

import pandas as pd
import requests
from markdownify import markdownify

from parser import parse_wmt, parse_sidearm_table

SEED = "data/seed_roster_urls.csv"
OUT = "data/program_roster_master.csv"
DELAY = 1.5          # seconds between requests
MIN_ROWS = 8         # fewer named players than this => we grabbed the wrong table
TIMEOUT = 25

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# --- Sidearm header dialects -------------------------------------------------
# Sidearm sites do not agree on column names: the roster header may say
# "Full Name" or "Name"; "Academic Year", "Yr.", "Year", "Cl." or "Class";
# "Hometown/Previous School", "Hometown / High School" or just "Hometown".
# parse_sidearm_table looks up one fixed spelling of each, so we canonicalize
# the header row to the spellings it expects before handing the table over.
NAME_COLS = {"full name", "name", "player"}
CANON_HEADER = {
    "#": "#", "no.": "#", "no": "#", "num": "#",
    "full name": "Full Name", "name": "Full Name", "player": "Full Name",
    "pos.": "Pos.", "pos": "Pos.", "position": "Pos.",
    "academic year": "Academic Year", "yr.": "Academic Year", "yr": "Academic Year",
    "year": "Academic Year", "cl.": "Academic Year", "cl": "Academic Year",
    "class": "Academic Year",
    "hometown/previous school": "Hometown/Previous School",
    "hometown / high school": "Hometown/Previous School",
    "hometown/high school": "Hometown/Previous School",
    "hometown / previous school": "Hometown/Previous School",
    "hometown": "Hometown/Previous School",
    "ht.": "Ht.", "ht": "Ht.", "height": "Ht.",
    "major": "Major", "club team": "Club Team", "club": "Club Team",
}

# --- Normalization (step 5) --------------------------------------------------
POSITION_MAP = {
    "gk": "GK", "g": "GK", "goalkeeper": "GK", "goalie": "GK", "keeper": "GK",
    "d": "D", "df": "D", "def": "D", "defender": "D", "defense": "D",
    "b": "D", "back": "D", "fullback": "D", "def.": "D",
    "m": "M", "mf": "M", "mid": "M", "midfield": "M", "midfielder": "M",
    "f": "F", "fw": "F", "fwd": "F", "for": "F", "forward": "F",
    "s": "F", "striker": "F", "a": "F", "att": "F", "attacker": "F", "winger": "F",
    # Note: "Team Impact" stays unmapped on purpose - it is an honorary roster
    # designation, not a playing position, so it should land as None.
}
CLASS_YEAR_MAP = {
    "fr": "Fr", "fresh": "Fr", "freshman": "Fr",
    "fy": "Fr", "first year": "Fr", "first-year": "Fr",  # D3 sites favor "Fy."
    "so": "So", "soph": "So", "sophomore": "So",
    "jr": "Jr", "junior": "Jr",
    "sr": "Sr", "senior": "Sr",
    # Graduate / 5th- / 6th-year players sit with seniors, matching parser.CLASS_MAP's "gr" -> "Sr".
    "gr": "Sr", "grad": "Sr", "graduate": "Sr", "gs": "Sr",
    "5th": "Sr", "5": "Sr", "6th": "Sr", "6": "Sr",
}

UNMAPPED_POS, UNMAPPED_YEAR = Counter(), Counter()


def normalize_position(raw):
    """'Goalkeeper'/'GK'/'M/D' -> GK, GK, M. Multi-position keeps the primary listing."""
    if not raw or not str(raw).strip():
        return None
    primary = re.split(r"[/,;&]| or ", str(raw).strip(), maxsplit=1)[0]
    key = primary.strip().strip(".").lower()
    if key in POSITION_MAP:
        return POSITION_MAP[key]
    UNMAPPED_POS[str(raw).strip()] += 1
    return None


def normalize_class_year(raw):
    """'Fr.'/'Freshman'/'R-Fr' -> Fr. Redshirt prefixes collapse to the base year."""
    if not raw or not str(raw).strip():
        return None
    key = str(raw).strip().strip(".").lower()
    key = re.sub(r"^(r|rs|redshirt|red-shirt)[\s.\-]+", "", key)  # R-Fr, Redshirt Freshman
    key = key.strip().strip(".")
    if key in CLASS_YEAR_MAP:
        return CLASS_YEAR_MAP[key]
    UNMAPPED_YEAR[str(raw).strip()] += 1
    return None


# --- Fetch / detect / parse --------------------------------------------------
def fetch_markdown(url):
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return markdownify(r.text)


def _markdown_tables(md):
    """Split page markdown into contiguous pipe-table blocks."""
    blocks, cur = [], []
    for line in md.split("\n"):
        if line.strip().startswith("|"):
            cur.append(line.strip())
        elif cur:
            blocks.append(cur)
            cur = []
    if cur:
        blocks.append(cur)
    return blocks


def extract_roster_table(md):
    """
    Return the roster table with a canonicalized header, or None.

    Rosters are not always the first table on the page (many Sidearm pages open
    with a '| Statistic |' block). Selecting blindly on lines[0] makes
    parse_sidearm_table read the wrong header and emit all-None rows, so match
    on a header that actually looks like a roster: a '#' column plus a name column.
    """
    for block in _markdown_tables(md):
        if len(block) < 3:
            continue
        header = [c.strip() for c in block[0].strip("|").split("|")]
        lowered = [c.lower() for c in header]
        if "#" not in lowered or not (NAME_COLS & set(lowered)):
            continue
        canon = [CANON_HEADER.get(low, orig) for low, orig in zip(lowered, header)]
        body = [r for r in block[2:] if r.count("|") >= len(header)]
        if not body:
            continue
        sep = "| " + " | ".join("---" for _ in canon) + " |"
        return "\n".join(["| " + " | ".join(canon) + " |", sep] + body)
    return None


def detect_and_parse(md, school, division, gender):
    """
    Detect the template live from page content and run the matching parser.
    The seed CSV's `template` column is deliberately ignored here so a mislabeled
    row still scrapes correctly; mismatches are reported in the summary instead.

    Returns (DataFrame, template_name) or (None, reason).
    """
    table = extract_roster_table(md)          # Sidearm: markdown table headed by "| #"
    if table is not None:
        df = parse_sidearm_table(table, school, division, gender)
        df = df[df["name"].notna()]
        if len(df) >= MIN_ROWS:
            return df, "sidearm"

    if md.count("**") > 20:                   # WMT: card-style **jersey** blocks
        df = parse_wmt(md, school, division, gender)
        df = df[df["name"].notna()]
        if len(df) >= MIN_ROWS:
            return df, "wmt"

    if table is not None:
        return None, "matched a roster table but parsed <%d players" % MIN_ROWS
    return None, "no Sidearm table and no WMT card blocks found"


def scrape(seed_path=SEED, out_path=OUT, limit=None, delay=DELAY):
    seed = pd.read_csv(seed_path)
    if limit:
        seed = seed.head(limit)

    frames, failures, mislabeled = [], [], []

    for i, row in enumerate(seed.itertuples(index=False), 1):
        label = f"{row.school} ({row.division} {row.gender})"
        try:
            md = fetch_markdown(row.url)
            df, info = detect_and_parse(md, row.school, row.division, row.gender)
            if df is None:
                failures.append((label, row.url, info))
                print(f"[{i:>2}/{len(seed)}] FAIL {label:<34} {info}")
            else:
                seed_tpl = str(getattr(row, "template", "")).strip().lower()
                if seed_tpl and seed_tpl != info:
                    mislabeled.append((label, seed_tpl, info))
                frames.append(df)
                print(f"[{i:>2}/{len(seed)}] ok   {label:<34} {info:<8} {len(df):>3} players")
        except requests.HTTPError as e:
            failures.append((label, row.url, f"HTTP {e.response.status_code}"))
            print(f"[{i:>2}/{len(seed)}] FAIL {label:<34} HTTP {e.response.status_code}")
        except Exception as e:                # network, encoding, parser blowup -> skip, never crash
            failures.append((label, row.url, f"{type(e).__name__}: {e}"))
            print(f"[{i:>2}/{len(seed)}] FAIL {label:<34} {type(e).__name__}: {e}")

        if i < len(seed):
            time.sleep(delay)

    if not frames:
        print("\nNothing parsed - leaving", out_path, "untouched.")
        return None

    master = pd.concat(frames, ignore_index=True)
    master["position"] = master["position"].apply(normalize_position)
    master["class_year"] = master["class_year"].apply(normalize_class_year)
    master.to_csv(out_path, index=False)

    # ---------------- summary ----------------
    print("\n" + "=" * 62)
    print(f"schools scraped : {master['school'].nunique()}  ({len(frames)}/{len(seed)} rosters)")
    print(f"players         : {len(master)}")
    print(f"written to      : {out_path}")

    by_div = master.groupby("division")["school"].nunique().to_dict()
    print(f"by division     : {by_div}")
    print(f"by gender       : {master['gender'].value_counts().to_dict()}")
    print(f"positions       : {master['position'].value_counts().to_dict()}")
    print(f"class years     : {master['class_year'].value_counts().to_dict()}")

    if mislabeled:
        print(f"\nseed template column wrong on {len(mislabeled)} row(s) (live detection won):")
        for label, said, was in mislabeled:
            print(f"  {label:<34} seed said {said}, actually {was}")

    if UNMAPPED_POS:
        print(f"\nunmapped positions -> None (extend POSITION_MAP): {dict(UNMAPPED_POS)}")
    if UNMAPPED_YEAR:
        print(f"unmapped class years -> None (extend CLASS_YEAR_MAP): {dict(UNMAPPED_YEAR)}")

    if failures:
        print(f"\n{len(failures)} URL(s) failed - fix these by hand:")
        for label, url, why in failures:
            print(f"  {label:<34} {why}")
            print(f"      {url}")
    else:
        print("\nno failures.")
    print("=" * 62)
    return master


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="only scrape the first N URLs")
    ap.add_argument("--delay", type=float, default=DELAY, help="seconds between requests")
    args = ap.parse_args()
    scrape(limit=args.limit, delay=args.delay)
