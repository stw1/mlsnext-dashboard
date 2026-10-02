#!/usr/bin/env python3
"""
Safety check before publishing: compare the freshly downloaded data (data/ in the working tree) with what's live
(the last commit), and refuse to publish if the feed looks broken. The weekly workflow runs it after refresh.py and
before committing; a failure stops the publish, so the site keeps showing the last good data and GitHub emails a
warning.

  python3 scripts/sanity_check.py            # compare with HEAD
  python3 scripts/sanity_check.py --base REF  # compare with another commit

What counts as broken (a normal weekend only adds results and moves a few kickoff times):
  - conferences or many teams disappear
  - the season's game list shrinks a lot, overall or in one conference
  - results that were already played disappear (more than a handful: MLS does void the odd game)
  - many past results change score at once
  - the Flex feed or the Flex tables come back empty when they weren't
  - the feed's sync time goes backwards (an old copy of the feed)
Exit code 0 = safe to publish, 1 = something looks wrong (details printed), 2 = nothing to compare with.
"""
import argparse, csv, io, json, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# limits; a real weekend is far inside all of these
MAX_BRACKETS_LOST = 0          # any conference vanishing is suspicious
MAX_TEAMS_LOST = 0.03          # share of teams
MAX_GAMES_LOST = 0.05          # share of the season's games, overall
MAX_BRACKET_GAMES_LOST = 0.25  # share of one conference's games (only for conferences with 20+ games)
MAX_RESULTS_LOST = 10          # played results that disappear or lose their score
MAX_RESULTS_CHANGED = 15       # played results whose score changes
MAX_FLEX_LOST = 0.25           # share of Flex games

def old_file(ref, path):
    try:
        return subprocess.run(["git", "-C", ROOT, "show", f"{ref}:{path}"], capture_output=True, text=True, check=True).stdout
    except subprocess.CalledProcessError:
        return None

def games(text):
    return list(csv.DictReader(io.StringIO(text)))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="HEAD")
    a = ap.parse_args()
    before = {p: old_file(a.base, f"data/{p}") for p in ("games.csv", "brackets.json", "meta.json", "flex_groups.json")}
    if not before["games.csv"] or not before["brackets.json"]:
        print(f"No earlier data in {a.base} to compare with; skipping the check.")
        return 2
    now = {p: open(f"{ROOT}/data/{p}").read() if os.path.exists(f"{ROOT}/data/{p}") else ""
           for p in ("games.csv", "brackets.json", "meta.json", "flex_groups.json")}
    problems, notes = [], []

    # conferences and teams
    bb, bn = json.loads(before["brackets.json"]), json.loads(now["brackets.json"] or "[]")
    kb, kn = {(b["age"], b["conf"]) for b in bb}, {(b["age"], b["conf"]) for b in bn}
    lost = sorted(kb - kn)
    if len(lost) > MAX_BRACKETS_LOST:
        problems.append(f"{len(lost)} conference(s) disappeared: " + ", ".join(f"{x} {y}" for x, y in lost[:6]))
    tb, tn = sum(len(b["teams"]) for b in bb), sum(len(b["teams"]) for b in bn)
    if tn < tb * (1 - MAX_TEAMS_LOST):
        problems.append(f"teams dropped from {tb} to {tn}")
    notes.append(f"conferences {len(kb)} → {len(kn)}, teams {tb} → {tn}")

    # games: overall, per conference, Flex
    gb, gn = games(before["games.csv"]), games(now["games.csv"])
    lg = lambda gs: [g for g in gs if g.get("comp", "league") == "league"]
    fx = lambda gs: [g for g in gs if g.get("comp") == "flex"]
    if len(lg(gn)) < len(lg(gb)) * (1 - MAX_GAMES_LOST):
        problems.append(f"league games dropped from {len(lg(gb))} to {len(lg(gn))}")
    per = lambda gs: {k: sum(1 for g in lg(gs) if (g["age"], g["conference"]) == k) for k in kb}
    pb, pn = per(gb), per(gn)
    shrunk = [f"{k[0]} {k[1]} {pb[k]}→{pn.get(k, 0)}" for k in sorted(pb) if pb[k] >= 20 and pn.get(k, 0) < pb[k] * (1 - MAX_BRACKET_GAMES_LOST)]
    if shrunk:
        problems.append(f"{len(shrunk)} conference(s) lost a lot of games: " + ", ".join(shrunk[:6]))
    if fx(gb) and len(fx(gn)) < len(fx(gb)) * (1 - MAX_FLEX_LOST):
        problems.append(f"Flex games dropped from {len(fx(gb))} to {len(fx(gn))}")
    try:
        fgb, fgn = json.loads(before["flex_groups.json"] or "[]"), json.loads(now["flex_groups.json"] or "[]")
        if fgb and not fgn:
            problems.append(f"the Flex group tables came back empty (were {len(fgb)} groups)")
    except ValueError:
        problems.append("data/flex_groups.json isn't valid JSON")
    notes.append(f"league games {len(lg(gb))} → {len(lg(gn))}, Flex games {len(fx(gb))} → {len(fx(gn))}")

    # results already played: they should stay, with the same score
    key = lambda g: (g.get("comp", "league"), g["match_id"])
    played = lambda gs: {key(g): (g["home_score"], g["away_score"]) for g in gs if g["home_score"] != ""}
    rb, rn, alln = played(gb), played(gn), {key(g) for g in gn}
    gone = [k for k in rb if k not in rn]
    changed = [k for k in rb if k in rn and rn[k] != rb[k]]
    if len(gone) > MAX_RESULTS_LOST:
        unplayed = sum(1 for k in gone if k in alln)
        problems.append(f"{len(gone)} results that were already played are missing ({unplayed} now without a score, "
                        f"{len(gone) - unplayed} gone from the schedule)")
    elif gone:
        notes.append(f"{len(gone)} earlier result(s) removed (within the limit: MLS voids the odd game)")
    if len(changed) > MAX_RESULTS_CHANGED:
        problems.append(f"{len(changed)} earlier results changed score")
    elif changed:
        notes.append(f"{len(changed)} earlier score(s) corrected")
    notes.append(f"played results {len(rb)} → {len(rn)} ({len(rn) - len(rb) + len(gone):+d} new)")

    # an old copy of the feed
    try:
        sb = json.loads(before["meta.json"] or "{}").get("synced_at", "")
        sn = json.loads(now["meta.json"] or "{}").get("synced_at", "")
        if sb and sn and sn < sb:
            problems.append(f"the feed's sync time went backwards ({sb} → {sn})")
    except ValueError:
        problems.append("data/meta.json isn't valid JSON")

    print("Safety check against the live data (" + a.base + "): " + "; ".join(notes) + ".")
    if problems:
        print(f"NOT PUBLISHING: {len(problems)} problem(s) with the new data:")
        for p in problems:
            print("  - " + p)
        print("The site keeps the last good data. If the change is real (MLS reorganised conferences, say), publish by "
              "hand or run the workflow with force=true.")
        return 1
    print("Looks normal: OK to publish.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
