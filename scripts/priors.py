#!/usr/bin/env python3
"""
Last-season priors: start each team's rating from how it did the season before, instead of "average".

  python3 scripts/priors.py --evaluate     # replay 2025-26 week by week with 2024-25 priors, compare settings
  python3 scripts/priors.py                # write data/priors.json for this season (from 2025-26)

Players move up an age group each season, so the "cohort" option uses the same club one age group younger
(this season's U14 <- last season's U13). Needs data/history/*.csv from scripts/history.py.
"""
import argparse, collections, csv, datetime, json, math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ratings import fit, probs, norm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGES = ["U13", "U14", "U15", "U16", "U17", "U19"]
PREV_AGE = {"U14": "U13", "U15": "U14", "U16": "U15", "U17": "U16", "U19": "U17"}  # same players, last season
LEAGUE = {"League", "League (Pro Player Pathway)"}

def load(season):
    with open(f"{ROOT}/data/history/{season}.csv") as f:
        return [r for r in csv.DictReader(f) if r["home_score"] != "" and r["age"] in AGES]

def key(name):
    return norm(name)

def season_teams(rows):
    """{(age, division): set(team keys)} from league games, plus all played games per age (league + Flex)."""
    br, games = collections.defaultdict(set), collections.defaultdict(list)
    for r in rows:
        h, a = key(r["home"]), key(r["away"])
        if r["bracket"] in LEAGUE:
            br[(r["age"], r["division"])].update((h, a))
        games[r["age"]].append((r["date"], h, a, int(r["home_score"]), int(r["away_score"]), r["bracket"] in LEAGUE))
    return br, games

def season_ratings(rows):
    """Final ratings of every team in a season: {age: {team: (att, def, conference)}}, fit per conference."""
    br, games = season_teams(rows)
    out = collections.defaultdict(dict)
    for (age, conf), teams in br.items():
        gs = [(h, a, x, y) for _, h, a, x, y, _ in games[age] if h in teams and a in teams]
        m = fit(gs, sorted(teams))
        for t in teams:
            out[age][t] = (m["att"][t], m["def"][t], conf)
    return out

def prior_for(age, team, last, mode, w):
    """Prior mean (att, def) for a team this season from last season's ratings.
    cohort = same club one age group younger (same players); same = same age group; cohort+same = cohort, else
    same; avg = mean of whichever of the two exist."""
    if mode == "avg":
        hits = [last[a][team][:2] for a in (PREV_AGE.get(age), age) if a and team in last.get(a, {})]
        return (w * sum(h[0] for h in hits) / len(hits), w * sum(h[1] for h in hits) / len(hits)) if hits else None
    src = []
    if mode in ("cohort", "cohort+same"):
        src.append(PREV_AGE.get(age))
    if mode in ("same", "cohort+same"):
        src.append(age)
    for a in src:
        if a and team in last.get(a, {}):
            at, de, _ = last[a][team]
            return (w * at, w * de)
    return None

VARIANTS = [("none", 0)] + [("cohort", w) for w in (0.25, 0.5, 0.75, 1.0)] + [("same", 0.5), ("cohort+same", 0.5)]

