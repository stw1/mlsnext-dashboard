"""
Past seasons (from data/history/<season>.csv, downloaded by scripts/history.py) for the dashboard build:
  past_data(season)       page data for season-<season>.html, same shape as the current season's DATA
  team_history(brackets)  this season's squads -> how the same players finished in earlier seasons
"""
import collections, csv, glob, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ratings import norm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGES = ["U13", "U14", "U15", "U16", "U17", "U19"]
LEAGUE = {"League", "League (Pro Player Pathway)"}
PREV_AGE = {"U14": "U13", "U15": "U14", "U16": "U15", "U17": "U16", "U19": "U17"}

def seasons():
    return sorted((os.path.basename(p)[:-4] for p in glob.glob(f"{ROOT}/data/history/*.csv")), reverse=True)

def label(season):  # "2025-26" -> "2025–26"
    return season.replace("-", "–")

def rows(season):
    with open(f"{ROOT}/data/history/{season}.csv") as f:
        return [r for r in csv.DictReader(f) if r["age"] in AGES]

def conference(r):
    # PPP conferences get the same "(Pro Player Pathway)" suffix the current feed uses
    d = r["division"] or r["group_home"]
    return d if r["bracket"] != "League (Pro Player Pathway)" or "Pro Player" in d else f"{d} (Pro Player Pathway)"

def brackets_of(rs):
    """{(age, conf): {team key: display name}} from league games."""
    out = collections.defaultdict(dict)
    for r in rs:
        if r["bracket"] in LEAGUE:
            for side in ("home", "away"):
                out[(r["age"], conference(r))].setdefault(norm(r[side]), r[side])
    return out

def ranked(games, teams):
    """Official order (HD rules XIII): points per match, head-to-head for two-team ties, then wins, GD, GF,
    away GD, away GF, home GD, home GF, all per match. games: [(h, a, hs, as)]."""
    T = {t: dict(mp=0, w=0, d=0, l=0, gf=0, ga=0, pts=0, hgf=0, hga=0, agf=0, aga=0) for t in teams}
    for h, a, x, y in games:
        H, A = T[h], T[a]
        H["mp"] += 1; A["mp"] += 1; H["gf"] += x; H["ga"] += y; A["gf"] += y; A["ga"] += x
        H["hgf"] += x; H["hga"] += y; A["agf"] += y; A["aga"] += x
        if x > y: H["w"] += 1; A["l"] += 1; H["pts"] += 3
        elif x < y: A["w"] += 1; H["l"] += 1; A["pts"] += 3
        else: H["d"] += 1; A["d"] += 1; H["pts"] += 1; A["pts"] += 1
    pm = lambda t, v: v / T[t]["mp"] if T[t]["mp"] else 0
    ppm = {t: pm(t, T[t]["pts"]) for t in teams}
    tied = collections.Counter(round(v, 6) for v in ppm.values())
    def h2h(t):  # points against the one team it is tied with
        others = [u for u in teams if u != t and round(ppm[u], 6) == round(ppm[t], 6)]
        if tied[round(ppm[t], 6)] != 2:
            return 0
        u = others[0]; p = 0
        for h, a, x, y in games:
            if (h, a) == (t, u): p += 3 if x > y else 1 if x == y else 0
            elif (h, a) == (u, t): p += 3 if y > x else 1 if x == y else 0
        return p
    key = lambda t: (ppm[t], h2h(t), pm(t, T[t]["w"]), pm(t, T[t]["gf"] - T[t]["ga"]), pm(t, T[t]["gf"]),
                     pm(t, T[t]["agf"] - T[t]["aga"]), pm(t, T[t]["agf"]), pm(t, T[t]["hgf"] - T[t]["hga"]), pm(t, T[t]["hgf"]))
    order = sorted(teams, key=key, reverse=True)
    return [(t, T[t]) for t in order]

