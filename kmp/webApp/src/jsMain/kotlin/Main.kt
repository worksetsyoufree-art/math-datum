import kotlinx.browser.document
import kotlinx.browser.window
import org.w3c.dom.HTMLButtonElement
import org.w3c.dom.HTMLElement
import org.w3c.dom.HTMLInputElement
import org.w3c.dom.HTMLSelectElement
import org.w3c.dom.HTMLTableElement
import org.w3c.dom.HTMLTextAreaElement
import org.w3c.dom.url.URL
import org.w3c.files.Blob
import org.w3c.files.BlobPropertyBag
import org.w3c.files.FileReader
import org.w3c.files.get
import ru.mathdatum.localization.Csv
import ru.mathdatum.localization.LocalizationDatum
import ru.mathdatum.localization.Use
import ru.mathdatum.localization.fixed
import ru.mathdatum.localization.localize

private const val EXAMPLE_PAIRS = """name;B;L;h;x;y;H;use
R1;55.0527657163;39.2668049556;215.5380;-200498.0340;3258049.8198;209.3761;both
R2;55.0535594458;39.2806016103;253.7579;-200408.1085;3258931.3713;247.5868;both
R3;55.1208700643;39.3082276071;227.9100;-192911.1103;3260680.0195;221.8751;both
R4;55.0649832215;39.3381236675;196.0714;-199128.0199;3262604.1443;189.9145;both
R5;55.0731607668;39.3145884923;213.5159;-198221.4409;3261098.3476;207.3795;both
R6;55.0541592429;39.2778088644;250.3094;-200341.6818;3258752.8084;244.1425;both
K1;55.0865060159;39.3507925267;230.8802;-196729.7400;3263406.7014;224.7592;none
K2;55.0737970986;39.2009338613;202.6549;-198161.7462;3253838.3032;196.5642;none
K3;55.0700550690;39.3254767656;232.0133;-198565.4874;3261794.7272;225.8586;none
K4;55.1235970181;39.2541676394;239.2869;-192613.9994;3257230.4339;233.2804;none
"""

private const val EXAMPLE_WGS = """name;B;L;h
T1;55.0895060159;39.3467925267;230.8802
T2;55.0767970986;39.1969338613;202.6549
T3;55.0730550690;39.3214767656;232.0133
T4;55.1265970181;39.2501676394;239.2869
"""

private var datum: LocalizationDatum? = null

private inline fun <reified T : HTMLElement> el(id: String): T = document.getElementById(id) as T

fun main() {
    val pairs = el<HTMLTextAreaElement>("pairs")
    pairs.value = EXAMPLE_PAIRS
    el<HTMLTextAreaElement>("input").value = EXAMPLE_WGS

    el<HTMLButtonElement>("example").onclick = { pairs.value = EXAMPLE_PAIRS; null }
    el<HTMLButtonElement>("calc").onclick = { calculate(); null }
    el<HTMLButtonElement>("transform").onclick = { transform(); null }
    el<HTMLButtonElement>("swap").onclick = { swap(); null }
    el<HTMLButtonElement>("saveDatum").onclick = {
        datum?.let { download("datum.json", it.toJson(), "application/json") }; null
    }
    el<HTMLButtonElement>("saveOutput").onclick = {
        download("points.csv", el<HTMLTextAreaElement>("output").value, "text/csv"); null
    }
    el<HTMLButtonElement>("copyProj").onclick = {
        datum?.let { window.navigator.clipboard.writeText(it.toProjPipeline()) }; null
    }
    el<HTMLSelectElement>("direction").onchange = { el<HTMLTextAreaElement>("output").value = ""; null }
    readFile("pairsFile") { pairs.value = it; calculate() }
    readFile("datumFile") { text ->
        try {
            show(LocalizationDatum.fromJson(text))
            el<HTMLElement>("calcError").textContent = ""
        } catch (e: Throwable) {
            el<HTMLElement>("calcError").textContent = "Не удалось прочитать датум: ${e.message}"
        }
    }
    calculate()
}

private fun calculate() {
    val err = el<HTMLElement>("calcError")
    try {
        show(localize(Csv.parsePairs(el<HTMLTextAreaElement>("pairs").value)))
        err.textContent = ""
    } catch (e: Throwable) {
        err.textContent = e.message ?: e.toString()
    }
}

