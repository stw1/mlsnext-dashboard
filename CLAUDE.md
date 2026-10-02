# MLS NEXT Standings & Prediction Dashboard

Personal project (Stephen). Builds a self-contained HTML dashboard for the MLS NEXT
**Homegrown Division**: every age group (U13–U19) and conference in one page, showing one bracket at a time. It shows standings, a head-to-head
("who beat who") grid, power ratings, results, and predicted scores for every remaining
game, plus a 10,000-run season simulation. First-time visitors land on **U14 Northwest** (2026-27 season).

## Layout
```
CLAUDE.md                          this file
scripts/refresh.py                 fetch live data -> data/ -> index.html (stdlib only)
template/dashboard_template.html   the dashboard; all model + rendering logic is inline JS
data/games.csv                     one row per game, all brackets: comp = league | flex, venue (blank scores = not played)
data/brackets.json                 [{age, conf, teams: {squad_id: name}}], sorted by age then conference
data/meta.json                     snapshot date, synced_at, season key
index.html                         built output with every bracket embedded (served by GitHub Pages)
.github/workflows/refresh.yml      weekend auto-refresh
scripts/history.py                 one-off download of past seasons from Modular11 -> data/history/<season>.csv
scripts/pastseasons.py             past-season page data, team history, last-season priors (used by refresh.py)
scripts/ratings.py, priors.py      Python copy of the model; backtests that choose prior / conference settings
data/history/<season>.csv          past seasons' games (2023-24, 2024-25, 2025-26): league, Flex, others
season-<season>.html               built pages for finished seasons (same template, DATA.past set)
scripts/check_official.py          compares the built tables with MLS's official standings (exit 1 on differences)
cal/<squad_id>.ics                 one subscribable calendar per team, rebuilt by refresh.py (current season only)
docs/rules-2026-27.md              HD rules summary (standings, tiebreakers, postseason) and how the site follows them
README.md                          short public description of the repo
analytics/                         reusable first-party analytics kit (fa.js, firestore.rules, report.html, README)
manifest.webmanifest, icon.svg     home-screen app name and icons (icon-192/512.png, apple-touch-icon.png,
  *.png                            favicon-32.png); regenerate PNGs from icon.svg with qlmanage + sips
```

## Common tasks
- **Update with new scores:** `python3 scripts/refresh.py` (every bracket; `--default U14:Northwest` sets the landing bracket)
- **Only some brackets:** `python3 scripts/refresh.py --age U13,U14 --conference Northwest` (still writes index.html)
- **Rebuild without network** (for example, after editing the template): `python3 scripts/refresh.py --offline`
- Open `index.html` in a browser to check the result (add `?age=U15&conf=southwest` for another bracket).
- **Check against MLS:** `python3 scripts/check_official.py` compares every U15–U19 team's MP, W-D-L and goals, and every
  conference's order, with MLS's official standings (U13/U14 have no official values). Teams level on every computable
  tiebreaker may swap. A team whose official record equals ours minus its games of the last 48 hours is reported as
  "not updated yet" (MLS allows 24 h for match reports + 48 h to verify), not as an error. Run it after any table change.
- **Auto-refresh:** `.github/workflows/refresh.yml` runs `refresh.py` on GitHub Actions Sat & Sun (~1, 5, 9 pm
  Pacific) and Mon & Tue (~9 am), and commits + pushes only when `data/games.csv` changed (calendar files change only
  when games do, so they ride along). Its last step runs `check_official.py` *after* publishing: new scores still go
  live, but a mismatch fails the run, so GitHub emails the repo owner; the result is in the run's summary. Actions are
  pinned to `actions/checkout@v7` / `actions/setup-python@v7` (Node 24). Run it on demand from
  the repo's Actions tab ("Refresh scores" → "Run workflow") or `gh workflow run refresh.yml`.
  GitHub pauses scheduled workflows in public repos after 60 days with no commits; re-enable on the Actions tab.
