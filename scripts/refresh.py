#!/usr/bin/env python3
"""
Refresh MLS NEXT data and rebuild the dashboard. One page (index.html) holds every age group and
conference; the page shows one bracket at a time, picked with ?age=U15&conf=southwest.

  python3 scripts/refresh.py                         # every bracket, live fetch
  python3 scripts/refresh.py --age U13,U14 --conference Northwest   # only some brackets
  python3 scripts/refresh.py --offline               # rebuild from data/ only

Python 3.9+ standard library only (no pip installs).
"""
import argparse, csv, json, os, re, urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "https://mls-assist.theintelligenceplatform.com/data"
UA = {"User-Agent": "Mozilla/5.0 (personal dashboard refresh)"}
FIELDS = ["age", "conference", "match_id", "start", "home_id", "away_id", "home_team", "away_team", "home_score", "away_score"]

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
    local 'YYYY-MM-DD' when the kickoff time isn't set yet (the feed marks those with venue 'TBD')."""
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
    games = []
    for e in sch["events"]:
        h, a = str(e["home_squad_id"]), str(e["away_squad_id"])
        br = team_bracket.get(h)
        if br is None or br != team_bracket.get(a):
            continue  # only league games inside one bracket
        t = datetime.fromisoformat(e["start_time"].replace("Z", "+00:00"))
        if (e.get("event_location") or {}).get("name", "") == "TBD":
            start = t.astimezone(ZoneInfo(e.get("local_timezone") or "America/New_York")).strftime("%Y-%m-%d")
        else:
            start = t.strftime("%Y-%m-%dT%H:%MZ")
        done = e.get("completed")
        teams = next(x["teams"] for x in brackets if (x["age"], x["conf"]) == br)
        games.append({"age": br[0], "conference": br[1], "match_id": e["game_key"], "start": start,
                      "home_id": h, "away_id": a, "home_team": teams[h], "away_team": teams[a],
                      "home_score": e["home_score"] if done else "", "away_score": e["away_score"] if done else ""})
    brackets.sort(key=bracket_order)
    games.sort(key=lambda g: (age_num(g["age"]), g["conference"], g["start"], g["match_id"]))
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
    by = {}
    for g in games:
        by.setdefault((g["age"], g["conference"]), []).append(
            ",".join([str(g["match_id"]), g["start"], g["home_id"], g["away_id"], str(g["home_score"]), str(g["away_score"])]))
    dage, dconf = default.split(":", 1)
    data = {"default": {"age": dage, "conf": dconf}, "snap": meta["snapshot"],
            "brackets": [{"age": b["age"], "conf": b["conf"], "teams": b["teams"],
                          "raw": ";".join(by.get((b["age"], b["conf"]), []))} for b in brackets]}
    m = re.search(r"(\d\d)-(\d\d)$", meta.get("season_key", ""))
    season = f"20{m[1]}–{m[2]} season" if m else ""
    html = (tpl.replace("/*__DATA__*/{}", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
               .replace("__TITLE__", "MLS NEXT Homegrown Division dashboard")
               .replace("__SEASON__", season))
    open(f"{ROOT}/index.html", "w").write(html)
    played = sum(1 for g in games if str(g["home_score"]) != "")
    print(f"Built index.html  ({len(html)//1024} KB): {len(brackets)} brackets, "
          f"{sum(len(b['teams']) for b in brackets)} teams, {played}/{len(games)} games played, snapshot {meta['snapshot']}")

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
