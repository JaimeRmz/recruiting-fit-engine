"""
Comparator: "here are real players like you, and where they play."

No prediction, no score, no confidence. find_comparables() returns real roster
rows matching a position and home state -- nothing computed, nothing ranked by
any model.

    python compare_athletes.py
"""
import pandas as pd

from enrich_with_census import normalize_state, parse_hometown

ROSTER = "data/program_roster_master.csv"

REGIONS = {
    "Northeast": ["ME", "NH", "VT", "MA", "RI", "CT", "NY", "NJ", "PA"],
    "Southeast": ["DE", "MD", "DC", "VA", "WV", "NC", "SC", "GA", "FL",
                  "KY", "TN", "AL", "MS", "AR", "LA"],
    "Midwest": ["OH", "MI", "IN", "IL", "WI", "MN", "IA", "MO", "ND", "SD",
                "NE", "KS"],
    "Southwest": ["TX", "OK", "NM", "AZ"],
    "West": ["CO", "WY", "MT", "ID", "UT", "NV", "CA", "OR", "WA", "AK", "HI"],
}
STATE_TO_REGION = {s: r for r, states in REGIONS.items() for s in states}

CLASS_ORDER = ["Fr", "So", "Jr", "Sr"]

_cache = None


def _load():
    """Roster with a `state` column derived by the enrichment script's parser."""
    global _cache
    if _cache is None:
        df = pd.read_csv(ROSTER)
        df["state"] = [parse_hometown(h)[1] for h in df["hometown"]]
        _cache = df
    return _cache


def find_comparables(position, hometown_state, gender, class_year=None, top_n=10):
    """
    Real players sharing a position, gender and home state (or region, on fallback).

    position and gender are exact filters -- results never cross them. class_year
    is only a soft preference (see below).

    Returns a list of dicts: school, division, gender, class_year, hometown,
    match_type. `match_type` is "state" or "region" -- it says how the row was
    found, not how good a match it is.
    """
    df = _load()
    state = normalize_state(hometown_state)
    if state is None:
        return []

    exact = (df["position"] == position) & (df["gender"] == gender)
    pool = df[exact & (df["state"] == state)]
    match_type = "state"

    # Thin state -> widen to the region rather than return almost nothing. The
    # position and gender filters still apply; only the geography loosens.
    if len(pool) < 5:
        region = STATE_TO_REGION.get(state)
        if region:
            pool = df[exact & df["state"].isin(REGIONS[region])]
            match_type = "region"

    pool = pool.copy()
    # class_year is a soft preference: same-year players sort first, everyone else
    # still appears. A hard filter here would empty out valid position+state matches.
    if class_year:
        pool["_pref"] = (pool["class_year"] != class_year).astype(int)
    else:
        pool["_pref"] = 0
    pool["_cls"] = pool["class_year"].apply(
        lambda c: CLASS_ORDER.index(c) if c in CLASS_ORDER else len(CLASS_ORDER))
    pool = pool.sort_values(["_pref", "_cls", "school"])

    return [
        {"school": r.school, "division": r.division, "gender": r.gender,
         "class_year": r.class_year, "hometown": r.hometown,
         "match_type": match_type}
        for r in pool.head(top_n).itertuples(index=False)
    ]


def _show(position, state, gender, class_year=None, top_n=10):
    rows = find_comparables(position, state, gender, class_year, top_n)
    header = f"find_comparables({position!r}, {state!r}, {gender!r}"
    header += f", class_year={class_year!r})" if class_year else ")"
    print("\n" + header)
    if not rows:
        print("  no comparables found")
        return
    mt = rows[0]["match_type"]
    if mt == "region":
        region = STATE_TO_REGION.get(normalize_state(state))
        print(f"  [REGIONAL FALLBACK] fewer than 5 players in {state}; "
              f"showing {region} instead -- these are NOT state matches")
    else:
        print(f"  [STATE MATCH] {state}")
    print(f"  {len(rows)} players")
    print(f"    {'school':22s} {'div':5s} {'g':2s} {'yr':3s} hometown")
    for r in rows:
        print(f"    {r['school']:22s} {r['division']:5s} {r['gender']:2s} "
              f"{str(r['class_year']):3s} {r['hometown']}")


if __name__ == "__main__":
    _show("GK", "Texas", "W")
    _show("M", "Rhode Island", "M")
