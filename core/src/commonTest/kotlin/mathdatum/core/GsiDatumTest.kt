package mathdatum.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class GsiDatumTest {
    private val json = """{
      "azimuth": "North", "orientation": "NE", "country": "Россия",
      "csCode": "Московская_область_МСК_50_Зона2_МГГТ",
      "ellipsoidOriginal": {"paramA": 6378137.0, "param1f": 298.257223563},
      "ellipsoid": {"type": "Krassowsky_1940", "paramA": 6378245.0, "param1f": 298.3},
      "projection": {"type": "ru.gsisoft.common.model.cs.Projection.ProjectionTM",
        "longitudeCenter": 38.4833333333, "eastShift": 2250000.0, "northShift": -5712900.566},
      "parameters7": {"d_x": 118.754, "d_y": 61.782, "d_z": 93.237, "r_x": 2.40896, "r_y": 3.47502, "r_z": -1.29688, "k": -6.5177},
      "isPredefined": true }"""

    // центр чертежа trench.surface.txt: X — север, Y — восток, Z
    private val n = 459636.76671992237
    private val e = 2253496.337317594
    private val z = 117.58783505821475

    @Test
    fun importsCrsAndMatchesProjForBothDirections() {
        val crs = GsiDatumJson.decode(json)
        assertEquals("user:Московская_область_МСК_50_Зона2_МГГТ", crs.id)
        assertEquals(false, crs.firstAxisIsEast)
        assertEquals(false, crs.helmertDirectionConfirmed)
        // эталон PROJ 9.8.1 (конвейер tmerc⁻¹ → cart → helmert[±] → cart⁻¹ WGS84), см. tools/ и docs/PLAN.md
        val a = crs.withHelmertDirection(HelmertDirection.WGS84_TO_LOCAL).toWgs84(n, e, z)
        assertEquals(55.67563471085616, a.latDeg, 2e-9); assertEquals(38.53731642961868, a.lonDeg, 2e-9); assertEquals(117.70624559838325, a.h, 1e-4)
        val b = crs.withHelmertDirection(HelmertDirection.LOCAL_TO_WGS84).toWgs84(n, e, z)
        assertEquals(55.67530700435318, b.latDeg, 2e-9); assertEquals(38.54049380543484, b.lonDeg, 2e-9); assertEquals(337.1534363711253, b.h, 1e-4)
    }

    @Test
    fun directionsDifferByAboutTwoHundredMetres() {
        val crs = GsiDatumJson.decode(json)
        val at = crs.toWgs84(n, e, z)
        val d = crs.helmertAmbiguityMeters(at)
        assertTrue(d in 150.0..260.0, "ambiguity=$d")
    }

    @Test
    fun heightEvidencePicksWgs84ToLocalForUsersParameters() {
        val ev = assertNotNull(GsiDatumJson.decode(json).checkHelmertDirection(n, e, z))
        assertTrue(kotlin.math.abs(ev.dhIfWgs84ToLocal) < 1.0, "dhA=${ev.dhIfWgs84ToLocal}")
        assertTrue(ev.dhIfLocalToWgs84 > 150.0, "dhB=${ev.dhIfLocalToWgs84}")
        assertEquals(HelmertDirection.WGS84_TO_LOCAL, ev.suggested)
    }

    @Test
    fun heightEvidenceAgreesWithRealPulkovoParameters() {
        // EPSG: СК-42 → WGS84 (направление local→WGS84): 23.57, −140.95, −79.8; −0, −0.35, −0.79; −0.22 ppm
        val tm = TransverseMercator(Ellipsoid.KRASSOVSKY, 0.0, 39.0 * DEG, 1.0, 7_500_000.0, 0.0)
        val h = Helmert(23.57, -140.95, -79.8, 0.0, -0.35, -0.79, -0.22)
        val ok = CrsDef("sk42", "sk42", Ellipsoid.KRASSOVSKY, h, tm, helmertDirection = HelmertDirection.LOCAL_TO_WGS84)
        val (north, east, hh) = ok.fromWgs84(Geodetic.ofDegrees(55.7, 37.6, 120.0))
        val ev = assertNotNull(ok.checkHelmertDirection(north, east, hh))
        assertEquals(HelmertDirection.LOCAL_TO_WGS84, ev.suggested)
        assertTrue(kotlin.math.abs(ev.dhIfLocalToWgs84) < 10.0, "dh=${ev.dhIfLocalToWgs84}")
        assertTrue(kotlin.math.abs(ev.dhIfWgs84ToLocal) > 100.0)
        assertEquals(null, GsiDatumJson.decode(json.replace("\"parameters7\"", "\"x\"")).checkHelmertDirection(n, e, z))
    }

    @Test
    fun unsupportedInputsAreRejectedClearly() {
        assertFailsWith<Json.ParseException> { GsiDatumJson.decode(json.replace("ProjectionTM", "ProjectionLCC")) }
        assertFailsWith<Json.ParseException> { GsiDatumJson.decode(json.replace("\"azimuth\": \"North\"", "\"azimuth\": \"South\"")) }
        assertFailsWith<Json.ParseException> { GsiDatumJson.decode(json.replace("6378137.0", "6378388.0")) }
        assertFailsWith<Json.ParseException> { GsiDatumJson.decode("{}") }
        val en = GsiDatumJson.decode(json.replace("\"NE\"", "\"EN\""))
        assertEquals(true, en.firstAxisIsEast)
    }
}
