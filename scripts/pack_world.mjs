// Filter the EPSG candidates by proj4js-vs-PROJ parity and pack them for the browser.
import fs from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const proj4 = require("../docs/vendor/proj4-2.12.1.js");
const Engine = require("../docs/js/engine.js");
const src = JSON.parse(fs.readFileSync(new URL("../build/world_candidates.json", import.meta.url), "utf8"));
const TOL = Number(process.env.TOL_M || 0.05);
const geoByCode = Object.fromEntries(src.geo.map((g) => [g.code, g]));

const geo = src.geo.map((g) => ({
  c: g.code, n: g.name, d: g.datum, e: g.ell, a: g.a, f: g.rf, ar: g.area, b: g.bbox, tw: g.tw, acc: g.acc, k: g.kind,
  ba: g.best_any, en: g.ensemble ? 1 : 0, op: g.opc, opn: g.opn,
}));

const bad = [], proj = [], seenCode = new Set();
for (const p of src.proj) {
  if (seenCode.has(p.code)) continue;
  seenCode.add(p.code);
  let ok = false, d = null;
  try {
    const r = proj4("EPSG:4326", p.p4, p.ctr);
    d = Math.hypot(r[0] - p.ref[0], r[1] - p.ref[1]);
    ok = Number.isFinite(d) && d <= TOL;
  } catch (e) { d = String(e.message || e).slice(0, 60); }
  if (!ok) { bad.push({ code: p.code, name: p.name, d }); continue; }
  const base = geoByCode[p.base];
  const item = { c: p.code, n: p.name, b0: p.base, dn: base ? base.datum : undefined, m: p.method, ar: p.area, b: p.bbox, p: p.p4, ap: p.approx };
  Engine.localRect(item, proj4); // area of use as a rectangle in the CRS's own coordinates
  proj.push(item);
}
const write = (name, key, data) => fs.writeFileSync(new URL(`../docs/data/${name}`, import.meta.url), `window.__${key}__=${JSON.stringify(data)};\n`);
fs.mkdirSync(new URL("../docs/data/", import.meta.url), { recursive: true });
write("world-geo.js", "GEO", geo);
write("world-proj.js", "PROJ", proj);
fs.writeFileSync(new URL("../build/pack_report.json", import.meta.url), JSON.stringify({ geo: geo.length, proj: proj.length, dropped: bad }, null, 1));
let meta = {};
try { meta = JSON.parse(fs.readFileSync(new URL("../build/meta.json", import.meta.url), "utf8")); } catch (e) { /* optional */ }
const byMethod = {};
for (const p of proj) byMethod[p.m] = (byMethod[p.m] || 0) + 1;
const approx = proj.map((p) => p.ap).filter((v) => v != null).sort((a, b) => a - b);
write("world-meta.js", "META", { epsg: meta.epsg, epsg_date: meta.epsg_date, proj_ver: meta.proj, pyproj: meta.pyproj, geo: geo.length, proj: proj.length, dropped: bad.length, byMethod,
  approxOver1m: approx.filter((v) => v > 1).length, approxOver10m: approx.filter((v) => v > 10).length, tolM: TOL });
const kb = (f) => Math.round(fs.statSync(new URL(`../docs/data/${f}`, import.meta.url)).size / 1024);
console.log(`geo ${geo.length} (${kb("world-geo.js")} KB), proj ${proj.length} (${kb("world-proj.js")} KB), dropped by parity: ${bad.length}`);
if (bad.length) console.log("examples:", JSON.stringify(bad.slice(0, 6)));
