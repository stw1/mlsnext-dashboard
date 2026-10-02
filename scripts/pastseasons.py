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

def main_conf(rs):
    """{(age, team key): conference}: where each team played most of its league games. A few seasons label some of
    a conference's games with a sub-division (2024-25 U16 "Mid-America (East)"), which would otherwise split a team
    across two tables."""
    n = collections.Counter()
    for r in rs:
        if r["bracket"] in LEAGUE:
            for side in ("home", "away"):
                n[(r["age"], norm(r[side]), conference(r))] += 1
    ranked_ = sorted(n.items(), key=lambda x: (-x[1], x[0][2]))
    best = {}
    for (age, k, conf), c in ranked_:
        best.setdefault((age, k), conf)
    # a "conference" that would hold a single team is a labelling leftover: use that team's next most common one
    size = collections.Counter((a, c) for (a, _), c in best.items())
    for (age, k), conf in list(best.items()):
        if size[(age, conf)] == 1:
            alt = next((c2 for (a2, k2, c2), _ in ranked_ if (a2, k2) == (age, k) and c2 != conf), None)
            base = conf.split(" (")[0]  # "Mid-America (East)" -> "Mid-America"
            alt = alt or (base if base != conf and size[(age, base)] else None)
            if alt:
                best[(age, k)] = alt
    return best

def brackets_of(rs):
    """{(age, conf): {team key: display name}} from league games, each team in its main conference."""
    main, out = main_conf(rs), collections.defaultdict(dict)
    for r in rs:
        if r["bracket"] in LEAGUE:
            for side in ("home", "away"):
                k = norm(r[side])
                out[(r["age"], main[(r["age"], k)])].setdefault(k, r[side])
    return out

def ranked(games, teams):
    """Official order (HD rules XIII): points per match, head-to-head for two-team ties, then wins, GD, GF,
    away GD and GF per away match, home GD and GF per home match. games: [(h, a, hs, as)]."""
    T = {t: dict(mp=0, w=0, d=0, l=0, gf=0, ga=0, pts=0, hgf=0, hga=0, agf=0, aga=0, hm=0, am=0) for t in teams}
    for h, a, x, y in games:
        H, A = T[h], T[a]
        H["mp"] += 1; A["mp"] += 1; H["gf"] += x; H["ga"] += y; A["gf"] += y; A["ga"] += x
        H["hgf"] += x; H["hga"] += y; A["agf"] += y; A["aga"] += x; H["hm"] += 1; A["am"] += 1
        if x > y: H["w"] += 1; A["l"] += 1; H["pts"] += 3
        elif x < y: A["w"] += 1; H["l"] += 1; A["pts"] += 3
        else: H["d"] += 1; A["d"] += 1; H["pts"] += 1; A["pts"] += 1
    pm = lambda t, v, d="mp": v / T[t][d] if T[t][d] else 0  # away/home figures are per away/home match
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
                     pm(t, T[t]["agf"] - T[t]["aga"], "am"), pm(t, T[t]["agf"], "am"), pm(t, T[t]["hgf"] - T[t]["hga"], "hm"), pm(t, T[t]["hgf"], "hm"))
    order = sorted(teams, key=key, reverse=True)
    return [(t, T[t]) for t in order]

def final_tables(season):
    rs = [r for r in rows(season) if r["home_score"] != ""]
    main, out = main_conf(rs), {}
    for (age, conf), teams in brackets_of(rs).items():
        gs = [(norm(r["home"]), norm(r["away"]), int(r["home_score"]), int(r["away_score"])) for r in rs
              if r["bracket"] in LEAGUE and r["age"] == age and main[(age, norm(r["home"]))] == conf == main[(age, norm(r["away"]))]]
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

def season_index(season):
    """{(age, team key): (conf, rank, of, stats, display name, [flex w, d, l])} for one finished season."""
    rs = [r for r in rows(season) if r["home_score"] != ""]
    names = brackets_of(rs)
    flex = collections.defaultdict(lambda: [0, 0, 0])
    for r in rs:
        if "Flex" not in r["bracket"]:
            continue
        x, y = int(r["home_score"]), int(r["away_score"])
        for side, f, a in (("home", x, y), ("away", y, x)):
            flex[(r["age"], norm(r[side]))][0 if f > a else 1 if f == a else 2] += 1
    out = {}
    for (age, conf), tb in final_tables(season).items():
        for i, (k, st) in enumerate(tb):
            out[(age, k)] = (conf, i + 1, len(tb), st, names[(age, conf)].get(k, k), flex.get((age, k), [0, 0, 0]))
    return out

def team_history(brackets):
    """Two views of each squad's past, newest season first, rows [season, age, conf, rank, of, w, d, l, gf, ga,
    name that season ("" if unchanged), flex w, flex d, flex l]:
      hist  the same players (this season's U15 = last season's U14 = the season before's U13)
      same  the club's team in this age group in earlier seasons (different players each year)"""
    idx = {s: season_index(s) for s in seasons()}
    # the name that season is only stored when it differs from this season's ("" = same name)
    row = lambda s, age, hit, now: [s, age, hit[0], hit[1], hit[2], hit[3]["w"], hit[3]["d"], hit[3]["l"], hit[3]["gf"], hit[3]["ga"],
                                    "" if hit[4] == now else hit[4], *hit[5]]
    hist, same = {}, {}
    for b in brackets:
        for sid, name in b["teams"].items():
            k, age, h, sm = norm(name), b["age"], [], []
            for s in seasons():  # newest first
                age = PREV_AGE.get(age)
                if not age:
                    break
                if (age, k) in idx[s]:
                    h.append(row(s, age, idx[s][(age, k)], name))
            for s in seasons():
                if (b["age"], k) in idx[s]:
                    sm.append(row(s, b["age"], idx[s][(b["age"], k)], name))
            if h:
                hist[sid] = h
            if sm:
                same[sid] = sm
    return hist, same

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
