#!/usr/bin/env python3
"""
Download past MLS NEXT seasons (results only) from Modular11, the platform MLS NEXT used before 2026-27.
Past seasons don't change, so this runs once per season, not in the weekly refresh.

  python3 scripts/history.py                    # 2023-24, 2024-25, 2025-26
  python3 scripts/history.py --season 2025-26   # one season

Writes data/history/<season>.csv. Polite: one request per second, retries, resumable (skips finished seasons
unless --force). Python 3.9+ standard library only.
"""
import argparse, csv, html, json, os, re, sys, time, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = f"{ROOT}/data/history"
BASE = "https://www.modular11.com/public_schedule/league"
UA = {"User-Agent": "Mozilla/5.0 (personal MLS NEXT fan dashboard; github.com/stw1/mlsnext-dashboard)",
      "X-Requested-With": "XMLHttpRequest"}
TOURNAMENT = 12  # MLS NEXT on Modular11 (league, Flex and other events)
SEASONS = {"2023-24": ("2023-08-01", "2024-07-31"), "2024-25": ("2024-08-01", "2025-07-31"),
           "2025-26": ("2025-08-01", "2026-07-31")}
FIELDS = ["season", "age", "bracket", "competition", "division", "group_home", "group_away", "round", "match_id",
          "date", "time", "venue", "home", "away", "home_club", "away_club", "home_score", "away_score"]
DELAY = 1.0

def get(url, tries=4):
    for k in range(tries):
        try:
            time.sleep(DELAY)
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as err:
            if k == tries - 1:
                raise
            print(f"  retry ({err})", flush=True)
            time.sleep(5 * (k + 1))

def ages_for(start, end):
    q = urllib.parse.urlencode({"UID_league": TOURNAMENT, "match_type": 2, "start_date": f"{start} 00:00:00",
                                "end_date": f"{end} 23:59:59", "with_steps": 1, "with_fields": 0, "with_locations": 0})
    steps = json.loads(get(f"{BASE}/get-filter-options?{q}"))["steps"]
    return [(a["value"], a["name"]) for a in steps["ages"]]

def page_url(age_id, start, end, page):
    q = {"open_page": page, "academy": 0, "tournament": TOURNAMENT, "gender": 0, "age": age_id, "brackets": "",
         "groups": "", "group": "", "match_number": 0, "status": "all", "match_type": 2, "schedule": 0, "team": 0,
         "location": 0, "as_referee": 0, "report_status": 0, "match_status": 0,
         "start_date": f"{start} 00:00:00", "end_date": f"{end} 23:59:59"}
    return f"{BASE}/get_matches?{urllib.parse.urlencode(q)}"

txt = lambda s: re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()

def parse(page, season):
    rows = []
    for blk in re.findall(r'<div class="row table-content-row hidden-xs"(.*?)<!-- desktop version -->', page, re.S):
        attr = dict(re.findall(r'js-match-([a-z_]+)="([^"]*)"', blk))
        head = txt(blk.split('<div class="col-sm-2">', 1)[0].split(">", 1)[1])            # "100568 MALE"
        when = re.search(r'<div class="col-sm-2">\s*(\d\d/\d\d/\d\d)\s+(\d{1,2}:\d\d\s*[ap]m)?', blk)
        venue = re.search(r'container-location">\s*<p data-title="([^"]*)"', blk)
        age = re.search(r"<!--Age-->\s*<div[^>]*>\s*([^<]+?)\s*</div>", blk)
        comp = re.search(r"<!--Competition-->(.*?)<!--Competition-->", blk, re.S)
        div = re.search(r"<!--Division-->(.*?)<!--Division-->", blk, re.S)
        home = re.search(r'container-first-team">\s*<p data-title="([^"]*)"', blk)
        away = re.search(r'container-second-team">\s*<p data-title="([^"]*)"', blk)
        clubs = re.findall(r"/academy/(\d+)/", blk)
        score = re.search(r'class="score-match-table[^"]*">\s*(\d+)\s*(?:&nbsp;?)?:\s*(?:&nbsp;?)?(\d+)', blk)
        if not (when and home and away):
            continue
        mm, dd, yy = when.group(1).split("/")
        tm = ""
        if when.group(2):
            t = when.group(2).replace(" ", "")
            h, mi = int(t[:-2].split(":")[0]), t[:-2].split(":")[1]
            h = h % 12 + (12 if t.endswith("pm") else 0)
            tm = f"{h:02d}:{mi}"
        rows.append({"season": season, "age": txt(age.group(1)) if age else "", "bracket": attr.get("bracket", ""),
                     "competition": txt(comp.group(1)) if comp else "", "division": txt(div.group(1)) if div else "",
                     "group_home": attr.get("group_home", ""), "group_away": attr.get("group_away", ""),
                     "round": attr.get("round", ""), "match_id": head.split(" ")[0],
                     "date": f"20{yy}-{mm}-{dd}", "time": tm, "venue": html.unescape(venue.group(1)) if venue else "",
                     "home": html.unescape(home.group(1)), "away": html.unescape(away.group(1)),
                     "home_club": clubs[0] if len(clubs) > 0 else "", "away_club": clubs[1] if len(clubs) > 1 else "",
                     "home_score": score.group(1) if score else "", "away_score": score.group(2) if score else ""})
    pages = re.search(r"page out of\s*(\d+)", page)
    return rows, int(pages.group(1)) if pages else 1

def season(name, force=False):
    path = f"{OUT}/{name}.csv"
    if os.path.exists(path) and not force:
        print(f"{name}: already downloaded ({path}); use --force to redo")
        return
    start, end = SEASONS[name]
    allrows, seen = [], set()
    for age_id, age in ages_for(start, end):
        page, pages = 0, 1
        while page < pages:
            rows, pages = parse(get(page_url(age_id, start, end, page)), name)
            for r in rows:
                if r["match_id"] not in seen:
                    seen.add(r["match_id"]); allrows.append(r)
            print(f"{name} {age}: page {page + 1}/{pages}, {len(allrows)} matches so far", flush=True)
            page += 1
    allrows.sort(key=lambda r: (r["age"], r["date"], r["time"], r["match_id"]))
    os.makedirs(OUT, exist_ok=True)
    with open(path + ".tmp", "w", newline="") as f:
        w = csv.DictWriter(f, FIELDS); w.writeheader(); w.writerows(allrows)
    os.replace(path + ".tmp", path)
    print(f"{name}: saved {len(allrows)} matches to {path}", flush=True)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", choices=sorted(SEASONS), action="append", help="default: all")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    for s in a.season or sorted(SEASONS):
        season(s, a.force)
