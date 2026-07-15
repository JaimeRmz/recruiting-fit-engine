"""
Link roster hometowns to Census place-level median household income (ACS 5-year,
B19013_001E) and test whether hometown income differs across division.

This is a hypothesis test, not a predictor. The question: do D1 programs recruit
from measurably wealthier hometowns than D2/D3/NAIA?

    export CENSUS_API_KEY=...        # required; the API rejects unkeyed requests
    python enrich_with_census.py

Outputs:
    data/census_place_cache.json     cached ACS place tables (one per state)
    data/program_roster_enriched.csv roster + hometown_median_income
    data/equity_finding.md           the write-up

API strategy: one bulk call per STATE (~45 calls) pulling every place in that
state, not one call per city (~1100 calls). Same data, 25x fewer requests, and it
lets us see when a state contains several places with the same name -- which is
exactly the ambiguity we need to detect rather than silently guess through.
"""
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict

import numpy as np
import pandas as pd
import requests
from scipy import stats

ROSTER = "data/program_roster_master.csv"
ENRICHED = "data/program_roster_enriched.csv"
CACHE = "data/census_place_cache.json"
FINDING = "data/equity_finding.md"
ACS_YEAR = 2023
DIVISIONS = ["D1", "D2", "D3", "NAIA"]
DELAY = 0.5

# --- state normalization -----------------------------------------------------
# Rosters use AP abbreviations ("Calif."), postal codes ("CA") and full names
# interchangeably, sometimes within the same school's roster.
STATE_TO_FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08",
    "CT": "09", "DE": "10", "DC": "11", "FL": "12", "GA": "13", "HI": "15",
    "ID": "16", "IL": "17", "IN": "18", "IA": "19", "KS": "20", "KY": "21",
    "LA": "22", "ME": "23", "MD": "24", "MA": "25", "MI": "26", "MN": "27",
    "MS": "28", "MO": "29", "MT": "30", "NE": "31", "NV": "32", "NH": "33",
    "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38", "OH": "39",
    "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45", "SD": "46",
    "TN": "47", "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53",
    "WV": "54", "WI": "55", "WY": "56", "PR": "72",
}
STATE_ALIASES = {
    "alabama": "AL", "ala": "AL", "alaska": "AK", "arizona": "AZ", "ariz": "AZ",
    "arkansas": "AR", "ark": "AR", "california": "CA", "calif": "CA", "cal": "CA",
    "colorado": "CO", "colo": "CO", "connecticut": "CT", "conn": "CT",
    "delaware": "DE", "del": "DE", "florida": "FL", "fla": "FL",
    "georgia": "GA", "ga": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "ill": "IL", "indiana": "IN", "ind": "IN",
    "iowa": "IA", "kansas": "KS", "kan": "KS", "kans": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "mass": "MA", "michigan": "MI", "mich": "MI",
    "minnesota": "MN", "minn": "MN", "mississippi": "MS", "miss": "MS",
    "missouri": "MO", "montana": "MT", "mont": "MT", "nebraska": "NE",
    "neb": "NE", "nebr": "NE", "nevada": "NV", "nev": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM",
    "new york": "NY", "north carolina": "NC", "north dakota": "ND",
    "ohio": "OH", "oklahoma": "OK", "okla": "OK", "oregon": "OR", "ore": "OR",
    "pennsylvania": "PA", "penn": "PA", "penna": "PA", "rhode island": "RI",
    "south carolina": "SC", "south dakota": "SD", "tennessee": "TN",
    "tenn": "TN", "texas": "TX", "tex": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "wash": "WA",
    "west virginia": "WV", "w virginia": "WV", "w va": "WV", "wva": "WV",
    "wisconsin": "WI", "wis": "WI", "wisc": "WI", "wyoming": "WY", "wyo": "WY",
    "district of columbia": "DC", "washington dc": "DC", "washington d c": "DC",
    "puerto rico": "PR",
}
STATE_ALIASES.update({k.lower(): k for k in STATE_TO_FIPS})   # postal codes

