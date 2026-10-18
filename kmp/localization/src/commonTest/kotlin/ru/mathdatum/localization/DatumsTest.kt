package ru.mathdatum.localization

import kotlin.math.abs
import kotlin.math.max
import kotlin.math.sqrt
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

/** Пересчёты между системами — сверка с Python-эталоном (DatumReferenceData.kt, tools/gen_kotlin_reference.py). */
class DatumsTest {

    private fun near(expected: Double, actual: Double, tol: Double, what: String) =
        assertTrue(abs(expected - actual) <= tol, "$what: ожидалось $expected, получено $actual (допуск $tol)")

    private fun dist(a: Xyz, x: Double, y: Double, z: Double) = max(abs(a.x - x), max(abs(a.y - y), abs(a.z - z)))

    @Test
    fun blhXyzMatchesPython() {
        for (c in BLH_XYZ_CASES) {
            val e = Datums.ellipsoid(c.ellipsoid).ellipsoid
            val x = Datums.blhToXyz(GeodeticPoint(c.lat, c.lon, c.h), e)
            assertTrue(dist(x, c.x, c.y, c.z) < 1e-6, "${c.ellipsoid} ${c.lat} $x")
            val b = Datums.xyzToBlh(Xyz(c.x, c.y, c.z), e)
            near(c.lat, b.lat, 1e-11, "B")
            near(c.h, b.h, 1e-6, "h")
            if (abs(c.lat) < 89.99) near(0.0, ((b.lon - c.lon + 540) % 360) - 180, 1e-11, "L")
        }
    }

    @Test
    fun transformationsMatchPython() {
        assertEquals(56 * 3, TRANSFORM_CASES.size)
        for (c in TRANSFORM_CASES) {
            assertEquals(c.steps, Datums.findPath(c.from, c.to).size, "${c.from} → ${c.to}")
            val r = Datums.transformXyz(Xyz(c.x, c.y, c.z), c.from, c.to)
            assertTrue(dist(r, c.ex, c.ey, c.ez) < 1e-6, "${c.from} → ${c.to}: $r")
            // Туда-обратно: точное обращение формулы ГОСТ.
            val back = Datums.transformXyz(r, c.to, c.from)
            assertTrue(dist(back, c.x, c.y, c.z) < 1e-8, "${c.from} ↔ ${c.to}: $back")
        }
    }

    @Test
    fun gostControlExample() {
        val (x0, v, x1, x2, x3) = GOST_EXAMPLE
        val p = Xyz(x0[0], x0[1], x0[2])
        val vel = Xyz(v[0], v[1], v[2])
        assertTrue(dist(Datums.propagateEpoch(p, vel, 2005.0, 2010.0), x1[0], x1[1], x1[2]) < 1e-6, "шаг 1")
        val s2 = Datums.transformXyz(p, "ITRF-2008", "PZ-90.11", epoch = 2005.0, velocity = vel)
        assertTrue(dist(s2, x2[0], x2[1], x2[2]) < 5e-5, "шаг 2: $s2")
        val s3 = Datums.transformXyz(p, "ITRF-2008", "PZ-90.11", epoch = 2005.0, velocity = vel, targetEpoch = 2013.9)
        assertTrue(dist(s3, x3[0], x3[1], x3[2]) < 5e-4, "шаг 3: $s3")
        val back = Datums.transformXyz(s3, "PZ-90.11", "ITRF-2008", epoch = 2013.9, velocity = vel, targetEpoch = 2005.0)
        assertTrue(dist(back, p.x, p.y, p.z) < 1e-8)
        assertFailsWith<IllegalArgumentException> { Datums.transformXyz(p, "ITRF-2008", "PZ-90.11", velocity = vel) }
    }

