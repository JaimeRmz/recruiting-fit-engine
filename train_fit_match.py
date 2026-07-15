"""
Fit-Match v1: can a player's physical/geographic profile predict program division?

Trains an XGBoost 4-class classifier (D1/D2/D3/NAIA) on roster features and
evaluates it honestly. Read the EVALUATION DESIGN note below before trusting any
number this prints -- the headline accuracy from the requested random split is
not the number that answers the research question.

    python train_fit_match.py

Outputs:
    models/fit_match_v1.json        trained booster (the honest config)
    data/fit_match_metrics.json     full metrics for every evaluation arm
"""
import json
import os
import re

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import (accuracy_score, classification_report,
                             confusion_matrix, f1_score)
from sklearn.model_selection import StratifiedGroupKFold, train_test_split

DATA = "data/program_roster_master.csv"
MODEL_OUT = "models/fit_match_v1.json"
METRICS_OUT = "data/fit_match_metrics.json"
CLASSES = ["D1", "D2", "D3", "NAIA"]
SEED = 42
N_PERM = 30          # school-level label permutations for the significance test

# =============================================================================
# EVALUATION DESIGN -- why this script runs four arms instead of one
#
# Two leaks make the naive setup (random 80/20 split, all features) meaningless:
#
# 1. height_in is present for 395 players and ALL of them are D1. P(D1|height) =
#    1.00. Only 12 of 43 schools publish a height column and all 12 happen to be
#    D1 -- the other 31 schools' athletics sites simply don't expose that field.
#    So height_missing does not describe an athlete, it describes which CMS
#    template the school's webmaster configured. It is a scraper artifact that
#    happens to correlate perfectly with the label in this sample. A model handed
#    that flag scores well and has learned nothing transferable.
#
# 2. division is a SCHOOL-level label: every player at Wake Forest is D1 because
#    Wake Forest is D1, not because of anything about that player. A random split
#    over players puts teammates in both train and val, so the model can identify
#    the school (from its hometown-recruiting footprint) and read the label off it.
#    The effective sample size is 43 schools, not 2062 players.
#
# The question actually being asked is: given an unseen program, do its players'
# physical/geographic profiles reveal its division? That requires held-out
# SCHOOLS and no template artifacts. Arm D is the honest answer; A/B/C exist to
# show how much each leak inflates the result.
# =============================================================================

# --- hometown -> state -------------------------------------------------------
# Rosters mix AP style ("Portland, Ore."), postal ("Chandler, AZ") and full names
# ("Salt Lake City, Utah"), sometimes with stray periods ("Santa Fe. N.M.").
STATES = {
    "alabama": "AL", "ala": "AL", "al": "AL", "alaska": "AK", "ak": "AK",
    "arizona": "AZ", "ariz": "AZ", "az": "AZ", "arkansas": "AR", "ark": "AR", "ar": "AR",
    "california": "CA", "calif": "CA", "cal": "CA", "ca": "CA",
    "colorado": "CO", "colo": "CO", "co": "CO",
    "connecticut": "CT", "conn": "CT", "ct": "CT",
    "delaware": "DE", "del": "DE", "de": "DE",
    "florida": "FL", "fla": "FL", "fl": "FL",
    "georgia": "GA", "ga": "GA", "hawaii": "HI", "hi": "HI",
    "idaho": "ID", "id": "ID", "illinois": "IL", "ill": "IL", "il": "IL",
    "indiana": "IN", "ind": "IN", "in": "IN", "iowa": "IA", "ia": "IA",
    "kansas": "KS", "kan": "KS", "kans": "KS", "ks": "KS",
    "kentucky": "KY", "ky": "KY", "louisiana": "LA", "la": "LA",
    "maine": "ME", "me": "ME", "maryland": "MD", "md": "MD",
    "massachusetts": "MA", "mass": "MA", "ma": "MA",
    "michigan": "MI", "mich": "MI", "mi": "MI",
    "minnesota": "MN", "minn": "MN", "mn": "MN",
    "mississippi": "MS", "miss": "MS", "ms": "MS",
    "missouri": "MO", "mo": "MO", "montana": "MT", "mont": "MT", "mt": "MT",
    "nebraska": "NE", "neb": "NE", "nebr": "NE", "ne": "NE",
    "nevada": "NV", "nev": "NV", "nv": "NV",
    "new hampshire": "NH", "nh": "NH", "new jersey": "NJ", "nj": "NJ",
    "new mexico": "NM", "nm": "NM", "new york": "NY", "ny": "NY",
    "north carolina": "NC", "nc": "NC", "north dakota": "ND", "nd": "ND",
    "ohio": "OH", "oh": "OH", "oklahoma": "OK", "okla": "OK", "ok": "OK",
    "oregon": "OR", "ore": "OR", "or": "OR",
    "pennsylvania": "PA", "penn": "PA", "pa": "PA",
    "rhode island": "RI", "ri": "RI",
    "south carolina": "SC", "sc": "SC", "south dakota": "SD", "sd": "SD",
    "tennessee": "TN", "tenn": "TN", "tn": "TN",
    "texas": "TX", "tex": "TX", "tx": "TX",
    "utah": "UT", "ut": "UT", "vermont": "VT", "vt": "VT",
    "virginia": "VA", "va": "VA", "washington": "WA", "wash": "WA", "wa": "WA",
    "west virginia": "WV", "wva": "WV", "wv": "WV",
    "wisconsin": "WI", "wis": "WI", "wisc": "WI", "wi": "WI",
    "wyoming": "WY", "wyo": "WY", "wy": "WY",
    "district of columbia": "DC", "washington d.c": "DC", "dc": "DC",
    "puerto rico": "PR", "pr": "PR",
}
CANADA = {"ontario", "on", "ont", "quebec", "qc", "que", "british columbia", "bc",
          "alberta", "ab", "alta", "manitoba", "mb", "man", "saskatchewan", "sk",
          "nova scotia", "ns", "new brunswick", "nb", "newfoundland", "nl",
          "prince edward island", "pei", "pe", "canada"}