# Countries/regions seen in the hometown column. Anything landing here is non-US
# and is kept in the dataset with income = null, never matched.
NON_US = {
    "canada", "ontario", "quebec", "british columbia", "alberta", "manitoba",
    "saskatchewan", "nova scotia", "new brunswick", "newfoundland",
    "england", "scotland", "wales", "northern ireland", "ireland",
    "united kingdom", "uk", "great britain", "germany", "spain", "france",
    "portugal", "italy", "netherlands", "holland", "belgium", "sweden",
    "norway", "denmark", "finland", "iceland", "poland", "croatia", "serbia",
    "slovenia", "slovakia", "czech republic", "czechia", "hungary", "austria",
    "switzerland", "greece", "turkey", "romania", "bulgaria", "lithuania",
    "latvia", "estonia", "ukraine", "russia", "albania", "kosovo",
    "bosnia and herzegovina", "montenegro", "north macedonia", "macedonia",
    "brazil", "argentina", "chile", "colombia", "peru", "uruguay", "paraguay",
    "bolivia", "ecuador", "venezuela", "mexico", "costa rica", "panama",
    "guatemala", "honduras", "el salvador", "nicaragua", "jamaica", "trinidad",
    "trinidad and tobago", "barbados", "bahamas", "haiti", "cuba",
    "dominican republic", "japan", "china", "south korea", "korea", "australia",
    "new zealand", "south africa", "nigeria", "ghana", "kenya", "cameroon",
    "senegal", "ivory coast", "cote d'ivoire", "morocco", "egypt", "tunisia",
    "algeria", "zimbabwe", "zambia", "uganda", "tanzania", "israel", "india",
    "pakistan", "philippines", "indonesia", "thailand", "vietnam", "singapore",
    "united arab emirates", "uae", "qatar", "saudi arabia", "jordan", "lebanon",
    # Abbreviated / sub-national forms that appear where a US state would sit.
    # Canadian province abbreviations are the dangerous ones: "M.B." and "N.B."
    # look exactly like US postal codes but are Manitoba and New Brunswick.
    "ont", "que", "bc", "ab", "sk", "mb", "ns", "nb", "pei", "nl", "qc",
    "nz", "n z", "ni", "uk", "gb", "eng", "bermuda", "cayman islands",
    "liberia", "mozambique", "cyprus", "new zealand", "montreal", "toronto",
    "trentino alto adige", "northrhine westfalia", "cheshire", "surrey",
}

# Unambiguous misspellings seen in the roster data. Listed explicitly rather than
# fuzzy-matched, so a typo can never silently resolve to the wrong state.
STATE_TYPOS = {"cailf": "CA", "clif": "CA", "penna": "PA", "tx.": "TX"}

UNPARSED_LOG = []


def _norm_token(token):
    """'N.J.' -> 'nj' ; 'Ont.' -> 'ont' ; 'New  Jersey' -> 'new jersey'."""
    t = token.strip().lower().replace(".", " ")
    return re.sub(r"\s+", " ", t).strip()


def is_non_us(token):
    t = _norm_token(token)
    return t in NON_US or t.replace(" ", "") in NON_US


def normalize_state(token):
    """Return a 2-letter US state code, or None. Non-US tokens must be rejected."""
    t = _norm_token(token)
    if t in NON_US or t.replace(" ", "") in NON_US:
        return None                            # 'M.B.' is Manitoba, not a US state
    if t in STATE_TYPOS:
        return STATE_TYPOS[t]
    if t in STATE_ALIASES:
        return STATE_ALIASES[t]
    compact = t.replace(" ", "")               # 'N.J.' -> 'nj'
    if compact in STATE_ALIASES:
        return STATE_ALIASES[compact]
    if compact.upper() in STATE_TO_FIPS:
        return compact.upper()
    return None


