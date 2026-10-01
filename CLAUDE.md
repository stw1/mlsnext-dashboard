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
data/games.csv                     one row per league game, all brackets (blank scores = not played yet)
data/brackets.json                 [{age, conf, teams: {squad_id: name}}], sorted by age then conference
data/meta.json                     snapshot date, synced_at, season key
index.html                         built output with every bracket embedded (served by GitHub Pages)
.github/workflows/refresh.yml      weekend auto-refresh
```

## Common tasks
- **Update with new scores:** `python3 scripts/refresh.py` (every bracket; `--default U14:Northwest` sets the landing bracket)
- **Only some brackets:** `python3 scripts/refresh.py --age U13,U14 --conference Northwest` (still writes index.html)
- **Rebuild without network** (for example, after editing the template): `python3 scripts/refresh.py --offline`
- Open `index.html` in a browser to check the result (add `?age=U15&conf=southwest` for another bracket).
- **Auto-refresh:** `.github/workflows/refresh.yml` runs `refresh.py` on GitHub Actions Sat & Sun (~1, 5, 9 pm
  Pacific) and Mon & Tue (~9 am), and commits + pushes only when `data/games.csv` changed. Run it on demand from
  the repo's Actions tab ("Refresh scores" → "Run workflow") or `gh workflow run refresh.yml`.
  GitHub pauses scheduled workflows in public repos after 60 days with no commits; re-enable on the Actions tab.
- **Publish by hand:** `git pull` first (the bot commits too), then `git add -A && git commit -m "..." && git push`. GitHub Pages serves
  https://stw1.github.io/mlsnext-dashboard/ from the `main` branch root (repo `stw1/mlsnext-dashboard`).
  Link to a bracket with `?age=U15&conf=southwest` (conf is the name lowercased, spaces → dashes, parentheses dropped,
  e.g. `west-pro-player-pathway`). `?age=U13` alone uses the last or default conference.

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
  - Filter to games where both squad_ids are in the bracket.
- MLS NEXT Flex uses a separate key, `mls-next-flex-26-27`, which is not included yet.
  For the **Academy Division**, open its standings page and read the iframe `data-src`
  to get its season key, then pass `--season <key>`.
- Next season the key will probably be `mls-next-league-27-28`.

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
- Season sim: 10k Monte Carlo runs with a seeded random number generator (so results are
  reproducible). Ranking uses points, then goal difference, then goals for. Outputs: projected
  points, chance of a top-4 finish, chance of finishing 1st.
- Accuracy check ("How accurate are the predictions?"): a walk-forward backtest. For each weekend it calls
  `fit()` on only the earlier games, predicts that weekend with `predict(h, a, model)`, and compares with the result.
  It needs no logging, but it scores the *current* model code, so changing the model changes past accuracy too.
- Standings sort: points, then points per match, then goal difference per match, then goals for
  (this matches the feed's tiebreaker list).

## Conventions / gotchas
- The dashboard must stay a **single self-contained HTML file**, with no external scripts or
  fetches. It is also published as a Claude Cowork artifact, which blocks network access.
- `start` in games.csv is UTC (`2026-10-03T16:00Z`); the page shows it in the viewer's time zone. Games without a set
  time (feed venue "TBD", stored at 06:00 local) keep only the local date (`2027-01-09`), from the event's `local_timezone`.
- Template placeholders filled by `refresh.py`: `__DATA__` (`{default:{age,conf}, snap, brackets:[{age, conf, teams, raw}]}`),
  `__TITLE__`, `__SEASON__` (from the season key, e.g. "2026–27 season").
- Bracket choice: `pickBracket()` runs once at load (`?age=&conf=` → last bracket viewed, saved in localStorage as
  `bracket` → `default`); everything after runs exactly as for a single bracket. Age tabs and the conference picker
  reload the page. "Find any team" searches all brackets and links with `&follow=<squad_id>`, which sets the
  followed team and is then removed from the URL.
- Team short names (used on phones and in column headers) come from the `SHORT` map in the template (~95 clubs,
  covering every name the regex fallback made too long or too terse). New clubs fall back to the regex.
- "Follow a team" is saved in the browser's localStorage, keyed by page title, so each bracket remembers its own team.
- `window.__debug` in the page exposes the model internals for testing in node or the browser console.
- Snapshot 2026-10-01: 869 of 7,711 league games played across 838 teams; index.html is ~323 KB.

## Ideas / backlog
- Add Flex and out-of-conference results to give the model more data
- Weight recent games more heavily
- Predict draws: the pick is never "draw" unless home/away are within 5%, so draws always count as misses in the accuracy check