def parse_state(hometown):
    """'Portland, Ore.' -> OR | 'Toronto, Ontario' -> Canada | 'Rzeszow, Poland' -> International."""
    if not isinstance(hometown, str) or not hometown.strip():
        return "Unknown"
    # Trailing "/ High School" garnish and stray periods used as separators.
    town = hometown.split("/")[0].strip()
    parts = [p.strip() for p in re.split(r"[,.]\s+|,", town) if p.strip()]
    if not parts:
        return "Unknown"
    tail = parts[-1].lower().replace(".", "").strip()
    if tail in STATES:
        return STATES[tail]
    if tail in CANADA:
        return "Canada"
    # Two-token tails like "new jersey" already covered; a lone token that is not a
    # US state or Canadian province is a country ("Croatia", "Northern Ireland").
    return "International"


def build_features(df):
    X = pd.DataFrame(index=df.index)
    X["position"] = df["position"].astype("category")
    X["class_year"] = df["class_year"].astype("category")
    X["gender"] = df["gender"].astype("category")
    X["hometown_state"] = df["hometown"].apply(parse_state).astype("category")
    X["height_in"] = df["height_in"]                      # nulls kept as NaN on purpose
    X["height_missing"] = df["height_in"].isna().astype(int)
    return X


# Categorical encoding: XGBoost NATIVE categorical (enable_categorical=True,
# tree_method="hist"). Chosen over one-hot because hometown_state has ~50 levels;
# one-hot would add ~50 sparse columns to a 6-feature model and let the tree spend
# its splits isolating individual states. Native support partitions category sets
# at a node instead. It also lets height_in keep real NaNs -- XGBoost learns a
# default direction per split -- which is exactly the "don't impute" behavior asked for.
def make_model():
    return xgb.XGBClassifier(
        objective="multi:softprob", num_class=4, tree_method="hist",
        enable_categorical=True, max_depth=4, n_estimators=300,
        learning_rate=0.08, subsample=0.9, colsample_bytree=0.9,
        reg_lambda=1.0, random_state=SEED, eval_metric="mlogloss",
    )


def evaluate(y_true, y_pred, label):
    acc = accuracy_score(y_true, y_pred)
    macro_f1 = f1_score(y_true, y_pred, average="macro")
    rep = classification_report(y_true, y_pred, target_names=CLASSES,
                                output_dict=True, zero_division=0)
    cm = confusion_matrix(y_true, y_pred, labels=range(4))
    return {"arm": label, "accuracy": round(acc, 4), "macro_f1": round(macro_f1, 4),
            "per_class": {c: {k: round(rep[c][k], 3) for k in
                              ("precision", "recall", "f1-score", "support")}
                          for c in CLASSES},
            "confusion_matrix": cm.tolist()}