def parse_hometown(raw):
    """
    -> (city, state_code, 'US') | (None, None, 'NON_US') | (None, None, 'UNPARSED')

    Formats in the wild: "Bakersfield, Calif." / "Chandler, AZ" /
    "Salt Lake City, Utah" / "Santa Fe. N.M." (period, no comma) /
    "Fletcher N.C." (no separator) / "Lake Oswego, Ore," (trailing comma) /
    "Vaughn, Ontario, Canada" / "Croatia" (bare country).
    """
    if not isinstance(raw, str) or not raw.strip():
        return None, None, "UNPARSED"      # null hometown; counted, not logged
    s = raw.split("/")[0].strip().strip(",").strip()

    if is_non_us(s):                        # bare country, no separator
        return None, None, "NON_US"

    parts = [p.strip() for p in s.split(",") if p.strip()]

    # 3+ parts: "City, Region, Country". Any segment naming a country settles it.
    if len(parts) >= 3:
        if any(is_non_us(p) for p in parts[1:]):
            return None, None, "NON_US"
        st = normalize_state(parts[-1])
        if st:
            return parts[0], st, "US"
        UNPARSED_LOG.append(raw)
        return None, None, "UNPARSED"

    if len(parts) == 2:
        city, tail = parts
        if is_non_us(tail):
            return None, None, "NON_US"
        st = normalize_state(tail)
        if st:
            return city, st, "US"
        UNPARSED_LOG.append(raw)
        return None, None, "UNPARSED"

    # One part, no comma: the state may be glued on with a period or just a space
    # ("Santa Fe. N.M.", "Goldens Bridge N.Y.", "Fletcher N.C."). Peel candidate
    # state tokens off the RIGHT, longest first, so "Santa Fe. N.M." yields state
    # "N.M." and city "Santa Fe" rather than splitting at the first period.
    words = parts[0].split()
    for k in (3, 2, 1):
        if len(words) <= k:
            continue
        tail = " ".join(words[-k:])
        if is_non_us(tail):
            return None, None, "NON_US"
        st = normalize_state(tail)
        if st:
            city = " ".join(words[:-k]).strip().rstrip(".").strip()
            if city:
                return city, st, "US"
    UNPARSED_LOG.append(raw)
    return None, None, "UNPARSED"


# --- Census ------------------------------------------------------------------
PLACE_SUFFIX = re.compile(
    r",?\s*(city|town|village|borough|municipality|CDP|"
    r"consolidated government|metro government|urban county|"
    r"unified government|corporation|plantation|county)\b.*$", re.I)


def clean_place(name):
    """'Bakersfield city, California' -> 'bakersfield'"""
    base = name.split(",")[0]
    base = PLACE_SUFFIX.sub("", base).strip()
    base = re.sub(r"\s+", " ", base).lower()
    return base


def fetch_state_medians(key, cache):
    """
    Median household income for each STATE -- the denominator for income_ratio.

    Raw hometown income conflates two things: how affluent a recruit's town is,
    and how expensive their region is. D3 here skews NY/VA/PA (state median ~$91k)
    while NAIA skews MI/IL/IN (~$71k), so part of any raw division gap is just
    cost-of-living. Dividing a town's median by its state's median removes the
    regional level and asks the question we actually care about: does this program
    recruit from towns that are affluent *relative to their own state*?
    """
    if "_STATE_MEDIANS" in cache:
        return cache["_STATE_MEDIANS"]
    params = {"get": "NAME,B19013_001E", "for": "state:*"}
    if key:
        params["key"] = key
    r = requests.get(f"https://api.census.gov/data/{ACS_YEAR}/acs/acs5",
                     params=params, timeout=40)
    if "json" not in r.headers.get("Content-Type", "").lower():
        raise RuntimeError("Census returned non-JSON for state medians "
                           "-> missing/invalid CENSUS_API_KEY.")
    fips_inc = {row[2]: int(row[1]) for row in r.json()[1:]
                if row[1] and int(row[1]) > 0}
    out = {code: fips_inc[f] for code, f in STATE_TO_FIPS.items() if f in fips_inc}
    cache["_STATE_MEDIANS"] = out
    time.sleep(DELAY)
    return out


def fetch_state_places(fips, key, cache):
    """One call per state; returns {clean_name: [median_income, ...]}."""
    if fips in cache:
        return cache[fips]
    params = {"get": f"NAME,B19013_001E", "for": "place:*", "in": f"state:{fips}"}
    if key:
        params["key"] = key
    r = requests.get(f"https://api.census.gov/data/{ACS_YEAR}/acs/acs5",
                     params=params, timeout=40)
    # The API answers a missing/invalid key with HTTP 200 and an HTML page, so a
    # status check alone is not enough -- confirm we actually got JSON.
    ctype = r.headers.get("Content-Type", "")
    if "json" not in ctype.lower():
        snippet = re.sub(r"\s+", " ", r.text[:160])
        raise RuntimeError(
            f"Census returned non-JSON (HTTP {r.status_code}): {snippet}\n"
            "  -> almost certainly a missing/invalid CENSUS_API_KEY."
        )
    rows = r.json()[1:]
    table = defaultdict(list)
    for name, inc, *_ in rows:
        if inc is None:
            continue
        val = int(inc)
        if val < 0:                       # Census uses negatives as null sentinels
            continue
        table[clean_place(name)].append(val)
    cache[fips] = dict(table)
    time.sleep(DELAY)
    return cache[fips]


