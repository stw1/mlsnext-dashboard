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
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pastseasons

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "https://mls-assist.theintelligenceplatform.com/data"
UA = {"User-Agent": "Mozilla/5.0 (personal dashboard refresh)"}
# Starting ratings from the season before (scripts/priors.py --evaluate chose these). None = start everyone at average.
PRIOR_WEIGHT, PRIOR_MODE = 0.75, "avg"
FIELDS = ["age", "conference", "comp", "match_id", "start", "home_id", "away_id", "home_team", "away_team",
          "home_score", "away_score", "venue", "pens"]

SITE = "https://stw1.github.io/mlsnext-dashboard/"  # used in calendar links
# Footer "Report a problem" link: a form URL (e.g. a Google Form) or an email address. "" = no link.
FEEDBACK = "support@spaikz.com"
# First-party analytics (analytics/fa.js -> your Firebase project; setup in analytics/README.md). The Firebase project
# comes from analytics/config.json; with no projectId there the tracker is inlined but does nothing.
ANALYTICS_SITE = "mlsnext"

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
    comp is 'league', or 'flex' for MLS NEXT Flex games (U15-U19, same squads). League games are always inside
    one bracket. Flex games are kept when at least one team is in a bracket: most are inside one conference, but
    Pro Player Pathway academies also play regular-conference clubs, and some opponents (MLS academies) have no
    league bracket at all. Flex never counts in the standings; only same-bracket Flex games feed the ratings."""
    st = get_json(f"{BASE}/standings/{season}.json")
    brackets, team_bracket = [], {}
    for b in st["competition_season"]["competition_brackets"]:
        age, conf = b["age_group"]["name"], b["name"]
        if not (wanted(age, ages) and wanted(conf, confs)):
            continue
        teams = {str(s["team"]["squad_id"]): s["team"]["name"] for s in b["standings"]}
        # MLS's own table position (published for U15-U19 once games are played): the final tiebreaker for teams level
        # on every number we can compute (the rules then use disciplinary points and a coin toss)
        pos = {str(s["team"]["squad_id"]): s["position"] for s in b["standings"] if s.get("tiebreaker_values")}
        brackets.append({"age": age, "conf": conf, "teams": teams, **({"pos": pos} if pos else {})})
        for sid in teams:
            team_bracket[sid] = (age, conf)
    sch = get_json(f"{BASE}/schedule/{season}.json")
    fkey = season.replace('-league-', '-flex-')
    try:
        flex = get_json(f"{BASE}/schedule/{fkey}.json")["events"]
    except Exception as err:  # Flex is a bonus; never block the league refresh on it
        print(f"warning: no Flex data ({err})")
        flex = []
    # official Flex group tables (MLS's own points: 3 win, 2 shootout win, 1 shootout loss; ranked by points per game)
    groups = []
    try:
        for b in get_json(f"{BASE}/standings/{fkey}.json")["competition_season"]["competition_brackets"]:
            if not wanted(b["age_group"]["name"], ages):
                continue
            rows = []
            for st_ in b["standings"]:
                tv = {k: v["value"] for k, v in (st_.get("tiebreaker_values") or {}).items()}
                rows.append([str(st_["team"]["squad_id"]), st_["team"]["name"], st_["position"], int(tv.get("matches_played", 0)),
                             int(tv.get("won_penalty_shootout", 0)), int(tv.get("tie_penalty_shootout", 0)), int(tv.get("loss_penalty_shootout", 0)),
                             int(tv.get("points_penalty_shootout", 0)), float(tv.get("points_per_match_penalty_shootout", 0)),
                             float(tv.get("goal_differential_per_match", 0))])
            groups.append({"age": b["age_group"]["name"], "name": b["name"], "rows": sorted(rows, key=lambda r: r[2])})
    except Exception as err:
        print(f"warning: no Flex standings ({err})")
    # Teams that play a conference's league schedule but are missing from MLS's standings feed (2026-27: FC Bay Area
    # Surf U15, New England Revolution U14) join the conference of their opponents, so their games and table row show.
    by_key = {(b["age"], b["conf"]): b for b in brackets}
    for e in sch["events"]:
        h, a = str(e["home_squad_id"]), str(e["away_squad_id"])
        for me, opp, side in ((h, a, "home"), (a, h, "away")):
            if me not in team_bracket and opp in team_bracket and by_key.get(team_bracket[opp]) is not None:
                name = ((e.get(f"{side}_organisation") or {}).get("name") or e.get(f"{side}_squad_name") or "?").strip()
                by_key[team_bracket[opp]]["teams"][me] = name
                team_bracket[me] = team_bracket[opp]
    games = []
    names = {sid: n for b in brackets for sid, n in b["teams"].items()}
    synced = sch.get("synced_at", "") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for comp, e in [("league", e) for e in sch["events"]] + [("flex", e) for e in flex]:
        h, a = str(e["home_squad_id"]), str(e["away_squad_id"])
        br = team_bracket.get(h) or team_bracket.get(a)
        if comp == "league" and (team_bracket.get(h) is None or team_bracket.get(a) is None):
            continue  # league: both teams in a bracket; a few cross age groups (San Diego FC U16 plays the U17 PPP
            # schedule) and count in each team's own table, like MLS's official standings
        if br is None:
            continue  # Flex: at least one of our teams
        t = datetime.fromisoformat(e["start_time"].replace("Z", "+00:00"))
        loc = ((e.get("event_location") or {}).get("name") or "").strip()
        if loc == "TBD":  # kickoff not set yet: keep only the local date
            venue, start = "", t.astimezone(ZoneInfo(e.get("local_timezone") or "America/New_York")).strftime("%Y-%m-%d")
        else:
            venue, start = loc, t.strftime("%Y-%m-%dT%H:%MZ")
        # a result dated after the feed's sync time can't have been played yet (a handful are marked completed with a
        # score but a future date); MLS's official standings leave those out, so do we
        done = e.get("completed") and e["start_time"] <= synced
        hp, ap = e.get("home_penalty_shootout_score"), e.get("away_penalty_shootout_score")
        pens = f"{hp}-{ap}" if done and comp == "flex" and e.get("home_score") == e.get("away_score") and (hp or ap) else ""
        org = lambda side: ((e.get(f"{side}_organisation") or {}).get("name") or e.get(f"{side}_squad_name") or "?").strip()
        games.append({"age": br[0], "conference": br[1], "comp": comp, "match_id": e["game_key"], "start": start,
                      "home_id": h, "away_id": a, "home_team": names.get(h) or org("home"), "away_team": names.get(a) or org("away"),
                      "home_score": e["home_score"] if done else "", "away_score": e["away_score"] if done else "",
                      "venue": venue, "pens": pens})
    brackets.sort(key=bracket_order)
    games.sort(key=lambda g: (age_num(g["age"]), g["conference"], g["comp"] != "league", g["start"], str(g["match_id"])))
    return brackets, games, sch.get("synced_at", ""), groups

def save(brackets, games, meta, groups=None):
    os.makedirs(f"{ROOT}/data", exist_ok=True)
    with open(f"{ROOT}/data/games.csv", "w", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        w.writerows(games)
    json.dump(brackets, open(f"{ROOT}/data/brackets.json", "w"), indent=1, ensure_ascii=False)
    json.dump(meta, open(f"{ROOT}/data/meta.json", "w"), indent=1)
    if groups is not None:
        json.dump(groups, open(f"{ROOT}/data/flex_groups.json", "w"), ensure_ascii=False)

def load():
    brackets = json.load(open(f"{ROOT}/data/brackets.json"))
    meta = json.load(open(f"{ROOT}/data/meta.json"))
    with open(f"{ROOT}/data/games.csv") as f:
        games = list(csv.DictReader(f))
    gpath = f"{ROOT}/data/flex_groups.json"
    groups = json.load(open(gpath)) if os.path.exists(gpath) else []
    return brackets, games, meta, groups

def slug_conf(c):  # same as the page's slugC: "West (Pro Player Pathway)" -> "west-pro-player-pathway"
    return re.sub(r"\s+", "-", re.sub(r"[()]", "", c.lower()).strip())

def slug_team(n):  # same as the page's slugT
    return re.sub(r"[^a-z0-9]+", "-", n.lower().replace("&", " and ")).strip("-")

def write_calendars(brackets, games):
    """cal/<squad id>.ics for every team: its league and Flex games, results in the title once played. Calendar apps
    subscribe to these (webcal://), so changed kickoff times and new results reach phones without re-downloading.
    Nothing time-dependent goes in (fixed DTSTAMP), so a file only changes when its games do. Only changed files are
    rewritten and only stray ones removed: deleting and recreating all 840 in a synced folder (iCloud Drive) makes the
    sync service leave "10461 2.ics"-style duplicates."""
    out = f"{ROOT}/cal"
    os.makedirs(out, exist_ok=True)
    wanted = set()
    where = {sid: b for b in brackets for sid in b["teams"]}
    tx = lambda t: re.sub(r"([\\,;])", r"\\\1", str(t)).replace("\n", "\\n")
    def fold(line):  # RFC 5545: lines of at most 75 octets, continuation lines start with a space
        b, parts = line.encode(), []
        while len(b) > (75 if not parts else 74):
            cut = 75 if not parts else 74
            while (b[cut] & 0xC0) == 0x80:  # don't split a UTF-8 character
                cut -= 1
            parts.append(b[:cut]); b = b[cut:]
        parts.append(b)
        return "\r\n ".join(x.decode() for x in parts)
    mine = {}
    for g in games:
        for side in ("home", "away"):
            if g[f"{side}_id"] in where:
                mine.setdefault(g[f"{side}_id"], {})[str(g["match_id"]) + g.get("comp", "league")] = g
    for sid, b in where.items():
        name, age = b["teams"][sid], b["age"]
        page = f"{SITE}?age={age}&conf={slug_conf(b['conf'])}&show={slug_team(name)}"
        ev = []
        for g in sorted(mine.get(sid, {}).values(), key=lambda g: g["start"]):
            home = g["home_id"] == sid
            opp_id = g["away_id"] if home else g["home_id"]
            ob = where.get(opp_id)
            opp = (ob["teams"][opp_id] + (f" {ob['age']}" if ob["age"] != age else "")) if ob else (g["away_team"] if home else g["home_team"])
            flex = g.get("comp") == "flex"
            res = ""
            if str(g["home_score"]) != "":
                f, a = (int(g["home_score"]), int(g["away_score"])) if home else (int(g["away_score"]), int(g["home_score"]))
                res = f" ({'W' if f > a else 'L' if f < a else 'D'} {f}–{a}"
                if g.get("pens"):
                    hp, ap = g["pens"].split("-"); pf, pa = (hp, ap) if home else (ap, hp)
                    res += f", {'won' if int(pf) > int(pa) else 'lost'} {pf}–{pa} on pens"
                res += ")"
            start = g["start"]
            when = ([f"DTSTART;VALUE=DATE:{start.replace('-', '')}"] if len(start) == 10 else
                    [f"DTSTART:{start.replace('-', '').replace(':', '').replace('Z', '00Z')}", "DURATION:PT2H"])
            title = f"{age} {name} {'vs' if home else 'at'} {opp}" + (" (Flex)" if flex else "") + res
            desc = f"MLS NEXT {'Flex' if flex else 'Homegrown'} · {age} {b['conf']}" + (" · kickoff time not set yet" if len(start) == 10 else "")
            ev += ["BEGIN:VEVENT", f"UID:mlsnext-{g['match_id']}{'-flex' if flex else ''}-{sid}@stw1.github.io", "DTSTAMP:20260801T000000Z", *when,
                   f"SUMMARY:{tx(title)}",
                   *([f"LOCATION:{tx(g['venue'])}"] if g.get("venue") else []),
                   f"DESCRIPTION:{tx(desc)}\\n{tx(page)}", f"URL:{page}", "END:VEVENT"]
        cal = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//mlsnext-dashboard//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
               f"X-WR-CALNAME:{tx(f'{name} {age} · MLS NEXT')}", "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
               "X-PUBLISHED-TTL:PT6H", *ev, "END:VCALENDAR"]
        text, path = "\r\n".join(fold(l) for l in cal) + "\r\n", f"{out}/{sid}.ics"
        wanted.add(f"{sid}.ics")
        try:
            same = open(path, newline="").read() == text
        except OSError:
            same = False
        if not same:
            with open(path, "w", newline="") as fh:
                fh.write(text)
    for f in os.listdir(out):  # teams that left, and sync-service duplicates
        if f not in wanted:
            os.remove(f"{out}/{f}")

def analytics_tag():
    """analytics/fa.js inlined (the page stays one file), configured from analytics/config.json."""
    try:
        cfg = json.load(open(f"{ROOT}/analytics/config.json"))
        js = open(f"{ROOT}/analytics/fa.js").read().replace("</", "<\\/")  # a "</script>" in it would end the tag
    except OSError:
        return ""
    # no API key: Firestore's REST API doesn't need one for these writes (the security rules decide), so none is
    # published in the pages or committed to the repo
    conf = {"site": ANALYTICS_SITE, "projectId": cfg.get("projectId", ""), "sections": '.card[id^="s-"]'}
    return f"<script>window.FA_CONFIG={json.dumps(conf)};</script>\n<script>\n{js}</script>"

def build(brackets, games, meta, default, groups=()):
    tpl = open(f"{ROOT}/template/dashboard_template.html").read()
    # league and Flex games: id,start,home,away,hs,as,venue# . A game is listed in the bracket of each of our teams
    # in it; opponents outside the bracket are named via DATA.xnames (teams of other brackets come from DATA itself).
    venues, vix, league, flex = [], {}, {}, {}
    where = {sid: (b["age"], b["conf"]) for b in brackets for sid in b["teams"]}
    known = {sid for b in brackets for sid in b["teams"]}
    xnames = {}
    for g in games:
        v = g.get("venue") or ""
        if v and v not in vix:
            vix[v] = len(venues); venues.append(v)
        row = ",".join([str(g["match_id"]), g["start"], g["home_id"], g["away_id"], str(g["home_score"]), str(g["away_score"]), str(vix[v]) if v else ""]
                       + ([g["pens"]] if g.get("pens") else []))
        if g.get("comp", "league") != "flex":  # league: in each team's bracket (two only for cross-age games)
            for k in {where.get(g["home_id"]), where.get(g["away_id"])} - {None} or {(g["age"], g["conference"])}:
                league.setdefault(k, []).append(row)
            continue
        for k in {where.get(g["home_id"]), where.get(g["away_id"])} - {None}:
            flex.setdefault(k, []).append(row)
        for side in ("home", "away"):
            if g[f"{side}_id"] not in known:
                xnames[g[f"{side}_id"]] = g[f"{side}_team"]
    dage, dconf = default.split(":", 1)
    # Flex groups: [age, name, [[squad, pos, mp, w, sho, l, pts, ppm, gdpm], ...]]; outsiders' names go to xnames
    for gr in groups:
        for r in gr["rows"]:
            if r[0] not in known:
                xnames.setdefault(r[0], r[1])
    data = {"default": {"age": dage, "conf": dconf}, "snap": meta["snapshot"], "venues": venues, "xnames": xnames,
            "feedback": FEEDBACK,
            "opos": {sid: p for b in brackets for sid, p in b.get("pos", {}).items()},
            "fgroups": [[gr["age"], gr["name"], [[r[0]] + r[2:] for r in gr["rows"]]] for gr in groups],
            "brackets": [{"age": b["age"], "conf": b["conf"], "teams": b["teams"],
                          "raw": ";".join(league.get((b["age"], b["conf"]), [])),
                          "flex": ";".join(flex.get((b["age"], b["conf"]), []))} for b in brackets]}
    m = re.search(r"(\d\d)-(\d\d)$", meta.get("season_key", ""))
    current = f"20{m[1]}–{m[2]}" if m else "This season"
    # past seasons (scripts/history.py) get their own pages; the season picker links them all
    past = pastseasons.seasons()
    data["seasons"] = [{"key": current, "file": "index.html"}] + [{"key": pastseasons.label(s), "file": f"season-{s}.html"} for s in past]
    data["hist"], data["hsame"] = pastseasons.team_history(brackets) if past else ({}, {})
    if past and PRIOR_WEIGHT:
        pri = pastseasons.priors(brackets, past[0], PRIOR_WEIGHT, PRIOR_MODE)
        for b in data["brackets"]:
            b["prior"] = {k: pri[k] for k in b["teams"] if k in pri}
    tpl = tpl.replace("<!--__ANALYTICS__-->", analytics_tag())
    def page(d, season_text):
        return (tpl.replace("/*__DATA__*/{}", json.dumps(d, ensure_ascii=False, separators=(",", ":")))
                   .replace("__TITLE__", "MLS NEXT Homegrown Division dashboard").replace("__SEASON__", season_text))
    html = page(data, f"{current} season")
    open(f"{ROOT}/index.html", "w").write(html)
    write_calendars(brackets, games)
    for s in past:
        d = pastseasons.past_data(s, default); d["seasons"] = data["seasons"]; d["feedback"] = FEEDBACK
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
        brackets, games, meta, groups = load()
    else:
        brackets, games, synced, groups = fetch(a.season, a.age, a.conference)
        if not brackets:
            raise SystemExit(f"No brackets match --age {a.age} --conference {a.conference}")
        meta = {"snapshot": datetime.now(ZoneInfo(a.tz)).date().isoformat(), "synced_at": synced, "season_key": a.season}
        save(brackets, games, meta, groups)
    build(brackets, games, meta, a.default, groups)
