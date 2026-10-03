/*
 * fa.js: first-party analytics for static sites, stored in your own Firebase project (Cloud Firestore).
 * No cookies, no third-party service, no SDK: events go straight to the Firestore REST API, where security
 * rules (firestore.rules) only allow creating well-formed events and only the owner can read them.
 * See README.md in this folder for setup, the event format and how to add it to another site.
 *
 * Configure with window.FA_CONFIG before this script runs, or with data attributes on the script tag:
 *   <script src="fa.js" data-site="ecnl" data-project-id="my-project" data-api-key="AIza..."></script>
 * Options: site (required, e.g. "mlsnext"), projectId, apiKey, sections (CSS selector of page sections to report
 * as "seen"), autoView (default true: send a plain page view if the site doesn't call fa.view()), debug (log to the
 * console and allow localhost), endpoint (default https://firestore.googleapis.com; the emulator for tests).
 *
 * API: fa.view(props) once per page with what the page shows (e.g. {view:"team", age:"U15"}); fa.track(name, props)
 * for anything else. Clicks on links/buttons, select changes, JavaScript errors, active time, scroll depth and
 * sections seen are recorded automatically. Visitors can opt out with ?fa=off (remembered; ?fa=on undoes it);
 * Do Not Track / Global Privacy Control are respected.
 */
