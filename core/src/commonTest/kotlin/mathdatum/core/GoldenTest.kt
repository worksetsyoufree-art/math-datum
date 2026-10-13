package mathdatum.core

import kotlin.math.abs
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * Эталоны сгенерированы PROJ 9.8.1 (pyproj 3.8.0), скрипт — tools/gen_golden.py.
 * Допуск 1e-4 м намеренно мягче фактического (≈1e-8 м) — на JS Double те же, но запас на libm.
 */
class GoldenTest {
    private val tol = 1e-4

    private class U(val lat: Double, val lon: Double, val north: Double, val east: Double)
    private class G(val lat: Double, val lon: Double, val h: Double, val north: Double, val east: Double, val hOut: Double)

    @Test
    fun utmMatchesProj() {
        val crs = Catalog.utm(37)
        listOf(
            U(55.75, 37.62, 6179118.146754007, 413380.7202778102),
            U(60.0, 30.3, 6683348.102614434, 15671.168680438423),
            U(0.0, 36.0, 0.0, 166021.44308054057),
            U(-33.9, 39.5, -3751180.769750892, 546228.17632192),
        ).forEach {
            val (n, e, _) = crs.fromWgs84(Geodetic.ofDegrees(it.lat, it.lon))
            assertEquals(it.north, n, tol, "north ${it.lat},${it.lon}")
            assertEquals(it.east, e, tol, "east ${it.lat},${it.lon}")
            val back = crs.toWgs84(it.north, it.east, 0.0)
            assertEquals(it.lat, back.latDeg, 1e-9)
            assertEquals(it.lon, back.lonDeg, 1e-9)
        }
    }

    /** Krassovsky + Helmert coordinate_frame (exact) + TM, CM 39°, x_0 = 7 500 000: PROJ pipeline из tools/gen_golden.py. */
    @Test
    fun helmertPipelineMatchesProj() {
        val crs = Catalog.sk42Gk(7)
        listOf(
            G(55.75, 37.62, 150.0, 6181700.449077682, 7413226.980507417, -65.37611489091069),
            G(60.0, 30.3, 10.0, 6686147.693097162, 7015342.929975245, -196.18850122578442),
            G(69.0, 33.0, 500.0, 7669316.29277795, 7260134.89930885, 292.95090953446925),
            G(55.0, 45.0, 0.0, 6113822.75731721, 7883621.232974407, -224.46367083955556),
        ).forEach {
            val (n, e, h) = crs.fromWgs84(Geodetic.ofDegrees(it.lat, it.lon, it.h))
            assertEquals(it.north, n, tol, "north ${it.lat},${it.lon}")
            assertEquals(it.east, e, tol, "east ${it.lat},${it.lon}")
            assertEquals(it.hOut, h, tol, "h ${it.lat},${it.lon}")
            val back = crs.toWgs84(n, e, h)
            assertEquals(it.lat, back.latDeg, 1e-10)
            assertEquals(it.lon, back.lonDeg, 1e-10)
            assertEquals(it.h, back.h, 1e-6)
        }
    }

    @Test
    fun helmertInverseIsExactNotNegatedParameters() {
        val h = Helmert(23.92, -141.27, -80.9, 0.0, -0.35, -0.82, -0.12)
        val p = Vec3(2_850_000.0, 2_190_000.0, 5_250_000.0)
        val round = h.inverse(h.forward(p))
        assertEquals(p.x, round.x, 1e-6); assertEquals(p.y, round.y, 1e-6); assertEquals(p.z, round.z, 1e-6)
        // отрицание параметров даёт заметную ошибку (регрессия на мм-уровневые различия)
        val neg = Helmert(-23.92, 141.27, 80.9, 0.0, 0.35, 0.82, 0.12).forward(h.forward(p))
        assertTrue(abs(neg.x - p.x) + abs(neg.y - p.y) + abs(neg.z - p.z) > 1e-6)
    }

    @Test
    fun cartRoundTripIncludingPolesAndAxis() {
        val e = Ellipsoid.WGS84
        listOf(Geodetic.ofDegrees(90.0, 0.0, 100.0), Geodetic.ofDegrees(-90.0, 0.0, 5.0), Geodetic.ofDegrees(89.9999, 120.0, 10.0),
            Geodetic.ofDegrees(0.0, -179.99, 0.0), Geodetic.ofDegrees(45.0, 90.0, 8000.0)).forEach {
            val b = Geodesy.fromCart(e, Geodesy.toCart(e, it))
            assertEquals(it.latDeg, b.latDeg, 1e-9, "lat")
            assertEquals(it.h, b.h, 1e-6, "h")
            if (abs(it.latDeg) < 89.0) assertEquals(it.lonDeg, b.lonDeg, 1e-9, "lon")
        }
    }

    @Test
    fun tmHandlesCentralMeridianBeyond180() {
        val tm = TransverseMercator(Ellipsoid.KRASSOVSKY, 0.0, 186.45 * DEG, 1.0, 0.0, 0.0)
        val p = Geodetic.ofDegrees(66.0, -173.0)
        val pr = tm.forward(p.lat, p.lon)
        val (lat, lon) = tm.inverse(pr.north, pr.east)
        assertEquals(p.latDeg, lat / DEG, 1e-9)
        assertEquals(p.lonDeg, lon / DEG, 1e-9)
        val tm90 = TransverseMercator(Ellipsoid.KRASSOVSKY, 0.0, 90.0 * DEG, 1.0, 0.0, 0.0)
        val q = tm90.forward(55.0 * DEG, 91.5 * DEG)
        val (lat2, lon2) = tm90.inverse(q.north, q.east)
        assertEquals(55.0, lat2 / DEG, 1e-9); assertEquals(91.5, lon2 / DEG, 1e-9)
    }
}