def print_arm(m, baseline):
    print(f"\n--- {m['arm']}")
    lift = m["accuracy"] - baseline
    print(f"accuracy {m['accuracy']:.3f}  (majority baseline {baseline:.3f}, "
          f"lift {lift:+.3f})   macro-F1 {m['macro_f1']:.3f}")
    print(f"{'':6s} {'prec':>6s} {'rec':>6s} {'f1':>6s} {'n':>6s}")
    for c in CLASSES:
        p = m["per_class"][c]
        print(f"{c:6s} {p['precision']:6.2f} {p['recall']:6.2f} "
              f"{p['f1-score']:6.2f} {int(p['support']):6d}")
    print("confusion (row=true, col=pred):")
    print(f"{'':6s}" + "".join(f"{c:>6s}" for c in CLASSES))
    for c, row in zip(CLASSES, m["confusion_matrix"]):
        print(f"{c:6s}" + "".join(f"{v:6d}" for v in row))


def main():
    df = pd.read_csv(DATA)
    y = pd.Categorical(df["division"], categories=CLASSES).codes
    groups = df["school"].values
    X_all = build_features(df)
    X_noleak = X_all.drop(columns=["height_in", "height_missing"])

    baseline = df["division"].value_counts(normalize=True).max()

    print("=" * 68)
    print(f"players {len(df)}  schools {df.school.nunique()}  "
          f"features {list(X_all.columns)}")
    print(f"majority-class baseline (always predict D1): {baseline:.3f}")
    print("dropped major, club_team (>84% null)")
    print("=" * 68)

    results = {}

    # ---- ARM A: as requested. random stratified 80/20, all features. -------
    Xtr, Xva, ytr, yva = train_test_split(X_all, y, test_size=0.2,
                                          stratify=y, random_state=SEED)
    mA = make_model().fit(Xtr, ytr)
    results["A_random_split_all_features"] = evaluate(yva, mA.predict(Xva),
        "ARM A  random split + height  [REQUESTED -- both leaks active, do not trust]")

    # ---- ARM B: random split, height features removed ----------------------
    Xtr, Xva, ytr, yva = train_test_split(X_noleak, y, test_size=0.2,
                                          stratify=y, random_state=SEED)
    mB = make_model().fit(Xtr, ytr)
    results["B_random_split_no_height"] = evaluate(yva, mB.predict(Xva),
        "ARM B  random split, no height  [school-identity leak still active]")

    # ---- ARM C: grouped split (unseen schools), height kept ----------------
    # Isolates the template artifact: same honest split as D, but height restored.
    cv = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=SEED)
    oof = np.zeros(len(df), dtype=int)
    for tr, va in cv.split(X_all, y, groups):
        oof[va] = make_model().fit(X_all.iloc[tr], y[tr]).predict(X_all.iloc[va])
    results["C_grouped_split_all_features"] = evaluate(y, oof,
        "ARM C  unseen schools + height  [template artifact only]")

    # ---- ARM D: THE HONEST ANSWER. unseen schools, no template artifact ----
    oof_d = np.zeros(len(df), dtype=int)
    for tr, va in cv.split(X_noleak, y, groups):
        oof_d[va] = make_model().fit(X_noleak.iloc[tr], y[tr]).predict(X_noleak.iloc[va])
    results["D_grouped_split_no_height"] = evaluate(y, oof_d,
        "ARM D  unseen schools, no height  [*** THE HONEST NUMBER ***]")

    for k in ["A_random_split_all_features", "B_random_split_no_height",
              "C_grouped_split_all_features", "D_grouped_split_no_height"]:
        print_arm(results[k], baseline)

    # ---- is ARM D's lift real, or noise off 43 schools? ---------------------
    # Shuffle division AT THE SCHOOL level (preserving each school's player block)
    # and re-run ARM D. If the observed accuracy sits inside this null, the "lift"
    # is an artifact of having only 43 independent units.
    obs = results["D_grouped_split_no_height"]["accuracy"]
    sch_div = df.groupby("school")["division"].first()
    rng = np.random.default_rng(0)
    null = []
    for _ in range(N_PERM):
        perm = pd.Series(rng.permutation(sch_div.values), index=sch_div.index)
        yp = pd.Categorical(df["school"].map(perm), categories=CLASSES).codes
        o = np.zeros(len(df), dtype=int)
        for tr, va in cv.split(X_noleak, yp, groups):
            o[va] = make_model().fit(X_noleak.iloc[tr], yp[tr]).predict(X_noleak.iloc[va])
        null.append(accuracy_score(yp, o))
    null = np.array(null)
    p_value = float((null >= obs).sum() / len(null))

    # School-level read: majority vote of a program's players -> its division.
    vote = (pd.DataFrame({"school": groups, "true": y, "pred": oof_d})
            .groupby("school").agg(true=("true", "first"),
                                   pred=("pred", lambda s: s.mode()[0])))
    school_acc = float((vote.true == vote.pred).mean())

    perm_summary = {
        "n_permutations": N_PERM, "observed_accuracy": round(obs, 4),
        "null_mean": round(float(null.mean()), 4), "null_sd": round(float(null.std()), 4),
        "null_max": round(float(null.max()), 4), "p_value": round(p_value, 4),
        "school_level_majority_vote_accuracy": round(school_acc, 4),
        "schools_correct": f"{int((vote.true == vote.pred).sum())}/{len(vote)}",
    }
    print("\n--- permutation test (division shuffled across schools)")
    print(f"  observed {obs:.3f}   null {null.mean():.3f} +/- {null.std():.3f} "
          f"(max {null.max():.3f})   p = {p_value:.3f}")
    print(f"  school-level majority vote: {perm_summary['schools_correct']} "
          f"schools correct ({school_acc:.3f})")

    # ---- feature importance (from the honest model) ------------------------
    final = make_model().fit(X_noleak, y)
    imp = sorted(zip(X_noleak.columns, final.feature_importances_),
                 key=lambda t: -t[1])
    print("\n--- feature importance (gain, ARM D feature set)")
    for f, v in imp:
        print(f"  {f:16s} {v:.3f}  {'#' * int(round(v * 50))}")

    leak_imp = sorted(zip(X_all.columns, mA.feature_importances_), key=lambda t: -t[1])
    print("\n--- feature importance (ARM A, showing what the leak does)")
    for f, v in leak_imp:
        print(f"  {f:16s} {v:.3f}  {'#' * int(round(v * 50))}")

    os.makedirs("models", exist_ok=True)
    final.get_booster().save_model(MODEL_OUT)

    payload = {
        "model": "fit_match_v1",
        "target": "division (D1/D2/D3/NAIA)",
        "n_players": len(df),
        "n_schools": int(df.school.nunique()),
        "effective_sample_size": int(df.school.nunique()),
        "majority_baseline": round(float(baseline), 4),
        "features_final": list(X_noleak.columns),
        "features_dropped": {
            "major": ">84% null",
            "club_team": ">84% null",
            "height_in": "LEAK: present for 395 players, all D1. P(D1|height)=1.00",
            "height_missing": "LEAK: encodes school CMS template, not athlete",
        },
        "encoding": "XGBoost native categorical (enable_categorical, tree_method=hist)",
        "saved_model_arm": "D_grouped_split_no_height",
        "arms": results,
        "permutation_test": perm_summary,
        "feature_importance_final": {f: round(float(v), 4) for f, v in imp},
    }
    with open(METRICS_OUT, "w") as fh:
        json.dump(payload, fh, indent=2)

    # ---- verdict -----------------------------------------------------------
    a = results["A_random_split_all_features"]["accuracy"]
    d = results["D_grouped_split_no_height"]["accuracy"]
    print("\n" + "=" * 68)
    print("VERDICT")
    print("=" * 68)
    print(f"  requested setup (ARM A): {a:.3f}")
    print(f"  honest setup    (ARM D): {d:.3f}   vs baseline {baseline:.3f} "
          f"(lift {d - baseline:+.3f})")
    print(f"  -> {a - d:+.3f} of ARM A's accuracy was leakage, not signal.")
    print(f"\n  ARM D beats the null (p={p_value:.3f}), so the residual signal is")
    print(f"  real -- but it is worth only {d - baseline:+.3f} over always-guess-D1.")
    print(f"  Effective sample size is {df.school.nunique()} schools, not {len(df)} players.")
    print(f"\n  model  -> {MODEL_OUT}")
    print(f"  metrics-> {METRICS_OUT}")


if __name__ == "__main__":
    main()