(function () {
  "use strict";
  var tag = document.currentScript, ds = (tag && tag.dataset) || {};
  var C = Object.assign({ autoView: true }, window.FA_CONFIG || {});
  if (ds.site) C.site = ds.site;
  if (ds.projectId) C.projectId = ds.projectId;
  if (ds.apiKey) C.apiKey = ds.apiKey;
  if (ds.sections) C.sections = ds.sections;
  var noop = function () {};
  var api = window.fa = { view: noop, track: noop, flush: noop, enabled: false, config: C };

  var ls = function (k, v) { try { if (v === undefined) return localStorage.getItem(k); if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) { return null; } };
  var q = new URLSearchParams(location.search);
  if (q.get("fa") === "off") ls("fa:off", "1");
  if (q.get("fa") === "on") ls("fa:off", null);
  var local = /^(localhost|127\.|\[::1\]|0\.0\.0\.0)/.test(location.hostname) || location.protocol === "file:";
  if (!C.site || !C.projectId || !/^[a-z0-9-]{1,30}$/.test(C.site) || ls("fa:off") === "1" ||
      navigator.doNotTrack === "1" || navigator.globalPrivacyControl === true || (local && !C.debug)) return;

  var MAX = 80, sent = 0, queue = [], timer = null, viewed = false, errors = 0;
  var rid = function (n) { var a = new Uint8Array(n), s = "", c = "abcdefghijklmnopqrstuvwxyz0123456789"; crypto.getRandomValues(a); for (var i = 0; i < n; i++) s += c[a[i] % 36]; return s; };
  var now = Date.now();
  // visitor: random id kept in this browser; visit number goes up after 30 minutes away (a new session)
  var vis = {}; try { vis = JSON.parse(ls("fa:v") || "{}"); } catch (e) {}
  if (!vis.id) vis = { id: rid(12), n: 0, last: 0 };
  if (now - (vis.last || 0) > 30 * 60 * 1000 || !vis.s) { vis.n = (vis.n || 0) + 1; vis.s = rid(12); }
  vis.last = now; ls("fa:v", JSON.stringify(vis));
  var touch = function () { vis.last = Date.now(); ls("fa:v", JSON.stringify(vis)); };

  var w = window.innerWidth || 0;
  var common = {
    v: vis.id, s: vis.s, pv: rid(10), nv: vis.n,
    p: (location.pathname + location.search.replace(/([?&])fa=(on|off)&?/, "$1").replace(/[?&]$/, "")).slice(0, 300),
    d: w < 700 ? "mobile" : w < 1100 ? "tablet" : "desktop", w: w,
    app: !!((window.matchMedia && matchMedia("(display-mode: standalone)").matches) || navigator.standalone),
    lang: (navigator.language || "").slice(0, 12),
    tz: (function () { try { return Intl.DateTimeFormat().resolvedOptions().timeZone.slice(0, 40); } catch (e) { return ""; } })()
  };
  var clean = function (props) {  // flat, at most 16 keys, short strings: what the security rules accept
    var o = {}, k = 0;
    for (var key in props || {}) {
      var x = props[key];
      if (x === undefined || x === null || x === "" || k >= 16 || !/^[A-Za-z0-9_]{1,30}$/.test(key)) continue;
      if (typeof x === "boolean" || (typeof x === "number" && isFinite(x))) o[key] = x;
      else o[key] = String(x).replace(/\s+/g, " ").trim().slice(0, 200);
      k++;
    }
    return o;
  };
  var val = function (x) {
    if (typeof x === "boolean") return { booleanValue: x };
    if (typeof x === "number") return Number.isInteger(x) ? { integerValue: String(x) } : { doubleValue: x };
    if (typeof x === "object") { var f = {}; for (var k in x) f[k] = val(x[k]); return { mapValue: { fields: f } }; }
    return { stringValue: String(x) };
  };
  var base = (C.endpoint || "https://firestore.googleapis.com").replace(/\/$/, "");
  var docs = "projects/" + C.projectId + "/databases/(default)/documents";
  var flush = function (leaving) {
    clearTimeout(timer); timer = null;
    while (queue.length) {
      var batch = queue.splice(0, 20);
      var body = JSON.stringify({ writes: batch.map(function (e) {
        var f = {}; for (var k in e) f[k] = val(e[k]);
        return { update: { name: docs + "/sites/" + C.site + "/events/" + rid(20), fields: f },
                 currentDocument: { exists: false }, updateTransforms: [{ fieldPath: "ts", setToServerValue: "REQUEST_TIME" }] };
      }) });
      try {
        fetch(base + "/v1/" + docs + ":commit" + (C.apiKey ? "?key=" + encodeURIComponent(C.apiKey) : ""),
              { method: "POST", headers: { "Content-Type": "application/json" }, body: body, keepalive: !!leaving, credentials: "omit" })
          .then(function (r) { if (!r.ok && C.debug) r.text().then(function (t) { console.warn("fa: rejected", r.status, t); }); })
          .catch(function () {});
      } catch (e) {}
    }
  };
  var track = function (name, props) {
    if (sent >= MAX || !/^[a-z_]{1,30}$/.test(name)) return;
    sent++;
    var e = Object.assign({ n: name }, common);
    var pr = clean(props); if (Object.keys(pr).length) e.props = pr;
    if (C.debug) console.log("fa", name, pr);
    queue.push(e); touch();
    if (!timer) timer = setTimeout(flush, 2000);
  };
  api.enabled = true; api.track = track; api.flush = flush;
  api.view = function (props) {
    if (viewed) return; viewed = true;
    var ref = "";
    try { var r = document.referrer && new URL(document.referrer); if (r && r.host !== location.host) ref = r.host; } catch (e) {}
    var dark = !!(window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches);
    track("view", Object.assign({ ref: ref, dark: dark, title: document.title }, props || {}));
  };
  if (C.autoView) window.addEventListener("load", function () { if (!viewed) api.view({}); });

  // clicks on links and buttons: label = data-track, aria-label, id or the visible text
  document.addEventListener("click", function (ev) {
    var el = ev.target && ev.target.closest && ev.target.closest("a,button,summary,[role=button],[data-track]");
    if (!el || el.closest("[data-notrack]")) return;
    // the visible text only (innerText skips hidden copies such as a long and a short team name), first line
    var text = ((el.innerText || el.textContent || "").replace(/[▲▼↑↓↕›‹→←✓]/g, "").trim().split("\n")[0] || "").trim().slice(0, 60);
    var label = el.getAttribute("data-track") || el.getAttribute("aria-label") || text || el.id || el.tagName;
    var pr = { label: label, id: el.id || "" }, href = el.getAttribute("href") || "";
    if (href) pr.to = /^mailto:/.test(href) ? "mailto" : /^webcal:/.test(href) ? "webcal" : href[0] === "#" ? "#" + href.slice(1, 40)
      : (function () { try { var u = new URL(href, location.href); return u.host === location.host ? "internal" : u.host; } catch (e) { return ""; } })();
    var sec = el.closest("[data-section],section[id],[id^=s-],.card[id],nav,header,footer");
    if (sec) pr.section = sec.getAttribute("data-section") || sec.id || sec.tagName.toLowerCase();
    track("click", pr);
  }, true);
  document.addEventListener("change", function (ev) {
    var el = ev.target; if (!el || !el.matches || !el.matches("select,input[type=checkbox],input[type=radio]") || el.closest("[data-notrack]")) return;
    var v = el.tagName === "SELECT" ? (el.options[el.selectedIndex] || {}).text : el.type === "checkbox" ? String(el.checked) : el.value;
    track("change", { label: el.getAttribute("data-track") || el.id || el.name || el.getAttribute("aria-label") || "input", value: v || "" });
  }, true);
  window.addEventListener("error", function (e) {
    if (errors++ >= 3) return;
    track("error", { msg: (e.message || "error").slice(0, 100), at: ((e.filename || "").split("/").pop() + ":" + (e.lineno || 0)).slice(0, 60) });
  });

  // engagement: active seconds (page visible and touched in the last 30 s), deepest scroll, sections seen.
  // Sent when the page is hidden or closed; each send covers the time since the previous one.
  var active = 0, lastAct = Date.now(), maxScroll = 0, seen = {}, seenList = [];
  ["pointerdown", "keydown", "scroll", "touchstart", "mousemove"].forEach(function (t) {
    window.addEventListener(t, function () { lastAct = Date.now(); }, { passive: true, capture: true });
  });
  setInterval(function () { if (document.visibilityState === "visible" && Date.now() - lastAct < 30000) active += 5; }, 5000);
  window.addEventListener("scroll", function () {
    var h = document.documentElement.scrollHeight - window.innerHeight;
    if (h > 0) maxScroll = Math.max(maxScroll, Math.min(100, Math.round(window.scrollY / h * 100)));
  }, { passive: true });
  if (C.sections && window.IntersectionObserver) {
    var io = new IntersectionObserver(function (es) {
      es.forEach(function (x) { var id = x.target.id || x.target.getAttribute("data-section"); if (x.isIntersecting && id && !seen[id]) { seen[id] = 1; seenList.push(id); } });
    }, { threshold: 0.3 });
    var watch = function () { document.querySelectorAll(C.sections).forEach(function (el) { if (!el.__fa) { el.__fa = 1; io.observe(el); } }); };
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", watch); else watch();
    window.addEventListener("load", watch);
  }
  var sentSeen = 0;
  var leave = function () {
    if (active > 0 || seenList.length > sentSeen) {
      track("engage", { sec: active, scroll: maxScroll, sections: seenList.slice(sentSeen).join(",").slice(0, 200) });
      active = 0; sentSeen = seenList.length;
    }
    flush(true);
  };
  document.addEventListener("visibilitychange", function () { if (document.visibilityState === "hidden") leave(); });
  window.addEventListener("pagehide", leave);
})();
