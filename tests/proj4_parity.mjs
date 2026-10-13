// Browser engine (proj4js) must agree with PROJ (pyproj) on every system and test point.
import fs from "node:fs";
import vm from "node:vm";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const proj4 = require("../docs/vendor/proj4-2.12.1.js");
const ctx = { window: {} };
vm.runInNewContext(fs.readFileSync(new URL("../docs/data/ru.js", import.meta.url), "utf8"), ctx);
const sys = Object.fromEntries(ctx.window.__RU__.systems.map((s) => [s.id, s]));
const ref = JSON.parse(fs.readFileSync(new URL("./reference.json", import.meta.url), "utf8"));
const TOL = Number(process.env.TOL_M || 0.05);
let worst = 0, worstRow = null, bad = 0, rt = 0;
for (const r of ref) {
  const s = sys[r.id];
  if (!s) continue;
  const [e, n] = proj4("EPSG:4326", s.p, [r.lon, r.lat]);
  const d = Math.hypot(e - r.e, n - r.n);
  if (d > worst) { worst = d; worstRow = `${r.id} ${r.city}`; }
  if (d > TOL) bad++;
  const [lo, la] = proj4(s.p, "EPSG:4326", [e, n]);
  const back = Math.hypot((lo - r.lon) * 111319.49 * Math.cos((r.lat * Math.PI) / 180), (la - r.lat) * 111132.95);
  if (back > 0.02) rt++;
}
console.log(`proj4js vs PROJ: ${ref.length} points, worst ${worst.toFixed(4)} m (${worstRow}), over ${TOL} m: ${bad}, round-trip > 2 cm: ${rt}`);
process.exit(bad || rt ? 1 : 0);