    @Test
    fun pathsAndLookup() {
        assertEquals("SK-42", Datums.system("ск-42").id)
        assertEquals("PZ-90.11", Datums.system("ПЗ-90.11").id)
        assertEquals("WGS-84", Datums.system("WGS-84 (G1150)").id)
        assertEquals("ITRF-2008", Datums.system("ITRF2008").id)
        assertFailsWith<IllegalArgumentException> { Datums.system("SK-63") }
        val p = Datums.findPath("SK-42", "WGS-84")
        assertEquals(listOf("SK-42" to "PZ-90.11", "PZ-90.11" to "WGS-84"), p.map { it.from to it.to })
        assertEquals("СК-42 → ПЗ-90.11 → WGS-84 (G1150) (прил. А.1; Г.1, обратный)", Datums.describePath(p))
        assertEquals(emptyList(), Datums.findPath("PZ-90.11", "ПЗ-90.11"))
        // СК-95: ωy = +0.00354″ (композиция ГОСТ Р 51794-2008 и прил. Б.1).
        assertEquals(0.00354, Datums.TRANSFORMATIONS.single { it.from == "SK-95" }.wy)
    }

    @Test
    fun gaussKrugerMatchesPython() {
        assertEquals(listOf(1, 1, 2, 7, 7, 30, 31, 32, 59), listOf(0.0, 5.999, 6.0, 37.6, 39.0, 179.9, 180.0, 190.0, -10.0).map { GaussKruger.zone(it) })
        for (c in GK_CASES) {
            val e = Datums.ellipsoid(c.ellipsoid).ellipsoid
            val zone = if (c.zone == 0) null else c.zone
            val p = GaussKruger.forward(c.lat, c.lon, e, zone)
            near(c.x, p.x, 1e-6, "ГК x ${c.lat} ${c.lon}")
            near(c.y, p.y, 1e-6, "ГК y ${c.lat} ${c.lon}")
            val (lat, lon) = GaussKruger.inverse(c.x, c.y, e, zone)
            near(c.lat, lat, 1e-10, "ГК B")
            near(c.lon, lon, 1e-10, "ГК L")
        }
        assertFailsWith<IllegalArgumentException> { GaussKruger.inverse(6.17e6, 7.4e6, Ellipsoid.KRASSOVSKY, zone = 8) }
        assertFailsWith<IllegalArgumentException> { GaussKruger.projection(61, Ellipsoid.KRASSOVSKY) }
        for (c in TM_PROJ_CASES) {
            val tm = TmProjection(Datums.ellipsoid(c.ellipsoid).ellipsoid, c.lon0, c.lat0, c.k0, c.x0, c.y0)
            val p = tm.forward(c.lat, c.lon)
            near(c.x, p.x, 1e-6, "ТМ x")
            near(c.y, p.y, 1e-6, "ТМ y")
            val (lat, lon) = tm.inverse(c.x, c.y)
            near(c.lat, lat, 1e-10, "ТМ B")
            near(c.lon, lon, 1e-10, "ТМ L")
        }
    }

    @Test
    fun csvColumns() {
        val pts = Csv.parseColumns("name;X;Y;Z\nA;1,5;2;3\n;4;5;6\n", listOf("X", "Y", "Z"))
        assertEquals(listOf("A", "P2"), pts.map { it.first })
        assertEquals(listOf(1.5, 2.0, 3.0), pts[0].second.toList())
        assertEquals("name;B;L\nA;1.50;2.000\n", Csv.formatColumns(listOf("A" to doubleArrayOf(1.5, 2.0)), listOf("B", "L"), listOf(2, 3)))
        assertFailsWith<IllegalArgumentException> { Csv.parseColumns("name;X\nA;1\n", listOf("X", "Y")) }
    }