- **Publish by hand:** `git pull` first (the bot commits too), then `git add -A && git commit -m "..." && git push`. GitHub Pages serves
  https://stw1.github.io/mlsnext-dashboard/ from the `main` branch root (repo `stw1/mlsnext-dashboard`).
  Link to a bracket with `?age=U15&conf=southwest` (conf is the name lowercased, spaces → dashes, parentheses dropped,
  e.g. `west-pro-player-pathway`). `?age=U13` alone uses the last or default conference. Add `&team=ballistic-united`
  to highlight a team.

## Data source
The page at mlssoccer.com/mlsnext/standings/homegrown_division/ embeds an iframe from
`mls-assist.theintelligenceplatform.com`. That iframe reads two public JSON files:
- `https://mls-assist.theintelligenceplatform.com/data/standings/mls-next-league-26-27.json`
  - `competition_season.competition_brackets[]`: one entry per age group + conference.
    Each has `age_group.name` (e.g. "U14"), `name` (e.g. "Northwest") and `standings[].team.{squad_id,name,logo_url}`.
  - 60 brackets: U13–U15 have 8 conferences; U16, U17 and U19 have 12, including four small "(Pro Player Pathway)"
    ones. There is no U18. U13 Northwest is id 101 (13 teams), U14 Northwest id 102 (14 teams).
  - Schedules differ: many conferences play each pair once, some twice, some a mix, and some pairs never meet.
  - Early in the season the `tiebreaker_values` are empty and the order is alphabetical,
    which is why the MLS site shows ALBION SC Merced as "#1". This project builds its own table instead.
