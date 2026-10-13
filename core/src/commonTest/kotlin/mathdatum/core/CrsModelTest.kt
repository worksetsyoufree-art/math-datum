package mathdatum.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertTrue

class CrsModelTest {
    private val h = Helmert(118.754, 61.782, 93.237, 2.40896, 3.47502, -1.29688, -6.5177)
    private val tm = TransverseMercator(Ellipsoid.KRASSOVSKY, 0.0, 38.4833333333 * DEG, 1.0, 2_250_000.0, -5_712_900.566)
    private val p = Geodetic.ofDegrees(55.69, 38.60, 150.0)

    private fun crs(dir: HelmertDirection) = CrsDef("t", "t", Ellipsoid.KRASSOVSKY, h, tm, helmertDirection = dir)

    @Test
    fun bothDirectionsRoundTripAndDiffer() {
        for (d in HelmertDirection.entries) {
            val c = crs(d)
            val (n, e, hh) = c.fromWgs84(p)
            val b = c.toWgs84(n, e, hh)
            assertEquals(p.lat, b.lat, 1e-13); assertEquals(p.lon, b.lon, 1e-13); assertEquals(p.h, b.h, 1e-6)
        }
        val a = crs(HelmertDirection.WGS84_TO_LOCAL).fromWgs84(p)
        val b = crs(HelmertDirection.LOCAL_TO_WGS84).fromWgs84(p)
        assertTrue(kotlin.math.hypot(a.first - b.first, a.second - b.second) > 100.0)
    }

    @Test
    fun localToWgsAppliesParametersForwardToLocalCoordinates() {
        // LOCAL_TO_WGS84: параметры переводят местные декартовы в WGS84 напрямую
        val c = crs(HelmertDirection.LOCAL_TO_WGS84)
        val (lat, lon) = tm.inverse(459_636.0, 2_253_500.0)
        val local = Geodesy.toCart(Ellipsoid.KRASSOVSKY, Geodetic(lat, lon, 130.0))
        val expected = Geodesy.fromCart(Ellipsoid.WGS84, h.forward(local))
        val got = c.toWgs84(459_636.0, 2_253_500.0, 130.0)
        assertEquals(expected.lat, got.lat, 1e-14); assertEquals(expected.h, got.h, 1e-6)
    }

    @Test
    fun ambiguityIsReportedInMeters() {
        val d = crs(HelmertDirection.WGS84_TO_LOCAL).helmertAmbiguityMeters(p)
        assertTrue(d in 100.0..400.0, "ambiguity=$d")
        assertEquals(0.0, CrsDef("u", "u", Ellipsoid.WGS84, null, tm).helmertAmbiguityMeters(p))
        assertEquals(d, crs(HelmertDirection.LOCAL_TO_WGS84).helmertAmbiguityMeters(p), 1e-6)
    }

    @Test
    fun jsonV2KeepsProjectionsAxesUnitsDirection() {
        val lcc2 = LambertConformalConic.twoParallel(Ellipsoid.GRS80, 46.5 * DEG, 3.0 * DEG, 49.0 * DEG, 44.0 * DEG, 700_000.0, 6_600_000.0)
        val lcc1 = LambertConformalConic.oneParallel(Ellipsoid.BESSEL, 49.5 * DEG, 2.3 * DEG, 0.99987734, 600_000.0, 200_000.0)
        val tms = TransverseMercatorSouthOriented(TransverseMercator(Ellipsoid.WGS84, 0.0, 19.0 * DEG, 1.0, 0.0, 0.0))
        val usft = 1200.0 / 3937.0
        val src = Catalog(listOf(
            CrsDef("a", "a", Ellipsoid.GRS80, null, lcc2, bounds = GeoBounds(41.0, 51.0, -5.0, 10.0), epsg = 2154, firstAxisIsEast = true),
            CrsDef("b", "b", Ellipsoid.BESSEL, h, lcc1, helmertDirection = HelmertDirection.LOCAL_TO_WGS84, helmertDirectionConfirmed = false),
            CrsDef("c", "c", Ellipsoid.WGS84, null, tms, unitToMeters = usft, firstAxisIsEast = true),
            CrsDef("d", "d", Ellipsoid.KRASSOVSKY, h, tm),
        ))
        val back = CatalogJson.decode(CatalogJson.encode(src))
        assertEquals(listOf("a", "b", "c", "d"), back.entries.map { it.id })
        assertIs<LambertConformalConic>(back.entries[0].projection)
        assertIs<TransverseMercatorSouthOriented>(back.entries[2].projection)
        assertEquals(usft, back.entries[2].unitToMeters)
        assertEquals(true, back.entries[0].firstAxisIsEast)
        assertEquals(HelmertDirection.LOCAL_TO_WGS84, back.entries[1].helmertDirection)
        assertEquals(false, back.entries[1].helmertDirectionConfirmed)
        for ((s, d) in src.entries.zip(back.entries)) {
            val q = Geodetic.ofDegrees(if (s.id == "c") -30.0 else 47.0, if (s.id == "c") 19.5 else 3.5, 100.0)
            val x = s.fromWgs84(q); val y = d.fromWgs84(q)
            assertEquals(x.first, y.first, 1e-6, s.id); assertEquals(x.second, y.second, 1e-6, s.id)
        }
    }

    @Test
    fun v1CatalogsAndSharedTablesStillLoad() {
        val v1 = """{"format":1,"entries":[{"id":"x","name":"x","ellipsoid":"WGS84","helmert":null,
            "tm":{"lat0":0,"lon0":39,"k0":0.9996,"x0":500000,"y0":0}}]}"""
        assertIs<TransverseMercator>(CatalogJson.decode(v1).entries[0].projection)
        val v2 = """{"format":2,"ellipsoids":{"E1":{"a":6378245,"invF":298.3,"name":"k"}},
            "helmerts":{"H1":{"t":[1,2,3],"r":[0,0,0],"ppm":0,"direction":"local_to_wgs84"}},
            "entries":[{"id":"y","name":"y","ellipsoid":"E1","helmert":"H1",
            "projection":{"method":9807,"lat0":0,"lon0":39,"k0":1,"x0":0,"y0":0}},
            {"id":"z","name":"z","ellipsoid":"E1","helmert":"H1","axes":"EN","unit":0.3048,
            "projection":{"method":9807,"lat0":0,"lon0":39,"k0":1,"x0":0,"y0":0}}]}"""
        val c = CatalogJson.decode(v2)
        assertEquals(HelmertDirection.LOCAL_TO_WGS84, c.entries[0].helmertDirection)
        assertEquals(6378245.0, c.entries[0].ellipsoid.a)
        val g = CrsGeoref.native(c.entries[1])
        assertEquals(true, g.swapXY); assertEquals(0.3048, g.unitToMeters)
    }
}