def evaluate(target="2025-26", before="2024-25"):
    rows, prev = load(target), load(before)
    last = season_ratings(prev)
    br, games = season_teams(rows)
    week = lambda d: datetime.date.fromisoformat(d).isocalendar()[:2]
    variants = VARIANTS
    res = {v: [0.0, 0, 0.0, 0, 0] for v in variants}  # ll, n, ll early, n early, hits
    cover = [0, 0]
    for (age, conf), teams in sorted(br.items()):
        tl = sorted(teams)
        gs = sorted(g for g in games[age] if g[1] in teams and g[2] in teams)
        weeks = sorted({week(g[0]) for g in gs if g[5]})
        for t in tl:
            cover[0] += 1; cover[1] += prior_for(age, t, last, "cohort", 1) is not None
        for v in variants:
            pri = {t: p for t in tl if (p := prior_for(age, t, last, v[0], v[1])) is not None} if v[0] != "none" else {}
            for i, wk in enumerate(weeks):
                train = [(h, a, x, y) for d, h, a, x, y, _ in gs if week(d) < wk]
                test = [(h, a, x, y) for d, h, a, x, y, lg in gs if week(d) == wk and lg]
                m = fit(train, tl, prior=pri, iters=25)
                for h, a, x, y in test:
                    ph, pd, pa = probs(m, h, a)
                    p = ph if x > y else pd if x == y else pa
                    r = res[v]; r[0] -= math.log(max(p, 1e-9)); r[1] += 1
                    if i < 6: r[2] -= math.log(max(p, 1e-9)); r[3] += 1
                    pick = "H" if ph - pa >= 0.05 else "A" if pa - ph >= 0.05 else "D"
                    r[4] += pick == ("H" if x > y else "A" if x < y else "D")
        print(f"  {age} {conf}: {len(tl)} teams, {len(gs)} games", flush=True)
    print(f"\nTeams with a cohort match in {before}: {cover[1]} of {cover[0]}")
    print(f"{'setting':<18}{'log-loss all':>13}{'first 6 wks':>13}{'picks right':>13}")
    for v, (ll, n, le, ne, hits) in res.items():
        print(f"{v[0] + (' x' + str(v[1]) if v[1] else ''):<18}{ll / n:>13.4f}{le / max(ne, 1):>13.4f}{hits / n:>12.1%}")

def evaluate_conf(target="2025-26", before="2024-25"):
    """Do last season's conference strengths help predict this season's games between conferences?
    Team ratings come from this season's own-conference games only (so cross-conference results never leak in);
    conference effects come from last season's joint fit (same age group), scaled by w."""
    from ratings import fit_conf
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from pastseasons import conference as conf_of
    rows, prev = load(target), load(before)
    for age in AGES:
        tc, tcp = {}, {}
        for r in rows:
            if r["age"] == age and r["bracket"] in LEAGUE:
                tc[key(r["home"])] = tc[key(r["away"])] = conf_of(r)
        for r in prev:
            if r["age"] == age and r["bracket"] in LEAGUE:
                tcp[key(r["home"])] = tcp[key(r["away"])] = conf_of(r)
        gs = [(key(r["home"]), key(r["away"]), int(r["home_score"]), int(r["away_score"])) for r in rows
              if r["age"] == age and key(r["home"]) in tc and key(r["away"]) in tc]
        cross = [g for g in gs if tc[g[0]] != tc[g[1]]]
        gp = [(key(r["home"]), key(r["away"]), int(r["home_score"]), int(r["away_score"])) for r in prev
              if r["age"] == age and key(r["home"]) in tcp and key(r["away"]) in tcp]
        pcross = sum(1 for g in gp if tcp[g[0]] != tcp[g[1]])
        if not cross or not pcross:
            print(f"{age}: {len(cross)} cross-conference games this season, {pcross} last season - nothing to test"); continue
        within = {}
        for c in set(tc.values()):
            teams = sorted(t for t in tc if tc[t] == c)
            m = fit([g for g in gs if tc[g[0]] == c and tc[g[1]] == c], teams)
            within[c] = m
        cm = fit_conf(gp, tcp)
        out = []
        for w in (0, 0.25, 0.5, 0.75, 1.0):
            ll = 0.0
            for h, a, x, y in cross:
                mh, ma = within[tc[h]], within[tc[a]]
                ca = lambda t: w * cm["ca"].get(tc[t], 0); cd = lambda t: w * cm["cd"].get(tc[t], 0)
                m = {"mu": (mh["mu"] + ma["mu"]) / 2, "home": (mh["home"] + ma["home"]) / 2,
                     "att": {h: mh["att"][h] + ca(h), a: ma["att"][a] + ca(a)}, "def": {h: mh["def"][h] + cd(h), a: ma["def"][a] + cd(a)}}
                ph, pd, pa = probs(m, h, a)
                ll -= math.log(max(ph if x > y else pd if x == y else pa, 1e-9))
            out.append(f"w={w}: {ll / len(cross):.4f}")
        print(f"{age}: {len(cross)} cross-conference games (last season {pcross}) | log-loss " + "  ".join(out))

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--evaluate", action="store_true")
    ap.add_argument("--evaluate-conf", action="store_true")
    a = ap.parse_args()
    if a.evaluate:
        evaluate()
    if a.evaluate_conf:
        evaluate_conf()
