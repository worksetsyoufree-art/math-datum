package mathdatum.app

import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.ImageComposeScene
import androidx.compose.ui.unit.Density
import org.jetbrains.skia.EncodedImageFormat
import java.io.File
import kotlin.test.Test
import kotlin.test.assertTrue

/** Офлайн-рендер экранов в PNG (app/build/screens): визуальная проверка без окна. */
@OptIn(ExperimentalComposeUiApi::class)
class ScreenshotTest {
    private fun shot(name: String, c: GeorefController) {
        val scene = ImageComposeScene(width = 900, height = 900, density = Density(1f)) { App(c) }
        val png = scene.render().encodeToData(EncodedImageFormat.PNG)!!.bytes
        scene.close()
        val f = File("build/screens/$name.png").also { it.parentFile.mkdirs() }
        f.writeBytes(png)
        assertTrue(f.length() > 5_000, "$name пустой")
    }

    private fun controller() = GeorefController(mathdatum.core.Catalog.demo(), DemoData.surface())

    @Test
    fun screens() {
        val a = controller().also { it.mode = Mode.AUTO; it.setAnchor(DemoData.DEMO_LAT, DemoData.DEMO_LON); it.runAuto() }
        shot("1-auto", a)
        a.apply(a.candidates.first()); shot("1b-auto-applied", a)
        shot("2-pick", controller().also { it.mode = Mode.PICK })
        val p = controller().also { it.mode = Mode.POINTS }
        val crs = mathdatum.core.Catalog.utm(37)
        listOf(0.0 to 0.0, 600.0 to 50.0, 100.0 to 450.0, 700.0 to 500.0, 350.0 to 250.0).forEachIndexed { i, (dx, dy) ->
            val x = 413_100.0 + dx; val y = 6_178_900.0 + dy
            val w = crs.toWgs84(y + if (i == 4) 3.0 else 0.0, x, 0.0)
            p.addPair(x, y, w.latDeg, w.lonDeg)
        }
        shot("3-points", p)
        p.mode = Mode.CHECK; shot("4-check", p)
    }
}
