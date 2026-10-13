package mathdatum.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertIs

class GeorefJsonTest {
    private val moscow = Geodetic.ofDegrees(55.75, 37.62, 150.0)

    @Test
    fun crsGeorefRoundTrip() {
        val g = CrsGeoref(Catalog.sk42Gk(7), swapXY = true, unitToMeters = 0.001)
        val b = GeorefJson.decode(GeorefJson.encode(g))
        assertIs<CrsGeoref>(b)
        assertEquals(true, b.swapXY); assertEquals(0.001, b.unitToMeters)
        val s1 = g.fromWgs84(moscow); val s2 = b.fromWgs84(moscow)
        assertEquals(s1.x, s2.x, 1e-6); assertEquals(s1.y, s2.y, 1e-6); assertEquals(s1.z, s2.z, 1e-6)
    }

    @Test
    fun localGeorefRoundTrip() {
        val g = LocalizedGeoref(
            LocalPlane(55.7 * DEG, 37.6 * DEG), Similarity2D(0.866, 0.5, 1234.5, -987.6), HeightModel(1e-4, -2e-4, 0.5, 10.0, 20.0),
        )
        val b = GeorefJson.decode(GeorefJson.encode(g))
        assertIs<LocalizedGeoref>(b)
        val s1 = g.fromWgs84(moscow); val s2 = b.fromWgs84(moscow)
        assertEquals(s1.x, s2.x, 1e-9); assertEquals(s1.y, s2.y, 1e-9); assertEquals(s1.z, s2.z, 1e-9)
        val w1 = g.toWgs84(100.0, 200.0, 5.0); val w2 = b.toWgs84(100.0, 200.0, 5.0)
        assertEquals(w1.lat, w2.lat, 1e-15); assertEquals(w1.h, w2.h, 1e-9)
    }

    @Test
    fun badFilesGiveClearErrors() {
        assertFailsWith<Json.ParseException> { GeorefJson.decode("""{"format":9,"type":"crs"}""") }
        assertFailsWith<Json.ParseException> { GeorefJson.decode("""{"format":1,"type":"zzz"}""") }
        assertFailsWith<Json.ParseException> { GeorefJson.decode("не json") }
        val ok = GeorefJson.encode(CrsGeoref(Catalog.utm(37)))
        assertFailsWith<Json.ParseException> { GeorefJson.decode(ok.replace("\"unitToMeters\": 1.0", "\"unitToMeters\": 0.0")) }
    }
}
