/* Localisation: build a datum from point pairs (local coordinates <-> WGS 84) and transform with it.
   Pure functions (browser: window.Calib, Node: require). Needs proj4 only for the local Transverse Mercator projection.

   Datum model = what survey software (Fieldworker, GOST 51794) stores:
     local system = projection (Transverse Mercator on a local ellipsoid)
                  + 3D Helmert from WGS 84 ECEF to local ECEF (translation / 7 parameters)
                  + vertical plane  H_local = h_ellipsoidal + a0
   Internally the Helmert is a position-vector one (WGS84 -> local); exported in the GOST "coordinate frame" form
   (rotations of opposite sign), exactly like datum.json. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.Calib = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  var RAD = Math.PI / 180, AS = RAD / 3600;
  var ELL = { WGS84: [6378137, 298.257223563], krass: [6378245, 298.3], bessel: [6377397.155, 299.1528128] };

  function ecef(lat, lon, h, ell) {
    var a = ell[0], f = 1 / ell[1], e2 = f * (2 - f), la = lat * RAD, lo = lon * RAD;
    var N = a / Math.sqrt(1 - e2 * Math.sin(la) * Math.sin(la));
    return [(N + h) * Math.cos(la) * Math.cos(lo), (N + h) * Math.cos(la) * Math.sin(lo), (N * (1 - e2) + h) * Math.sin(la)];
  }
  function geodetic(X, Y, Z, ell) {
    var a = ell[0], f = 1 / ell[1], e2 = f * (2 - f), p = Math.hypot(X, Y), lat = Math.atan2(Z, p * (1 - e2)), h = 0, N;
    for (var i = 0; i < 12; i++) {
      N = a / Math.sqrt(1 - e2 * Math.sin(lat) * Math.sin(lat));
      h = p / Math.cos(lat) - N;
      lat = Math.atan2(Z, p * (1 - e2 * N / (N + h)));
    }
    return [lat / RAD, Math.atan2(Y, X) / RAD, h];
  }

  /* ---- small linear algebra ---- */
  function solve(A, b) { // Gaussian elimination with partial pivoting; returns null if singular
    var n = b.length, M = A.map(function (r, i) { return r.concat([b[i]]); }), i, j, k;
    for (i = 0; i < n; i++) {
      var piv = i;
      for (j = i + 1; j < n; j++) if (Math.abs(M[j][i]) > Math.abs(M[piv][i])) piv = j;
      if (Math.abs(M[piv][i]) < 1e-12) return null;
      var t = M[i]; M[i] = M[piv]; M[piv] = t;
      for (j = i + 1; j < n; j++) { var f = M[j][i] / M[i][i]; for (k = i; k <= n; k++) M[j][k] -= f * M[i][k]; }
    }
    var x = new Array(n);
    for (i = n - 1; i >= 0; i--) { var s = M[i][n]; for (j = i + 1; j < n; j++) s -= M[i][j] * x[j]; x[i] = s / M[i][i]; }
    return x;
  }
  function mat(par) { return [[1, -par.r[2], par.r[1]], [par.r[2], 1, -par.r[0]], [-par.r[1], par.r[0], 1]]; }
  function inv3(m) {
    var a = m[0][0], b = m[0][1], c = m[0][2], d = m[1][0], e = m[1][1], f = m[1][2], g = m[2][0], h = m[2][1], i = m[2][2];
    var A = e * i - f * h, B = -(d * i - f * g), C = d * h - e * g, det = a * A + b * B + c * C;
    return [[A / det, -(b * i - c * h) / det, (b * f - c * e) / det], [B / det, (a * i - c * g) / det, -(a * f - c * d) / det], [C / det, -(a * h - b * g) / det, (a * e - b * d) / det]];
  }
  var mulv = function (m, v) { return [m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2], m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2], m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2]]; };

  /* par: {t:[m], r:[rad] position vector, s: unitless}, direction WGS84 ECEF -> local ECEF */
  function apply(par, X) { var v = mulv(mat(par), X), k = 1 + par.s; return [par.t[0] + k * v[0], par.t[1] + k * v[1], par.t[2] + k * v[2]]; }
  function applyInv(par, X) { var k = 1 + par.s, w = [(X[0] - par.t[0]) / k, (X[1] - par.t[1]) / k, (X[2] - par.t[2]) / k]; return mulv(inv3(mat(par)), w); }

  /* least-squares Helmert from pairs: from[] -> to[] (ECEF). model: "t3" translation only, "h7" seven parameters */
  function fitHelmert(from, to, model) {
    var n = from.length, c = [0, 0, 0], i, k;
    for (i = 0; i < n; i++) for (k = 0; k < 3; k++) c[k] += from[i][k] / n;
    if (model === "t3" || n < 3) {
      var t = [0, 0, 0];
      for (i = 0; i < n; i++) for (k = 0; k < 3; k++) t[k] += (to[i][k] - from[i][k]) / n;
      return { par: { t: t, r: [0, 0, 0], s: 0 }, model: "t3", ok: true };
    }
    var A = [], b = [];
    for (i = 0; i < n; i++) { // centred coordinates keep rotations and translations decoupled
      var p = [from[i][0] - c[0], from[i][1] - c[1], from[i][2] - c[2]], d = [to[i][0] - from[i][0], to[i][1] - from[i][1], to[i][2] - from[i][2]];
      A.push([1, 0, 0, p[0], 0, p[2], -p[1]]); b.push(d[0]);
      A.push([0, 1, 0, p[1], -p[2], 0, p[0]]); b.push(d[1]);
      A.push([0, 0, 1, p[2], p[1], -p[0], 0]); b.push(d[2]);
    }
    var N = [], y = [], r, q;
    for (r = 0; r < 7; r++) { N.push([]); y.push(0); for (q = 0; q < 7; q++) N[r].push(0); }
    for (i = 0; i < A.length; i++) for (r = 0; r < 7; r++) { y[r] += A[i][r] * b[i]; for (q = 0; q < 7; q++) N[r][q] += A[i][r] * A[i][q]; }
    // scale columns (metres vs ppm vs radians) for a meaningful pivot test
    var sc = N.map(function (row, j) { return Math.sqrt(row[j]) || 1; });
    var Ns = N.map(function (row, j) { return row.map(function (v, q2) { return v / (sc[j] * sc[q2]); }); }), ys = y.map(function (v, j) { return v / sc[j]; });
    var x = solve(Ns, ys);
    if (!x || n < 3) return { par: null, ok: false };
    x = x.map(function (v, j) { return v / sc[j]; });
    var tp = [x[0], x[1], x[2]], s = x[3], w = [x[4], x[5], x[6]];
    var wc = [w[1] * c[2] - w[2] * c[1], w[2] * c[0] - w[0] * c[2], w[0] * c[1] - w[1] * c[0]];
    return { par: { t: [tp[0] - s * c[0] - wc[0], tp[1] - s * c[1] - wc[1], tp[2] - s * c[2] - wc[2]], r: w, s: s }, model: "h7", ok: true };
  }

  /* ---- datum object: projection + local ellipsoid + helmert + vertical offset ---- */
  function projDef(d) {
    var e = ELL[d.ellipsoid];
    return "+proj=tmerc +lat_0=" + (d.lat0 || 0) + " +lon_0=" + d.lon0 + " +k=" + (d.k0 == null ? 1 : d.k0) + " +x_0=" + d.fe + " +y_0=" + d.fn + " +a=" + e[0] + " +rf=" + e[1] + " +units=m +no_defs";
  }
  function geoDefOf(d) { var e = ELL[d.ellipsoid]; return "+proj=longlat +a=" + e[0] + " +rf=" + e[1] + " +no_defs"; }
  function converter(proj4, d) { return proj4(geoDefOf(d), projDef(d)); }

  function wgsToLocal(proj4, d, lat, lon, h) {
    var X = ecef(lat, lon, h || 0, ELL.WGS84), Xl = apply(d.par, X), g = geodetic(Xl[0], Xl[1], Xl[2], ELL[d.ellipsoid]);
    var en = converter(proj4, d).forward([g[1], g[0]]);
    return { e: en[0], n: en[1], h: g[2] + (d.a0 || 0) };
  }
  function localToWgs(proj4, d, e, n, H) {
    var ll = converter(proj4, d).inverse([e, n]), hl = (H == null ? 0 : H) - (d.a0 || 0);
    var Xl = ecef(ll[1], ll[0], hl, ELL[d.ellipsoid]), X = applyInv(d.par, Xl), g = geodetic(X[0], X[1], X[2], ELL.WGS84);
    return { lat: g[0], lon: g[1], h: g[2] };
  }

  /* pairs: [{e, n, z, lat, lon, h}] (z, h optional). cfg: {ellipsoid, lon0, lat0, k0, fe, fn, model}.
     Returns {datum, residuals:[{dE,dN,dH}], rms, rmsH, warnings:[...]} */
  function fitDatum(proj4, pairs, cfg) {
    var d = { ellipsoid: cfg.ellipsoid || "WGS84", lon0: cfg.lon0, lat0: cfg.lat0 || 0, k0: cfg.k0 == null ? 1 : cfg.k0, fe: cfg.fe, fn: cfg.fn, a0: 0, par: null };
    var warnings = [], conv = converter(proj4, d), hasH = pairs.every(function (p) { return p.z != null && p.h != null && isFinite(p.z) && isFinite(p.h); });
    if (hasH) { var s = 0; pairs.forEach(function (p) { s += p.z - p.h; }); d.a0 = s / pairs.length; }
    var from = [], to = [];
    pairs.forEach(function (p) {
      var ll = conv.inverse([p.e, p.n]), hl = hasH ? p.h : 0;
      from.push(ecef(p.lat, p.lon, hasH ? p.h : 0, ELL.WGS84));
      to.push(ecef(ll[1], ll[0], hl, ELL[d.ellipsoid]));
    });
    var span = 0, i, j;
    for (i = 0; i < pairs.length; i++) for (j = i + 1; j < pairs.length; j++) span = Math.max(span, Math.hypot(from[i][0] - from[j][0], from[i][1] - from[j][1], from[i][2] - from[j][2]));
    var model = cfg.model || (pairs.length >= 4 && span > 2000 ? "h7" : "t3");
    var fit = fitHelmert(from, to, model);
    if (!fit.ok) { fit = fitHelmert(from, to, "t3"); warnings.push("singular"); }
    if (model === "h7" && pairs.length < 4) warnings.push("few");
    if (model === "h7" && span < 2000) warnings.push("small");
    if (!hasH) warnings.push("noHeights");
    d.par = fit.par; d.model = fit.model;
    var res = [], sE = 0, sH = 0;
    pairs.forEach(function (p) {
      var q = wgsToLocal(proj4, d, p.lat, p.lon, hasH ? p.h : 0), dE = q.e - p.e, dN = q.n - p.n, dH = hasH ? q.h - p.z : null;
      res.push({ dE: dE, dN: dN, dH: dH }); sE += dE * dE + dN * dN; if (hasH) sH += dH * dH;
    });
    return { datum: d, residuals: res, rms: Math.sqrt(sE / (2 * pairs.length)), rmsH: hasH ? Math.sqrt(sH / pairs.length) : null, span: span, warnings: warnings, model: fit.model };
  }

  /* exports */
  function toFieldworker(d, name) { // same layout as datum.json: WGS84 -> local, coordinate frame, arcsec, ppm
    return {
      azimuth: "North", orientation: "NE", country: "", csCode: name || "local", isPredefined: false,
      ellipsoidOriginal: { paramA: ELL.WGS84[0], param1f: ELL.WGS84[1] }, ellipsoid: { paramA: ELL[d.ellipsoid][0], param1f: ELL[d.ellipsoid][1] },
      projection: { type: "ru.gsisoft.common.model.cs.Projection.ProjectionTM", longitudeCenter: d.lon0, eastShift: d.fe, northShift: d.fn },
      parameters7: { d_x: d.par.t[0], d_y: d.par.t[1], d_z: d.par.t[2], r_x: -d.par.r[0] / AS, r_y: -d.par.r[1] / AS, r_z: -d.par.r[2] / AS, k: d.par.s * 1e6 },
      paramVSKO: { type: "ru.gsisoft.common.model.cs.ParamVSKO.Plane", a0: d.a0 }, isPredefined2: false,
    };
  }
  function toProj4(d) { // local -> WGS84 as PROJ +towgs84 (position vector, first-order inverse of the fitted WGS84 -> local)
    var e = ELL[d.ellipsoid], tw = [-d.par.t[0], -d.par.t[1], -d.par.t[2], -d.par.r[0] / AS, -d.par.r[1] / AS, -d.par.r[2] / AS, -d.par.s * 1e6].map(function (v) { return +v.toPrecision(10); });
    return "+proj=tmerc +lat_0=" + (d.lat0 || 0) + " +lon_0=" + d.lon0 + " +k=" + d.k0 + " +x_0=" + d.fe + " +y_0=" + d.fn + " +a=" + e[0] + " +rf=" + e[1] + " +towgs84=" + tw.join(",") + " +units=m +no_defs";
  }
  /* datum object from a Fieldworker-style JSON (WGS84 -> local, coordinate frame) */
  function fromFieldworker(j) {
    var p = j.parameters7, pr = j.projection, ell = Math.abs(j.ellipsoid.paramA - 6378245) < 1 ? "krass" : Math.abs(j.ellipsoid.paramA - 6377397.155) < 1 ? "bessel" : "WGS84";
    return { ellipsoid: ell, lon0: pr.longitudeCenter, lat0: 0, k0: 1, fe: pr.eastShift, fn: pr.northShift, a0: j.paramVSKO ? j.paramVSKO.a0 : 0,
      par: { t: [p.d_x, p.d_y, p.d_z], r: [-p.r_x * AS, -p.r_y * AS, -p.r_z * AS], s: p.k * 1e-6 } };
  }

  return { ELL: ELL, ecef: ecef, geodetic: geodetic, apply: apply, applyInv: applyInv, fitHelmert: fitHelmert, fitDatum: fitDatum, wgsToLocal: wgsToLocal,
    localToWgs: localToWgs, toFieldworker: toFieldworker, toProj4: toProj4, fromFieldworker: fromFieldworker, projDef: projDef };
});