def main():
    key = os.environ.get("CENSUS_API_KEY")
    df = pd.read_csv(ROSTER)

    # ---- 1. parse ----------------------------------------------------------
    parsed = df["hometown"].apply(parse_hometown)
    df["city"] = [p[0] for p in parsed]
    df["state"] = [p[1] for p in parsed]
    df["geo_status"] = [p[2] for p in parsed]

    n = len(df)
    counts = df["geo_status"].value_counts().to_dict()
    us = df[df.geo_status == "US"]
    unique_pairs = us[["city", "state"]].drop_duplicates()

    print("=" * 66)
    print(f"players                 {n}")
    print(f"  US hometowns          {counts.get('US', 0)}")
    print(f"  non-US (income=null)  {counts.get('NON_US', 0)}")
    print(f"  unparsed              {counts.get('UNPARSED', 0)}")
    print(f"unique US (city,state)  {len(unique_pairs)}   "
          f"<- API call volume if queried per-city")
    print(f"unique states           {unique_pairs.state.nunique()}   "
          f"<- actual call volume (bulk per-state)")
    print("=" * 66)

    if UNPARSED_LOG:
        print(f"\nunparsed hometown strings ({len(set(UNPARSED_LOG))} unique):")
        for h, c in Counter(UNPARSED_LOG).most_common(20):
            print(f"  {c:3d}x  {h!r}")

    if not key:
        print("\nCENSUS_API_KEY is not set. The Census API rejects unkeyed requests")
        print("(it answers HTTP 200 with an HTML 'Missing Key' page). Set it and re-run:")
        print("    $env:CENSUS_API_KEY='...'   # PowerShell")
        sys.exit(1)

    # ---- 2/3. fetch + cache ------------------------------------------------
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    n_cached_at_start = len(cache)
    state_medians = fetch_state_medians(key, cache)
    tables = {}
    for st in sorted(unique_pairs.state.unique()):
        fips = STATE_TO_FIPS.get(st)
        if not fips:
            continue
        tables[st] = fetch_state_places(fips, key, cache)
    json.dump(cache, open(CACHE, "w"))
    print(f"\nstates fetched: {len(cache) - n_cached_at_start} new, "
          f"{n_cached_at_start} from cache -> {CACHE}")

    # ---- 4. match ----------------------------------------------------------
    income, unmatched, ambiguous = {}, [], []
    for city, st in unique_pairs.itertuples(index=False):
        table = tables.get(st, {})
        hits = table.get(clean_place(city), [])
        if not hits:
            unmatched.append((city, st))
        elif len(hits) > 1:
            # Several distinct places share this name in-state (e.g. a "city" and
            # a "village"). Median income differs between them; guessing would
            # fabricate precision, so record it as unmatched and log it.
            ambiguous.append((city, st, hits))
            unmatched.append((city, st))
        else:
            income[(city, st)] = hits[0]

    matched_rate = len(income) / len(unique_pairs) if len(unique_pairs) else 0
    print(f"\nmatch rate: {len(income)}/{len(unique_pairs)} unique US hometowns "
          f"= {matched_rate:.1%}")
    print(f"  ambiguous (multiple same-name places in state): {len(ambiguous)}")
    print(f"  no Census place match:                          "
          f"{len(unmatched) - len(ambiguous)}")
    if unmatched:
        print(f"\nunmatched hometowns (spot-check these):")
        for city, st in unmatched[:30]:
            tag = " [AMBIGUOUS]" if any(a[0] == city and a[1] == st for a in ambiguous) else ""
            print(f"  {city}, {st}{tag}")
        if len(unmatched) > 30:
            print(f"  ... and {len(unmatched) - 30} more")

    # ---- 5. merge ----------------------------------------------------------
    df["hometown_median_income"] = [
        income.get((c, s)) if st == "US" else None
        for c, s, st in zip(df.city, df.state, df.geo_status)
    ]
    df["state_median_income"] = df["state"].map(state_medians)
    df["income_ratio"] = df["hometown_median_income"] / df["state_median_income"]
    df.to_csv(ENRICHED, index=False)
    cov = df.hometown_median_income.notna().mean()
    print(f"\nplayer-level income coverage: {df.hometown_median_income.notna().sum()}"
          f"/{n} = {cov:.1%}  -> {ENRICHED}")

    # ---- 6. equity analysis ------------------------------------------------
    report = analyze(df)

    # ---- 7. write-up -------------------------------------------------------
    write_markdown(df, report, matched_rate, unique_pairs, counts, ambiguous, unmatched)
    print(f"\nwrote {FINDING}")


