package mathdatum.core

import java.io.File
import kotlin.math.abs
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** Справочник EPSG (app/…/files/epsg.json) против эталонов PROJ: tools/gen_epsg_golden.py. */
class EpsgCatalogTest {
    private val catalogFile = File("../app/src/commonMain/composeResources/files/epsg.json")
    private val catalog: Catalog by lazy { CatalogJson.decode(catalogFile.readText()) }

    @Test
    fun wholeCatalogLoads() {
        val c = catalog
        assertTrue(c.entries.size > 4500, "entries=${c.entries.size}")
        assertTrue(c.unsupported.isNotEmpty())
        assertTrue(c.entries.any { it.id == "EPSG:32637" } && c.entries.any { it.id == "EPSG:2154" })
        val utm = c.entries.first { it.id == "EPSG:32637" }
        assertEquals(DatumStatus.EXACT, utm.datumStatus)
        val ft = c.entries.firstOrNull { it.unitToMeters != 1.0 }
        assertTrue(ft != null, "должны быть СК в футах")
        println("catalog: ${c.version}; ${c.entries.size} supported, ${c.unsupported.size} unsupported; " +
            DatumStatus.entries.joinToString { s -> "$s=${c.entries.count { it.datumStatus == s }}" })
    }

    @Test
    fun matchesProjWithin0_1mmForSampledCatalogEntries() {
        val root = Json.parse(File("src/desktopTest/resources/epsg-golden.json").readText()).asMap("golden")
        val byId = catalog.entries.associateBy { it.id }
        var checked = 0
        var worst = 0.0; var worstId = ""
        for (item in root["crs"].asList("crs")) {
            val m = item.asMap("crs")
            val crs = byId[m["id"].asString("id")] ?: error("нет в каталоге: ${m["id"]}")
            val g = CrsGeoref.native(crs)
            for (pt in m["points"].asList("points")) {
                val p = pt.asList("pt").map { it.asDouble("v") }
                val s = g.fromWgs84(Geodetic.ofDegrees(p[0], p[1], p[2]))
                val d = maxOf(abs(s.x - p[3]), abs(s.y - p[4])) * crs.unitToMeters
                if (d > worst) { worst = d; worstId = "${crs.id} ${crs.name} @${p[0]},${p[1]}" }
                checked++
            }
        }
        assertTrue(checked > 1500, "checked=$checked")
        assertTrue(worst <= 1e-4, "worst=$worst m at $worstId")
        println("epsg golden: $checked points, worst diff $worst m")
    }
}
