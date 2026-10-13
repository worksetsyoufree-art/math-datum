package mathdatum.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue

class CatalogJsonTest {
    @Test
    fun jsonRoundTrip() {
        val v = linkedMapOf("a" to 1.5, "b" to listOf(1.0, "x\"y\n\u0001", null, true), "c" to linkedMapOf("d" to -1e-9, "e" to 1.0E7))
        assertEquals(v, Json.parse(Json.write(v)))
        assertEquals(v, Json.parse(Json.write(v, indent = true)))
        assertFailsWith<Json.ParseException> { Json.parse("{\"a\":}") }
        assertFailsWith<Json.ParseException> { Json.parse("[1,2") }
        assertFailsWith<Json.ParseException> { Json.parse("{} x") }
    }

    @Test
    fun catalogRoundTripKeepsTransforms() {
        val src = Catalog.demo()
        val back = CatalogJson.decode(CatalogJson.encode(src, version = "t", source = "demo"))
        assertEquals(src.entries.map { it.id }, back.entries.map { it.id })
        val p = Geodetic.ofDegrees(55.75, 37.62, 150.0)
        for ((a, b) in src.entries.zip(back.entries)) {
            val (n1, e1, h1) = a.fromWgs84(p)
            val (n2, e2, h2) = b.fromWgs84(p)
            assertEquals(n1, n2, 1e-9); assertEquals(e1, e2, 1e-9); assertEquals(h1, h2, 1e-9)
        }
        assertEquals(32637, back.entries.first { it.id == "demo:utm37" }.epsg)
        assertNull(back.entries.first { it.id == "demo:sk42gk7" }.epsg)
    }

    @Test
    fun badCatalogsGiveClearErrors() {
        val bad = { s: String -> assertFailsWith<Json.ParseException> { CatalogJson.decode(s) } }
        bad("""{"format":2,"entries":[]}""")
        bad("""{"format":1,"entries":[{"id":"a","name":"n","ellipsoid":"NOPE","helmert":null,"tm":{"lat0":0,"lon0":0,"k0":1,"x0":0,"y0":0}}]}""")
        val one = CatalogJson.encodeCrs(Catalog.utm(37))
        assertTrue(runCatching { CatalogJson.decode(Json.write(linkedMapOf("format" to 1.0, "entries" to listOf(one, one)))) }.exceptionOrNull() is Json.ParseException)
    }
}