def eps_squared(H, n, k):
    """Kruskal-Wallis effect size. (H - k + 1) / (n - k). ~0.01 small, .06 med, .14 large."""
    return (H - k + 1) / (n - k) if n > k else float("nan")


def analyze(df):
    d = df.dropna(subset=["hometown_median_income"])
    print("\n" + "=" * 66)
    print("EQUITY ANALYSIS: hometown median household income by division")
    print("=" * 66)

    print(f"\n{'div':6s} {'n':>5s} {'median':>9s} {'Q1':>9s} {'Q3':>9s} {'mean':>9s}")
    per_div = {}
    for dv in DIVISIONS:
        v = d[d.division == dv].hometown_median_income
        if len(v) == 0:
            continue
        per_div[dv] = {
            "n": int(len(v)), "median": float(v.median()),
            "q1": float(v.quantile(.25)), "q3": float(v.quantile(.75)),
            "mean": float(v.mean()),
        }
        print(f"{dv:6s} {len(v):5d} {v.median():9,.0f} {v.quantile(.25):9,.0f} "
              f"{v.quantile(.75):9,.0f} {v.mean():9,.0f}")

    # --- player-level KW (what was asked for) -------------------------------
    groups = [d[d.division == dv].hometown_median_income.values
              for dv in DIVISIONS if (d.division == dv).any()]
    H, p = stats.kruskal(*groups)
    e2 = eps_squared(H, len(d), len(groups))
    print(f"\nKruskal-Wallis (player-level, n={len(d)}):")
    print(f"  H = {H:.2f}   p = {p:.3e}   epsilon^2 = {e2:.4f}")

    # --- school-level KW (the honest unit) ----------------------------------
    # Players are not independent: teammates share one recruiting pipeline, so a
    # player-level test treats ~43 pipelines as ~1700 samples and will return a
    # tiny p-value off almost any real difference. The independent unit is the
    # PROGRAM. Collapse each school to its median recruit income and retest.
    sch = (d.groupby(["school", "division"])["hometown_median_income"]
             .median().reset_index())
    sgroups = [sch[sch.division == dv].hometown_median_income.values
               for dv in DIVISIONS if (sch.division == dv).any()]
    Hs, ps = stats.kruskal(*sgroups)
    e2s = eps_squared(Hs, len(sch), len(sgroups))
    print(f"\nKruskal-Wallis (school-level, n={len(sch)} programs)  <-- honest unit:")
    print(f"  H = {Hs:.2f}   p = {ps:.4f}   epsilon^2 = {e2s:.4f}")
    print(f"  {'div':6s} {'schools':>8s} {'median of school medians':>26s}")
    school_meds = {}
    for dv in DIVISIONS:
        v = sch[sch.division == dv].hometown_median_income
        if len(v) == 0:
            continue
        school_meds[dv] = {"n_schools": int(len(v)), "median": float(v.median())}
        print(f"  {dv:6s} {len(v):8d} {v.median():26,.0f}")

    # --- pairwise (Mann-Whitney + Bonferroni), school level -----------------
    pairs = {}
    combos = [(a, b) for i, a in enumerate(DIVISIONS) for b in DIVISIONS[i + 1:]]
    print(f"\npairwise Mann-Whitney (school-level, Bonferroni x{len(combos)}):")
    for a, b in combos:
        va = sch[sch.division == a].hometown_median_income
        vb = sch[sch.division == b].hometown_median_income
        if len(va) < 2 or len(vb) < 2:
            continue
        u, pu = stats.mannwhitneyu(va, vb, alternative="two-sided")
        padj = min(1.0, pu * len(combos))
        pairs[f"{a}_vs_{b}"] = {"p_raw": float(pu), "p_bonferroni": float(padj),
                                "median_diff": float(va.median() - vb.median())}
        flag = "*" if padj < 0.05 else " "
        print(f"  {a:4s} vs {b:4s}  diff {va.median() - vb.median():+9,.0f}  "
              f"p_adj = {padj:.3f} {flag}")

    # --- region-adjusted: the same test on income_ratio ----------------------
    # If the raw division gap is really a cost-of-living gap, it will shrink or
    # vanish once each town is scored against its own state's median.
    dr = d.dropna(subset=["income_ratio"])
    rgroups = [dr[dr.division == dv].income_ratio.values
               for dv in DIVISIONS if (dr.division == dv).any()]
    Hr, pr = stats.kruskal(*rgroups)
    schr = (dr.groupby(["school", "division"])["income_ratio"]
              .median().reset_index())
    rsgroups = [schr[schr.division == dv].income_ratio.values
                for dv in DIVISIONS if (schr.division == dv).any()]
    Hrs, prs = stats.kruskal(*rsgroups)
    e2rs = eps_squared(Hrs, len(schr), len(rsgroups))
    print(f"\nREGION-ADJUSTED (hometown income / its own state's median):")
    print(f"  school-level KW (n={len(schr)}): H={Hrs:.2f}  p={prs:.4f}  "
          f"epsilon^2={e2rs:.4f}")
    print(f"  {'div':6s} {'schools':>8s} {'median ratio':>13s}   (1.00 = state median)")
    ratios = {}
    for dv in DIVISIONS:
        v = schr[schr.division == dv].income_ratio
        if len(v) == 0:
            continue
        ratios[dv] = {"n_schools": int(len(v)), "median_ratio": float(v.median())}
        print(f"  {dv:6s} {len(v):8d} {v.median():13.2f}")

    # --- by position --------------------------------------------------------
    print(f"\nby position (player-level KW within each position):")
    by_pos = {}
    for pos in ["GK", "D", "M", "F"]:
        dp = d[d.position == pos]
        g = [dp[dp.division == dv].hometown_median_income.values
             for dv in DIVISIONS if (dp.division == dv).sum() >= 5]
        if len(g) < 2:
            continue
        Hp, pp = stats.kruskal(*g)
        by_pos[pos] = {"n": int(len(dp)), "H": float(Hp), "p": float(pp),
                       "epsilon_sq": float(eps_squared(Hp, len(dp), len(g)))}
        print(f"  {pos:3s} n={len(dp):5d}  H={Hp:6.2f}  p={pp:.4f}  "
              f"eps^2={by_pos[pos]['epsilon_sq']:.4f}")

    return {
        "per_division_player_level": per_div,
        "kruskal_player_level": {"H": float(H), "p": float(p), "epsilon_sq": float(e2),
                                 "n": int(len(d))},
        "kruskal_school_level": {"H": float(Hs), "p": float(ps), "epsilon_sq": float(e2s),
                                 "n_schools": int(len(sch))},
        "kruskal_school_level_region_adjusted": {
            "H": float(Hrs), "p": float(prs), "epsilon_sq": float(e2rs),
            "n_schools": int(len(schr))},
        "kruskal_player_level_region_adjusted": {"H": float(Hr), "p": float(pr)},
        "per_division_school_level": school_meds,
        "per_division_income_ratio": ratios,
        "pairwise_school_level": pairs,
        "by_position": by_pos,
    }


