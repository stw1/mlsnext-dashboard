# MLS NEXT Standings & Prediction Dashboard

Personal project (Stephen). Builds a self-contained HTML dashboard for one MLS NEXT
**Homegrown Division** age group + conference. It shows standings, a head-to-head
("who beat who") grid, power ratings, results, and predicted scores for every remaining
game, plus a 10,000-run season simulation. The default page covers **U13 and U14 Northwest** (2026-27 season), with a toggle between them.

## Layout
```
CLAUDE.md                          this file
scripts/refresh.py                 fetch live data -> data/*.csv -> dashboards/*.html (stdlib only)
template/dashboard_template.html   the dashboard; all model + rendering logic is inline JS
data/<AGE>_<CONF>_games.csv        one row per league game (blank scores = not played yet)
data/<AGE>_<CONF>_teams.json       squad_id -> team name
data/<AGE>_<CONF>_meta.json        snapshot date, season key
dashboards/<CONF>_dashboard.html   built output (all ages for that conference in one file)
index.html                         copy of the Northwest dashboard (served by GitHub Pages)
```

## Common tasks
- **Update with new scores:** `python3 scripts/refresh.py` (defaults: `--age U13,U14 --conference Northwest --default-age U14`)
- **Another conference:** `python3 scripts/refresh.py --age U15,U16 --conference Southwest --default-age U16`
  (if the conference name is wrong, the script prints the valid names)
- **Rebuild without network** (for example, after editing the template): `python3 scripts/refresh.py --offline`
- Open `dashboards/Northwest_dashboard.html` (or `?age=U13`) in a browser to check the result.
- **Auto-refresh:** `.github/workflows/refresh.yml` runs `refresh.py` on GitHub Actions Sat & Sun (~1, 5, 9 pm
  Pacific) and Mon & Tue (~9 am), and commits + pushes only when `data/*_games.csv` changed. Run it on demand from
  the repo's Actions tab ("Refresh scores" → "Run workflow") or `gh workflow run refresh.yml`.
  GitHub pauses scheduled workflows in public repos after 60 days with no commits; re-enable on the Actions tab.
- **Publish by hand:** `git pull` first (the bot commits too), then `git add -A && git commit -m "..." && git push`. GitHub Pages serves
  https://stw1.github.io/mlsnext-dashboard/ from the `main` branch root (repo `stw1/mlsnext-dashboard`).
  Link straight to an age with `?age=U13` / `?age=U14`. Other conferences are at `/dashboards/<CONF>_dashboard.html`.

## Data source
The page at mlssoccer.com/mlsnext/standings/homegrown_division/ embeds an iframe from
`mls-assist.theintelligenceplatform.com`. That iframe reads two public JSON files:
- `https://mls-assist.theintelligenceplatform.com/data/standings/mls-next-league-26-27.json`
  - `competition_season.competition_brackets[]`: one entry per age group + conference.
    Each has `age_group.name` (e.g. "U14"), `name` (e.g. "Northwest") and `standings[].team.{squad_id,name,logo_url}`.
  - U13 Northwest is bracket id 101 (13 teams, no San Jose Earthquakes); U14 Northwest is id 102 (14 teams). Some brackets have a "(Pro Player Pathway)" suffix.
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
- Dates in the CSV are in local Pacific time (`--tz`). Games without a set time store the date only.
- Template placeholders filled by `refresh.py`: `__DATA__` (`{conf, default, brackets:[{age, conf, raw, teams, snap}]}`),
  `__TITLE__`, `__SEASON__` (from the season key, e.g. "2026–27 season").
- Age toggle: the script picks one bracket at load (`?age=` → last age viewed, saved in localStorage → `default`),
  then everything else runs exactly as for a single bracket. The toggle links reload the page with `?age=`.
- Team short names (used on phones and in column headers) come from the `SHORT` map in the template, with a
  regex fallback for brackets that aren't in the map.
- "Follow a team" is saved in the browser's localStorage, keyed by page title, so each bracket remembers its own team.
- `window.__debug` in the page exposes the model internals for testing in node or the browser console.
- Snapshot 2026-10-01: U13 20/156 games played, U14 23/182.

## Ideas / backlog
- Add Flex and out-of-conference results to give the model more data
- Add a conference switcher (age toggle exists; conferences are still separate pages)
- Weight recent games more heavily
- Predict draws: the pick is never "draw" unless home/away are within 5%, so draws always count as misses in the accuracy check
