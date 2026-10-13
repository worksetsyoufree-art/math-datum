// Localisation: datum from point pairs. Truth = the real МСК_78(5) datum (tests/fixtures/msk78_5_datum.json).
import fs from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const proj4 = require("../docs/vendor/proj4-2.12.1.js");
const Calib = require("../docs/js/calib.js");
const truth = Calib.fromFieldworker(JSON.parse(fs.readFileSync(new URL("./fixtures/msk78_5_datum.json", import.meta.url))));
let fails = 0;
const check = (name, ok, info) => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${info ? "  — " + info : ""}`); if (!ok) fails++; };
const mm = (v) => (v * 1000).toFixed(2) + " mm";

// 1. the survey origin through the real datum (pyproj gave N=78496.563, E=122396.077)
const o = Calib.wgsToLocal(proj4, truth, 59.79377436625999, 30.468959363475914, 32.10144398268312);
check("ENU origin -> МСК_78(5): X=78496.563 Y=122396.077", Math.abs(o.n - 78496.563) < 0.002 && Math.abs(o.e - 122396.077) < 0.002, `${o.n.toFixed(3)} ${o.e.toFixed(3)}`);
check("vertical plane: H = h - 16.36", Math.abs(o.h - (32.10144398 - 16.36)) < 1e-3, o.h.toFixed(3));
const back = Calib.localToWgs(proj4, truth, o.e, o.n, o.h);
check("round trip local -> WGS", Math.abs(back.lat - 59.79377436626) < 1e-10 && Math.abs(back.lon - 30.46895936348) < 1e-10 && Math.abs(back.h - 32.10144398) < 1e-5, `${mm(Math.hypot((back.lat - 59.79377436626) * 111e3, (back.lon - 30.46895936348) * 55e3))}`);

// 2. synthetic localisation with the real datum as truth
let seed = 12345; const rnd = () => ((seed = (seed * 1664525 + 1013904223) % 4294967296) / 4294967296);
const mk = (n, spanKm, sigma) => Array.from({ length: n }, () => {
  const lat = 59.79377 + (rnd() - 0.5) * spanKm / 111, lon = 30.46896 + (rnd() - 0.5) * spanKm / 55.7, h = 20 + rnd() * 20;
  const q = Calib.wgsToLocal(proj4, truth, lat, lon, h), g = () => (rnd() - 0.5) * 2 * sigma;
  return { e: q.e + g(), n: q.n + g(), z: q.h + g(), lat, lon, h };
});
const cfg = { ellipsoid: "WGS84", lon0: 30, fe: 95900, fn: -6552800 };
const pairs = mk(16, 8, 0), test = mk(8, 8, 0);
const fit = Calib.fitDatum(proj4, pairs, { ...cfg, model: "h7" });
check("7-parameter fit, exact data: RMS < 1 mm (linearisation level)", fit.rms < 1e-3 && fit.rmsH < 1e-3, `rms ${mm(fit.rms)}, rmsH ${mm(fit.rmsH)}`);
check("vertical offset a0 recovered (-16.36)", Math.abs(fit.datum.a0 + 16.36) < 1e-3, fit.datum.a0.toFixed(4));
const worstHold = Math.max(...test.map((p) => { const q = Calib.wgsToLocal(proj4, fit.datum, p.lat, p.lon, p.h); return Math.hypot(q.e - p.e, q.n - p.n); }));
check("hold-out points reproduced < 1 mm", worstHold < 1e-3, mm(worstHold));
const fw = Calib.toFieldworker(fit.datum, "test");
console.log("     recovered (WGS84->local, CF):", ["d_x", "d_y", "d_z", "r_x", "r_y", "r_z", "k"].map((k) => k + "=" + fw.parameters7[k].toFixed(3)).join(" "));
// 3. noise: residuals ~ sigma, hold-out ~ sigma
const noisy = Calib.fitDatum(proj4, mk(30, 10, 0.02), { ...cfg, model: "h7" });
check("noisy data (σ=2 cm): RMS within 0.5–3 cm", noisy.rms > 0.005 && noisy.rms < 0.03, mm(noisy.rms));
// 4. translation-only model on a tiny site
const tiny = mk(5, 0.3, 0);
const t3 = Calib.fitDatum(proj4, tiny, { ...cfg, model: "t3" });
check("3-parameter model on a 300 m site: RMS < 5 cm", t3.rms < 0.05, mm(t3.rms));
const auto = Calib.fitDatum(proj4, tiny, cfg);
check("auto model picks translation for a small site", auto.model === "t3", auto.model);
// 5. exported PROJ string agrees with the datum (first-order inverse, cm level)
const p4 = Calib.toProj4(truth);
const pt = { lat: 59.79377, lon: 30.46896, h: 30 };
const a = Calib.wgsToLocal(proj4, truth, pt.lat, pt.lon, pt.h), b = proj4("EPSG:4326", p4, [pt.lon, pt.lat]);
check("PROJ string (+towgs84) agrees with the datum within 2 cm", Math.hypot(a.e - b[0], a.n - b[1]) < 0.02, mm(Math.hypot(a.e - b[0], a.n - b[1])));
// 6. degenerate input must not crash
const same = Array.from({ length: 4 }, () => ({ e: 122000, n: 78000, z: 13, lat: 59.79, lon: 30.46, h: 30 }));
const deg = Calib.fitDatum(proj4, same, { ...cfg, model: "h7" });
check("identical points: falls back and warns", deg.model === "t3" && deg.warnings.includes("singular"), deg.warnings.join(","));
process.exit(fails ? 1 : 0);