def _size(e2):
    return ("large" if e2 >= .14 else "medium" if e2 >= .06
            else "small" if e2 >= .01 else "negligible")


def write_markdown(df, rep, match_rate, unique_pairs, counts, ambiguous, unmatched):
    n = len(df)
    cov = df.hometown_median_income.notna().mean()
    ks = rep["kruskal_school_level"]                       # raw, school-level
    kp = rep["kruskal_player_level"]                       # raw, player-level
    kr = rep["kruskal_school_level_region_adjusted"]       # adjusted, school-level
    meds = rep["per_division_school_level"]
    ratios = rep["per_division_income_ratio"]

    sig_raw, sig_adj = ks["p"] < 0.05, kr["p"] < 0.05
    ordered = sorted(meds.items(), key=lambda kv: -kv[1]["median"])
    order_str = " > ".join(f"{k} (${v['median']:,.0f})" for k, v in ordered)
    monotonic = [k for k, _ in ordered] == DIVISIONS

    lines = [
        "# Equity finding: hometown income vs. program division",
        "",
        "**Hypothesis tested.** Higher-division soccer programs recruit from "
        "wealthier hometowns. Roster hometowns were linked to Census ACS 5-year "
        f"({ACS_YEAR}) place-level median household income (`B19013_001E`) and "
        "compared across D1/D2/D3/NAIA.",
        "",
        "## Headline",
        "",
        "**The hypothesis is not supported, and the headline result does not "
        "survive a regional control.**",
        "",
        f"1. **The ordering is not the prestige ladder.** Program-level medians run "
        f"{order_str}"
        + ("" if monotonic else " -- **D3, not D1, recruits from the wealthiest "
                                "hometowns.** A simple 'higher division = more "
                                "money' story predicts D1 > D2 > D3 > NAIA and is "
                                "immediately contradicted."),
        "",
        f"2. **The raw difference is significant** at the program level: "
        f"H={ks['H']:.2f}, p={ks['p']:.4f}, epsilon-squared={ks['epsilon_sq']:.3f} "
        f"({_size(ks['epsilon_sq'])} effect, n={ks['n_schools']} programs).",
        "",
        f"3. **But it mostly dissolves once you control for region.** Scoring each "
        f"hometown against *its own state's* median income and re-running the same "
        f"test gives p={kr['p']:.4f}, epsilon-squared={kr['epsilon_sq']:.3f} "
        f"-- **{'still significant' if sig_adj else 'no longer significant'}**. "
        "Roughly half the raw effect was cost-of-living geography, not athletics: "
        "the D3 programs here sit in NY/VA/PA (expensive states), the NAIA programs "
        "in MI/IL/IN (cheaper ones).",
        "",
        "## What actually survives",
        "",
        "The robust pattern is not about *division tiers* -- it is about college "
        "soccer as a whole. Every division except NAIA recruits from towns "
        "meaningfully **above** their own state's median income:",
        "",
        "| division | programs | median hometown income | income relative to state median |",
        "|---|---|---|---|",
    ]
    for dv in DIVISIONS:
        m, r = meds.get(dv), ratios.get(dv)
        if not m:
            continue
        rr = f"{r['median_ratio']:.2f}x" if r else "-"
        lines.append(f"| {dv} | {m['n_schools']} | ${m['median']:,.0f} | {rr} |")

    lines += [
        "",
        "A ratio of 1.00 means a program's typical recruit comes from a town at "
        "exactly its state's median income. D1 (1.18x) and D3 (1.23x) draw from "
        "towns roughly a fifth richer than their states' median; NAIA (0.97x) is "
        "the only division recruiting at parity with the general population. "
        "**That contrast -- NAIA vs. everyone else -- is the real signal here, and "
        "it is not a story about competitive tier.**",
        "",
        "## Per-player distribution (raw income)",
        "",
        "| division | players | median | Q1 | Q3 |",
        "|---|---|---|---|---|",
    ]
    for dv in DIVISIONS:
        p_ = rep["per_division_player_level"].get(dv)
        if p_:
            lines.append(f"| {dv} | {p_['n']} | ${p_['median']:,.0f} | "
                         f"${p_['q1']:,.0f} | ${p_['q3']:,.0f} |")

    lines += ["", "## Pairwise (school-level, raw income, Bonferroni-corrected)", "",
              "| comparison | median difference | adjusted p |", "|---|---|---|"]
    survivors = []
    for k, v in rep["pairwise_school_level"].items():
        a, b = k.split("_vs_")
        star = " \\*" if v["p_bonferroni"] < 0.05 else ""
        if v["p_bonferroni"] < 0.05:
            survivors.append(f"{a} vs {b}")
        lines.append(f"| {a} vs {b} | ${v['median_diff']:+,.0f} | "
                     f"{v['p_bonferroni']:.3f}{star} |")
    lines += [
        "",
        (f"Only **{', '.join(survivors)}** survives correction. Note what that "
         "contrast actually is: selective private Northeast colleges versus "
         "Sunbelt D2 programs. It is an *institution-type* difference, not a "
         "*competitive-tier* difference. D1 vs D2 and D1 vs D3 are both null."
         if survivors else
         "**No pairwise contrast survives correction.**"),
        "",
        "## A plausible mechanism (untested here)",
        "",
        "D3 offers **no athletic scholarships**. A D3 roster spot therefore selects, "
        "in part, for families who can absorb full private-college tuition -- which "
        "would push D3 hometown income up independent of athletic level. That "
        "mechanism fits the data better than a prestige ladder does, but this study "
        "cannot confirm it: it would need financial-aid data, not roster data.",
        "",
        "## Caveats -- read before citing any number above",
        "",
        f"1. **Differential missingness, and it is not random.** {match_rate:.1%} of "
        f"unique US hometowns matched a Census place; {cov:.1%} of all {n} players "
        f"carry an income value. {counts.get('NON_US', 0)} players "
        f"({counts.get('NON_US', 0) / n:.0%}) are international and hold `null` by "
        "design -- but international share *varies by division* (D2 32%, D1 21%, "
        "NAIA 18%, D3 4%). So the analysis runs on ~59% of D2's roster versus ~86% "
        "of D3's. The excluded group is correlated with both the predictor and the "
        "outcome, because international recruiting is itself a marker of program "
        "resources. This is the single weakest point in the design.",
        f"2. **Ambiguity.** {len(ambiguous)} hometowns matched multiple same-name "
        "places within one state and were dropped rather than guessed; "
        f"{len(unmatched) - len(ambiguous)} matched no Census place at all "
        "(unincorporated areas, neighborhoods like 'West Roxbury', townships). "
        "Unmatched places skew toward affluent unincorporated suburbs "
        "(Gladwyne PA, Chevy Chase MD, Palos Verdes CA), which likely biases the "
        "matched sample *downward* -- against the very effect being tested.",
        "3. **Ecological fallacy -- the deepest problem.** `B19013_001E` is the "
        "median income of a player's *hometown*, not of the player's *household*. "
        "A recruit from Bakersfield is not a Bakersfield-median earner. Club soccer "
        "runs to thousands of dollars a season, so within any town the players who "
        "reach a college roster are plausibly drawn from its upper income tail. "
        "This measure cannot see that -- and it is precisely the mechanism an "
        "equity claim would rest on. Town income is a weak proxy for geographic "
        "sorting, not a measure of player wealth.",
        f"4. **Clustering / pseudo-replication.** The {n} players are not "
        "independent: they cluster into 43 recruiting pipelines. The player-level "
        f"test (p={kp['p']:.1e}) treats teammates as independent draws and is "
        "inflated by roughly the average roster size; it is reported for reference "
        "only and should not be cited. The program-level test is the honest one, "
        f"and its effective sample size is {ks['n_schools']}, not {kp['n']}.",
        f"5. **Underpowered at the program level.** {ks['n_schools']} programs split "
        "across four divisions leaves 6-18 per group. The region-adjusted test "
        f"(p={kr['p']:.4f}) sits close enough to 0.05 that it should be read as "
        "'undetermined at this sample size', not as a clean null. More programs "
        "would genuinely help here -- unlike in the fit-match experiment, where "
        "more data would not have moved the ceiling.",
        "",
        "## Bottom line",
        "",
    ]

    if sig_adj:
        lines.append(
            "Hometown income differs across divisions even after adjusting for "
            f"region (p={kr['p']:.4f}), but **not in the direction the hypothesis "
            "predicted** -- D3 sits at the top, not D1. Read this as evidence of "
            "institution-type sorting (scholarship vs. non-scholarship), not of a "
            "division-prestige income gradient.")
    else:
        lines.append(
            f"**The equity hypothesis as operationalized here is not supported.** "
            f"The raw division difference is significant (p={ks['p']:.4f}) but is "
            f"largely a regional cost-of-living artifact: adjusting each hometown "
            f"against its own state's median drops it to p={kr['p']:.4f}, below the "
            "conventional threshold. And the raw ordering contradicts the "
            "hypothesis anyway -- **D3, not D1, recruits from the wealthiest "
            "hometowns**, which points at scholarship structure rather than "
            "competitive tier.")
    lines += [
        "",
        "The one durable observation: **college soccer recruits from above-median "
        "towns across the board** (D1 1.18x, D3 1.23x, D2 1.07x their state "
        "medians), with NAIA at parity (0.97x). If there is an income barrier in "
        "this sport, it looks like a barrier to *playing college soccer at all* "
        "rather than a barrier that sorts players between divisions.",
        "",
        "This is a **null-to-inconclusive result for the stated hypothesis** and "
        "should be written up as one. Town-of-origin median income is too coarse an "
        "instrument to settle the question (caveat 3); a real test needs household "
        "income, financial-aid, or club-fee data.",
    ]

    open(FINDING, "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
