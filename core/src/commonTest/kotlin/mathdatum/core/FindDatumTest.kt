package mathdatum.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class FindDatumTest {
    private val moscow = Geodetic.ofDegrees(55.75, 37.62)

    // UTM 37N: север 6179118.15, восток 413380.72. Чертёж CAD (x = восток, y = север) в миллиметрах.
    private val boundsMm = SurfaceBounds(
        minX = 413_000_000.0, maxX = 413_800_000.0, minY = 6_178_800_000.0, maxY = 6_179_400_000.0,
    )

    @Test
    fun rightCrsIsTopWithAnchor() {
        val r = DatumFinder.find(boundsMm, Anchor(moscow), Catalog.demo())
        val top = r.first()
        assertEquals("demo:utm37", top.crs.id)
        assertTrue(top.swapXY)
        assertEquals(0.001, top.unitToMeters)
        assertEquals(MatchStatus.MATCH, top.status)
        assertEquals(Reliability.ANCHORED, top.reliability)
        val back = top.toGeoref().toWgs84(boundsMm.centerX, boundsMm.centerY)
        assertTrue(Geodesy.haversine(back, moscow) < 2_000.0)
    }

    @Test
    fun farAnchorGivesNoMatch() {
        val spb = Geodetic.ofDegrees(-33.9, 151.2)
        assertTrue(DatumFinder.find(boundsMm, Anchor(spb), Catalog.demo()).none { it.status == MatchStatus.MATCH })
    }

    @Test
    fun withoutAnchorResultIsMarkedIndirect() {
        val r = DatumFinder.find(boundsMm, null, Catalog.demo())
        assertTrue(r.isNotEmpty() && r.all { it.reliability == Reliability.INDIRECT })
    }

    @Test
    fun unboundLocalDrawingYieldsNothingReliable() {
        val local = SurfaceBounds(0.0, 1000.0, 0.0, 1000.0)
        val r = DatumFinder.find(local, Anchor(moscow), Catalog.demo())
        assertTrue(r.none { it.status == MatchStatus.MATCH })
    }
}
