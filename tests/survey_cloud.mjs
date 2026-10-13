// Same survey check with the browser engine (proj4js) on the shipped data.
import fs from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const proj4 = require("../docs/vendor/proj4-2.12.1.js");
const L = fs.readFileSync(new URL("./fixtures/surface_m11_ring.txt", import.meta.url), "utf8").split("\n");
const n = parseInt(L[2]);
const pts = L.slice(4, 4 + n).map((l) => l.trim().split(/\s+/).map(Number));
const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
const [X, Y, Z] = [2772743.0666661696, 1631247.7534042243, 5488981.23905303];
const a = 6378137, f = 1 / 298.257223563, e2 = f * (2 - f);
let lon = Math.atan2(Y, X), p = Math.hypot(X, Y), lat = Math.atan2(Z, p * (1 - e2));
for (let i = 0; i < 10; i++) { const N = a / Math.sqrt(1 - e2 * Math.sin(lat) ** 2), h = p / Math.cos(lat) - N; lat = Math.atan2(Z, p * (1 - e2 * N / (N + h))); }
lat *= 180 / Math.PI; lon *= 180 / Math.PI;
const data = [...JSON.parse(fs.readFileSync(new URL("../data/systems.json", import.meta.url))), ...JSON.parse(fs.readFileSync(new URL("../data/systems_unverified.json", import.meta.url)))];
const s = data.find((o) => o.names.includes("МСК_78(5)"));
const [e, nn] = proj4("EPSG:4326", s.proj4, [lon, lat]);
const inside = nn >= Math.min(...xs) && nn <= Math.max(...xs) && e >= Math.min(...ys) && e <= Math.max(...ys);
console.log(`proj4js ${s.id}: X=${nn.toFixed(3)} Y=${e.toFixed(3)} inside survey surface: ${inside}`);
process.exit(inside ? 0 : 1);
