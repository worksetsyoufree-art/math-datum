package mathdatum.app

import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.ImageComposeScene
import androidx.compose.ui.unit.Density
import mathdatum.core.CatalogJson
import mathdatum.core.Geodesy
import mathdatum.core.HelmertDirection
import mathdatum.core.MatchStatus
import org.jetbrains.skia.EncodedImageFormat
import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

/** Сквозной сценарий на реальных файлах пользователя и полном справочнике EPSG. */
@OptIn(ExperimentalComposeUiApi::class)
class RealFlowTest {
    private val catalogText by lazy { File("src/commonMain/composeResources/files/epsg.json").readText() }
    private fun fixture(name: String) = File("../core/src/desktopTest/resources/$name").readText()

    private fun shot(name: String, c: GeorefController, h: Int = 1100) {
        val scene = ImageComposeScene(width = 1000, height = h, density = Density(1f)) { App(c) }
        val png = scene.render().encodeToData(EncodedImageFormat.PNG)!!.bytes
        scene.close()
        File("build/screens/$name.png").also { it.parentFile.mkdirs() }.writeBytes(png)
    }

    @Test
    fun trenchWithMggtDatumEndToEnd() {
        val t0 = System.nanoTime()
        val catalog = CatalogJson.decode(catalogText)
        val loadMs = (System.nanoTime() - t0) / 1_000_000
        val c = GeorefController(catalog, DemoData.surface())
        c.open("trench.surface.txt", fixture("trench.surface.txt"))
        assertEquals("ACAD-Траншея с раскрытием для полигона", c.surface.name)
        assertEquals(1546, c.surface.vertices.size)
        assertEquals(0, c.surface.junkVertices)
        c.open("mggt.datum.json", fixture("mggt-msk50-zone2.datum.json"))
        val user = c.userCrs.single()

        // подсказка по направлению параметров
        val ev = assertNotNull(c.directionEvidence(user))
        assertEquals(HelmertDirection.WGS84_TO_LOCAL, ev.suggested)
        val amb = assertNotNull(c.directionAmbiguityMeters(user))
        assertTrue(amb in 150.0..260.0, "ambiguity=$amb")

        // Авто с меткой рядом с ожидаемым положением: пользовательская СК первая, оси X — север, метры
        c.pick(user)
        val where = assertNotNull(c.surfaceCenterWgs84())
        assertTrue(where.latDeg in 55.64..55.70 && where.lonDeg in 38.44..38.56, "${where.latDeg}, ${where.lonDeg}")
        c.setAnchor(where.latDeg + 0.0005, where.lonDeg + 0.0005)
        val t1 = System.nanoTime()
        c.runAuto()
        val autoMs = (System.nanoTime() - t1) / 1_000_000
        val top = c.candidates.first()
        assertEquals(user.id, top.crs.id)
        assertEquals(MatchStatus.MATCH, top.status)
        assertEquals(false, top.swapXY); assertEquals(1.0, top.unitToMeters)
        println("catalog load $loadMs ms; auto over ${catalog.entries.size + 1} systems: $autoMs ms; top=${top.crs.name}; ambiguity=$amb m; where=$where")

        // другая трактовка сдвигает положение на ~200 м
        c.setHelmertDirection(user, HelmertDirection.LOCAL_TO_WGS84)
        val other = assertNotNull(c.surfaceCenterWgs84())
        val moved = Geodesy.haversine(where, other)
        assertTrue(moved in 150.0..260.0, "moved=$moved")
        c.setHelmertDirection(c.userCrs.single(), HelmertDirection.WGS84_TO_LOCAL)

        c.mode = Mode.AUTO; c.apply(c.candidates.first())
        shot("5-real-auto", c)
        c.mode = Mode.PICK; c.query = "МГГТ"; shot("6-real-pick-user", c)
        c.query = "gauss-kruger zone 7"; shot("7-real-pick-epsg", c)
        c.mode = Mode.CHECK; shot("8-real-check", c)
    }

    @Test
    fun noAnchorStillReturnsIndirectResultsFast() {
        val c = GeorefController(CatalogJson.decode(catalogText), DemoData.surface())
        c.open("t.txt", fixture("trench.surface.txt")); c.open("d.json", fixture("mggt-msk50-zone2.datum.json"))
        val t = System.nanoTime()
        c.runAuto()
        val ms = (System.nanoTime() - t) / 1_000_000
        assertTrue(c.candidates.isNotEmpty())
        assertTrue(c.candidates.all { it.reliability == mathdatum.core.Reliability.INDIRECT })
        assertTrue(ms < 5000, "auto took $ms ms")
    }
}
