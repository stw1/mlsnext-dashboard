#!/usr/bin/env python3
"""
Compare the dashboard's league tables with MLS's official standings (U15-U19; MLS publishes no official U13/U14
values). Run after refresh.py; the weekly GitHub workflow runs it after publishing and fails if anything differs,
so GitHub emails a warning.

  python3 scripts/check_official.py

Checks for every team that MLS lists with values: games played, wins, draws, losses, goals for and against; and
for every conference: the order of the table. Teams level on every tiebreaker the site can compute may be in any
order (MLS then uses disciplinary points and a coin toss; the page copies MLS's position for those).
MLS's standings can lag the scores (match reports within 24 h, 48 h to verify), so a team whose official record
equals ours without its games of the last 48 hours counts as "not updated yet", not as a difference.
Exit code 0 = all match, 1 = differences (listed), 2 = could not fetch the official standings.
"""
import collections, functools, os, sys
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import refresh

def tables(brackets, games, before=None):
    """Per bracket: {team: stats} and the played games, counted the way the page counts them: a league game is in
    the bracket of each of its teams, and only the bracket's own teams are tallied."""
    where = {sid: (b["age"], b["conf"]) for b in brackets for sid in b["teams"]}
    out = {}
    for b in brackets:
        out[(b["age"], b["conf"])] = ({c: dict(c=c, mp=0, w=0, d=0, l=0, pts=0, gf=0, ga=0, hgf=0, hga=0, agf=0, aga=0, hm=0, am=0)
                                       for c in b["teams"]}, [])
    for g in games:
        if g.get("comp", "league") != "league" or str(g["home_score"]) == "":
            continue
        if before and g["start"][:16] >= before:
            continue
        h, a, x, y = g["home_id"], g["away_id"], int(g["home_score"]), int(g["away_score"])
        for k in {where.get(h), where.get(a)} - {None}:
            T, gl = out[k]
            gl.append((h, a, x, y))
            for t, f, o, home in ((h, x, y, True), (a, y, x, False)):
                if t not in T:
                    continue
                r = T[t]; r["mp"] += 1; r["gf"] += f; r["ga"] += o
                r["w"] += f > o; r["d"] += f == o; r["l"] += f < o; r["pts"] += 3 if f > o else 1 if f == o else 0
                if home: r["hgf"] += f; r["hga"] += o; r["hm"] += 1
                else: r["agf"] += f; r["aga"] += o; r["am"] += 1
    return out

def sort_key(t):
    """Everything after head-to-head (rules XIII.l ii-viii): per match, away/home figures per away/home match."""
    pm = lambda v, d: v / d if d else 0
    return (pm(t["w"], t["mp"]), pm(t["gf"] - t["ga"], t["mp"]), pm(t["gf"], t["mp"]),
            pm(t["agf"] - t["aga"], t["am"]), pm(t["agf"], t["am"]), pm(t["hgf"] - t["hga"], t["hm"]), pm(t["hgf"], t["hm"]))

def ordered(T, gl):
    ppm = lambda t: t["pts"] / t["mp"] if t["mp"] else 0
    level = collections.Counter(round(ppm(t), 6) for t in T.values())
    def h2h(a, b):  # points b took off a minus points a took off b
        pa = pb = 0
        for h, aw, x, y in gl:
            if {h, aw} == {a["c"], b["c"]}:
                fa, fb = (x, y) if h == a["c"] else (y, x)
                pa += 3 if fa > fb else 1 if fa == fb else 0
                pb += 3 if fb > fa else 1 if fa == fb else 0
        return pb - pa
    def cmp(a, b):
        if ppm(a) != ppm(b):
            return -1 if ppm(a) > ppm(b) else 1
        if level[round(ppm(a), 6)] == 2 and (r := h2h(a, b)):
            return r
        ka, kb = sort_key(a), sort_key(b)
        return -1 if ka > kb else 1 if ka < kb else 0
    return sorted(T.values(), key=functools.cmp_to_key(cmp))

def main():
    brackets, games, meta, _ = refresh.load()
    try:
        st = refresh.get_json(f"{refresh.BASE}/standings/{meta.get('season_key', 'mls-next-league-26-27')}.json")
    except Exception as err:
        print(f"Could not fetch the official standings: {err}")
        return 2
    mine = tables(brackets, games)
    recent = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M")
    older = tables(brackets, games, before=recent)  # the same, leaving out games of the last 48 hours
    problems, lagging, teams, confs = [], [], 0, 0
    for b in st["competition_season"]["competition_brackets"]:
        key = (b["age_group"]["name"], b["name"])
        rows = sorted(b["standings"], key=lambda s: s["position"])
        off = {str(s["team"]["squad_id"]): {k: v["value"] for k, v in (s.get("tiebreaker_values") or {}).items()} for s in rows}
        if not any(off.values()):
            continue  # U13/U14, or no games yet: nothing official to compare
        if key not in mine:
            problems.append(f"{key[0]} {key[1]}: conference missing from the dashboard"); continue
        T, gl = mine[key]
        stat = lambda r: (r["mp"], r["w"], r["d"], r["l"], r["gf"], r["ga"]) if r else None
        confs += 1
        lag_here = False
        for s in rows:
            sid, tv, name = str(s["team"]["squad_id"]), off[str(s["team"]["squad_id"])], s["team"]["name"]
            if not tv:
                continue
            teams += 1
            mp = int(tv["matches_played"])
            want = (mp, int(tv["won_penalty_shootout"]), int(tv["tie_penalty_shootout"]), int(tv["loss_penalty_shootout"]),
                    round(float(tv["goals_for_per_match"]) * mp), round(float(tv["goals_against_per_match"]) * mp))
            got = stat(T.get(sid))
            if got != want and stat(older[key][0].get(sid)) == want:
                lagging.append(f"{key[0]} {key[1]} · {name}"); lag_here = True
            elif got != want:
                problems.append(f"{key[0]} {key[1]} · {name}: MLS has MP {want[0]}, W-D-L {want[1]}-{want[2]}-{want[3]}, "
                                f"goals {want[4]}-{want[5]}; dashboard has " + (
                                    f"MP {got[0]}, W-D-L {got[1]}-{got[2]}-{got[3]}, goals {got[4]}-{got[5]}" if got else "no such team"))
        # order: compare MLS's order with ours over the teams MLS lists; teams level on everything may swap
        if lag_here:
            continue  # MLS's table hasn't caught up with the latest games yet
        ours = [t for t in ordered(T, gl) if t["c"] in off]
        theirs = [str(s["team"]["squad_id"]) for s in rows]
        for i, (t, c) in enumerate(zip(ours, theirs)):
            if t["c"] != c and c in T and (t["pts"], t["mp"], sort_key(t)) != (T[c]["pts"], T[c]["mp"], sort_key(T[c])):
                n = {str(s["team"]["squad_id"]): s["team"]["name"] for s in rows}
                problems.append(f"{key[0]} {key[1]}: position {i + 1} is {n.get(c, c)} for MLS but {n.get(t['c'], t['c'])} on the dashboard")
                break
    print(f"Checked {teams} teams in {confs} conferences against MLS's official standings.")
    if lagging:
        print(f"{len(lagging)} team(s) where MLS's table doesn't include the last 48 hours of games yet (not an error):")
        for t in lagging:
            print("  - " + t)
    if problems:
        print(f"{len(problems)} difference(s):")
        for p in problems:
            print("  - " + p)
        return 1
    print("Everything matches.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