- `https://mls-assist.theintelligenceplatform.com/data/schedule/mls-next-league-26-27.json`
  - `events[]` covers every age group (~7,700 events), with fields `game_key`, `start_time` (UTC),
    `home_squad_id`, `away_squad_id`, `home_organisation.name`, `completed`, `home_score`, `away_score`,
    `competition.name` ("League"), `event_location.name` ("TBD" means the time isn't set yet).
  - League games are kept when both teams have a bracket (see "Feed quirks" below for cross-age games).
- Flex in the page: every Flex game with at least one of our teams is kept (`DATA.brackets[].flex`, same 7-field format as
  league; a game appears in each of its teams' brackets; opponents with no bracket are named via `DATA.xnames`).
  Shown with a "Flex" tag in Results, Upcoming, the My team card (separate Flex W-D-L), the club page and the calendar.
  Standings, Who beat who, the season sim and the accuracy check stay League-only (like MLS NEXT's table). Only played
  same-bracket Flex games feed the ratings (`ratable`); Flex games vs another bracket get no prediction.
- Flex group tables: `standings/mls-next-flex-26-27.json` (52 groups, U15-U19; groups mix regular clubs with Pro Player
  Pathway academies). refresh.py stores MLS's own values in `data/flex_groups.json` (position, MP, W, shootouts, L,
  points, points/match, GD/match) and the page shows them as-is (`DATA.fgroups`): conference page "Flex groups" card,
  team page "Flex group" card, club cards. Drawn Flex games go to penalty shootouts (`pens` column, "4-2"), shown as
  "(4–2 pens)"; the official Flex table gives 3 win / 2 shootout win / 1 shootout loss (fits 177 of 190 teams with shootouts).
- "League games vs MLS NEXT Flex games" explainer card (`#s-flexhelp`) on every page, linked as "what's Flex?".
- MLS NEXT Flex: `schedule/mls-next-flex-26-27.json`. U15–U19 only, the **same squad ids** as the league, in Flex groups
  that are mostly subdivisions of a league conference; ~800 games pit Pro Player Pathway academies against regular-conference clubs.
- No earlier seasons exist on this host (25-26 and other keys return a 631-byte HTML page), so there is no
  last-season prior. League and Flex games never cross conferences, so conference strengths can't be compared.
  For the **Academy Division**, open its standings page and read the iframe `data-src`
  to get its season key, then pass `--season <key>`.
- Next season the key will probably be `mls-next-league-27-28`.

## Past seasons (Modular11)
- MLS NEXT's results platform before 2026-27. Public endpoint used by modular11.com/schedule:
  `https://www.modular11.com/public_schedule/league/get_matches?tournament=12&age=<id>&status=all&match_type=2&open_page=<n>&start_date=...&end_date=...`
  (HTML rows, 25 per page, "page out of N"). Age ids: U13=21, U14=22, U15=33, U16=14, U17=15, U19=26 (from
  `get-filter-options`). Each row has match id, date/time, venue, age, bracket (League, League (Pro Player Pathway),
  MLS NEXT Flex (Regular Season), Flex League, Others), division, teams, club ids (logo URL `/academy/<id>/`), score.
- `python3 scripts/history.py [--season 2025-26] [--force]`: rate-limited (1 req/s), ~20 min per season. Past seasons
  don't change, so this is not part of the weekly refresh. refresh.py rebuilds the season pages from the CSVs.
- Team matching across seasons is by normalised name (`ratings.norm`, with `ALIASES` for renamed clubs). Players move up
  an age group each year: this season's U14 = last season's U13 (`PREV_AGE`). U13 teams have no earlier history.
- In 2025-26 several MLS academies played only Flex ("MLS Academy" group), so they have no league table that season.
- Cross-conference games exist only for U16/U17/U19 (Flex + Pro Player Pathway, ~800 in 2025-26). Test
  (`priors.py --evaluate-conf`: 2024-25 conference effects from `ratings.fit_conf` predicting 2025-26 cross-conference
  games): U16 log-loss 0.87 -> 0.93 at w=0.5 (worse), U19 0.95 -> 0.88 (better), U17 untestable. Not used.

## Last-season priors
- `refresh.PRIOR_WEIGHT, PRIOR_MODE = 0.75, "avg"`: each squad's att/def prior mean = 0.75 × the average of its
  cohort rating (same club, one age group younger, last season) and its same-age rating last season (whichever exist),
  from `priors.season_ratings` (league + Flex, per conference). Embedded per bracket as `prior: {squad: [att, def]}`;
  the page centres them and passes them to `fit()` (ridge prior N(prior, SIG²) instead of N(0, SIG²)).
- Chosen by `python3 scripts/priors.py --evaluate` (replays all of 2025-26 week by week with 2024-25 priors):
  log-loss 0.8025 (none) -> 0.7855 (avg ×0.75); first 6 weeks 0.8929 -> 0.8245; picks 64.1% -> 65.5%.
  On 2026-27's first 869 games: log-loss 0.935 -> 0.861, picks 54.5% -> 60.2%. Past-season pages use the season before.

## Model (in template JS, search for "fit penalised Poisson model")
- Goals follow a Poisson distribution: `log λ_home = μ + home + att[home] − def[away]`, `log λ_away = μ + att[away] − def[home]`.
- Fit by gradient ascent on the log-likelihood, with ridge priors: att/def σ = 0.35, home σ = 0.15.
  The priors are deliberately strong because each team has played very few games. You can loosen
  SIG as the season goes on (for example, 0.5 once teams have played 10+ games).
- Dixon-Coles low-score correction: scoreline probability = Poisson × Poisson × τ(x, y), where τ only changes 0–0, 1–0,
  0–1 and 1–1 (helpers `tau` and `pxy`). `rho` is fit in `fit()` by grid search over [−0.30, 0.10] on the low-score
  likelihood given the fitted ratings, with a prior N(−0.1, 0.1). Negative rho means more 0–0 and 1–1. The season sim
  samples whole scorelines from the same adjusted table (not independent Poisson draws).
- Each prediction is a 0–10 × 0–10 scoreline matrix, which gives win/draw/loss chances.
  The pick is the favourite (or "Too close to call" when |P(home win) − P(away win)| < 5%).
  The margin is round(|expected goal difference|), with a minimum of 1. Confidence labels:
  Strong ≥ 60%, Lean ≥ 45%, otherwise Toss-up.
- Ratings use league + Flex games (`USE_FLEX`). Backtest across U15–U19 (256 league games, Oct 1): picks right
  38% → 56%, log-loss 0.98 → 0.91 with Flex.
- Season sim: 10k Monte Carlo runs with a seeded random number generator (so results are
  reproducible). Ranks by points per match (final games played), then GD and GF per match. Outputs: projected
  points, chance of finishing in the top `CH` / top `CUP`, chance of finishing 1st.
- Cup lines (`CUP_EST`): MLS NEXT hasn't published 2026-27 spots. U13/U14 use last season's per-conference
  Championship/Premier seeds as reported by UpNext Analytics (MLS's own wording: "Quality of Play rankings"),
  shown as "(est.)". U15–U19: 48 Cup spots, split unannounced, so the generic, labelled "Top 4" stays.
  Update `CUP_EST` when MLS publishes the 2026-27 allocation (HD Rules & Regulations / MLS NEXT news).
- Accuracy check ("How accurate are the predictions?"): a walk-forward backtest. For each weekend it calls
  `fit()` on only the earlier games, predicts that weekend with `predict(h, a, model)`, and compares with the result.
  It needs no logging, but it scores the *current* model code, so changing the model changes past accuracy too.
- Rules: see `docs/rules-2026-27.md` (summary of the HD Rules & Regulations with section numbers, and how the
  site follows each rule). Standings sort (XIII.l): points per match; head-to-head for two-team ties only; then
  wins, GD, GF per match; away GD and GF per *away* match; home GD and GF per *home* match; level teams keep MLS's
  published position (`DATA.opos`, standing in for disciplinary points and the coin toss). Checked on 2026-10-02:
  all 568 U15–U19 records and all 44 conference orders match MLS's feed. Rerun that check after changing table logic.
- Feed quirks handled in `refresh.py`: "completed" games dated after `synced_at` count as not played; teams playing a
  league schedule but missing from the standings feed (Bay Area Surf U15, New England Revolution U14) join their
  opponents' bracket; cross-age league games (San Diego FC U16 vs the U17 PPP schedule) are listed in both brackets
  and counted in each team's own table, but kept out of ratings/Who beat who (`inB`); opponents get an age suffix (`xAge`).

## Conventions / gotchas
- The dashboard stays a **single HTML file** with no external scripts or data fetches (all data is embedded).
  Only the home-screen icons/manifest and the calendar files are separate; Directions links open Google Maps. Analytics
  (when configured) posts events to the owner's Firestore; the tracker itself is inlined.
- `start` in games.csv is UTC (`2026-10-03T16:00Z`); the page shows it in the viewer's time zone. Games without a set
  time (feed venue "TBD", stored at 06:00 local) keep only the local date (`2027-01-09`), from the event's `local_timezone`.
- Template placeholders filled by `refresh.py`: `__DATA__` (`{default:{age,conf}, snap, venues:[...], brackets:[{age, conf,
  teams, raw: "id,start,home,away,hs,as,venue#;…", flex: "start,home,away,hs,as;…" (played Flex games only)}]}`),
  `__TITLE__`, `__SEASON__` (from the season key, e.g. "2026–27 season").
- Bracket choice: `pickBracket()` runs once at load (`?age=&conf=` → last bracket viewed, saved in localStorage as
  `bracket` → `default`); everything after runs exactly as for a single bracket. Age tabs and the conference picker
  reload the page. "Find any team" searches all brackets.
- Team links: `&team=<slug>` (name lowercased, non-letters → dashes, e.g. `ballistic-united`; the short-name slug like
  `lafc` or a squad id also works,
  as does the older `&follow=<squad_id>`). A linked team becomes that browser's followed team for the bracket.
  `syncUrl()` keeps the address bar equal to bracket + followed team, so copying it (or "Share link", which uses
  the phone share sheet or the clipboard) shares exactly that view. Age tabs carry the same club to other ages.
- Team short names (used on phones and in column headers) come from the `SHORT` map in the template (~95 clubs,
  covering every name the regex fallback made too long or too terse). New clubs fall back to the regex.
- "Follow a team" is saved in the browser's localStorage, keyed by page title, so each bracket remembers its own team.
- National view: `?age=U13&conf=national` (first option in the conference picker). Fits each conference of the
  age group separately and lists all teams by rating (expected goal margin vs an average team in its own conference).
  The page says plainly that this treats conferences as equally strong. Pro Player Pathway gets its own table.
- Team page: `?age=&conf=&show=<team slug>` (`drawTeam`): overview KPIs (position, league, Flex, power, national,
  projection), Follow / calendar / share buttons, form (last 10, Flex outlined) and stats, full league + Flex schedule
  with results or odds (next game highlighted), results vs each conference opponent, same-players history and the
  club's other age groups. Every team name (standings, power, results, upcoming, national, club, My team card) links
  here via `tlink()`/`showUrl()`; `show=` never changes the followed team (`team=` still does).
- Insights: `?view=insights[&age=U15]` (`drawInsights`; conference picker option, "Insights →" in conference-page menus):
  biggest climbers / drops vs the same players last season (table position as a share of the table, teams with 3+
  league games), biggest upsets (walk-forward predictions per bracket, `btFor`), perfect/unbeaten starts, winning
  streaks, rising three seasons running, goals for/against per game, biggest wins, highest-scoring games, strongest
  clubs across age groups (all ages only). Renders all 60 brackets in ~0.2 s.
  Top section is one weekend at a time (`&wk=<Monday>`, default the latest; weekend chips): KPIs (games, goals/game vs
  the weekend before, home wins, draws, predictions right, upsets, biggest win, new leaders), table movers (each
  bracket's `table()` just before vs just after the weekend), new conference leaders, still-perfect / first defeats,
  streaks reached / ended, rating risers and fallers (fit before vs after the weekend, same prior), the weekend's upsets
  (`btFor`), next weekend's top-four meetings with odds (latest only), and a week-by-week trend table.
- Team page "Previous seasons" card (`pastCard`): this season vs last season headline, the same players' past
  seasons (`DATA.hist`) and the club's same-age team in past seasons (`DATA.hsame`), rows [season, age, conf, rank, of,
  w, d, l, gf, ga, name then ("" = same), flex w, d, l], each linking to that season's team page.
- Past seasons: `pastseasons.main_conf` puts each team in the conference where it played most league games (some
  seasons label part of a conference's games with a sub-division, e.g. 2024-25 U16 "Mid-America (East)"); a one-team
  leftover falls back to the base name. 2024-25 now has 54 tables.
- Club view: `?club=<slug>` (full or short name slug, e.g. `ballistic-united`, `lafc`). Lists the club's team in every
  age group with conference position, record, national rank, power rank, simulated top-line / 1st chances (2,000 runs per
  bracket), next game; plus club-wide upcoming games and recent results. Reached from "Find any team" (club rows first)
  and the My team card. `bracketInfo(b)` caches each bracket's model + table for the national and club views.
- Model fit: per-parameter Newton steps (60 rounds) instead of 6,000 gradient steps — same MAP objective, equal or better
  in all 60 brackets (gradient ascent stalled on lopsided U13 Southwest scores), ~27× faster. `fit(list, IX, NN, prior)`.
- "My team" card (top of the page when a team is followed): record, form, next game with odds and venue, outlook.
- Calendars: "Add to calendar" (team page and My team card) opens a panel (`wireCal`): subscribe via `webcal://…/cal/<squad
  id>.ics` (iPhone/Mac), Google Calendar (`calendar.google.com/calendar/render?cid=<webcal url>`), copy link, or download
  the remaining games once (`downloadIcs`, the old one-off file). `refresh.write_calendars` writes every team's file:
  league + Flex games, result in the title once played ("(W 2–1)", pens), opponent age suffix for cross-age games, timed
  games in UTC with 2 h duration, no time = all-day, fixed DTSTAMP so files only change when games do, lines folded at 75
  octets. Past-season pages keep the download only. Google refreshes subscriptions slowly (up to a day).
- Home: `‹ Home` button (club, national and team pages) and the eyebrow title link to the page with no options, which
  opens the last conference viewed.
- Set in `refresh.py`: `FEEDBACK = "support@spaikz.com"` (form URL or email → footer "Report a problem or suggest an
  idea"; an email becomes a mailto with the page URL).
- Analytics: `analytics/` is a reusable first-party kit (README there): `fa.js` tracker → the owner's Firebase
  Firestore via REST (`sites/<site>/events`), `firestore.rules` (create-only, owner-read), `report.html` (Google
  sign-in; `?demo=1`, `?emulator=1`), `config.json` (projectId/apiKey/authDomain + site list; empty projectId = off).
  `refresh.analytics_tag()` inlines fa.js into every page (`<!--__ANALYTICS__-->` in the head, `</` escaped) with
  `ANALYTICS_SITE = "mlsnext"`; the page calls `fa.view({view, season, age, conf, team, club, following, page})` after
  drawing. Clicks, select changes, errors, active time, scroll and sections seen (`.card[id^="s-"]`) are automatic.
  Footer shows "Anonymous usage stats, no cookies (opt out)" when on. Tested with the Firestore + Auth emulators.
  Live project: Firebase `spaikz-dashboards` (owned by Stephen's spaikz.com Google account; Firestore nam5; web app
  "Dashboards"). Rules deploy with `analytics/deploy_rules.sh <owner email>` so the email isn't committed. Report:
  https://spaikz-dashboards.web.app (`analytics/deploy_report.sh`; the GitHub Pages copy just links there). **No API
  key in the repo or the site**: the tracker writes to Firestore without one (rules decide). The report's key ("Analytics
  report (restricted)": web.app/firebaseapp.com referrers; identitytoolkit, securetoken, firestore) lives only in Google
  Cloud and the deployed report. Two earlier keys were committed by mistake on 2026-10-02 and deleted (GitHub
  secret-scanning alerts closed as revoked). Firebase CLI and gcloud on this Mac are signed in.
- "New since your last visit": localStorage `seen:<title>` keeps the played-game ids at the end of the previous
  visit (a visit ends after 6 quiet hours). New results get a "New" pill (results, tooltips, card) and a ring in Who beat who.
- Phones (≤700px): the header packs pickers into a grid; `.xs-hide` columns drop out (W/D/L/Goals in standings,
  Scores/Concedes in power, Conference/W-D-L/GD in national) so the ranking numbers fit without scrolling.
- Dark mode follows the device (`prefers-color-scheme`), one override block at the end of the CSS.
- `window.__debug` in the page exposes the model internals for testing in node or the browser console.
- Snapshot 2026-10-02: 867 league + 672 Flex games played, 840 teams (incl. the two added from the schedule); index.html
  is ~694 KB; cal/ is ~11 MB (840 files).

## Ideas / backlog
- Use cross-conference events (MLS NEXT Fest, Cup qualifiers) to estimate conference strength for the national view
- Save each weekend's predictions before kickoff for an honest, frozen track record
- Safety check in the workflow: refuse to publish if the feed returns far fewer games than last time
- Update `CUP_EST` / the Top-4 line once MLS publishes the 2026-27 Cup allocation; re-run `check_official.py` after the
  first winter Showcase weekend (cross-conference league games)
- Weight recent games more heavily
- Predict draws: the pick is never "draw" unless home/away are within 5%, so draws always count as misses in the accuracy check
