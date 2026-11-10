"""
Scrape soccer-coach emails from the /staff-directory page of every school
already in data/seed_roster_urls.csv into data/coach_directory.csv.

A deliberately separate dataset from data/program_roster_master.csv: it's a
different page type (staff directory, not roster), scraped once per SCHOOL
rather than once per roster URL (the directory covers both genders already),
and it goes stale on a different clock -- coaching turnover, not eligibility
years -- hence the explicit scrape_date column.

Scoped to the same 43 schools already validated for rosters on purpose, not
the larger 2,244-program national list -- see parser.py's module docstring
for how the two real staff-directory sub-templates (card blocks vs. one long
table) were confirmed against live fetches before writing the parsers.

Usage:
    python scrape_coaches.py            # full run, all 43 schools
    python scrape_coaches.py --limit 5  # smoke test on the first 5 schools
"""
import argparse
import time
from datetime import date
from urllib.parse import urlparse

import pandas as pd
import requests
from markdownify import markdownify

from parser import parse_sidearm_staff_directory, parse_wmt_staff_directory

SEED = "data/seed_roster_urls.csv"
OUT = "data/coach_directory.csv"
DELAY = 1.5
TIMEOUT = 25
SPORT = "soccer"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

PARSERS = {
    "sidearm": parse_sidearm_staff_directory,
    "wmt": parse_wmt_staff_directory,
}


def load_schools(seed_path=SEED):
    """One row per school (not per roster URL -- /staff-directory is site-wide,
    covering both genders already). Errors loudly if a school's roster rows
    disagree on domain/division/template rather than silently picking one."""
    seed = pd.read_csv(seed_path)
    seed["domain"] = seed["url"].apply(lambda u: "{0.scheme}://{0.netloc}".format(urlparse(u)))
    check_cols = ["division", "template", "domain"]
    inconsistent = seed.groupby("school")[check_cols].nunique()
    bad = inconsistent[(inconsistent > 1).any(axis=1)]
    if len(bad):
        raise ValueError(f"school(s) disagree on division/template/domain across roster rows: {list(bad.index)}")
    schools = seed.drop_duplicates("school")[["school"] + check_cols].reset_index(drop=True)
    schools["staff_url"] = schools["domain"] + "/staff-directory"
    return schools[["school", "division", "template", "staff_url"]]


def fetch_markdown(url):
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return markdownify(r.text)


def scrape(seed_path=SEED, out_path=OUT, limit=None, delay=DELAY):
    schools = load_schools(seed_path)
    if limit:
        schools = schools.head(limit)

    scrape_date = date.today().isoformat()
    frames, empty, failures, misfires = [], [], [], []

    for i, row in enumerate(schools.itertuples(index=False), 1):
        parse_fn = PARSERS.get(row.template)
        if parse_fn is None:
            failures.append((row.school, row.staff_url, f"no parser for template '{row.template}'"))
            print(f"[{i:>2}/{len(schools)}] FAIL {row.school:<16} unknown template '{row.template}'")
            continue
        try:
            md = fetch_markdown(row.staff_url)
            df = parse_fn(md, row.school, row.division, SPORT)
            if df.empty:
                empty.append(row.school)
                print(f"[{i:>2}/{len(schools)}] empty {row.school:<16} 0 soccer staff rows found")
            else:
                df["source_template"] = row.template
                df["scrape_date"] = scrape_date
                n_email = df["coach_email"].notna().sum()
                frames.append(df)
                print(f"[{i:>2}/{len(schools)}] ok    {row.school:<16} {row.template:<8} "
                      f"{len(df):>2} staff, {n_email:>2} with email")
        except requests.HTTPError as e:
            failures.append((row.school, row.staff_url, f"HTTP {e.response.status_code}"))
            print(f"[{i:>2}/{len(schools)}] FAIL  {row.school:<16} HTTP {e.response.status_code}")
        except Exception as e:  # network, encoding, parser blowup -> skip, never crash the run
            failures.append((row.school, row.staff_url, f"{type(e).__name__}: {e}"))
            print(f"[{i:>2}/{len(schools)}] FAIL  {row.school:<16} {type(e).__name__}: {e}")

        if i < len(schools):
            time.sleep(delay)

    if not frames:
        print("\nNothing parsed - leaving", out_path, "untouched.")
        return None

    master = pd.concat(frames, ignore_index=True)
    column_order = ["school", "division", "sport", "gender", "coach_name", "coach_title",
                     "coach_email", "source_template", "scrape_date"]
    master = master[column_order]
    master.to_csv(out_path, index=False)

    print("\n" + "=" * 66)
    print(f"schools scraped     : {len(schools)}")
    print(f"schools w/ >=1 email: {sum(1 for f in frames if f['coach_email'].notna().any())}")
    print(f"schools empty       : {len(empty)}  {empty}")
    print(f"staff rows written  : {len(master)}  ({master['coach_email'].notna().sum()} with email)")
    print(f"written to          : {out_path}")
    print(f"by gender           : {master['gender'].value_counts(dropna=False).to_dict()}")

    if failures:
        print(f"\n{len(failures)} school(s) failed to fetch/parse:")
        for school, url, why in failures:
            print(f"  {school:<16} {why}")
            print(f"      {url}")
    else:
        print("\nno fetch failures.")
    print("=" * 66)
    return master


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="only scrape the first N schools")
    ap.add_argument("--delay", type=float, default=DELAY, help="seconds between requests")
    args = ap.parse_args()
    scrape(limit=args.limit, delay=args.delay)
