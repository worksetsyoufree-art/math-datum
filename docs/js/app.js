(function () {
  "use strict";
  var E = window.Engine, C = window.Calib, GEO = window.__GEO__, META = window.__META__ || {};
  var $ = function (id) { return document.getElementById(id); };
  var esc = function (v) { return String(v == null ? "" : v).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); };
  var short = function (s, n) { s = String(s || ""); return s.length > n ? s.slice(0, n - 1).replace(/[;,\s]+\S*$/, "") + "…" : s; };

  /* ---------------- i18n ---------------- */
  var LANG = "";
  try { LANG = localStorage.getItem("lang") || ""; } catch (e) { /* storage blocked */ }
  if (!window.I18N.D[LANG]) LANG = /^ru/i.test(navigator.language || "") ? "ru" : "en";
  function t(k, p) {
    var s = window.I18N.D[LANG][k];
    if (s == null) s = window.I18N.D.en[k];
    if (s == null) return k;
    if (p) Object.keys(p).forEach(function (n) { s = s.split("{" + n + "}").join(p[n]); });
    return s;
  }
  function nf(v, d) {
    if (v == null || !isFinite(v)) return "—";
    return Number(v).toLocaleString(LANG === "ru" ? "ru-RU" : "en-US", { minimumFractionDigits: d, maximumFractionDigits: d }).replace(/ /g, " ");
  }

  /* ---------------- helpers ---------------- */
  function parseCoord(v) {
    v = String(v == null ? "" : v).trim().replace(",", ".");
    if (!v) return NaN;
    var sign = /^-|[SWЮЗsw]\s*$/.test(v) ? -1 : 1;
    var nums = v.replace(/[^0-9.\s°'′"″:]/g, " ").split(/[\s°'′"″:]+/).filter(Boolean).map(Number);
    if (!nums.length || nums.some(isNaN)) return NaN;
    return sign * (Math.abs(nums[0]) + (nums[1] || 0) / 60 + (nums[2] || 0) / 3600);
  }
  function copy(text, btn) {
    var done = function () { var o = btn.textContent; btn.textContent = t("copied"); setTimeout(function () { btn.textContent = o; }, 1200); };
    if (navigator.clipboard) navigator.clipboard.writeText(text).then(done, function () { window.prompt("", text); });
    else window.prompt("", text);
  }
  function download(name, mime, text) {
    var el = document.createElement("a");
    el.href = URL.createObjectURL(new Blob([text], { type: mime }));
    el.download = name; document.body.appendChild(el); el.click(); el.remove();
  }
  function readFile(input, cb) {
    var f = input.files && input.files[0]; if (!f) return;
    var r = new FileReader(); r.onload = function () { cb(String(r.result), f.name); input.value = ""; }; r.readAsText(f);
  }
  function tag(w) {
    var cls = /noTransform|ballpark|old$|gridBetter|mskUnverified/.test(w.k) ? "bad" : /modern$|gnssNative|helmert|identity|mskVerified|sameDatum|inBorders/.test(w.k) ? "good" : "";
    var v = w.v;
    if (v != null && /w_(helmert|identity|gridBetter|shift)/.test(w.k)) v = nf(v, v < 1 ? 2 : v < 10 ? 1 : 0);
    return '<span class="tag ' + cls + '">' + esc(t(w.k, { v: v })) + "</span>";
  }

  /* ---------------- data ---------------- */
  GEO.forEach(function (g) { g.tp = "geo"; });
  var GEOIDX = {}; GEO.forEach(function (g) { GEOIDX[g.c] = g; });
  var PROJ = [], MSK = [], loading = {}, dataP = null;
  function load(src) {
    if (!loading[src]) loading[src] = new Promise(function (res, rej) {
      var s = document.createElement("script"); s.src = src; s.onload = res; s.onerror = rej; document.head.appendChild(s);
    });
    return loading[src];
  }
  function ensureData() {
    if (!dataP) dataP = Promise.all([
      load("data/areas.js").then(function () { E.setAreas(window.__COUNTRIES__, window.__AREAS__); AREAS = null; }),
      load("data/world-proj.js").then(function () { PROJ = window.__PROJ__ || []; PROJ.forEach(function (p) { p.tp = "proj"; }); }),
      load("data/regions.js").then(function () { E.setRegions(window.__REGIONS__); }),
      load("data/ru.js").then(function () {
        MSK = window.__RU__.systems.filter(function (s) { return s.st === "verified"; }).map(function (s) {
          return { tp: "msk", src: "msk", id: s.id, c: null, n: s.t, ar: s.ar + " / " + s.are, rn: s.ar, are: s.are, b: s.b, m: s.m, p: s.p, st: s.st, fe: s.fe, fn: s.fn, rc: s.rc, b0: "msk" + s.rc };
        });
      }),
    ]).then(function () { renderAbout(); });
    return dataP;
  }

  /* ---------------- tabs ---------------- */
  var TABS = ["finder", "calib"];
  function showTab(name) {
    document.querySelectorAll(".tabs button").forEach(function (b) { b.setAttribute("aria-selected", String(b.dataset.tab === name)); });
    TABS.forEach(function (x) { $("tab-" + x).hidden = x !== name; });
    try { history.replaceState(null, "", "#" + name); } catch (e) { /* file:// */ }
  }
  document.querySelectorAll(".tabs button").forEach(function (b) { b.addEventListener("click", function () { showTab(b.dataset.tab); }); });
  if (TABS.indexOf((location.hash || "").slice(1)) >= 0) showTab(location.hash.slice(1));

  /* ================================================================ FINDER ================================================================ */
  var MODE = "local", AREA = null, AREAS = null;
  var EXAMPLES = [
    ["Москва / Moscow", 55.7558, 37.6173], ["Санкт-Петербург / Saint Petersburg", 59.9343, 30.3351], ["Калининград / Kaliningrad", 54.7104, 20.4522],
    ["Владивосток / Vladivostok", 43.1155, 131.8855], ["Berlin", 52.52, 13.405], ["Paris", 48.8566, 2.3522], ["London", 51.5074, -0.1278],
    ["New York", 40.7128, -74.006], ["Mexico City", 19.4326, -99.1332], ["São Paulo", -23.5505, -46.6333], ["Cairo", 30.0444, 31.2357],
    ["Johannesburg", -26.2041, 28.0473], ["Dubai", 25.2048, 55.2708], ["Delhi", 28.6139, 77.209], ["Beijing", 39.9042, 116.4074],
    ["Tokyo", 35.6762, 139.6503], ["Sydney", -33.8688, 151.2093], ["Auckland", -36.8485, 174.7633],
  ];
  var ALIAS = { "россия": "russian federation", "германия": "germany", "франция": "france", "сша": "united states", "китай": "china", "япония": "japan",
    "индия": "india", "бразилия": "brazil", "канада": "canada", "австралия": "australia", "украина": "ukraine", "беларусь": "belarus",
    "казахстан": "kazakhstan", "турция": "turkey", "италия": "italy", "испания": "spain", "великобритания": "united kingdom", "польша": "poland",
    "финляндия": "finland", "швеция": "sweden", "норвегия": "norway", "мексика": "mexico", "аргентина": "argentina", "египет": "egypt",
    "юар": "south africa", "иран": "iran", "монголия": "mongolia", "грузия": "georgia", "армения": "armenia", "азербайджан": "azerbaijan",
    "узбекистан": "uzbekistan", "кыргызстан": "kyrgyzstan", "латвия": "latvia", "литва": "lithuania", "эстония": "estonia", "молдова": "moldova",
    "чехия": "czech", "швейцария": "switzerland", "нидерланды": "netherlands", "бельгия": "belgium", "австрия": "austria", "греция": "greece",
    "португалия": "portugal", "дания": "denmark", "израиль": "israel", "вьетнам": "vietnam", "таиланд": "thailand", "индонезия": "indonesia",
    "корея": "korea", "крым": "crimea", "новая зеландия": "new zealand", "оаэ": "united arab emirates" };
  function areas() {
    if (AREAS) return AREAS;
    var seen = {}; AREAS = [];
    GEO.concat(PROJ).forEach(function (x) { if (!x.ar || seen[x.ar]) return; seen[x.ar] = 1; AREAS.push({ name: x.ar, b: x.b, lc: x.ar.toLowerCase() }); });
    return AREAS;
  }
  function findAreas(q0) {
    var q = String(q0 || "").toLowerCase().trim();
    Object.keys(ALIAS).forEach(function (k) { if (q.indexOf(k) >= 0) q = q.replace(k, ALIAS[k]); });
    var toks = q.split(/\s+/).filter(Boolean);
    if (!toks.length) return [];
    return areas().filter(function (a) { return toks.every(function (w) { return a.lc.indexOf(w) >= 0; }); }).sort(function (a, b) {
      var sa = a.lc.indexOf(toks[0]) === 0 ? 0 : 1, sb = b.lc.indexOf(toks[0]) === 0 ? 0 : 1;
      return sa - sb || a.lc.length - b.lc.length || E.areaDeg2(b.b) - E.areaDeg2(a.b);
    }).slice(0, 6);
  }
  function findRegions(q0) { // Russian MSK regions by name (ru/en)
    var toks = String(q0 || "").toLowerCase().trim().split(/\s+/).filter(Boolean), seen = {}, out = [];
    if (!toks.length) return out;
    MSK.forEach(function (m) {
      if (seen[m.rc]) { var r = seen[m.rc]; r.b = [Math.min(r.b[0], m.b[0]), Math.min(r.b[1], m.b[1]), Math.max(r.b[2], m.b[2]), Math.max(r.b[3], m.b[3])]; return; }
      var hay = (m.rn + " " + m.are).toLowerCase();
      if (!toks.every(function (w) { return hay.indexOf(w) >= 0; })) return;
      seen[m.rc] = { name: (LANG === "ru" ? m.rn : m.are) + " (" + t("area_msk") + ")", b: m.b.slice(), rc: m.rc, region: true }; out.push(seen[m.rc]);
    });
    return out;
  }
  function setArea(a) {
    AREA = a || null;
    $("area-res").innerHTML = AREA ? esc(t("areaSet")) + " <b>" + esc(short(AREA.name, 80)) + '</b> <button class="ghost" id="area-x">' + esc(t("areaClear")) + "</button>" : "";
    if ($("area-x")) $("area-x").onclick = function () { setArea(null); };
  }
  $("area").addEventListener("input", function () {
    ensureData().then(function () {
      var out = findRegions($("area").value).concat(findAreas($("area").value)).slice(0, 8);
      $("area-res").innerHTML = out.map(function (a, i) { return '<button data-i="' + i + '">' + esc(short(a.name, 90)) + "</button>"; }).join("");
      $("area-res").querySelectorAll("button").forEach(function (b) { b.onclick = function () { setArea(out[b.dataset.i]); $("area").value = ""; }; });
    });
  });

  function setMode(m) {
    MODE = m;
    $("m-local").setAttribute("aria-pressed", String(m === "local")); $("m-ll").setAttribute("aria-pressed", String(m === "ll"));
    $("in-local").hidden = m !== "local"; $("in-ll").hidden = m !== "ll"; $("order-wrap").hidden = m !== "local";
    $("results").innerHTML = ""; $("msg").textContent = "";
  }
  $("m-local").onclick = function () { setMode("local"); }; $("m-ll").onclick = function () { setMode("ll"); };

  /* ---- point parsing: lines "X Y [Z]", <P name="..">X Y Z</P>, SURFACE_V1 ---- */
  function parsePoints(text) {
    var L = String(text || "").split(/\r?\n/), out = [], i;
    if (/^\s*SURFACE_V1/.test(L[0] || "")) {
      var k = 1; while (k < L.length && !/^\s*\d+\s*$/.test(L[k])) k++;
      var n = parseInt(L[k], 10); k += 2; // point count, then the second counter
      for (i = k; i < k + n && i < L.length; i++) {
        var q = L[i].trim().split(/\s+/).map(Number);
        if (q.length >= 2 && q.every(isFinite)) out.push({ name: "P" + (out.length + 1), a: q[0], b: q[1], z: q.length > 2 ? q[2] : null });
      }
      return out;
    }
    L.forEach(function (line) {
      var nm = /name="([^"]*)"/.exec(line), nums = line.replace(/<[^>]*>/g, " ").replace(/,/g, ".").match(/-?\d+(?:\.\d+)?/g);
      if (!nums || nums.length < 2) return;
      out.push({ name: nm ? nm[1] : "P" + (out.length + 1), a: parseFloat(nums[0]), b: parseFloat(nums[1]), z: nums[2] != null ? parseFloat(nums[2]) : null });
    });
    return out;
  }
  function rng(vals) { var a = Math.min.apply(null, vals), b = Math.max.apply(null, vals); return a === b ? nf(a, 3) : nf(a, 3) + "…" + nf(b, 3); }
  function updateSummary() {
    var pts = parsePoints($("pts").value);
    if (!pts.length) { $("pts-sum").textContent = ""; return; }
    var zs = pts.map(function (p) { return p.z; }).filter(function (z) { return z != null; });
    $("pts-sum").textContent = zs.length ? t("sumPts", { n: pts.length, x: rng(pts.map(function (p) { return p.a; })), y: rng(pts.map(function (p) { return p.b; })), z: rng(zs) })
      : t("sumPtsNoZ", { n: pts.length, x: rng(pts.map(function (p) { return p.a; })), y: rng(pts.map(function (p) { return p.b; })) });
  }
  $("pts").addEventListener("input", updateSummary);
  $("pts-file").addEventListener("change", function () { readFile(this, function (txt) { $("pts").value = txt; updateSummary(); run(); }); });
  $("ex-points").onclick = function () {
    $("pts").value = ['<P id="1" name="П_1">453594.207 2238973.376 144.153</P>', '<P id="2" name="П_2">453592.333 2238975.140 144.082</P>', '<P id="3" name="П_3">453585.483 2238974.514 144.043</P>',
      '<P id="4" name="П_4">453585.403 2238972.128 143.971</P>', '<P id="5" name="П_5">453571.586 2238973.450 143.936</P>', '<P id="6" name="П_6">453571.156 2238971.407 143.872</P>'].join("\n");
    $("box").value = "55.619783, 38.310216, 55.623095, 38.304913"; $("order").value = "auto"; document.querySelector("details.more").open = true;
    updateSummary(); run();
  };
  $("ex-surface").onclick = function () {
    $("pts").value = "SURFACE_V1\nexample surface\n6\n6\n78498.614 122401.552 13.029\n78355.583 122222.961 12.770\n78738.125 122569.593 13.200\n78505.812 122398.192 13.050\n78738.006 122303.616 12.904\n78649.269 122230.923 13.150\n";
    $("box").value = ""; setArea(null); updateSummary(); run();
  };
  function fillExamples() {
    $("example").innerHTML = '<option value="">' + esc(t("examplePh")) + "</option>" + EXAMPLES.map(function (x, i) { return '<option value="' + i + '">' + esc(x[0]) + "</option>"; }).join("");
  }
  $("example").addEventListener("change", function () { var x = EXAMPLES[this.value]; if (!x) return; $("lat").value = x[1]; $("lon").value = x[2]; run(); });
  ["lat", "lon"].forEach(function (id) { $(id).addEventListener("keydown", function (e) { if (e.key === "Enter") run(); }); });
  $("purpose").addEventListener("change", run);
  $("myloc").onclick = function () {
    $("locmsg").textContent = "…";
    if (!navigator.geolocation) { $("locmsg").textContent = t("geoDenied"); return; }
    navigator.geolocation.getCurrentPosition(function (p) { $("lat").value = p.coords.latitude.toFixed(5); $("lon").value = p.coords.longitude.toFixed(5); $("locmsg").textContent = ""; run(); },
      function () { $("locmsg").textContent = t("geoDenied"); }, { timeout: 8000 });
  };
  $("go").onclick = function () { run(); };

  function getHint() {
    var hint = {};
    if (AREA && AREA.region) hint.region = { rc: AREA.rc, b: AREA.b };
    else if (AREA) hint.area = { ar: AREA.name, b: AREA.b };
    var ap = String($("approx").value || "").match(/-?\d+(?:\.\d+)?/g);
    if (ap && ap.length >= 2) { hint.lat = parseFloat(ap[0]); hint.lon = parseFloat(ap[1]); hint.radiusKm = ap[2] ? parseFloat(ap[2]) : 100; }
    var bx = String($("box").value || "").replace(/,/g, " ").match(/-?\d+(?:\.\d+)?/g);
    if (bx && bx.length) {
      bx = bx.map(Number);
      if (bx.length !== 4) return null;
      hint.box = [Math.min(bx[0], bx[2]), Math.min(bx[1], bx[3]), Math.max(bx[0], bx[2]), Math.max(bx[1], bx[3])];
    }
    return hint;
  }

  /* ---- drawing the area rectangle (local coordinates) with the points ---- */
  function drawRect(cv, rect, pts) {
    var W = cv.width = 560, H = cv.height = 280, ctx = cv.getContext("2d"), cs = getComputedStyle(document.body);
    var line = cs.getPropertyValue("--line").trim() || "#ccc", acc = cs.getPropertyValue("--accent").trim() || "#1f5fbf", mut = cs.getPropertyValue("--muted").trim() || "#666";
    var pad = 28, sx = (W - 2 * pad) / Math.max(1, rect[2] - rect[0]), sy = (H - 2 * pad) / Math.max(1, rect[3] - rect[1]);
    var X = function (e) { return pad + (e - rect[0]) * sx; }, Y = function (n) { return H - pad - (n - rect[1]) * sy; };
    ctx.clearRect(0, 0, W, H); ctx.strokeStyle = acc; ctx.fillStyle = acc; ctx.globalAlpha = 0.12; ctx.fillRect(pad, pad, W - 2 * pad, H - 2 * pad);
    ctx.globalAlpha = 1; ctx.lineWidth = 1.5; ctx.strokeRect(pad, pad, W - 2 * pad, H - 2 * pad);
    ctx.fillStyle = mut; ctx.font = "11px sans-serif";
    ctx.fillText("E " + nf(rect[0], 0), pad, H - 8); ctx.fillText(nf(rect[2], 0), W - pad - 60, H - 8); ctx.fillText("N " + nf(rect[3], 0), 2, 14); ctx.fillText(nf(rect[1], 0), 2, H - pad);
    ctx.fillStyle = "#d92d20";
    (pts || []).slice(0, 400).forEach(function (p) { ctx.beginPath(); ctx.arc(X(p.e), Y(p.n), 3, 0, 7); ctx.fill(); });
    ctx.strokeStyle = line;
  }

  /* ---- result rendering: groups of datums, each with matching projected systems ---- */
  var GROUPS = [];
  function sysName(p) { return p.tp === "msk" ? p.n + " (MSK)" : p.n + " (EPSG:" + p.c + ")"; }
  function itemHtml(it, gi, ii, ctx) {
    var p = it.p, tags = (it.why || []).map(tag).join("");
    var rect = it.r ? t("rectLabel", { e: nf(it.r[0], 0) + "…" + nf(it.r[2], 0), n: nf(it.r[1], 0) + "…" + nf(it.r[3], 0) }) : "";
    var pos = it.u != null ? t("fromCenter", { u: Math.round(Math.min(it.u, 1 - it.u) * 200), v: Math.round(Math.min(it.v, 1 - it.v) * 200) }) : "";
    var head = '<div><b>' + esc(sysName(p)) + "</b>" + (it.hy ? ' <span class="tag">' + esc(t("hyp_" + it.hy)) + "</span>" : "") +
      (it.frac != null ? ' <span class="tag ' + (it.frac >= 0.99 ? "good" : "bad") + '">' + esc(t("fits", { p: Math.round(it.frac * 100) })) + "</span>" : "") + "</div>";
    var mapUrl = "https://www.openstreetmap.org/?mlat=" + it.lat.toFixed(6) + "&mlon=" + it.lon.toFixed(6) + "#map=12/" + it.lat.toFixed(5) + "/" + it.lon.toFixed(5);
    var meta = ctx.mode === "local"
      ? t("center") + ": " + it.lat.toFixed(6) + ", " + it.lon.toFixed(6) + " · " + pos
      : t("east") + ": " + nf(it.xy[0], 3) + " · " + t("north") + ": " + nf(it.xy[1], 3) + " · " + pos;
    return '<div class="sysrow" data-g="' + gi + '" data-i="' + ii + '">' + head + '<div class="meta">' + esc(meta) + (ctx.mode === "local" ? ' · <a href="' + mapUrl + '" target="_blank" rel="noopener">' + esc(t("mapLink")) + "</a>" : "") + "</div><div class=\"meta\">" + esc(rect) + "</div>" +
      (tags ? '<div class="tags">' + tags + "</div>" : "") + '<div class="row"><button class="ghost" data-act="det">' + esc(t("details")) + '</button><button class="ghost" data-act="proj">' + esc(t("copyProj")) +
      '</button></div><div class="slot"></div></div>';
  }
  function renderGroups(groups, ctx) {
    GROUPS = groups;
    var out = $("results");
    if (!groups.length) { out.innerHTML = '<p class="muted">' + esc(t("noResults")) + "</p>"; return; }
    out.innerHTML = '<h2 class="sect">' + esc(t("resultsTitle")) + '</h2><div class="dlist">' + groups.slice(0, 12).map(function (g, gi) {
      var items = g.items.slice(0, g.open ? 8 : 2);
      return '<article class="dcard"><header class="grp-title"><span class="rank">#' + (gi + 1) + "</span><b>" + esc(g.title) + '</b><span class="muted">' + esc(g.code || "") + "</span></header>" +
        (g.sub ? '<div class="muted">' + esc(short(g.sub, 140)) + "</div>" : "") + (g.why && g.why.length ? '<div class="tags">' + g.why.map(tag).join("") + "</div>" : "") +
        items.map(function (it, ii) { return itemHtml(it, gi, ii, ctx); }).join("") +
        (g.items.length > 2 ? '<div class="row"><button class="ghost" data-more="' + gi + '">' + (g.open ? esc(t("hide")) : esc(t("sysShown", { n: Math.min(g.items.length, 8) - 2 }))) + "</button></div>" : "") + "</article>";
    }).join("") + "</div>";
    out.querySelectorAll("[data-more]").forEach(function (b) { b.onclick = function () { var g = GROUPS[b.dataset.more]; g.open = !g.open; renderGroups(GROUPS, ctx); }; });
    out.querySelectorAll(".sysrow").forEach(function (row) {
      var it = GROUPS[row.dataset.g].items[row.dataset.i];
      row.querySelector('[data-act="proj"]').onclick = function () { copy(it.p.p, this); };
      row.querySelector('[data-act="det"]').onclick = function () { toggleDetail(row, it, ctx); };
    });
  }
  function toggleDetail(row, it, ctx) {
    var slot = row.querySelector(".slot");
    if (slot.innerHTML) { slot.innerHTML = ""; return; }
    var h = '<canvas class="rectcv"></canvas><div class="meta"><code>' + esc(it.p.p) + "</code></div>";
    if (it.p.tp === "msk") h += '<div class="note">' + esc(t("mskNote")) + "</div>";
    var conv = null;
    if (ctx.mode === "local") {
      conv = it.pts.map(function (q, k) { var ll = window.proj4(it.p.p, "EPSG:4326", [q.e, q.n]); return { name: ctx.pts[k].name, lat: ll[1], lon: ll[0], z: ctx.pts[k].z, sys: sysName(it.p) }; });
      h += '<table class="mini"><thead><tr><th>#</th><th>lat</th><th>lon</th><th>Z</th></tr></thead><tbody>' + conv.slice(0, 30).map(function (c) {
        return "<tr><td>" + esc(c.name) + '</td><td class="num">' + c.lat.toFixed(8) + '</td><td class="num">' + c.lon.toFixed(8) + '</td><td class="num">' + (c.z == null ? "" : c.z) + "</td></tr>";
      }).join("") + "</tbody></table>";
      h += '<div class="row"><button class="ghost" data-a="csv">' + esc(t("csv")) + '</button><button class="ghost" data-a="cp">' + esc(t("copy")) + " lat, lon</button></div>";
    }
    slot.innerHTML = h;
    if (it.r) drawRect(slot.querySelector("canvas"), it.r, ctx.mode === "local" ? it.pts : [{ e: it.xy[0], n: it.xy[1] }]);
    if (conv) {
      var csv = function () { var q = function (v) { return '"' + String(v == null ? "" : v).replace(/"/g, '""') + '"'; }; return "﻿" + ["name,lat,lon,z,system"].concat(conv.map(function (r) { return [r.name, r.lat.toFixed(9), r.lon.toFixed(9), r.z, r.sys].map(q).join(","); })).join("\n"); };
      slot.querySelector('[data-a="csv"]').onclick = function () { download("points.csv", "text/csv;charset=utf-8", csv()); };
      slot.querySelector('[data-a="cp"]').onclick = function () { copy(conv.map(function (c) { return c.lat.toFixed(8) + ", " + c.lon.toFixed(8); }).join("\n"), this); };
    }
  }

  /* ---- local-coordinates mode ---- */
  function runLocal() {
    var pts = parsePoints($("pts").value), hint = getHint();
    if (!pts.length) { $("msg").textContent = t("noPoints"); return; }
    if (hint == null) { $("msg").textContent = t("boxBad"); return; }
    $("msg").textContent = t("loading");
    ensureData().then(function () {
      setTimeout(function () {
        var order = $("order").value, hyps = order === "xy" ? ["xy"] : order === "en" ? ["en"] : ["xy", "en"], res = [], list = PROJ.concat(MSK);
        hyps.forEach(function (hy) {
          var P = pts.map(function (p) { return { e: hy === "xy" ? p.b : p.a, n: hy === "xy" ? p.a : p.b }; });
          E.identifyLocal(list, P, window.proj4, hint).forEach(function (x) { x.hy = hy; x.pts = P; res.push(x); });
        });
        res.sort(function (a, b) { return b.score - a.score; });
        var map = {}, groups = [];
        res.forEach(function (x) {
          var p = x.p, key = p.tp === "msk" ? "msk" + p.rc : "g" + p.b0;
          if (!map[key]) {
            var g = p.tp === "msk" ? null : GEOIDX[p.b0];
            map[key] = { key: key, items: [], score: x.score, title: p.tp === "msk" ? t("datumMsk", { r: LANG === "ru" ? p.rn : p.are }) : g ? g.n : (p.dn || t("datumNone")),
              code: g ? "EPSG:" + g.c : "", sub: g ? g.ar : "", why: [] };
            groups.push(map[key]);
          }
          map[key].items.push(x);
        });
        $("msg").textContent = groups.length ? t("shown", { n: Math.min(groups.length, 12), m: groups.length }) : "";
        renderGroups(groups, { mode: "local", pts: pts });
        var nMsk = groups.filter(function (g) { return /^msk/.test(g.key); }).length, hinted = hint.area || hint.region || hint.box || hint.lat != null;
        if (nMsk >= 3 && !hinted && groups.length) $("results").insertAdjacentHTML("afterbegin", '<p class="notice">' + esc(t("ambig", { n: nMsk })) + "</p>");
      }, 20);
    });
  }

  /* ---- latitude / longitude mode ---- */
  function runLL() {
    var lat = parseCoord($("lat").value), lon = parseCoord($("lon").value), purpose = $("purpose").value;
    if (isNaN(lat) || isNaN(lon) || Math.abs(lat) > 90) { $("results").innerHTML = ""; return; }
    $("msg").textContent = t("loading");
    ensureData().then(function () {
      setTimeout(function () {
        var datums = E.recommendDatums(GEO, lat, lon, purpose, { proj4: window.proj4 }).filter(function (d) { return !/^(WGS 84 \(|ETRF\d|ITRF\d|IGb\d|IGS\d)/.test(d.g.n); }).slice(0, 8);
        var projs = E.recommendProjections(PROJ, MSK, lat, lon, null, window.proj4, { purpose: purpose });
        var used = {}, groups = [];
        function item(r) {
          var rect = E.localRect(r.p, window.proj4), u = rect ? (r.xy[0] - rect[0]) / Math.max(1, rect[2] - rect[0]) : null, v = rect ? (r.xy[1] - rect[1]) / Math.max(1, rect[3] - rect[1]) : null;
          return { p: r.p, xy: r.xy, r: rect, u: u, v: v, why: r.why, lat: lat, lon: lon, score: r.score };
        }
        var msk = projs.filter(function (r) { return r.p.tp === "msk"; }).slice(0, 6).map(item);
        datums.forEach(function (d) {
          var g = d.g, items = projs.filter(function (r) { return r.p.tp !== "msk" && (r.p.b0 === g.c || (r.p.dn && r.p.dn === g.d)); }).slice(0, 6).map(item);
          var why = d.why.slice(); if (d.shift != null && d.shift > 0.001) why.push({ k: "w_shift", v: d.shift });
          groups.push({ key: "g" + g.c, items: items, score: d.score, title: g.n, code: "EPSG:" + g.c, sub: g.d + " · " + g.ar, why: why });
        });
        if (msk.length) groups.splice(purpose === "survey" ? 0 : Math.min(2, groups.length), 0, { key: "msk", items: msk, score: 0, title: t("datumMsk", { r: LANG === "ru" ? msk[0].p.rn : msk[0].p.are }), code: "", sub: "", why: [] });
        $("msg").textContent = groups.length ? t("shown", { n: Math.min(groups.length, 12), m: groups.length }) : "";
        renderGroups(groups, { mode: "ll" });
      }, 20);
    });
  }
  function run() { MODE === "local" ? runLocal() : runLL(); }

  /* ================================================================ LOCALISATION ================================================================ */
  var CAL = { datum: null, order: "xy" };
  var TRUTH = { azimuth: "North", ellipsoid: { paramA: 6378137, param1f: 298.257223563 }, projection: { longitudeCenter: 30, eastShift: 95900, northShift: -6552800 },
    parameters7: { d_x: -5.476, d_y: -2.074, d_z: -9.338, r_x: 3.38086, r_y: 5.93454, r_z: -0.49579, k: 1.676094 }, paramVSKO: { a0: -16.36 } };
  var num = function (id) { return parseFloat(String($(id).value).replace(",", ".")); };
  function parsePairs(text, order) {
    var out = [];
    String(text || "").split(/\r?\n/).forEach(function (line) {
      var q = line.replace(/<[^>]*>/g, " ").replace(/;/g, " ").match(/-?\d+(?:\.\d+)?/g);
      if (!q || q.length < 4) return;
      q = q.map(Number);
      var a = q[0], b = q[1], z = null, lat, lon, h = null;
      if (q.length === 4) { lat = q[2]; lon = q[3]; } else if (q.length === 5) { z = q[2]; lat = q[3]; lon = q[4]; } else { z = q[2]; lat = q[3]; lon = q[4]; h = q[5]; }
      out.push({ name: "P" + (out.length + 1), e: order === "xy" ? b : a, n: order === "xy" ? a : b, z: z, lat: lat, lon: lon, h: h });
    });
    return out;
  }
  function calSummary() { var n = parsePairs($("cal-pairs").value, $("cal-order").value).length; $("cal-sum").textContent = n ? n + " ×" : ""; }
  $("cal-pairs").addEventListener("input", calSummary); $("cal-order").addEventListener("change", calSummary);
  $("cal-ex").onclick = function () {
    var truth = C.fromFieldworker(TRUTH), seed = 7, rnd = function () { return ((seed = (seed * 1664525 + 1013904223) % 4294967296) / 4294967296); }, lines = [];
    for (var i = 0; i < 12; i++) {
      var lat = 59.79377 + (rnd() - 0.5) * 6 / 111, lon = 30.46896 + (rnd() - 0.5) * 6 / 55.7, h = 20 + rnd() * 20, q = C.wgsToLocal(window.proj4, truth, lat, lon, h);
      lines.push([q.n.toFixed(3), q.e.toFixed(3), q.h.toFixed(3), lat.toFixed(8), lon.toFixed(8), h.toFixed(3)].join(" "));
    }
    $("cal-pairs").value = lines.join("\n"); $("cal-order").value = "xy"; $("cal-ell").value = "WGS84"; $("cal-lon0").value = 30; $("cal-k").value = 1; $("cal-fe").value = 95900; $("cal-fn").value = -6552800; $("cal-lat0").value = 0; calSummary();
  };
  function parseProjDef(p4) {
    var g = function (k) { var m = new RegExp("\\+" + k + "=([-\\d.eE+]+)").exec(p4); return m ? Number(m[1]) : null; }, o = { lon0: g("lon_0"), lat0: g("lat_0") || 0, k0: g("k") != null ? g("k") : g("k_0") != null ? g("k_0") : 1, fe: g("x_0") || 0, fn: g("y_0") || 0 };
    if (/\+proj=utm/.test(p4)) { var z = g("zone"); o.lon0 = -183 + 6 * z; o.k0 = 0.9996; o.fe = 500000; o.fn = /\+south/.test(p4) ? 10000000 : 0; o.lat0 = 0; }
    var a = g("a") || 6378137; o.ell = Math.abs(a - 6378245) < 1 ? "krass" : Math.abs(a - 6377397.155) < 1 ? "bessel" : "WGS84";
    return o;
  }
  function fillProj(o) { $("cal-ell").value = o.ell; $("cal-lon0").value = +o.lon0.toFixed(9); $("cal-k").value = o.k0; $("cal-fe").value = o.fe; $("cal-fn").value = o.fn; $("cal-lat0").value = o.lat0; }
  $("cal-suggest").onclick = function () {
    var pairs = parsePairs($("cal-pairs").value, $("cal-order").value);
    if (!pairs.length) { $("cal-msg").textContent = t("calNeedPairs"); return; }
    $("cal-msg").textContent = t("loading");
    ensureData().then(function () {
      setTimeout(function () {
        var P = pairs.map(function (p) { return { e: p.e, n: p.n }; }), list = PROJ.concat(MSK).filter(function (p) { return p.m === "tmerc" || p.m === "utm"; });
        var res = E.identifyLocal(list, P, window.proj4, { lat: pairs[0].lat, lon: pairs[0].lon, radiusKm: 25 }).slice(0, 6);
        $("cal-msg").textContent = "";
        $("cal-sug").innerHTML = res.length ? esc(t("calSugFound")) + " " + res.map(function (x, i) { return '<button data-i="' + i + '">' + esc(sysName(x.p)) + "</button>"; }).join("") : esc(t("calNone"));
        $("cal-sug").querySelectorAll("button").forEach(function (b) { b.onclick = function () { fillProj(parseProjDef(res[b.dataset.i].p.p)); }; });
      }, 20);
    });
  };
  function cfgFromFields() {
    return { ellipsoid: $("cal-ell").value, lon0: num("cal-lon0"), lat0: num("cal-lat0") || 0, k0: isFinite(num("cal-k")) ? num("cal-k") : 1, fe: num("cal-fe"), fn: num("cal-fn"), model: $("cal-model").value === "auto" ? undefined : $("cal-model").value };
  }
  function showDatum(d, fit, name) {
    CAL.datum = d; CAL.order = $("cal-order").value;
    var fw = C.toFieldworker(d, name || "local"), p = fw.parameters7, h = "";
    h += '<div class="card"><h2>' + esc(t("calParams")) + "</h2>";
    if (fit) {
      h += '<p>' + esc(fit.rmsH != null ? t("calRms", { v: nf(fit.rms * 1000, 2), h: nf(fit.rmsH * 1000, 2) }) : t("calRmsNoH", { v: nf(fit.rms * 1000, 2) })) + " · " + esc(t("calModelUsed", { m: fit.model === "h7" ? t("calModelH7") : t("calModelT3") })) + "</p>";
      fit.warnings.forEach(function (w) { h += '<p class="warn">⚠ ' + esc(t("w_" + w)) + "</p>"; });
    }
    h += '<table class="mini"><thead><tr><th>ΔX, m</th><th>ΔY, m</th><th>ΔZ, m</th><th>ωx, ″</th><th>ωy, ″</th><th>ωz, ″</th><th>m, ppm</th><th>a0, m</th></tr></thead><tbody><tr>' +
      [p.d_x, p.d_y, p.d_z].map(function (v) { return '<td class="num">' + nf(v, 3) + "</td>"; }).join("") + [p.r_x, p.r_y, p.r_z].map(function (v) { return '<td class="num">' + nf(v, 5) + "</td>"; }).join("") +
      '<td class="num">' + nf(p.k, 4) + '</td><td class="num">' + nf(d.a0, 3) + "</td></tr></tbody></table>";
    h += '<p class="muted">WGS 84 → local, coordinate frame (GOST / Fieldworker).</p>';
    if (fit) {
      h += "<h3>" + esc(t("calResid")) + '</h3><table class="mini"><thead><tr><th>' + esc(t("calResidHead")) + "</th><th>dE, mm</th><th>dN, mm</th><th>dH, mm</th></tr></thead><tbody>" +
        fit.residuals.map(function (r, i) { return "<tr><td>P" + (i + 1) + '</td><td class="num">' + nf(r.dE * 1000, 2) + '</td><td class="num">' + nf(r.dN * 1000, 2) + '</td><td class="num">' + (r.dH == null ? "—" : nf(r.dH * 1000, 2)) + "</td></tr>"; }).join("") + "</tbody></table>";
    }
    h += "<h3>" + esc(t("calResultProj")) + "</h3><pre>" + esc(C.toProj4(d)) + '</pre><div class="row"><button class="ghost" id="cal-cp-proj">' + esc(t("copyProj")) + '</button><button class="ghost" id="cal-cp-json">' + esc(t("copy")) + ' JSON</button><button class="ghost" id="cal-dl">' + esc(t("calDownload")) + "</button></div></div>";
    $("cal-out").innerHTML = h; $("cal-apply").hidden = false; setApplyLabels();
    $("cal-cp-proj").onclick = function () { copy(C.toProj4(d), this); };
    $("cal-cp-json").onclick = function () { copy(JSON.stringify(fw, null, 2), this); };
    $("cal-dl").onclick = function () { download("datum.json", "application/json", JSON.stringify(fw, null, 2)); };
  }
  $("cal-fit").onclick = function () {
    var pairs = parsePairs($("cal-pairs").value, $("cal-order").value), cfg = cfgFromFields();
    if (pairs.length < 2) { $("cal-msg").textContent = t("calNeedPairs"); return; }
    if (!isFinite(cfg.lon0) || !isFinite(cfg.fe) || !isFinite(cfg.fn)) { $("cal-msg").textContent = "lon0 / FE / FN"; return; }
    $("cal-msg").textContent = "";
    try { var fit = C.fitDatum(window.proj4, pairs, cfg); showDatum(fit.datum, fit, "local"); } catch (e) { $("cal-msg").textContent = e.message; }
  };
  $("cal-import").addEventListener("change", function () {
    readFile(this, function (txt) {
      try { var j = JSON.parse(txt), d = C.fromFieldworker(j); fillProj({ ell: d.ellipsoid, lon0: d.lon0, lat0: 0, k0: 1, fe: d.fe, fn: d.fn }); showDatum(d, null, j.csCode); $("cal-msg").textContent = t("calImported"); }
      catch (e) { $("cal-msg").textContent = t("calBadJson"); }
    });
  });
  function setApplyLabels() {
    var w2l = $("cal-dir").value === "w2l";
    $("cal-in-label").textContent = w2l ? t("calInW") : t("calInL");
    $("cal-in").placeholder = w2l ? "59.79377437 30.46895936 32.10" : "78496.563 122396.077 15.74";
  }
  $("cal-dir").addEventListener("change", setApplyLabels);
  $("cal-run").onclick = function () {
    var d = CAL.datum; if (!d) return;
    var rows = [], w2l = $("cal-dir").value === "w2l", xy = CAL.order === "xy";
    String($("cal-in").value || "").split(/\r?\n/).forEach(function (line) {
      var q = line.replace(/<[^>]*>/g, " ").replace(/;/g, " ").match(/-?\d+(?:\.\d+)?/g);
      if (!q || q.length < 2) return; q = q.map(Number);
      try {
        if (w2l) { var r = C.wgsToLocal(window.proj4, d, q[0], q[1], q[2] || 0); rows.push({ a: xy ? r.n : r.e, b: xy ? r.e : r.n, c: r.h }); }
        else { var e = xy ? q[1] : q[0], n = xy ? q[0] : q[1], g = C.localToWgs(window.proj4, d, e, n, q[2] == null ? 0 : q[2]); rows.push({ a: g.lat, b: g.lon, c: g.h }); }
      } catch (err) { /* skip bad line */ }
    });
    var fmtA = w2l ? 3 : 9;
    $("cal-res").innerHTML = rows.length ? '<table class="mini"><thead><tr><th>#</th><th>' + (w2l ? (xy ? "X (N)" : "E") : "lat") + "</th><th>" + (w2l ? (xy ? "Y (E)" : "N") : "lon") + "</th><th>" + (w2l ? "H" : "h") + "</th></tr></thead><tbody>" +
      rows.slice(0, 200).map(function (r, i) { return "<tr><td>" + (i + 1) + '</td><td class="num">' + r.a.toFixed(fmtA) + '</td><td class="num">' + r.b.toFixed(fmtA) + '</td><td class="num">' + r.c.toFixed(3) + "</td></tr>"; }).join("") +
      '</tbody></table><div class="row"><button class="ghost" id="cal-csv">' + esc(t("csv")) + "</button></div>" : "";
    if (rows.length) $("cal-csv").onclick = function () { download("points.csv", "text/csv;charset=utf-8", "﻿" + rows.map(function (r) { return [r.a.toFixed(fmtA), r.b.toFixed(fmtA), r.c.toFixed(3)].join(","); }).join("\n")); };
    $("cal-run-msg").textContent = rows.length ? "" : "—";
  };

  /* ================================================================ ABOUT + language ================================================================ */
  function renderAbout() {
    var ru = window.__RU__ && window.__RU__.checks, html = window.I18N.D[LANG].about;
    var miss = ru ? Object.keys(ru.missing_regions).map(function (k) { return ru.missing_regions[k][LANG === "ru" ? 0 : 1]; }).join(", ") : "…";
    var tok = { geo: META.geo, proj: META.proj, epsg: META.epsg, epsg_date: META.epsg_date, proj_ver: META.proj_ver || "PROJ", dropped: META.dropped, tol: META.tolM, approx1: META.approxOver1m,
      ru_ver: ru ? ru.verified : "…", ru_total: ru ? ru.total : "…", missing: miss };
    Object.keys(tok).forEach(function (k) { html = html.split("{" + k + "}").join(tok[k] == null ? "?" : tok[k]); });
    $("about").innerHTML = html;
  }
  function applyLang() {
    document.documentElement.lang = LANG; document.title = t("title");
    document.querySelectorAll("[data-i18n]").forEach(function (el) { el.textContent = t(el.getAttribute("data-i18n")); });
    document.querySelectorAll("[data-i18n-ph]").forEach(function (el) { el.placeholder = t(el.getAttribute("data-i18n-ph")); });
    $("built").textContent = "EPSG " + (META.epsg || "") + (META.epsg_date ? " (" + META.epsg_date + ")" : "");
    fillExamples(); renderAbout(); setApplyLabels(); updateSummary(); calSummary();
    if (AREA) setArea(AREA);
  }
  $("lang").innerHTML = Object.keys(window.I18N.LANGS).map(function (k) { return '<option value="' + k + '">' + esc(window.I18N.LANGS[k]) + "</option>"; }).join("");
  $("lang").value = LANG;
  $("lang").addEventListener("change", function () { LANG = this.value; try { localStorage.setItem("lang", LANG); } catch (e) { /* ignore */ } applyLang(); if ($("results").innerHTML) run(); });

  applyLang();
  ensureData();
})();
