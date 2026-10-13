(function () {
  "use strict";
  var E = window.Engine, GEO = window.__GEO__, META = window.__META__ || {};
  var $ = function (id) { return document.getElementById(id); };
  var esc = function (v) { return String(v == null ? "" : v).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); };

  /* ---------------- i18n ---------------- */
  var LANG = "en";
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

  /* ---------------- data ---------------- */
  GEO.forEach(function (g) { g.tp = "geo"; });
  var PROJ = [], MSK = [], ALL = GEO.slice();
  var loading = {};
  function load(src) {
    if (!loading[src]) loading[src] = new Promise(function (res, rej) {
      var s = document.createElement("script"); s.src = src; s.onload = res; s.onerror = rej; document.head.appendChild(s);
    });
    return loading[src];
  }
  function onProj() {
    PROJ = window.__PROJ__ || [];
    PROJ.forEach(function (p) { p.tp = "proj"; });
    rebuildAll();
    var utm = item("proj", 32637);
    if (utm && !CV.touched && pkTo) pkTo.set(utm, true);
  }
  function onRu() {
    var ru = window.__RU__;
    MSK = ru.systems.map(function (s) {
      return { tp: "msk", src: "msk", id: s.id, c: null, n: s.t, ar: s.ar + " / " + s.are, are: s.are, b: s.b, m: s.m, p: s.p, st: s.st, fe: s.fe,
        fn: s.fn, lon0: s.lon0, e: s.e, dd: s.d, db: s.db, s: s.s, u: s.u, fl: s.fl, ur: s.ur, ck: s.ck, rc: s.rc };
    });
    rebuildAll();
  }
  function rebuildAll() { ALL = GEO.concat(PROJ, MSK); refreshAll(); }
  var mskList = function () { return MSK.filter(function (s) { return s.st === "verified" || $("showUnv").checked; }); };
  var item = function (tp, key) { var L = tp === "geo" ? GEO : tp === "proj" ? PROJ : MSK; for (var i = 0; i < L.length; i++) if ((tp === "msk" ? L[i].id : L[i].c) === key) return L[i]; return null; };
  var short = function (s, n) { s = String(s || ""); return s.length > n ? s.slice(0, n - 1).replace(/[;,\s]+\S*$/, "") + "…" : s; };
  var label = function (it) { return it.tp === "msk" ? it.n : it.n + " (EPSG:" + it.c + ")"; };
  var defOf = function (it) { return it.tp === "geo" ? E.geoDef(it) : it.p; };

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
  function tag(w) {
    var cls = /noTransform|ballpark|old$|gridBetter|mskUnverified/.test(w.k) ? "bad" : /modern$|gnssNative|helmert|identity|mskVerified|sameDatum/.test(w.k) ? "good" : "";
    var v = w.v;
    if (v != null && (w.k === "w_helmert" || w.k === "w_identity" || w.k === "w_gridBetter")) v = nf(v, v < 1 ? 2 : 1);
    return '<span class="tag ' + cls + '">' + esc(t(w.k, { v: v })) + "</span>";
  }

  /* ---------------- tabs ---------------- */
  var tabs = document.querySelectorAll(".tabs button");
  var TABS = ["finder", "identify", "convert", "catalog", "about"];
  function showTab(name) {
    tabs.forEach(function (b) { b.setAttribute("aria-selected", String(b.dataset.tab === name)); });
    TABS.forEach(function (x) { $("tab-" + x).hidden = x !== name; });
    try { history.replaceState(null, "", "#" + name); } catch (e) { /* file:// */ }
  }
  tabs.forEach(function (b) { b.addEventListener("click", function () { showTab(b.dataset.tab); }); });
  var h0 = (location.hash || "").slice(1);
  if (TABS.indexOf(h0) >= 0) showTab(h0);

  /* ---------------- FINDER ---------------- */
  var EXAMPLES = [
    ["Москва / Moscow", 55.7558, 37.6173], ["Санкт-Петербург / Saint Petersburg", 59.9343, 30.3351], ["Калининград / Kaliningrad", 54.7104, 20.4522],
    ["Владивосток / Vladivostok", 43.1155, 131.8855], ["Berlin", 52.52, 13.405], ["Paris", 48.8566, 2.3522], ["London", 51.5074, -0.1278],
    ["New York", 40.7128, -74.006], ["Mexico City", 19.4326, -99.1332], ["São Paulo", -23.5505, -46.6333], ["Cairo", 30.0444, 31.2357],
    ["Johannesburg", -26.2041, 28.0473], ["Dubai", 25.2048, 55.2708], ["Delhi", 28.6139, 77.209], ["Beijing", 39.9042, 116.4074],
    ["Tokyo", 35.6762, 139.6503], ["Sydney", -33.8688, 151.2093], ["Auckland", -36.8485, 174.7633],
  ];
  var S = { datum: null, purpose: "survey" };
  function fillExamples() {
    $("example").innerHTML = '<option value="">' + esc(t("examplePh")) + "</option>" + EXAMPLES.map(function (x, i) { return '<option value="' + i + '">' + esc(x[0]) + "</option>"; }).join("");
  }
  $("example").addEventListener("change", function () {
    var x = EXAMPLES[this.value]; if (!x) return;
    $("lat").value = x[1]; $("lon").value = x[2]; S.datum = null; runFinder();
  });
  document.querySelectorAll("input[name=purpose]").forEach(function (r) { r.addEventListener("change", function () { S.purpose = this.value; S.datum = null; runFinder(); }); });
  ["lat", "lon"].forEach(function (id) { $(id).addEventListener("input", function () { S.datum = null; runFinder(); }); });
  $("showUnv").addEventListener("change", function () { runFinder(); renderCatalog(); });
  $("myloc").onclick = function () {
    $("locmsg").textContent = "…";
    if (!navigator.geolocation) { $("locmsg").textContent = t("geoDenied"); return; }
    navigator.geolocation.getCurrentPosition(function (p) {
      $("lat").value = p.coords.latitude.toFixed(5); $("lon").value = p.coords.longitude.toFixed(5); $("locmsg").textContent = ""; S.datum = null; runFinder();
    }, function () { $("locmsg").textContent = t("geoDenied"); }, { timeout: 8000 });
  };

  /* place search over EPSG area names */
  var ALIAS = { "россия": "russian federation", "германия": "germany", "франция": "france", "сша": "united states", "китай": "china", "япония": "japan",
    "индия": "india", "бразилия": "brazil", "канада": "canada", "австралия": "australia", "украина": "ukraine", "беларусь": "belarus",
    "казахстан": "kazakhstan", "турция": "turkey", "италия": "italy", "испания": "spain", "великобритания": "united kingdom", "польша": "poland",
    "финляндия": "finland", "швеция": "sweden", "норвегия": "norway", "мексика": "mexico", "аргентина": "argentina", "египет": "egypt",
    "юар": "south africa", "иран": "iran", "монголия": "mongolia", "грузия": "georgia", "армения": "armenia", "азербайджан": "azerbaijan",
    "узбекистан": "uzbekistan", "кыргызстан": "kyrgyzstan", "латвия": "latvia", "литва": "lithuania", "эстония": "estonia", "молдова": "moldova",
    "чехия": "czech", "швейцария": "switzerland", "нидерланды": "netherlands", "бельгия": "belgium", "австрия": "austria", "греция": "greece",
    "португалия": "portugal", "дания": "denmark", "израиль": "israel", "вьетнам": "vietnam", "таиланд": "thailand", "индонезия": "indonesia",
    "корея": "korea", "крым": "crimea", "новая зеландия": "new zealand", "объединенные арабские эмираты": "united arab emirates", "оаэ": "united arab emirates" };
  var AREAS = null;
  function areas() {
    if (AREAS) return AREAS;
    var seen = {}; AREAS = [];
    GEO.concat(PROJ).forEach(function (x) { if (!x.ar || seen[x.ar]) return; seen[x.ar] = 1; AREAS.push({ name: x.ar, b: x.b, lc: x.ar.toLowerCase() }); });
    return AREAS;
  }
  $("place").addEventListener("input", function () {
    var q = this.value.toLowerCase().trim();
    Object.keys(ALIAS).forEach(function (k) { if (q.indexOf(k) >= 0) q = q.replace(k, ALIAS[k]); });
    var toks = q.split(/\s+/).filter(Boolean), out = [];
    if (toks.length) out = areas().filter(function (a) { return toks.every(function (w) { return a.lc.indexOf(w) >= 0; }); }).sort(function (a, b) {
      var sa = a.lc.indexOf(toks[0]) === 0 ? 0 : 1, sb = b.lc.indexOf(toks[0]) === 0 ? 0 : 1; // names that start with the query first
      return sa - sb || a.lc.length - b.lc.length || E.areaDeg2(b.b) - E.areaDeg2(a.b);
    }).slice(0, 6);
    $("placeres").innerHTML = out.map(function (a, i) { return '<button data-i="' + i + '">' + esc(a.name) + "</button>"; }).join("");
    $("placeres").querySelectorAll("button").forEach(function (b) {
      b.onclick = function () { var c = E.centre(out[b.dataset.i].b); $("lat").value = c[0].toFixed(4); $("lon").value = c[1].toFixed(4); S.datum = null; runFinder(); };
    });
  });

  function transformText(g) {
    if (g.tw == null || g.k == null) return t("noTransform");
    if (g.k === "ballpark") return t("ballpark");
    if (g.k === "identity") return t("identity", { v: nf(g.acc, g.acc < 1 ? 2 : 1) });
    return t("helmert", { v: nf(g.acc, g.acc < 1 ? 2 : 1) });
  }
  function drawMap(cv, bbox, lat, lon) {
    var W = cv.width = 720, H = cv.height = 360, ctx = cv.getContext("2d");
    var cs = getComputedStyle(document.body);
    var line = cs.getPropertyValue("--line").trim() || "#ccc", acc = cs.getPropertyValue("--accent").trim() || "#1f5fbf", ink = cs.getPropertyValue("--muted").trim() || "#666";
    var X = function (lo) { return (lo + 180) / 360 * W; }, Y = function (la) { return (90 - la) / 180 * H; };
    ctx.clearRect(0, 0, W, H); ctx.lineWidth = 1; ctx.strokeStyle = line; ctx.fillStyle = ink; ctx.font = "11px sans-serif";
    for (var lo = -180; lo <= 180; lo += 30) { ctx.beginPath(); ctx.moveTo(X(lo), 0); ctx.lineTo(X(lo), H); ctx.stroke(); if (lo > -180 && lo < 180) ctx.fillText(lo + "°", X(lo) + 2, H - 3); }
    for (var la = -60; la <= 60; la += 30) { ctx.beginPath(); ctx.moveTo(0, Y(la)); ctx.lineTo(W, Y(la)); ctx.stroke(); ctx.fillText(la + "°", 2, Y(la) - 2); }
    ctx.fillStyle = acc; ctx.globalAlpha = 0.18; ctx.strokeStyle = acc;
    var rect = function (w, e) { ctx.fillRect(X(w), Y(bbox[3]), X(e) - X(w), Y(bbox[1]) - Y(bbox[3])); ctx.strokeRect(X(w), Y(bbox[3]), X(e) - X(w), Y(bbox[1]) - Y(bbox[3])); };
    if (bbox[0] <= bbox[2]) rect(bbox[0], bbox[2]); else { rect(bbox[0], 180); rect(-180, bbox[2]); }
    ctx.globalAlpha = 1; ctx.fillStyle = "#d92d20"; ctx.beginPath(); ctx.arc(X(lon), Y(lat), 5, 0, 7); ctx.fill();
  }

  var lastRes = [];
  function runFinder() {
    var lat = parseCoord($("lat").value), lon = parseCoord($("lon").value);
    var box = $("datums");
    if (isNaN(lat) || isNaN(lon) || Math.abs(lat) > 90) { box.innerHTML = ""; $("detail").innerHTML = ""; $("projs").innerHTML = ""; $("projh").hidden = true; return; }
    lastRes = E.recommendDatums(GEO, lat, lon, S.purpose, { proj4: window.proj4 });
    if (!lastRes.length) { box.innerHTML = '<p class="muted">' + esc(t("noResults")) + "</p>"; $("detail").innerHTML = ""; $("projs").innerHTML = ""; $("projh").hidden = true; return; }
    var top = lastRes.slice(0, 8), max = top[0].score, min = Math.min(0, top[top.length - 1].score);
    if (S.datum == null || !top.some(function (r) { return r.g.c === S.datum; })) S.datum = top[0].g.c;
    box.innerHTML = top.map(function (r, i) {
      var pct = Math.max(4, Math.round((r.score - min) / (max - min || 1) * 100));
      return '<article class="dcard" data-c="' + r.g.c + '" aria-selected="' + (r.g.c === S.datum) + '" tabindex="0"><header><span class="rank">#' + (i + 1) + "</span><b>" + esc(r.g.n) +
        '</b><span class="muted">EPSG:' + r.g.c + '</span></header><div class="muted">' + esc(r.g.d) + " · " + esc(short(r.g.ar, 120)) + '</div><div class="tags">' + r.why.map(tag).join("") +
        '</div><div class="bar" title="' + esc(t("score")) + " " + nf(r.score, 0) + '"><i style="width:' + pct + '%"></i></div></article>';
    }).join("");
    box.querySelectorAll(".dcard").forEach(function (c) {
      var pick = function () { S.datum = Number(c.dataset.c); runFinder(); };
      c.addEventListener("click", pick); c.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } });
    });
    renderDetail(lat, lon);
  }
  function renderDetail(lat, lon) {
    var r = lastRes.filter(function (x) { return x.g.c === S.datum; })[0];
    if (!r) return;
    var g = r.g;
    var h = '<div class="card"><h2>' + esc(t("selectDatum")) + ": " + esc(g.n) + " (EPSG:" + g.c + ")</h2><dl class=\"facts\">" +
      "<dt>" + esc(t("areaOfUse")) + "</dt><dd>" + esc(short(g.ar, 420)) + " [" + g.b.join(", ") + "]</dd>" +
      "<dt>" + esc(t("ellipsoid")) + "</dt><dd>" + esc(g.e) + " (a = " + nf(g.a, 3) + ", 1/f = " + nf(g.f, 9) + ")</dd>" +
      "<dt>" + esc(t("toWgs")) + "</dt><dd>" + esc(transformText(g)) + (g.opn ? " — " + esc(g.opn) : "") + "</dd>";
    if (g.tw && g.k === "helmert") h += "<dt>Helmert</dt><dd><code>" + g.tw.map(function (v) { return +v.toFixed(6); }).join(", ") + "</code> (ΔX ΔY ΔZ m; ωx ωy ωz ″; m ppm)</dd>";
    if (r.shift != null && r.shift > 0.001) h += "<dt>≈</dt><dd>" + esc(t("shift", { v: nf(r.shift, r.shift < 10 ? 2 : 1) })) + "</dd>";
    h += '</dl><canvas class="map" id="map" aria-hidden="true"></canvas></div>';
    $("detail").innerHTML = h;
    drawMap($("map"), g.b, lat, lon);
    renderProjs(lat, lon, g);
  }
  function renderProjs(lat, lon, g) {
    $("projh").hidden = false;
    if (!PROJ.length) { $("projs").innerHTML = '<p class="muted">' + esc(t("projLoading")) + "</p>"; return; }
    var res = E.recommendProjections(PROJ, mskList(), lat, lon, g, window.proj4, { purpose: S.purpose }).slice(0, 8);
    if (!res.length) { $("projs").innerHTML = '<p class="muted">' + esc(t("projNone")) + "</p>"; return; }
    $("projs").innerHTML = res.map(function (r, i) {
      var p = r.p, isMsk = p.tp === "msk";
      var off = r.why.filter(function (w) { return w.k === "w_offset"; })[0];
      return '<div class="prow"><div><span class="rank">#' + (i + 1) + "</span> <b>" + esc(p.n) + "</b> " + (isMsk ? '<span class="muted">MSK</span>' : '<span class="muted">EPSG:' + p.c + "</span>") +
        '</div><div class="muted">' + esc(short(p.ar || "", 160)) + '</div><div class="tags">' + r.why.map(tag).join("") + (p.ap > 1 ? '<span class="tag bad">' + esc(t("approxNote", { v: nf(p.ap, 1) })) + "</span>" : "") +
        '</div><div class="xy">' + esc(t("east")) + ": <b>" + nf(r.xy[0], 3) + "</b> &nbsp; " + esc(t("north")) + ": <b>" + nf(r.xy[1], 3) + "</b></div>" +
        (isMsk ? '<div class="note">' + esc(t("mskNote")) + "</div>" : "") +
        '<div class="row"><button class="ghost" data-cp="' + i + '">' + esc(isMsk ? t("copyProj") : t("copyEpsg")) + '</button><button class="ghost" data-pj="' + i + '">' + esc(t("copyProj")) + "</button></div></div>";
    }).join("");
    $("projs").querySelectorAll("[data-cp]").forEach(function (b) { b.onclick = function () { var p = res[b.dataset.cp].p; copy(p.tp === "msk" ? p.p : "EPSG:" + p.c, b); }; });
    $("projs").querySelectorAll("[data-pj]").forEach(function (b) { b.onclick = function () { copy(res[b.dataset.pj].p.p, b); }; });
  }

  /* ---------------- IDENTIFY ---------------- */
  $("id-ex").onclick = function () {
    $("id-e").value = "1365816.032"; $("id-n").value = "478559.171"; $("id-lat").value = "55.75"; $("id-lon").value = "37.6"; $("id-r").value = "300"; $("id-go").click();
  };
  $("id-go").onclick = function () {
    var e = parseFloat(String($("id-e").value).replace(/\s/g, "").replace(",", ".")), n = parseFloat(String($("id-n").value).replace(/\s/g, "").replace(",", "."));
    if (isNaN(e) || isNaN(n)) { $("id-msg").textContent = t("inE") + " / " + t("inN"); return; }
    $("id-msg").textContent = t("idLoading");
    Promise.all([load("data/world-proj.js").then(onProj), load("data/ru.js").then(onRu)]).catch(function () { }).then(function () {
      setTimeout(function () {
        var lat = parseCoord($("id-lat").value), lon = parseCoord($("id-lon").value), r = parseFloat($("id-r").value);
        var hint = !isNaN(lat) && !isNaN(lon) ? { lat: lat, lon: lon, radiusKm: isNaN(r) ? 300 : r } : null;
        var res = E.identify(PROJ.concat(mskList()), e, n, window.proj4, hint);
        $("id-msg").textContent = res.length ? t("idShown", { n: Math.min(res.length, 30), m: res.length }) : "";
        $("id-out").innerHTML = res.length ? '<div class="tablewrap"><table><thead><tr><th>' + esc(t("idTable")) + "</th><th>" + esc(t("idLat")) + "</th><th>" + esc(t("idLon")) + "</th><th>" + esc(t("idDist")) + "</th></tr></thead><tbody>" +
          res.slice(0, 30).map(function (x) {
            return "<tr><td>" + esc(x.p.tp === "msk" ? x.p.n + " (MSK)" : x.p.n + " (EPSG:" + x.p.c + ")") + '<div class="muted">' + esc(short(x.p.ar || "", 140)) + '</div></td><td class="num">' + x.lat.toFixed(5) + '</td><td class="num">' + x.lon.toFixed(5) + '</td><td class="num">' + (x.dist == null ? "—" : nf(x.dist, 1) + " " + t("km")) + "</td></tr>";
          }).join("") + "</tbody></table></div>" : '<p class="muted">' + esc(t("idNone")) + "</p>";
      }, 20);
    });
  };

  /* ---------------- CONVERT ---------------- */
  var CV = { from: null, to: null };
  function makePicker(root, key, onPick) {
    var input = root.querySelector(".pk-in"), list = root.querySelector(".pk-list");
    function show(q) {
      var res = E.search(ALL, q, 30);
      list.innerHTML = res.map(function (x, i) { return '<li data-i="' + i + '">' + esc(label(x)) + "<small>" + esc(x.ar || "") + "</small></li>"; }).join("");
      list.hidden = !res.length;
      list.querySelectorAll("li").forEach(function (li) { li.onmousedown = function (ev) { ev.preventDefault(); pick(res[li.dataset.i]); }; });
    }
    function pick(x, init) { CV[key] = x; if (!init) CV.touched = true; input.value = label(x); list.hidden = true; onPick(); }
    input.addEventListener("input", function () { show(input.value); });
    input.addEventListener("focus", function () { input.select(); show(input.value); });
    input.addEventListener("blur", function () { setTimeout(function () { list.hidden = true; }, 120); });
    return { set: pick };
  }
  var pkFrom, pkTo;
  function convLabels() {
    var f = CV.from, g = f && f.tp === "geo";
    $("cv-l1").textContent = g ? t("inLon") : t("inE"); $("cv-l2").textContent = g ? t("inLat") : t("inN");
  }
  function convert() {
    convLabels();
    var out = $("cv-out");
    if (!CV.from || !CV.to) { out.textContent = t("pickFirst"); return; }
    var a = CV.from.tp === "geo" ? parseCoord($("cv-a").value) : parseFloat(String($("cv-a").value).replace(/\s/g, "").replace(",", "."));
    var b = CV.from.tp === "geo" ? parseCoord($("cv-b").value) : parseFloat(String($("cv-b").value).replace(/\s/g, "").replace(",", "."));
    if (isNaN(a) || isNaN(b)) { out.textContent = ""; return; }
    try {
      var r = window.proj4(defOf(CV.from), defOf(CV.to), [a, b]);
      if (!isFinite(r[0]) || !isFinite(r[1])) throw new Error("NaN");
      out.innerHTML = CV.to.tp === "geo" ? "<b>" + esc(t("inLon")) + "</b> " + r[0].toFixed(9) + " &nbsp; <b>" + esc(t("inLat")) + "</b> " + r[1].toFixed(9)
        : "<b>" + esc(t("inE")) + "</b> " + nf(r[0], 3) + " &nbsp; <b>" + esc(t("inN")) + "</b> " + nf(r[1], 3);
    } catch (e) { out.textContent = t("convError") + ": " + e.message; }
  }
  function initConvert() {
    pkFrom = makePicker($("pk-from"), "from", convert); pkTo = makePicker($("pk-to"), "to", convert);
    var from = item("geo", 4326), to = item("proj", 32637) || item("geo", 4326);
    if (from) pkFrom.set(from, true); if (to) pkTo.set(to, true);
    $("cv-a").value = "37.6173"; $("cv-b").value = "55.7558";
    ["cv-a", "cv-b"].forEach(function (id) { $(id).addEventListener("input", convert); });
    $("cv-swap").onclick = function () { var f = CV.from; CV.from = CV.to; CV.to = f; $("pk-from").querySelector(".pk-in").value = CV.from ? label(CV.from) : ""; $("pk-to").querySelector(".pk-in").value = CV.to ? label(CV.to) : ""; convert(); };
    convert();
  }

  /* ---------------- CATALOG ---------------- */
  var cLimit = 150;
  function renderCatalog() {
    var q = $("c-q").value, type = $("c-type").value, onlyVer = $("c-ver").checked;
    var list = ALL.filter(function (x) { return (type === "all" || x.tp === type) && !(x.tp === "msk" && onlyVer && x.st !== "verified"); });
    var res = E.search(list, q, 100000);
    $("c-count").textContent = t("catShown", { n: Math.min(cLimit, res.length), m: res.length });
    $("c-tbl").tBodies[0].innerHTML = res.slice(0, cLimit).map(function (x, i) {
      return '<tr data-i="' + i + '"><td><span class="tp">' + (x.tp === "geo" ? "datum" : x.tp === "msk" ? "MSK" : "CRS") + "</span></td><td>" + esc(x.n) + "</td><td class=\"muted\">" + (x.tp === "msk" ? "MSK" : "EPSG:" + x.c) + "</td><td class=\"muted\">" + esc(short(x.ar || "", 130)) + "</td></tr>";
    }).join("");
    $("c-tbl").tBodies[0].onclick = function (ev) {
      var tr = ev.target.closest("tr[data-i]"); if (!tr) return;
      var nx = tr.nextElementSibling; if (nx && nx.classList.contains("detail")) { nx.remove(); return; }
      var x = res[tr.dataset.i], h = "<td colspan=\"4\"><dl class=\"facts\">";
      var row = function (k, v) { h += "<dt>" + esc(k) + "</dt><dd>" + v + "</dd>"; };
      row(t("areaOfUse"), esc(x.ar || "") + (x.b ? " [" + x.b.join(", ") + "]" : ""));
      if (x.tp === "geo") {
        row("Datum", esc(x.d)); row(t("ellipsoid"), esc(x.e) + " a=" + nf(x.a, 3) + ", 1/f=" + nf(x.f, 9)); row(t("toWgs"), esc(transformText(x)) + (x.opn ? " — " + esc(x.opn) : ""));
        if (x.tw && x.k === "helmert") row("Helmert", "<code>" + x.tw.map(function (v) { return +v.toFixed(6); }).join(", ") + "</code>");
        if (x.ba != null && x.acc != null && x.ba < x.acc) row(t("w_gridBetter", { v: x.ba }), "");
      } else {
        row("PROJ", "<pre>" + esc(x.p) + "</pre>");
        if (x.ap > 1) row("≈", esc(t("approxNote", { v: nf(x.ap, 1) })));
        if (x.tp === "msk") {
          row(t("catSources"), esc((x.s || []).join(", ")) + " — " + esc(x.st === "verified" ? t("verified") : t("unverified")));
          row("Datum", "<code>" + (x.dd || []).map(function (v) { return v == null ? "?" : +Number(v).toFixed(5); }).join(", ") + "</code> — " + esc(x.db || ""));
          if (x.fl && x.fl.length) row(t("catFlags"), x.fl.map(esc).join("<br>"));
          if (x.ur && x.ur.length) row(t("catChecks"), x.ur.map(esc).join("; "));
          row(t("catChecks"), "<code>" + esc(JSON.stringify(x.ck || {})) + "</code>");
          row("", esc(t("mskNote")));
        }
      }
      h += '</dl><div class="row"><button class="ghost" data-use="1">' + esc(t("catUse")) + "</button></div></td>";
      var d = document.createElement("tr"); d.className = "detail"; d.innerHTML = h; tr.after(d);
      d.querySelector("[data-use]").onclick = function () { pkFrom.set(x); convert(); showTab("convert"); };
    };
  }
  $("c-q").addEventListener("input", renderCatalog);
  ["c-type", "c-ver"].forEach(function (id) { $(id).addEventListener("change", renderCatalog); });

  /* ---------------- ABOUT ---------------- */
  function renderAbout() {
    var ru = window.__RU__ && window.__RU__.checks;
    var miss = ru ? Object.keys(ru.missing_regions).map(function (k) { return ru.missing_regions[k][LANG === "ru" ? 0 : 1]; }).join(", ") : "…";
    var html = window.I18N.D[LANG].about;
    var tok = { geo: META.geo, proj: META.proj, epsg: META.epsg, epsg_date: META.epsg_date, proj_ver: META.proj_ver || "PROJ", dropped: META.dropped,
      tol: META.tolM, approx1: META.approxOver1m, ru_ver: ru ? ru.verified : "…", ru_total: ru ? ru.total : "…", missing: miss };
    Object.keys(tok).forEach(function (k) { html = html.split("{" + k + "}").join(tok[k] == null ? "?" : tok[k]); });
    $("about").innerHTML = html;
  }

  /* ---------------- language ---------------- */
  function applyLang() {
    document.documentElement.lang = LANG;
    document.title = t("title");
    document.querySelectorAll("[data-i18n]").forEach(function (el) { el.textContent = t(el.getAttribute("data-i18n")); });
    document.querySelectorAll("[data-i18n-ph]").forEach(function (el) { el.placeholder = t(el.getAttribute("data-i18n-ph")); });
    $("built").textContent = "EPSG " + (META.epsg || "") + (META.epsg_date ? " (" + META.epsg_date + ")" : "");
    fillExamples(); renderAbout(); convLabels();
    if ($("tab-finder")) runFinder();
    renderCatalog();
  }
  function initLang() {
    $("lang").innerHTML = Object.keys(window.I18N.LANGS).map(function (k) { return '<option value="' + k + '">' + esc(window.I18N.LANGS[k]) + "</option>"; }).join("");
    $("lang").value = LANG;
    $("lang").addEventListener("change", function () {
      LANG = this.value; try { localStorage.setItem("lang", LANG); } catch (e) { /* ignore */ }
      applyLang(); convert();
    });
  }
  function refreshAll() { runFinder(); renderCatalog(); if (!CV.from) initConvert(); else convert(); renderAbout(); }

  initLang(); applyLang(); initConvert();
  Promise.all([load("data/world-proj.js").then(onProj), load("data/ru.js").then(onRu)]).catch(function (e) { console.error(e); });
})();