    @Test
    fun regionsHelmert7p() {
        assertEquals(83, REGION_HELMERT.size)
        val krass = Ellipsoid.KRASSOVSKY
        for (r in REGION_HELMERT) {
            var ss = 0.0
            r.rows.forEachIndexed { i, row ->
                val src = Datums.blhToXyz(GeodeticPoint(row[0], row[1], row[2]), krass)
                assertTrue(dist(src, row[3], row[4], row[5]) < 2e-4, "${r.iso} BLH → XYZ")
                val pred = Datums.transformXyz(Xyz(row[3], row[4], row[5]), "SK-42", "PZ-90.11")
                assertTrue(dist(pred, row[9], row[10], row[11]) < 1e-6, "${r.iso} = Python")
                if (i < 5) {
                    assertTrue(dist(pred, row[6], row[7], row[8]) < 1e-4, "${r.iso} exact")
                } else {
                    ss += (row[6] - pred.x) * (row[6] - pred.x) + (row[7] - pred.y) * (row[7] - pred.y) + (row[8] - pred.z) * (row[8] - pred.z)
                }
            }
            // Шум 2 см на координату (по 5 точкам из 15 — грубая проверка порядка).
            assertTrue(sqrt(ss / 15) in 0.005..0.05, "${r.iso} noisy rms ${sqrt(ss / 15)}")
        }
    }

    @Test
    fun localizationWithGnssDatum() {
        for (c in GNSS_DATUM_CASES) {
            val d = localize(c.pairs, gnssDatum = c.system)
            assertEquals(c.system, d.gnssDatum)
            assertEquals(c.ellipsoid, d.ellipsoid)
            near(c.expected[4], d.a, 1e-10, "${c.iso} a")
            near(c.expected[5], d.b, 1e-10, "${c.iso} b")
            near(c.expected[6], d.tx, 1e-6, "${c.iso} tx")
            near(c.expected[8], d.c0, 1e-6, "${c.iso} c0")
            c.check.forEachIndexed { i, p ->
                val l = d.toLocal(WgsPoint(p[0], p[1], p[2]), datum = "PZ-90.11")
                near(c.local[i][0], l.x, 1e-4, "${c.iso} x")
                near(c.local[i][1], l.y, 1e-4, "${c.iso} y")
                near(c.local[i][2], l.height, 1e-4, "${c.iso} H")
                val w = d.toWgs(LocalPoint(c.local[i][0], c.local[i][1], c.local[i][2]), datum = "WGS-84")
                near(c.back[i][0], w.lat, 2e-9, "${c.iso} B")
                near(c.back[i][1], w.lon, 2e-9, "${c.iso} L")
                near(c.back[i][2], w.h, 1e-4, "${c.iso} h")
            }
            assertTrue("ГНСС:" in d.report())
        }
        // По умолчанию — WGS-84, как раньше; датум из Python с gnss_datum читается.
        val def = localize(REGIONS.first().pairs)
        assertEquals("WGS-84", def.gnssDatum)
        assertEquals("+ellps=WGS84", def.ellipsoid)
        assertTrue("ГНСС:" !in def.report())
        val py = LocalizationDatum.fromJson(PY_PZ_DATUM_JSON)
        assertEquals("PZ-90.11", py.gnssDatum)
        near(PY_PZ_DATUM_PARAMS[6], py.tx, 1e-9, "tx")
        assertEquals("\"gnss_datum\": \"WGS-84\"" in def.toJson(), true)
        // Старый JSON без gnss_datum на WGS-84: система — WGS-84, пересчёт из ПЗ-90.11 работает.
        val old = LocalizationDatum.fromJson(PY_DATUM_JSON.replace("\"gnss_datum\": \"WGS-84\",", ""))
        assertEquals(null, old.gnssDatum)
        assertEquals("WGS-84", old.gnssSystem)
        val w = WgsPoint(55.07, 39.3, 200.0)
        val pz = Datums.transformBlh(GeodeticPoint(w.lat, w.lon, w.h), "WGS-84", "PZ-90.11")
        val a = old.toLocal(w)
        val b = old.toLocal(WgsPoint(pz.lat, pz.lon, pz.h), datum = "PZ-90.11")
        near(a.x, b.x, 1e-6, "x"); near(a.y, b.y, 1e-6, "y"); near(a.height, b.height, 1e-6, "H")
        val k = LocalizationDatum.fromJson(PY_DATUM_JSON.replace("\"gnss_datum\": \"WGS-84\",", "").replace("+ellps=WGS84", "+ellps=krass"))
        assertEquals(null, k.gnssSystem)
        assertFailsWith<IllegalArgumentException> { k.toLocal(w, datum = "WGS-84") }
    }
}
