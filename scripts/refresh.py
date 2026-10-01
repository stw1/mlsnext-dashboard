#!/usr/bin/env python3
"""
Refresh MLS NEXT data and rebuild the dashboard.

  python3 scripts/refresh.py                         # U14 Northwest, live fetch
  python3 scripts/refresh.py --age U15 --conference Southwest
  python3 scripts/refresh.py --offline               # rebuild from data/*.csv only

Python 3.9+ standard library only (no pip installs).
"""
import argparse, csv, json, os, re, sys, urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "https://mls-assist.theintelligenceplatform.com/data"
UA = {"User-Agent": "Mozilla/5.0 (personal dashboard refresh)"}

def get_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)

def slug(age, conf):
    return f"{age}_{conf.replace(' ', '-')}"

def fetch(age, conf, season, tz):
    st = get_json(f"{BASE}/standings/{season}.json")
    brackets = st["competition_season"]["competition_brackets"]
    br = [b for b in brackets if b["age_group"]["name"] == age and b["name"] == conf]
    if not br:
        opts = sorted({b["name"] for b in brackets if b["age_group"]["name"] == age})
        sys.exit(f"No bracket '{conf}' for {age}. Available: {opts}")
    teams = {str(s["team"]["squad_id"]): s["team"]["name"] for s in br[0]["standings"]}
    sch = get_json(f"{BASE}/schedule/{season}.json")
    zone = ZoneInfo(tz)
    rows = []
    for e in sch["events"]:
        h, a = str(e["home_squad_id"]), str(e["away_squad_id"])
        if h not in teams or a not in teams:
            continue
        t = datetime.fromisoformat(e["start_time"].replace("Z", "+00:00")).astimezone(zone)
        loc = (e.get("event_location") or {}).get("name", "")
        dt = t.strftime("%Y-%m-%d") if loc == "TBD" else t.strftime("%Y-%m-%d %H:%M")
        done = e.get("completed")
        rows.append([e["game_key"], dt, h, a, teams[h], teams[a],
                     e["home_score"] if done else "", e["away_score"] if done else ""])
    rows.sort(key=lambda r: r[1])
    return teams, rows, sch.get("synced_at", "")

def save(age, conf, teams, rows, meta):
    s = slug(age, conf)
    with open(f"{ROOT}/data/{s}_games.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["match_id","date_local","home_id","away_id","home_team","away_team","home_score","away_score"])
        w.writerows(rows)
    json.dump(teams, open(f"{ROOT}/data/{s}_teams.json", "w"), indent=1)
    json.dump(meta, open(f"{ROOT}/data/{s}_meta.json", "w"), indent=1)

def load(age, conf):
    s = slug(age, conf)
    teams = json.load(open(f"{ROOT}/data/{s}_teams.json"))
    meta = json.load(open(f"{ROOT}/data/{s}_meta.json"))
    with open(f"{ROOT}/data/{s}_games.csv") as f:
        rows = list(csv.reader(f))[1:]
    return teams, rows, meta

def build(age, conf, teams, rows, meta):
    tpl = open(f"{ROOT}/template/dashboard_template.html").read()
    raw = ";".join(",".join([r[0], r[1], r[2], r[3], str(r[6]), str(r[7])]) for r in rows)
    title = f"MLS NEXT Homegrown Division · {age} {conf} Conference"
    m = re.search(r"(\d\d)-(\d\d)$", meta.get("season_key", ""))
    season = f"20{m[1]}–{m[2]} season" if m else ""
    html = (tpl.replace('/*__RAW__*/""', json.dumps(raw))
               .replace("/*__TEAMS__*/{}", json.dumps(teams))
               .replace('/*__SNAP__*/""', json.dumps(meta["snapshot"]))
               .replace("__TITLE__", title)
               .replace("__BRACKET__", f"{age} {conf} Conference")
               .replace("__SEASON__", season))
    out = f"{ROOT}/dashboards/{slug(age, conf)}_dashboard.html"
    open(out, "w").write(html)
    if (age, conf) == ("U14", "Northwest"):  # GitHub Pages serves index.html at the site root
        open(f"{ROOT}/index.html", "w").write(html)
    played = sum(1 for r in rows if str(r[6]) != "")
    print(f"Built {out}  ({len(teams)} teams, {played}/{len(rows)} games played, snapshot {meta['snapshot']})")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--age", default="U14")
    ap.add_argument("--conference", default="Northwest")
    ap.add_argument("--season", default="mls-next-league-26-27")
    ap.add_argument("--tz", default="America/Los_Angeles")
    ap.add_argument("--offline", action="store_true", help="skip download, rebuild from data/")
    a = ap.parse_args()
    if a.offline:
        teams, rows, meta = load(a.age, a.conference)
    else:
        teams, rows, synced = fetch(a.age, a.conference, a.season, a.tz)
        meta = {"snapshot": datetime.now(ZoneInfo(a.tz)).date().isoformat(), "synced_at": synced, "age_group": a.age,
                "conference": a.conference, "season_key": a.season}
        save(a.age, a.conference, teams, rows, meta)
    build(a.age, a.conference, teams, rows, meta)
