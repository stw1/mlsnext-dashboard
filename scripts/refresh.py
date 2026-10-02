#!/usr/bin/env python3
"""
Refresh MLS NEXT data and rebuild the dashboard. One page (index.html) holds every age group and
conference; the page shows one bracket at a time, picked with ?age=U15&conf=southwest.

  python3 scripts/refresh.py                         # every bracket, live fetch
  python3 scripts/refresh.py --age U13,U14 --conference Northwest   # only some brackets
  python3 scripts/refresh.py --offline               # rebuild from data/ only

Python 3.9+ standard library only (no pip installs).
"""
import argparse, csv, json, os, re, sys, urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pastseasons

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "https://mls-assist.theintelligenceplatform.com/data"
UA = {"User-Agent": "Mozilla/5.0 (personal dashboard refresh)"}
# Starting ratings from the season before (scripts/priors.py --evaluate chose these). None = start everyone at average.
PRIOR_WEIGHT, PRIOR_MODE = 0.75, "avg"
FIELDS = ["age", "conference", "comp", "match_id", "start", "home_id", "away_id", "home_team", "away_team",
          "home_score", "away_score", "venue"]

def get_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)

def age_num(age):
    return int(re.sub(r"\D", "", age) or 0)

def bracket_order(b):
    # by age, then regular conferences A–Z, then Pro Player Pathway ones
    return (age_num(b["age"]), "Pro Player" in b["conf"], b["conf"])

def wanted(value, spec):
    return spec == "all" or value.lower() in {s.strip().lower() for s in spec.split(",")}

def fetch(season, ages, confs):
    """Return (brackets, games, synced_at). Each game's start is UTC 'YYYY-MM-DDTHH:MMZ', or a
    local 'YYYY-MM-DD' when the kickoff time isn't set yet (the feed marks those with venue 'TBD').
    comp is 'league', or 'flex' for MLS NEXT Flex games (U15-U19, same squads, always inside one
    league conference); Flex games only feed the ratings, never the standings."""
    st = get_json(f"{BASE}/standings/{season}.json")
    brackets, team_bracket = [], {}
    for b in st["competition_season"]["competition_brackets"]:
        age, conf = b["age_group"]["name"], b["name"]
        if not (wanted(age, ages) and wanted(conf, confs)):
            continue
        teams = {str(s["team"]["squad_id"]): s["team"]["name"] for s in b["standings"]}
        brackets.append({"age": age, "conf": conf, "teams": teams})
        for sid in teams:
            team_bracket[sid] = (age, conf)
    sch = get_json(f"{BASE}/schedule/{season}.json")
    try:
        flex = get_json(f"{BASE}/schedule/{season.replace('-league-', '-flex-')}.json")["events"]
    except Exception as err:  # Flex is a bonus; never block the league refresh on it
        print(f"warning: no Flex data ({err})")
        flex = []
    games = []
    for comp, e in [("league", e) for e in sch["events"]] + [("flex", e) for e in flex]:
        h, a = str(e["home_squad_id"]), str(e["away_squad_id"])
        br = team_bracket.get(h)
        if br is None or br != team_bracket.get(a):
            continue  # only games between two teams of the same bracket
        t = datetime.fromisoformat(e["start_time"].replace("Z", "+00:00"))
        loc = ((e.get("event_location") or {}).get("name") or "").strip()
        if loc == "TBD":  # kickoff not set yet: keep only the local date
            venue, start = "", t.astimezone(ZoneInfo(e.get("local_timezone") or "America/New_York")).strftime("%Y-%m-%d")
        else:
            venue, start = loc, t.strftime("%Y-%m-%dT%H:%MZ")
        done = e.get("completed")
        teams = next(x["teams"] for x in brackets if (x["age"], x["conf"]) == br)
        games.append({"age": br[0], "conference": br[1], "comp": comp, "match_id": e["game_key"], "start": start,
                      "home_id": h, "away_id": a, "home_team": teams[h], "away_team": teams[a],
                      "home_score": e["home_score"] if done else "", "away_score": e["away_score"] if done else "",
                      "venue": venue})
    brackets.sort(key=bracket_order)
    games.sort(key=lambda g: (age_num(g["age"]), g["conference"], g["comp"] != "league", g["start"], str(g["match_id"])))
    return brackets, games, sch.get("synced_at", "")

