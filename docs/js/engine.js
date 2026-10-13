/* Datum / CRS selection engine. Pure functions, no DOM. Works in the browser (window.Engine) and in Node (require). */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.Engine = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  var RAD = Math.PI / 180;

  function inBox(b, lon, lat, margin) {
    margin = margin || 0;
    var w = b[0], s = b[1], e = b[2], n = b[3];
    if (lat < s - margin || lat > n + margin) return false;
    if (w <= e) return lon >= w - margin && lon <= e + margin;
    return lon >= w - margin || lon <= e + margin; // crosses the antimeridian
  }
  function areaDeg2(b) {
    var dw = b[2] >= b[0] ? b[2] - b[0] : b[2] - b[0] + 360;
    return dw * (b[3] - b[1]) * Math.max(0.05, Math.cos(((b[1] + b[3]) / 2) * RAD));
  }
  /* 0 = whole world, 1 = a point */
  function specificity(b) {
    var v = 1 - Math.log10(Math.max(areaDeg2(b), 0.01) + 1) / Math.log10(41000);
    return Math.max(0, Math.min(1, v));
  }
  function distKm(lat1, lon1, lat2, lon2) {
    var dLat = (lat2 - lat1) * RAD, dLon = (lon2 - lon1) * RAD;
    var a = Math.sin(dLat / 2) * Math.sin(dLat / 2) + Math.cos(lat1 * RAD) * Math.cos(lat2 * RAD) * Math.sin(dLon / 2) * Math.sin(dLon / 2);
    return 6371.0088 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  }
  function centre(b) {
    var lon = b[0] <= b[2] ? (b[0] + b[2]) / 2 : (((b[0] + b[2] + 360) / 2 + 180) % 360) - 180;
    return [(b[1] + b[3]) / 2, lon];
  }

  /* "modern" = a plate-fixed / GNSS-era realisation (heuristic on the names) */
  var MODERN = /WGS 84|WGS84|ETRS89|ETRF|NAD83|ITRF|IGS|SIRGAS|GDA2020|NZGD2000|GSK-2011|CGCS2000|JGD2011|KGD2002|EUREF|\b(199[5-9]|20[0-3]\d)\b/i;
  function isModern(g) { return !!(g.en || MODERN.test(g.n + " " + g.d)); }

  var PURPOSES = ["gnss", "survey", "legacy"];

  function accQuality(g) {
    if (g.k === "ballpark" || g.tw == null) return 0.04;
    var acc = g.acc && g.acc > 0 ? g.acc : 5;
    return 1 / (1 + acc);
  }

  /* shift (m) when coordinates labelled with datum g are read as WGS 84 */
  function shiftMeters(proj4, g, lat, lon) {
    if (!proj4 || !g.tw || !g.a) return null;
    try {
      var def = "+proj=longlat +a=" + g.a + " +rf=" + g.f + " +towgs84=" + g.tw.join(",") + " +no_defs";
      var r = proj4(def, "EPSG:4326", [lon, lat]);
      var dN = (r[1] - lat) * 111132.95, dE = (r[0] - lon) * 111319.49 * Math.cos(lat * RAD);
      return Math.hypot(dE, dN);
    } catch (e) { return null; }
  }

  /* Rank datums (geographic CRS) for a location and purpose. Returns [{g, score, why:[{k,v}], shift}] */
  function recommendDatums(geo, lat, lon, purpose, opts) {
    opts = opts || {};
    var out = [];
    for (var i = 0; i < geo.length; i++) {
      var g = geo[i];
      if (!inBox(g.b, lon, lat)) continue;
      var sp = specificity(g.b), q = accQuality(g), modern = isModern(g), why = [], score = 0;
      var global = sp < 0.08;
      if (purpose === "gnss") {
        score = 50 * (modern ? 1 : 0) + 30 * q + 15 * sp + (g.c === 4326 ? 12 : 0);
        why.push({ k: modern ? "w_modern" : "w_old" });
        if (g.c === 4326) why.push({ k: "w_gnssNative" });
      } else if (purpose === "survey") {
        score = 40 * sp + 25 * q + 25 * (modern ? 1 : 0) + (g.en ? 0 : 8);
        why.push({ k: global ? "w_global" : "w_local", v: Math.round(sp * 100) });
        if (modern) why.push({ k: "w_modern" });
      } else {
        score = 50 * (modern ? 0 : 1) + 30 * sp + 10 * q;
        why.push({ k: modern ? "w_modernNotLegacy" : "w_old" });
        if (!global) why.push({ k: "w_local", v: Math.round(sp * 100) });
      }
      if (g.tw == null) { why.push({ k: "w_noTransform" }); score -= 10; }
      else if (g.k === "ballpark") { why.push({ k: "w_ballpark" }); score -= 8; }
      else if (g.k === "identity") why.push({ k: "w_identity", v: g.acc });
      else why.push({ k: "w_helmert", v: g.acc });
      if (g.ba != null && g.acc != null && g.ba < g.acc * 0.6) why.push({ k: "w_gridBetter", v: g.ba });
      if (g.en) why.push({ k: "w_ensemble" });
      if (opts.prefer && g.d === opts.prefer) score += 20;
      out.push({ g: g, score: score, why: why, shift: shiftMeters(opts.proj4, g, lat, lon) });
    }
    out.sort(function (a, b) { return b.score - a.score || a.g.c - b.g.c; });
    return out;
  }

  var METHOD_BONUS = { utm: 10, tmerc: 8, lcc: 6, stere: 3, sterea: 3, aea: 3, laea: 3, merc: 1 };

  /* Rank projected CRS for a location; `datum` (a geo item) boosts CRS that are based on it.
     proj: [{c,n,b0,m,ar,b,p,...}], extra: same shape (e.g. Russian MSK, src:'msk'). */
  function recommendProjections(proj, extra, lat, lon, datum, proj4, opts) {
    opts = opts || {};
    var out = [], list = proj.concat(extra || []);
    for (var i = 0; i < list.length; i++) {
      var p = list[i];
      if (!inBox(p.b, lon, lat)) continue;
      var sp = specificity(p.b), score = 30 + 25 * sp, why = [];
      if (datum && p.b0 === datum.c) { score += 30; why.push({ k: "w_sameDatum" }); }
      else if (datum && p.dn && p.dn === datum.d) { score += 20; why.push({ k: "w_sameDatum" }); }
      score += METHOD_BONUS[p.m] || 0;
      if (p.src === "msk") {
        score += p.st === "verified" ? 10 : -5;
        why.push({ k: p.st === "verified" ? "w_mskVerified" : "w_mskUnverified" });
        why.push({ k: "w_mskArea" });
      } else if (sp > 0.45) why.push({ k: "w_local", v: Math.round(sp * 100) });
      var xy = null;
      try {
        xy = proj4("EPSG:4326", p.p, [lon, lat]);
        if (p.m === "tmerc" || p.m === "utm") {
          var fe = p.fe != null ? p.fe : /\+x_0=([-\d.e+]+)/.exec(p.p) ? Number(/\+x_0=([-\d.e+]+)/.exec(p.p)[1]) : 0;
          var off = Math.abs(xy[0] - fe) / 1000;
          score -= Math.min(25, off / 15);
          why.push({ k: "w_offset", v: Math.round(off) });
        }
      } catch (e) { continue; }
      if (!xy || !isFinite(xy[0]) || !isFinite(xy[1])) continue;
      out.push({ p: p, score: score, why: why, xy: xy });
    }
    out.sort(function (a, b) { return b.score - a.score; });
    return out;
  }

  /* Which CRS could these projected coordinates be in? hint = {lat, lon, radiusKm} (optional) */
  function identify(list, e, n, proj4, hint) {
    var out = [];
    for (var i = 0; i < list.length; i++) {
      var p = list[i], ll;
      try { ll = proj4(p.p, "EPSG:4326", [e, n]); } catch (err) { continue; }
      if (!ll || !isFinite(ll[0]) || !isFinite(ll[1]) || Math.abs(ll[1]) > 90) continue;
      var lon = ((ll[0] + 540) % 360) - 180, lat = ll[1];
      if (!inBox(p.b, lon, lat, 0.5)) continue;
      var d = null;
      if (hint && hint.lat != null && hint.lon != null) {
        d = distKm(lat, lon, hint.lat, hint.lon);
        if (hint.radiusKm && d > hint.radiusKm) continue;
      }
      var sp = specificity(p.b);
      var score = (d == null ? 0 : 100 / (1 + d / 25)) + 30 * sp + (p.src === "msk" ? (p.st === "verified" ? 4 : -4) : 0);
      out.push({ p: p, lat: lat, lon: lon, dist: d, score: score });
    }
    out.sort(function (a, b) { return b.score - a.score; });
    return out;
  }

  /* text search over names/areas/codes; tokens are AND-ed */
  function search(list, q, limit) {
    var toks = String(q || "").toLowerCase().split(/\s+/).filter(Boolean), out = [];
    for (var i = 0; i < list.length && out.length < (limit || 200); i++) {
      var it = list[i], hay = ((it.c != null ? it.c : "") + " " + it.n + " " + (it.ar || "") + " " + (it.d || "") + " " + (it.t || "")).toLowerCase();
      var ok = true;
      for (var j = 0; j < toks.length; j++) if (hay.indexOf(toks[j]) < 0) { ok = false; break; }
      if (ok) out.push(it);
    }
    return out;
  }

  /* proj4 definition string of a geographic CRS item */
  function geoDef(g) {
    var tw = g.tw && g.k !== "ballpark" ? " +towgs84=" + g.tw.join(",") : "";
    return "+proj=longlat +a=" + g.a + " +rf=" + g.f + tw + " +no_defs";
  }

  return { inBox: inBox, areaDeg2: areaDeg2, specificity: specificity, distKm: distKm, centre: centre, isModern: isModern,
    recommendDatums: recommendDatums, recommendProjections: recommendProjections, identify: identify, search: search,
    shiftMeters: shiftMeters, geoDef: geoDef, PURPOSES: PURPOSES };
});