def final_tables(season):
    rs = [r for r in rows(season) if r["home_score"] != ""]
    out = {}
    for (age, conf), teams in brackets_of(rs).items():
        gs = [(norm(r["home"]), norm(r["away"]), int(r["home_score"]), int(r["away_score"])) for r in rs
              if r["bracket"] in LEAGUE and r["age"] == age and conference(r) == conf]
        out[(age, conf)] = ranked(gs, list(teams))
    return out

def past_data(season, default):
    """Page data for a finished season. Team ids are per-season ("p12"); kickoff times are venue-local
    ("YYYY-MM-DD HH:MM", shown as is). Flex and other games between two teams of a conference feed the ratings."""
    rs = [r for r in rows(season) if r["home_score"] != ""]
    br = brackets_of(rs)
    ids, conf_of = {}, {}
    for (age, conf), teams in sorted(br.items()):
        for k in sorted(teams):
            ids[(age, k)] = f"p{len(ids)}"; conf_of[(age, k)] = conf
    venues, vix, league, extra = [], {}, collections.defaultdict(list), collections.defaultdict(list)
    for r in rs:
        h, a = (r["age"], norm(r["home"])), (r["age"], norm(r["away"]))
        if h not in ids or a not in ids or conf_of[h] != conf_of[a]:
            continue
        start = f"{r['date']} {r['time']}" if r["time"] else r["date"]
        key = (r["age"], conf_of[h])
        if r["bracket"] in LEAGUE:
            v = r["venue"]
            if v and v not in vix:
                vix[v] = len(venues); venues.append(v)
            league[key].append(",".join([r["match_id"], start, ids[h], ids[a], r["home_score"], r["away_score"], str(vix[v]) if v else ""]))
        else:
            v = r["venue"]
            if v and v not in vix:
                vix[v] = len(venues); venues.append(v)
            extra[key].append(",".join([r["match_id"], start, ids[h], ids[a], r["home_score"], r["away_score"], str(vix[v]) if v else ""]))
    order = lambda k: (AGES.index(k[0]), "Pro Player" in k[1], k[1])
    dage, dconf = default.split(":", 1)
    last = max(r["date"] for r in rs) if rs else ""
    return {"default": {"age": dage, "conf": dconf}, "snap": last, "venues": venues, "past": label(season),
            "brackets": [{"age": age, "conf": conf, "teams": {ids[(age, k)]: n for k, n in sorted(br[(age, conf)].items())},
                          "raw": ";".join(league[(age, conf)]), "flex": ";".join(extra[(age, conf)])}
                         for age, conf in sorted(br, key=order)]}

def team_history(brackets):
    """{squad_id: [[season, age, conf, rank, of, w, d, l, gf, ga], ...]} following the same players back
    (this season's U14 -> last season's U13 -> the season before's U12 is not in MLS NEXT, so it stops)."""
    tables = {s: final_tables(s) for s in seasons()}
    where = {s: {(age, k): (conf, i + 1, len(tb), st) for (age, conf), tb in t.items() for i, (k, st) in enumerate(tb)}
             for s, t in tables.items()}
    out = {}
    for b in brackets:
        for sid, name in b["teams"].items():
            k, age, hist = norm(name), b["age"], []
            for s in seasons():  # newest first
                age = PREV_AGE.get(age)
                if not age:
                    break
                hit = where[s].get((age, k))
                if hit:
                    conf, rank, n, st = hit
                    hist.append([s, age, conf, rank, n, st["w"], st["d"], st["l"], st["gf"], st["ga"]])
            if hist:
                out[sid] = hist
    return out

def priors(brackets, prev_season, weight, mode="cohort"):
    """Starting ratings for each team from the season before: {squad_id: [att, def]} (weight already applied).
    mode "cohort" = same club one age group younger (the same players), "same" = same age group last season."""
    import priors as P
    last = P.season_ratings(P.load(prev_season))
    out = {}
    for b in brackets:
        for sid, name in b["teams"].items():
            p = P.prior_for(b["age"], norm(name), last, mode, weight)
            if p:
                out[sid] = [round(p[0], 3), round(p[1], 3)]
    return out
