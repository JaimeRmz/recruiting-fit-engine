"""
Build data/all_programs.csv -- a program-LEVEL national soccer directory for the
Outreach Assistant's "browse all programs" selector.

This is DELIBERATELY separate from data/program_roster_master.csv (the 43-school
roster the Comparator uses). It carries no player data -- just, per program:
    school, division (D1/D2/D3/NAIA), conference, state, gender (M/W)

SOURCES (each is soccer-specific -- it lists schools that actually field soccer in
that division/gender; we never assert sponsorship a source doesn't state):
  * NCAA D1 & D2, men's & women's:  Wikipedia "List of NCAA Division ... soccer
    programs" tables. These include conference.
  * NCAA D3 & NAIA, men's & women's:  ncsasports.org division/NAIA soccer college
    lists. Wikipedia has NO soccer-specific D3 or NAIA list (only general member-
    institution lists, which don't say which schools field soccer, so using them
    would fabricate sponsorship). NCSA's lists ARE soccer-specific. They do not
    publish conference, so conference is left blank for D3/NAIA rows -- blank, not
    guessed.

Run:  python build_all_programs.py
"""
import html as _html
import io
import os
import re
import sys

import pandas as pd
import requests

UA = {"User-Agent": "recruiting-fit-engine/1.0 (educational; program directory build)"}
OUT = os.path.join("data", "all_programs.csv")

WIKI_SOURCES = [
    ("D1", "M", "https://en.wikipedia.org/wiki/List_of_NCAA_Division_I_men%27s_soccer_programs"),
    ("D1", "W", "https://en.wikipedia.org/wiki/List_of_NCAA_Division_I_women%27s_soccer_programs"),
    ("D2", "M", "https://en.wikipedia.org/wiki/List_of_NCAA_Division_II_men%27s_soccer_programs"),
    ("D2", "W", "https://en.wikipedia.org/wiki/List_of_NCAA_Division_II_women%27s_soccer_programs"),
]
NCSA_SOURCES = [
    ("D3", "M", "mens-soccer", "https://www.ncsasports.org/mens-soccer/division-3-colleges"),
    ("D3", "W", "womens-soccer", "https://www.ncsasports.org/womens-soccer/division-3-colleges"),
    ("NAIA", "M", "mens-soccer", "https://www.ncsasports.org/mens-soccer/naia-colleges"),
    ("NAIA", "W", "womens-soccer", "https://www.ncsasports.org/womens-soccer/naia-colleges"),
]

_SMALL = {"of", "and"}  # keep lowercase inside a state name (e.g. District of Columbia)


def _get(url):
    r = requests.get(url, headers=UA, timeout=45)
    r.raise_for_status()
    r.encoding = "utf-8"  # Wikipedia + NCSA are UTF-8; force it so en-dashes survive
    return r.text


def _clean(s):
    if not isinstance(s, str):
        s = "" if s is None else str(s)
    s = re.sub(r"\[.*?\]", "", s)          # footnote markers: [5], [note 1]
    s = s.replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def _pick(cols, *names):
    low = {str(c).strip().lower(): c for c in cols}
    for n in names:
        if n.lower() in low:
            return low[n.lower()]
    return None


def _norm_state(s):
    """Canonicalize state spelling so the same state from different sources merges
    (Wikipedia vs NCSA differ on D.C. and the Hawaii okina)."""
    s = _clean(s)
    return {
        "D.C.": "District of Columbia",
        "DC": "District of Columbia",
        "Hawai'i": "Hawaii",
        "Hawaiʻi": "Hawaii",
    }.get(s, s)


def _state_from_slug(slug):
    return " ".join(w if w in _SMALL else w.capitalize() for w in slug.split("-"))


def from_wikipedia():
    rows = []
    for div, gender, url in WIKI_SOURCES:
        tables = pd.read_html(io.StringIO(_get(url)))
        df = max(tables, key=len)          # the program table is the largest one
        cols = df.columns.tolist()
        c_school = _pick(cols, "Institution", "School")
        c_state = _pick(cols, "State", "State/ Province", "State/Province")
        c_conf = _pick(cols, "Conference")
        if not c_school:
            raise RuntimeError(f"{div} {gender}: no school column in {cols}")
        n = 0
        for _, row in df.iterrows():
            school = _clean(row[c_school])
            if not school or school.lower() == "nan":
                continue
            rows.append({
                "school": school, "division": div,
                "conference": _clean(row[c_conf]) if c_conf else "",
                "state": _norm_state(row[c_state]) if c_state else "",
                "gender": gender,
            })
            n += 1
        print(f"  wiki {div} {gender}: {n}")
    return rows


def from_ncsa():
    rows = []
    for div, gender, gslug, url in NCSA_SOURCES:
        text = _get(url)
        pat = re.compile(
            r'href="https://www\.ncsasports\.org/athletic-scholarships/'
            + re.escape(gslug) + r'/([^/]+)/([^"]+)"[^>]*>(.*?)</a>', re.S)
        seen = {}
        for state_slug, _school_slug, anchor in pat.findall(text):
            name = _clean(_html.unescape(re.sub(r"<[^>]+>", "", anchor)))
            if name and name.lower() not in seen:
                seen[name.lower()] = (name, state_slug)
        if not seen:
            raise RuntimeError(f"{div} {gender}: no school links parsed from {url}")
        for name, state_slug in seen.values():
            rows.append({
                "school": name, "division": div, "conference": "",
                "state": _norm_state(_state_from_slug(state_slug)), "gender": gender,
            })
        print(f"  ncsa {div} {gender}: {len(seen)}")
    return rows


def main():
    print("fetching Wikipedia (D1/D2)...")
    rows = from_wikipedia()
    print("fetching NCSA (D3/NAIA)...")
    rows += from_ncsa()

    df = pd.DataFrame(rows, columns=["school", "division", "conference", "state", "gender"])
    before = len(df)
    df = df.drop_duplicates(subset=["school", "gender", "division"])
    df = df.sort_values(["school", "gender", "division"], kind="stable").reset_index(drop=True)

    os.makedirs("data", exist_ok=True)
    df.to_csv(OUT, index=False, encoding="utf-8")

    print(f"\nwrote {OUT}: {len(df)} programs ({before - len(df)} duplicate rows dropped)")
    print("\nby division / gender:")
    print(df.groupby(["division", "gender"]).size().to_string())
    print("\nby division:")
    print(df.groupby("division").size().to_string())
    print(f"\ndistinct schools: {df['school'].nunique()} | states: {df['state'].nunique()}")

    # Sanity check against expected scale; flag anything that looks like a parse error.
    exp = {("D1", "M"): 213, ("D1", "W"): 349, ("D2", "M"): 201, ("D2", "W"): 258}
    counts = df.groupby(["division", "gender"]).size().to_dict()
    warn = []
    for k, e in exp.items():
        got = counts.get(k, 0)
        if abs(got - e) > max(15, e * 0.1):
            warn.append(f"{k}: got {got}, expected ~{e}")
    for k in [("D3", "M"), ("D3", "W"), ("NAIA", "M"), ("NAIA", "W")]:
        if counts.get(k, 0) < 100:
            warn.append(f"{k}: only {counts.get(k, 0)} (expected 100s) -- possible parse break")
    if warn:
        print("\n!! SANITY WARNINGS:")
        for w in warn:
            print("   -", w)
        sys.exit(1)
    print("\nsanity: all division/gender counts within expected scale.")


if __name__ == "__main__":
    main()
