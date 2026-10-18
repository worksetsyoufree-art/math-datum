package ru.mathdatum.localization

import kotlin.math.abs
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

/** Малоискажающая проекция (Ldp.kt) против Python-эталона mathdatum.ldp (LdpReferenceData.kt). */
class LdpTest {
    @Test
    fun tmScaleConvergenceAndHeightFactor() {
        for (c in TM_SCALE_CASES) {
            val e = Datums.ellipsoid(c.ellipsoid).ellipsoid
            val tm = TransverseMercator(e, 0.0, c.lon0)
            near(c.k, tm.scale(c.lat, c.lon), 1e-13, "k ${c.ellipsoid} ${c.lat} ${c.lon}")
            near(c.gamma, tm.convergence(c.lat, c.lon), 1e-11, "γ")
            near(c.r, Ldp.gaussRadius(e, c.lat), 1e-6, "R")
            near(c.hf, Ldp.heightFactor(e, c.lat, c.h), 1e-15, "R/(R+h)")
            // На осевом меридиане k = k0.
            near(1.0000784, TmProjection(e, c.lon0, 0.0, 1.0000784).scale(c.lat, c.lon0), 1e-13, "k0")
        }
    }

    private fun stats(what: String, e: DoubleArray, s: LdpStats) {
        assertEquals(e[0].toInt(), s.n, "$what n")
        near(e[1], s.minPpm, 1e-6, "$what min")
        near(e[2], s.maxPpm, 1e-6, "$what max")
        near(e[3], s.meanPpm, 1e-6, "$what mean")
        near(e[4], s.rmsPpm, 1e-6, "$what rms")
        near(e[5], s.maxAbsPpm, 1e-6, "$what maxAbs")
        near(e[6], s.shareInTolerance, 1e-9, "$what share")
    }

    @Test
    fun designMatchesPython() {
        for (c in LDP_CASES) {
            val r = Ldp.design(
                LdpContour(c.kind, c.vertices, c.zType), LdpHeights(constant = c.height, dem = c.dem), c.datum, c.tolerance,
                c.criterion, c.step, c.options,
            )
            val p = r.projection
            val w = c.name
            near(c.projection[0], p.lat0, 1e-9, "$w lat0")
            near(c.projection[1], p.lon0, 1e-7, "$w lon0")
            near(c.projection[2], p.k0, 1e-11, "$w k0")
            near(c.projection[3], p.x0, 0.0, "$w x0")
            near(c.projection[4], p.y0, 0.0, "$w y0")
            near(c.projection[5], r.step, 1e-9, "$w step")
            stats("$w LDP", c.stats, r.stats)
            assertEquals(c.measure, r.stats.measure, "$w measure")
            stats("$w ГК", c.gk, r.gk.stats)
            assertEquals(c.gkZones, r.gk.zones, "$w зоны ГК")
            stats("$w UTM", c.utm, r.utm.stats)
            assertEquals(c.utmZones, r.utm.zones, "$w зоны UTM")
            assertEquals(c.zones.size, r.zones.size, "$w число зон")
            c.zones.forEachIndexed { i, z ->
                val rz = r.zones[i]
                near(z[0], rz.start, 1e-6, "$w зона $i начало")
                near(z[1], rz.end, 1e-6, "$w зона $i конец")
                near(z[2], rz.projection.lat0, 1e-9, "$w зона $i lat0")
                near(z[3], rz.projection.lon0, 1e-7, "$w зона $i lon0")
                near(z[4], rz.projection.k0, 1e-11, "$w зона $i k0")
                near(z[5], rz.projection.x0, 0.0, "$w зона $i x0")
                near(z[6], rz.projection.y0, 0.0, "$w зона $i y0")
                stats("$w зона $i", z.copyOfRange(7, 14), rz.stats)
            }
            val bnd = r.zones.drop(1).flatMap { it.boundary!! }
            assertEquals(c.boundary.size, bnd.size, "$w границы")
            c.boundary.forEachIndexed { i, b ->
                near(b[0], bnd[i].first, 1e-10, "$w граница $i B")
                near(b[1], bnd[i].second, 1e-10, "$w граница $i L")
            }
            assertEquals(c.warnings, r.warnings.size, "$w замечаний: ${r.warnings}")
            val m = r.distortionMap(24)
            assertEquals(c.mapRows, m.rows, "$w строк карты")
            assertEquals(c.mapCols, m.cols, "$w столбцов карты")
            for (e in c.map) {
                val q = e[0].toInt()
                near(e[1], m.lat[q], 1e-10, "$w карта $q B")
                near(e[2], m.lon[q], 1e-10, "$w карта $q L")
                near(e[3], m.h[q], 1e-7, "$w карта $q h")
                assertEquals(e[4].toInt(), m.zone[q], "$w карта $q зона")
                near(e[5], m.ppm[q], 1e-6, "$w карта $q ppm")
                near(e[6], m.dist[q], 1e-6, "$w карта $q dist")
            }
        }
    }