def save(brackets, games, meta):
    os.makedirs(f"{ROOT}/data", exist_ok=True)
    with open(f"{ROOT}/data/games.csv", "w", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        w.writerows(games)
    json.dump(brackets, open(f"{ROOT}/data/brackets.json", "w"), indent=1, ensure_ascii=False)
    json.dump(meta, open(f"{ROOT}/data/meta.json", "w"), indent=1)

def load():
    brackets = json.load(open(f"{ROOT}/data/brackets.json"))
    meta = json.load(open(f"{ROOT}/data/meta.json"))
    with open(f"{ROOT}/data/games.csv") as f:
        games = list(csv.DictReader(f))
    return brackets, games, meta

def build(brackets, games, meta, default):
    tpl = open(f"{ROOT}/template/dashboard_template.html").read()
    # league games: id,start,home,away,hs,as,venue# ; Flex games (played only, for the ratings): start,home,away,hs,as
    venues, vix, league, flex = [], {}, {}, {}
    for g in games:
        key = (g["age"], g["conference"])
        if g.get("comp", "league") == "flex":
            if str(g["home_score"]) != "":
                flex.setdefault(key, []).append(",".join([g["start"], g["home_id"], g["away_id"], str(g["home_score"]), str(g["away_score"])]))
            continue
        v = g.get("venue") or ""
        if v and v not in vix:
            vix[v] = len(venues); venues.append(v)
        league.setdefault(key, []).append(",".join([str(g["match_id"]), g["start"], g["home_id"], g["away_id"],
                                                    str(g["home_score"]), str(g["away_score"]), str(vix[v]) if v else ""]))
    dage, dconf = default.split(":", 1)
    data = {"default": {"age": dage, "conf": dconf}, "snap": meta["snapshot"], "venues": venues,
            "brackets": [{"age": b["age"], "conf": b["conf"], "teams": b["teams"],
                          "raw": ";".join(league.get((b["age"], b["conf"]), [])),
                          "flex": ";".join(flex.get((b["age"], b["conf"]), []))} for b in brackets]}
    m = re.search(r"(\d\d)-(\d\d)$", meta.get("season_key", ""))
    current = f"20{m[1]}–{m[2]}" if m else "This season"
    # past seasons (scripts/history.py) get their own pages; the season picker links them all
    past = pastseasons.seasons()
    data["seasons"] = [{"key": current, "file": "index.html"}] + [{"key": pastseasons.label(s), "file": f"season-{s}.html"} for s in past]
    data["hist"] = pastseasons.team_history(brackets) if past else {}
    if past and PRIOR_WEIGHT:
        pri = pastseasons.priors(brackets, past[0], PRIOR_WEIGHT, PRIOR_MODE)
        for b in data["brackets"]:
            b["prior"] = {k: pri[k] for k in b["teams"] if k in pri}
    def page(d, season_text):
        return (tpl.replace("/*__DATA__*/{}", json.dumps(d, ensure_ascii=False, separators=(",", ":")))
                   .replace("__TITLE__", "MLS NEXT Homegrown Division dashboard").replace("__SEASON__", season_text))
    html = page(data, f"{current} season")
    open(f"{ROOT}/index.html", "w").write(html)
    for s in past:
        d = pastseasons.past_data(s, default); d["seasons"] = data["seasons"]
        before = [x for x in past if x < s]
        if before and PRIOR_WEIGHT:  # the replayed accuracy of a past season also starts from the season before it
            pri = pastseasons.priors(d["brackets"], before[0], PRIOR_WEIGHT, PRIOR_MODE)
            for b in d["brackets"]:
                b["prior"] = {k: pri[k] for k in b["teams"] if k in pri}
        open(f"{ROOT}/season-{s}.html", "w").write(page(d, f"{pastseasons.label(s)} season · final"))
        print(f"Built season-{s}.html ({len(d['brackets'])} brackets)")
    played = sum(1 for g in games if str(g["home_score"]) != "" and g.get("comp", "league") == "league")
    fplayed = sum(1 for g in games if str(g["home_score"]) != "" and g.get("comp") == "flex")
    print(f"Built index.html  ({len(html)//1024} KB): {len(brackets)} brackets, "
          f"{sum(len(b['teams']) for b in brackets)} teams, {played} league + {fplayed} Flex games played, snapshot {meta['snapshot']}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--age", default="all", help="'all' or comma-separated age groups, e.g. U13,U14")
    ap.add_argument("--conference", default="all", help="'all' or comma-separated conference names")
    ap.add_argument("--default", default="U14:Northwest", help="bracket shown to first-time visitors, AGE:CONFERENCE")
    ap.add_argument("--season", default="mls-next-league-26-27")
    ap.add_argument("--tz", default="America/Los_Angeles", help="time zone for the snapshot date")
    ap.add_argument("--offline", action="store_true", help="skip download, rebuild from data/")
    a = ap.parse_args()
    if a.offline:
        brackets, games, meta = load()
    else:
        brackets, games, synced = fetch(a.season, a.age, a.conference)
        if not brackets:
            raise SystemExit(f"No brackets match --age {a.age} --conference {a.conference}")
        meta = {"snapshot": datetime.now(ZoneInfo(a.tz)).date().isoformat(), "synced_at": synced, "season_key": a.season}
        save(brackets, games, meta)
    build(brackets, games, meta, a.default)
