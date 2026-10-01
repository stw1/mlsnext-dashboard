#!/usr/bin/env python3
"""
Refresh MLS NEXT data and rebuild the dashboard. One page holds every age group passed in --age,
with a toggle between them (the page reads ?age=U13 etc.).

  python3 scripts/refresh.py                         # U13 + U14 Northwest, live fetch
  python3 scripts/refresh.py --age U15,U16 --conference Southwest --default-age U16
  python3 scripts/refresh.py --offline               # rebuild from data/*.csv only

Python 3.9+ standard library only (no pip installs).
"""
import argparse, csv, json, os, re, sys, urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "https://mls-assist.theintelligenceplatform.com/data"
UA = {"User-Agent": "Mozilla/5.0 (personal dashboard refresh)"}
SITE_CONF = "Northwest"  # this conference's page is also written to index.html (the GitHub Pages root)

def get_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)

def slug(age, conf):
    return f"{age}_{conf.replace(' ', '-')}"

def fetch(ages, conf, season, tz):
    """Download standings + schedule once and return {age: (teams, rows)} for each age group."""
    st = get_json(f"{BASE}/standings/{season}.json")
    brackets = st["competition_season"]["competition_brackets"]
    teams_by_age = {}
    for age in ages:
        br = [b for b in brackets if b["age_group"]["name"] == age and b["name"] == conf]
        if not br:
            opts = sorted({b["name"] for b in brackets if b["age_group"]["name"] == age})
            sys.exit(f"No bracket '{conf}' for {age}. Available: {opts}")
        teams_by_age[age] = {str(s["team"]["squad_id"]): s["team"]["name"] for s in br[0]["standings"]}
    sch = get_json(f"{BASE}/schedule/{season}.json")
    zone = ZoneInfo(tz)
    out = {}
    for age, teams in teams_by_age.items():
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
        out[age] = (teams, rows)
    return out, sch.get("synced_at", "")

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

def build(conf, brackets, default_age):
    """brackets: list of (age, teams, rows, meta), all for the same conference."""
    tpl = open(f"{ROOT}/template/dashboard_template.html").read()
    data = {"conf": conf, "default": default_age, "brackets": []}
    for age, teams, rows, meta in brackets:
        raw = ";".join(",".join([r[0], r[1], r[2], r[3], str(r[6]), str(r[7])]) for r in rows)
        data["brackets"].append({"age": age, "conf": conf, "raw": raw, "teams": teams, "snap": meta["snapshot"]})
    m = re.search(r"(\d\d)-(\d\d)$", brackets[0][3].get("season_key", ""))
    season = f"20{m[1]}–{m[2]} season" if m else ""
    html = (tpl.replace("/*__DATA__*/{}", json.dumps(data, ensure_ascii=False))
               .replace("__TITLE__", f"MLS NEXT Homegrown Division · {conf} Conference")
               .replace("__SEASON__", season))
    out = f"{ROOT}/dashboards/{conf.replace(' ', '-')}_dashboard.html"
    open(out, "w").write(html)
    if conf == SITE_CONF:
        open(f"{ROOT}/index.html", "w").write(html)
    print(f"Built {out}")
    for age, teams, rows, meta in brackets:
        played = sum(1 for r in rows if str(r[6]) != "")
        print(f"  {age}: {len(teams)} teams, {played}/{len(rows)} games played, snapshot {meta['snapshot']}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--age", default="U13,U14", help="comma-separated age groups, e.g. U13,U14")
    ap.add_argument("--conference", default="Northwest")
    ap.add_argument("--default-age", default="U14", help="age shown when the page has no ?age= and no saved choice")
    ap.add_argument("--season", default="mls-next-league-26-27")
    ap.add_argument("--tz", default="America/Los_Angeles")
    ap.add_argument("--offline", action="store_true", help="skip download, rebuild from data/")
    a = ap.parse_args()
    ages = sorted({x.strip() for x in a.age.split(",") if x.strip()}, key=lambda s: int(re.sub(r"\D", "", s) or 0))
    brackets = []
    if a.offline:
        for age in ages:
            brackets.append((age, *load(age, a.conference)))
    else:
        fetched, synced = fetch(ages, a.conference, a.season, a.tz)
        snap = datetime.now(ZoneInfo(a.tz)).date().isoformat()
        for age in ages:
            teams, rows = fetched[age]
            meta = {"snapshot": snap, "synced_at": synced, "age_group": age,
                    "conference": a.conference, "season_key": a.season}
            save(age, a.conference, teams, rows, meta)
            brackets.append((age, teams, rows, meta))
    build(a.conference, brackets, a.default_age if a.default_age in ages else ages[-1])
