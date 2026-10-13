package mathdatum.core

import kotlin.test.Test
import kotlin.test.assertTrue

/** Метрики поиска СК на синтетике: истина — случайная СК каталога, X/Y и единицы, anchor в ~1 км от центра. */
class FindDatumMetricsTest {
    private class Lcg(var s: Long) {
        fun next(): Double { s = (s * 6364136223846793005L + 1442695040888963407L); return ((s ushr 11).toDouble() / (1L shl 53)) }
        fun range(a: Double, b: Double) = a + (b - a) * next()
    }

    private class Case(val crs: CrsDef, val swap: Boolean, val unit: Double, val bounds: SurfaceBounds, val center: Geodetic)

    private fun cases(n: Int, seed: Long): List<Case> {
        val rnd = Lcg(seed)
        val cat = Catalog.demo().entries
        val units = listOf(1.0, 0.001, 0.01)
        return List(n) {
            val crs = cat[(rnd.next() * cat.size).toInt()]
            val lon = crs.tm.lon0 / DEG + rnd.range(-2.5, 2.5)
            val lat = rnd.range(45.0, 68.0)
            val center = Geodetic.ofDegrees(lat, lon)
            val (north, east, _) = crs.fromWgs84(center)
            val swap = rnd.next() < 0.5
            val unit = units[(rnd.next() * units.size).toInt()]
            val half = rnd.range(100.0, 2000.0)
            val cx = (if (swap) east else north) / unit
            val cy = (if (swap) north else east) / unit
            val h = half / unit
            Case(crs, swap, unit, SurfaceBounds(cx - h, cx + h, cy - h, cy + h), center)
        }
    }

    private fun anchorNear(c: Geodetic, rnd: Lcg) =
        Anchor(Geodetic(c.lat + rnd.range(-0.005, 0.005) * DEG, c.lon + rnd.range(-0.008, 0.008) * DEG, 0.0))

    private fun isTruth(c: Candidate, t: Case) = c.crs.id == t.crs.id && c.swapXY == t.swap && c.unitToMeters == t.unit

    @Test
    fun trueCandidateIsTopWithAnchor() {
        val rnd = Lcg(99)
        val set = cases(60, 1234)
        var top1 = 0; var top3 = 0
        for (t in set) {
            val r = DatumFinder.find(t.bounds, anchorNear(t.center, rnd), Catalog.demo())
            if (r.firstOrNull()?.let { isTruth(it, t) } == true) top1++
            if (r.take(3).any { isTruth(it, t) }) top3++
        }
        assertTrue(top3 == set.size, "top3=$top3/${set.size} top1=$top1")
        assertTrue(top1 >= set.size * 0.9, "top1=$top1/${set.size}")
    }

    @Test
    fun withoutAnchorTruthIsPresentButNeverClaimedAsMatch() {
        val set = cases(40, 777)
        var present = 0
        for (t in set) {
            val r = DatumFinder.find(t.bounds, null, Catalog.demo(), FindDatumOptions(topN = 12))
            if (r.any { isTruth(it, t) }) present++
            assertTrue(r.all { it.reliability == Reliability.INDIRECT && it.status != MatchStatus.MATCH })
        }
        assertTrue(present == set.size, "present=$present/${set.size}")
    }

}
