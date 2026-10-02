# fa.js: first-party analytics in your own Firebase project

In use: Firebase project `spaikz-dashboards`, sites `mlsnext` and `ecnl`.
Report: https://stw1.github.io/mlsnext-dashboard/analytics/report.html

A small, reusable analytics kit for static sites (GitHub Pages and the like). Events go straight from the browser
to **your** Cloud Firestore database: no third-party analytics service, no cookies, no SDK on the tracked site.
Several sites (this MLS NEXT dashboard, the ECNL dashboard, ...) can share one Firebase project; each one has its
own `site` code, and one report page shows any of them.

| File | What it is |
|---|---|
| `fa.js` | The tracker (about 8 KB, no dependencies). Include it on a page or inline it. |
| `firestore.rules` | Security rules: anyone may *create* well-formed events for a listed site; only your Google account can *read*; nothing can be changed or deleted. |
| `report.html` | The analytics report. Sign in with Google to see the data (`?demo=1` previews it with made-up data). |
| `config.json` | The Firebase project the report and builds use (`projectId`, `apiKey`, `authDomain`) and the list of site codes. |
| `firebase.json` | For the local emulators used in testing. |
| `deploy_rules.sh` | Deploys `firestore.rules` with the owner emails filled in. |

## What it records

Every event has: `n` (name), `v` (random visitor id kept in the browser), `s` (session: a new one after 30 minutes
away), `pv` (page-view id), `nv` (visit number), `p` (path and query), `d` (mobile / tablet / desktop), `w` (window
width), `app` (opened from the home screen), `lang`, `tz`, `ts` (server time), and `props` (details, at most 16).

| Event | When | Props |
|---|---|---|
| `view` | once per page: the site calls `fa.view({...})`, otherwise sent automatically on load | whatever the site sends (for example `page`, `view`, `age`, `team`), plus `ref` (referring site), `dark`, `title` |
| `click` | a click on a link, button, `summary`, `[role=button]` or `[data-track]` | `label` (`data-track`, `aria-label`, text, or id), `id`, `section` (enclosing `[data-section]`, `section`, `.card[id]`...), `to` (`internal`, `#hash`, `mailto`, `webcal`, or another site's host) |
| `change` | a change to a select, checkbox or radio | `label`, `value` (the chosen option's text) |
| `engage` | when the page is hidden or closed | `sec` (active seconds: page visible and used in the last 30 s), `scroll` (deepest %), `sections` (ids of `sections` elements that came into view) |
| `error` | an uncaught JavaScript error (at most 3 per page) | `msg`, `at` |
| anything | `fa.track("name", {...})` from the site | your own |

Not recorded: IP addresses (Firestore doesn't keep them), names, emails, cookies, or anything typed into a box.
Do Not Track and Global Privacy Control are respected. Anyone can opt out on a device by opening the site once with
`?fa=off` (`?fa=on` undoes it). **Do that on your own devices** so your visits don't count.

## One-time Firebase setup (about 10 minutes)

1. Go to https://console.firebase.google.com, choose **Create a project** (for example `dashboards-analytics`), and
   turn Google Analytics *off*. It isn't needed. The free Spark plan is enough.
2. **Build → Firestore Database → Create database**: production mode, any US location (for example `nam5`).
3. **Build → Authentication → Get started → Sign-in method → Google → Enable → Save.** Then go to **Settings →
   Authorized domains** and add `stw1.github.io` (and any other domain the report will be opened from).
4. **Project settings (gear) → General → Your apps → Web (`</>`)**: register an app (any nickname, no Hosting) and
   copy `apiKey`, `authDomain` and `projectId` into `config.json`. These are public identifiers, not secrets: the
   security rules are what protect the data.
5. Add every site code to `knownSite` in `firestore.rules`. The Google accounts allowed to read the analytics replace
   `OWNER_EMAIL` at deploy time. Deploy the rules either:
   - with the CLI: `analytics/deploy_rules.sh you@example.com` (fills in the owner emails, so they never need to be
     committed, and deploys to the `projectId` in `config.json`), or
   - by pasting the file into **Firestore → Rules → Publish**.
6. Rebuild and publish the site. The report is at `<site>/analytics/report.html`.

Free-plan limits are 20,000 event writes and 50,000 reads a day. A typical page view writes 3–6 events, and opening
the report reads every event in the chosen date range. That's plenty for a team or club audience; for much more
traffic, see "Ideas" below.

## Adding it to another site (for example the ECNL dashboard)

1. Pick a site code (lowercase letters, digits, dashes), for example `ecnl`, and make sure it's in `knownSite` in
   `firestore.rules` and in `sites` in `config.json`.
2. Put the tracker on the page. Either load it from this repo:
   ```html
   <script src="https://stw1.github.io/mlsnext-dashboard/analytics/fa.js"
           data-site="ecnl" data-project-id="YOUR_PROJECT_ID" data-api-key="YOUR_API_KEY"
           data-sections=".card[id]"></script>
   ```
   or copy `fa.js` into that project and inline it (that's what `refresh.py` does here: it reads `config.json`,
   sets `window.FA_CONFIG` and inlines `fa.js`, so the dashboard stays one file). When inlining, replace `</` with
   `<\/` so the `</script>` example in the header comment can't end the tag.
3. Optional but useful: call `fa.view({page: "...", ...})` once the page knows what it's showing, so the report can
   list pages by name and break them down by detail. Add `data-track="..."` to buttons whose text isn't a good label,
   and `data-notrack` to anything that shouldn't be recorded.
4. Open `report.html` and pick the site from the drop-down.

## Testing locally

```bash
cd analytics
firebase emulators:start --only firestore,auth --project demo-fa   # Firestore on :8085, Auth on :9099
```

Then point a page at the emulator with `window.FA_CONFIG = {site: "mlsnext", projectId: "demo-fa",
endpoint: "http://127.0.0.1:8085", debug: true}` (`debug` also logs each event to the console and allows
localhost). Open `report.html?emulator=1` to read the data back. The emulator's Google sign-in accepts any test
account; it has to match `OWNER_EMAIL`.

## Ideas

- Firebase App Check (reCAPTCHA Enterprise) so only your pages can write events.
- A scheduled Cloud Function that rolls old events up into daily totals, to keep the report fast as data grows.
- Freeze each weekend's predictions in Firestore for a tamper-proof track record.
