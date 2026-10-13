package mathdatum.core

import kotlin.math.abs
import kotlin.test.Test
import kotlin.test.assertTrue

/** Сверка с PROJ по сетке СК и точек (B2 плана). Допуск 0,1 мм по плану и высоте. */
class GoldenGridTest {
    private fun crsOf(c: GridCase): CrsDef {
        val ell = Ellipsoid.byId(c.ellipsoid)!!
        val h = c.helmert?.let { Helmert(it[0], it[1], it[2], it[3], it[4], it[5], it[6]) }
        val p = c.params
        val proj: MapProjection = when (c.method) {
            MapProjection.TM -> TransverseMercator(ell, p[0] * DEG, p[1] * DEG, p[2], p[3], p[4])
            MapProjection.TM_SOUTH_ORIENTED -> TransverseMercatorSouthOriented(TransverseMercator(ell, p[0] * DEG, p[1] * DEG, p[2], p[3], p[4]))
            MapProjection.LCC_1SP -> LambertConformalConic.oneParallel(ell, p[0] * DEG, p[1] * DEG, p[2], p[3], p[4])
            MapProjection.LCC_2SP -> LambertConformalConic.twoParallel(ell, p[0] * DEG, p[1] * DEG, p[2] * DEG, p[3] * DEG, p[4], p[5])
            else -> error("method ${c.method}")
        }
        return CrsDef(c.id, c.id, ell, h, proj)
    }

    @Test
    fun forwardMatchesProjWithin0_1mm() {
        var worst = 0.0
        var worstAt = ""
        for (c in GRID_CASES) {
            val crs = crsOf(c)
            for (p in c.points) {
                val (n, e, h) = crs.fromWgs84(Geodetic.ofDegrees(p[0], p[1], p[2]))
                val d = maxOf(abs(n - p[3]), abs(e - p[4]), abs(h - p[5]))
                if (d > worst) { worst = d; worstAt = "${c.id} lat=${p[0]} lon=${p[1]}" }
            }
        }
        assertTrue(worst <= 1e-4, "worst=$worst m at $worstAt")
    }

    @Test
    fun inverseReturnsInputWithin0_1mm() {
        var worst = 0.0
        var worstAt = ""
        for (c in GRID_CASES) {
            val crs = crsOf(c)
            for (p in c.points) {
                val g = crs.toWgs84(p[3], p[4], p[5])
                val dLat = abs(g.lat - p[0] * DEG) * 6.4e6
                val dLon = abs(Geodesy.normLon(g.lon - p[1] * DEG)) * 6.4e6 * kotlin.math.cos(p[0] * DEG)
                val d = maxOf(dLat, dLon, abs(g.h - p[2]))
                if (d > worst) { worst = d; worstAt = "${c.id} lat=${p[0]} lon=${p[1]}" }
            }
        }
        assertTrue(worst <= 1e-4, "worst=$worst m at $worstAt")
    }
}
