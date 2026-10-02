# MLS NEXT Homegrown Division dashboard

An unofficial fan dashboard for the MLS NEXT Allstate Homegrown Division. It's not affiliated with MLS NEXT.

**https://stw1.github.io/mlsnext-dashboard/**

- Standings for every age group (U13–U19) and conference, ordered by the official rules, plus national rankings
- Who beat who, power rankings, results and predicted scores for every remaining game
- League and MLS NEXT Flex games, including the official Flex group tables
- Team pages (with how the same players and the club's team did in earlier seasons), club pages and past seasons
  back to 2023–24
- An Insights page: biggest climbers and drops since last season, upsets, unbeaten starts, streaks and more
- Calendars you can subscribe to for any team; they update by themselves when kickoff times change

## How it works

- `scripts/refresh.py` downloads the public standings and schedule data behind mlssoccer.com/mlsnext and builds
  `index.html` (one self-contained page), the past-season pages and the team calendars in `cal/`.
  It uses only the Python standard library.
- A GitHub Actions workflow (`.github/workflows/refresh.yml`) runs it on Saturdays and Sundays, and on Monday and
  Tuesday mornings for late scores. It publishes when anything changed, then runs `scripts/check_official.py` to
  confirm every U15–U19 table still matches MLS's official standings.
- Predictions come from a Poisson goals model with a Dixon-Coles low-score adjustment, fitted to each conference's
  games and started from last season's ratings. The page shows how accurate the predictions have been.
- The rules the tables follow are summarised in [docs/rules-2026-27.md](docs/rules-2026-27.md).
- Usage analytics are first-party: [analytics/](analytics/README.md) is a small reusable kit that sends anonymous,
  cookie-free events to the owner's Firebase project, with a report page only the owner can open.

## Run it yourself

```bash
python3 scripts/refresh.py            # fetch the latest data and rebuild
python3 scripts/refresh.py --offline  # rebuild from data/ without downloading
python3 scripts/check_official.py     # compare the tables with MLS's official standings
```
