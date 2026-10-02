"""
Python version of the dashboard's goals model (template JS: fit penalised Poisson model), used offline for
past seasons: last-season priors, conference strength and the backtests that choose their settings.

  log λ_home = mu + home + att[h] - def[a],   log λ_away = mu + att[a] - def[h]

MAP fit with ridge priors att, def ~ N(prior, SIG²), home ~ N(0, 0.15²), solved by Newton steps per parameter
(fast and close to the browser's gradient ascent). No Dixon-Coles here: it hardly moves the ratings.
"""
import math, re, unicodedata

SIG = 0.35

def fit(games, teams, prior=None, sig=SIG, iters=60):
    """games: [(home, away, hs, as)]; teams: list of ids; prior: {id: (att, def)} means (default 0)."""
    att = {t: 0.0 for t in teams}; df = {t: 0.0 for t in teams}
    pa = {t: (prior or {}).get(t, (0.0, 0.0))[0] for t in teams}
    pd = {t: (prior or {}).get(t, (0.0, 0.0))[1] for t in teams}
    mu, home = math.log(1.5), 0.1
    if not games:
        return {"mu": mu, "home": home, "att": dict(pa), "def": dict(pd)}
    for t in teams:
        att[t], df[t] = pa[t], pd[t]
    w = 1 / sig ** 2
    for _ in range(iters):
        # mu and home advantage
        g = h = gh = hh = 0.0
        for a, b, x, y in games:
            lh = math.exp(mu + home + att[a] - df[b]); la = math.exp(mu + att[b] - df[a])
            g += x - lh + y - la; h -= lh + la; gh += x - lh; hh -= lh
        mu -= g / h
        gh -= home / 0.15 ** 2; hh -= 1 / 0.15 ** 2; home -= gh / hh
        # attack, then defence, one Newton step each
        ga = {t: -(att[t] - pa[t]) * w for t in teams}; ha = {t: -w for t in teams}
        for a, b, x, y in games:
            lh = math.exp(mu + home + att[a] - df[b]); la = math.exp(mu + att[b] - df[a])
            ga[a] += x - lh; ha[a] -= lh; ga[b] += y - la; ha[b] -= la
        for t in teams:
            att[t] -= ga[t] / ha[t]
        gd = {t: -(df[t] - pd[t]) * w for t in teams}; hd = {t: -w for t in teams}
        for a, b, x, y in games:
            lh = math.exp(mu + home + att[a] - df[b]); la = math.exp(mu + att[b] - df[a])
            gd[b] -= x - lh; hd[b] -= lh; gd[a] -= y - la; hd[a] -= la
        for t in teams:
            df[t] -= gd[t] / hd[t]
    return {"mu": mu, "home": home, "att": att, "def": df}

def probs(m, a, b, rho=-0.1, maxg=10):
    """Home win / draw / away win chances, with the Dixon-Coles low-score adjustment like the page."""
    lh = math.exp(m["mu"] + m["home"] + m["att"].get(a, 0) - m["def"].get(b, 0))
    la = math.exp(m["mu"] + m["att"].get(b, 0) - m["def"].get(a, 0))
    ph = pd = pa = 0.0
    px = [math.exp(-lh) * lh ** k / math.factorial(k) for k in range(maxg + 1)]
    py = [math.exp(-la) * la ** k / math.factorial(k) for k in range(maxg + 1)]
    for x in range(maxg + 1):
        for y in range(maxg + 1):
            p = px[x] * py[y]
            if x <= 1 and y <= 1:
                p *= max(0.0, 1 - lh * la * rho if (x, y) == (0, 0) else 1 + lh * rho if (x, y) == (0, 1)
                         else 1 + la * rho if (x, y) == (1, 0) else 1 - rho)
            if x > y: ph += p
            elif x == y: pd += p
            else: pa += p
    s = ph + pd + pa
    return ph / s, pd / s, pa / s

STOP = {"fc", "sc", "cf", "soccer", "club", "academy", "football", "futbol", "the", "of", "sa", "ac", "afc"}
# Modular11 (past seasons) name -> this season's name, for clubs that were renamed. Unclear pairs are left out
# (e.g. "Los Angeles SC" vs "Los Angeles Sports Club"), so those clubs simply get no history.
ALIASES = {"new york red bulls": "red bull new york", "fc golden state": "golden state force",
           "los angeles surf": "la surf", "la bulls": "los angeles bulls",
           "nashville united soccer academy": "nashville united nusa next"}

def norm(name):
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower().replace("&", " and ")
    s = ALIASES.get(s.strip(), s)
    return " ".join(w for w in re.findall(r"[a-z0-9]+", s) if w not in STOP)

def fit_conf(games, team_conf, sig=SIG, csig=0.5, iters=60):
    """Joint fit across conferences: att = ca[conf] + a[team], def = cd[conf] + d[team]. Conference effects are
    identified only by games between conferences; with none they stay at 0 (prior N(0, csig²)).
    Returns {"mu","home","ca","cd","att","def"} where att/def already include the conference part."""
    teams = sorted(team_conf); confs = sorted(set(team_conf.values()))
    a = {t: 0.0 for t in teams}; d = {t: 0.0 for t in teams}; ca = {c: 0.0 for c in confs}; cd = {c: 0.0 for c in confs}
    mu, home = math.log(1.5), 0.1
    A = lambda t: ca[team_conf[t]] + a[t]; D = lambda t: cd[team_conf[t]] + d[t]
    for _ in range(iters):
        g = h = gh = hh = 0.0
        for x_, y_, x, y in games:
            lh = math.exp(mu + home + A(x_) - D(y_)); la = math.exp(mu + A(y_) - D(x_))
            g += x - lh + y - la; h -= lh + la; gh += x - lh; hh -= lh
        mu -= g / h; gh -= home / 0.15 ** 2; hh -= 1 / 0.15 ** 2; home -= gh / hh
        for par, pri, keyf, sign in ((a, sig, lambda t: t, 1), (ca, csig, lambda t: team_conf[t], 1),
                                     (d, sig, lambda t: t, -1), (cd, csig, lambda t: team_conf[t], -1)):
            gr = {k: -v / pri ** 2 for k, v in par.items()}; he = {k: -1 / pri ** 2 for k in par}
            for x_, y_, x, y in games:
                lh = math.exp(mu + home + A(x_) - D(y_)); la = math.exp(mu + A(y_) - D(x_))
                if sign > 0:  # attack side: home attack with lh, away attack with la
                    gr[keyf(x_)] += x - lh; he[keyf(x_)] -= lh; gr[keyf(y_)] += y - la; he[keyf(y_)] -= la
                else:         # defence side
                    gr[keyf(y_)] -= x - lh; he[keyf(y_)] -= lh; gr[keyf(x_)] -= y - la; he[keyf(x_)] -= la
            for k in par:
                par[k] -= gr[k] / he[k]
    return {"mu": mu, "home": home, "ca": ca, "cd": cd, "att": {t: A(t) for t in teams}, "def": {t: D(t) for t in teams}}