    @Test
    fun loadProjectionAndJson() {
        assertFailsWith<LdpException> { Ldp.loadProjection(PY_LDP_JSON) }
        val z2 = Ldp.loadProjection(PY_LDP_JSON, zone = 2)
        val c = LDP_CASES.first { it.name == "route_ew_150km" }
        near(c.zones[1][3], z2.lon0, 1e-7, "lon0 зоны 2")
        near(c.zones[1][4], z2.k0, 1e-11, "k0 зоны 2")
        assertEquals("GSK-2011", z2.datum)
        val bare = Ldp.loadProjection("""{"type": "tmerc", "lat0": 55.0, "lon0": 38.0, "k0": 1.00002, "future": 1}""")
        assertEquals(LdpProjection("GSK-2011", 55.0, 38.0, 1.00002), bare)
        assertFailsWith<LdpException> { Ldp.loadProjection("""{"type": "omerc", "lat0": 55.0, "lon0": 38.0, "alpha": 10}""") }
        // JSON Kotlin читается обратно (тот же формат).
        val r = Ldp.design(LdpContour(c.kind, c.vertices), LdpHeights(constant = c.height), options = c.options)
        val back = Ldp.loadProjection(r.toJson(), zone = 1)
        assertEquals(r.zones[0].projection, back)
        assertTrue("+proj=tmerc" in back.proj && "+a=6378136.5 +rf=298.2564151" in back.proj)
    }

    @Test
    fun localizeInLdp() {
        val sq = LDP_CASES.first { it.name == "square_500m" }
        val p = LdpProjection("GSK-2011", sq.projection[0], sq.projection[1], sq.projection[2], sq.projection[3], sq.projection[4])
        val d = localizeIn(p, PY_LDP_PAIRS, gnssDatum = "GSK-2011")
        checkParams("LDP", d, PY_LDP_LOCALIZE)
        near(PY_LDP_LOCALIZE_K0[0], d.k0, 0.0, "k0")
        near(PY_LDP_LOCALIZE_K0[3], d.scalePpm, 1e-4, "масштаб, ppm")
        assertTrue(abs(d.scalePpm) < 1.0, "масштаб подобия ≈ 1: ${d.scalePpm} ppm")
        val plain = localize(PY_LDP_PAIRS, gnssDatum = "GSK-2011")
        assertTrue(plain.scalePpm > 70, "без LDP масштаб ≈ +78 ppm: ${plain.scalePpm}")
        PY_LDP_CHECK.forEachIndexed { i, q ->
            val l = d.toLocal(WgsPoint(q[0], q[1], q[2]))
            near(PY_LDP_CHECK_LOCAL[i][0], l.x, 1e-5, "x")
            near(PY_LDP_CHECK_LOCAL[i][1], l.y, 1e-5, "y")
            near(PY_LDP_CHECK_LOCAL[i][2], l.height, 1e-6, "H")
            val w = d.toWgs(l)
            near(q[0], w.lat, 1e-11, "B туда-обратно")
            near(q[1], w.lon, 1e-11, "L туда-обратно")
        }
        // Датум из Python с k0, x0, y0 и обратно в JSON.
        val py = LocalizationDatum.fromJson(PY_LDP_DATUM_JSON)
        near(d.k0, py.k0, 0.0, "k0 из JSON")
        val l = py.toLocal(WgsPoint(PY_LDP_CHECK[0][0], PY_LDP_CHECK[0][1], PY_LDP_CHECK[0][2]))
        near(PY_LDP_CHECK_LOCAL[0][0], l.x, 1e-5, "x из JSON")
        val again = LocalizationDatum.fromJson(py.toJson())
        assertEquals(py.y0, again.y0)
        assertTrue("+k=1.000078" in d.projection && "+x_0=100000" in d.projection, d.projection)
        assertTrue("+k=1 +x_0=0 +y_0=0" in plain.projection)
    }

    @Test
    fun csvContourAndErrors() {
        val c = LdpContour.parseCsv("name;B;L;h\nA;55;38;100\nB;55.1;38;110\nC;55.1;38.2;120\nA;55;38;100\n")
        assertEquals("polygon", c.kind)
        assertEquals(3, c.vertices.size)
        assertEquals("ellipsoidal", c.zType)
        val t = LdpContour.parseCsv("name;B;L;H\nA;55;38;100\nB;55.1;38.1;110\n")
        assertEquals("polyline", t.kind)
        assertEquals("normal", t.zType)
        assertFailsWith<LdpException> { Ldp.design(LdpContour.parseCsv("name;B;L\nA;55;38\nB;55.1;38.1\n"), LdpHeights()) }
        assertFailsWith<LdpException> { LdpContour("polygon", listOf(LdpVertex(55.0, 38.0), LdpVertex(55.1, 38.0))) }
        assertFailsWith<LdpException> { Ldp.design(t, LdpHeights(constant = 0.0), tolerance = 0.0) }
    }
}