private fun show(d: LocalizationDatum) {
    datum = d
    el<HTMLElement>("resultSection").classList.remove("hidden")
    el<HTMLElement>("transformSection").classList.remove("hidden")
    fun stat(k: String, v: String) = "<div class=\"stat\"><div class=\"k\">$k</div><div class=\"v\">$v</div></div>"
    el<HTMLElement>("stats").innerHTML = listOf(
        stat("СКО в плане", d.rmsPlan?.let { "${(it * 1000).fixed(1)} мм" } ?: "—"),
        stat("СКО по высоте", d.rmsHeight?.let { "${(it * 1000).fixed(1)} мм" } ?: "—"),
        stat("Масштаб", "${d.scalePpm.fixed(2)} ppm"),
        stat("Разворот", "${d.rotationArcsec.fixed(2)}″"),
        stat("Сдвиг высоты c0", "${d.c0.fixed(4)} м"),
        stat("Наклон N / E", "${(d.c1 * 1e6).fixed(2)} / ${(d.c2 * 1e6).fixed(2)} мм/км"),
        stat("Модель", "план: ${d.planModel}, высота: ${d.heightModel}"),
    ).joinToString("")

    val table = el<HTMLTableElement>("residuals")
    if (d.residuals.isEmpty()) {
        table.innerHTML = ""
    } else {
        // Подсвечиваем невязки больше трёх СКО — кандидаты на исключение.
        val limPlan = 3 * (d.rmsPlan ?: Double.MAX_VALUE)
        val limH = 3 * (d.rmsHeight ?: Double.MAX_VALUE)
        fun cell(v: Double, lim: Double) = "<td${if (kotlin.math.abs(v) > lim && lim > 0.001) " class=\"big\"" else ""}>${(v * 1000).fixed(1)}</td>"
        table.innerHTML = "<tr><th>Точка</th><th>Использование</th><th>dx, мм</th><th>dy, мм</th><th>dH, мм</th></tr>" +
            d.residuals.joinToString("") { r ->
                val use = when (r.use) {
                    Use.BOTH -> "план и высота"
                    Use.PLAN -> "план"
                    Use.HEIGHT -> "высота"
                    Use.NONE -> "контроль"
                }
                "<tr${if (r.use == Use.NONE) " class=\"control\"" else ""}><td>${escape(r.name)}</td><td>$use</td>" +
                    cell(r.dx, limPlan) + cell(r.dy, limPlan) + cell(r.dH, limH) + "</tr>"
            }
    }
    el<HTMLElement>("proj").textContent = d.toProjPipeline()
}

private fun transform() {
    val d = datum ?: return
    val err = el<HTMLElement>("transformError")
    val input = el<HTMLTextAreaElement>("input").value
    try {
        el<HTMLTextAreaElement>("output").value = when (el<HTMLSelectElement>("direction").value) {
            "toLocal" -> Csv.formatLocal(Csv.parseWgsPoints(input).map { (n, p) -> n to d.toLocal(p) })
            else -> Csv.formatWgs(Csv.parseLocalPoints(input).map { (n, p) -> n to d.toWgs(p) })
        }
        err.textContent = ""
    } catch (e: Throwable) {
        err.textContent = e.message ?: e.toString()
    }
}

/** Переносит результат во вход и меняет направление — удобно проверить пересчёт туда и обратно. */
private fun swap() {
    val dir = el<HTMLSelectElement>("direction")
    val output = el<HTMLTextAreaElement>("output")
    if (output.value.isBlank()) return
    el<HTMLTextAreaElement>("input").value = output.value
    output.value = ""
    dir.value = if (dir.value == "toLocal") "toWgs" else "toLocal"
    transform()
}

private fun readFile(inputId: String, onText: (String) -> Unit) {
    val input = el<HTMLInputElement>(inputId)
    input.onchange = {
        input.files?.get(0)?.let { file ->
            val reader = FileReader()
            reader.onload = { onText(reader.result as String); null }
            reader.readAsText(file)
        }
        input.value = ""
        null
    }
}

private fun download(name: String, text: String, type: String) {
    val url = URL.createObjectURL(Blob(arrayOf(text), BlobPropertyBag(type = "$type;charset=utf-8")))
    val a = document.createElement("a") as HTMLElement
    a.setAttribute("href", url)
    a.setAttribute("download", name)
    document.body?.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
}

private fun escape(s: String) = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
