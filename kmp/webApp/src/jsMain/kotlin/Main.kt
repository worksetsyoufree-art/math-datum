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
import org.khronos.webgl.ArrayBuffer
import org.khronos.webgl.Int8Array
import ru.mathdatum.localization.GeoidGrid
import ru.mathdatum.localization.Csv
import ru.mathdatum.localization.Datums
import ru.mathdatum.localization.GaussKruger
import ru.mathdatum.localization.GeodeticPoint
import ru.mathdatum.localization.Xyz
import ru.mathdatum.localization.Exclusion
import ru.mathdatum.localization.LocalizationDatum
import ru.mathdatum.localization.PointQuality
import ru.mathdatum.localization.Use
import ru.mathdatum.localization.fixed
import ru.mathdatum.localization.localize
import ru.mathdatum.localization.suggestExclusions
import kotlin.math.abs

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

private const val EXAMPLE_SK42 = """name;B;L;h
T1;55.7520000000;37.6175000000;150.0000
T2;59.9390000000;30.3158000000;10.0000
T3;43.1155000000;131.8855000000;30.0000
"""

private var datum: LocalizationDatum? = null
/** Загруженная сетка геоида (файл читается в браузере, на сервер не отправляется). */
private var geoidGrid: GeoidGrid? = null
/** Датум со ссылкой на сетку, ожидающий загрузки этой сетки. */
private var pendingDatumJson: String? = null

/** Форматы пересчёта между системами: столбцы и знаки после точки. */
private val FORMATS = mapOf(
    "blh" to (listOf("B", "L", "h") to listOf(10, 10, 4)),
    "xyz" to (listOf("X", "Y", "Z") to listOf(4, 4, 4)),
    "gk" to (listOf("x", "y", "H") to listOf(4, 4, 4)),
)

private fun fillSystems(id: String, selected: String, extra: Pair<String, String>? = null) {
    val s = el<HTMLSelectElement>(id)
    s.innerHTML = (listOfNotNull(extra) + Datums.SYSTEMS.map { it.id to it.name })
        .joinToString("") { (v, n) -> "<option value=\"$v\"${if (v == selected) " selected" else ""}>${escape(n)}</option>" }
}

private inline fun <reified T : HTMLElement> el(id: String): T = document.getElementById(id) as T

fun main() {
    val pairs = el<HTMLTextAreaElement>("pairs")
    pairs.value = EXAMPLE_PAIRS
    el<HTMLTextAreaElement>("input").value = EXAMPLE_WGS
    fillSystems("gnssDatum", "WGS-84")
    fillSystems("pointsDatum", "", "" to "как у датума")
    fillSystems("sysFrom", "SK-42")
    fillSystems("sysTo", "WGS-84")
    for (id in listOf("fmtFrom", "fmtTo")) {
        el<HTMLSelectElement>(id).innerHTML = listOf("blh" to "BLH", "xyz" to "XYZ", "gk" to "ГК 6°")
            .joinToString("") { (v, n) -> "<option value=\"$v\">$n</option>" }
    }
    el<HTMLTextAreaElement>("sysInput").value = EXAMPLE_SK42
    el<HTMLButtonElement>("sysTransform").onclick = { transformSystems(); null }
    el<HTMLButtonElement>("sysSwap").onclick = { swapSystems(); null }
    el<HTMLSelectElement>("gnssDatum").onchange = { calculate(); null }
    el<HTMLSelectElement>("heightModel").onchange = { updateGeoidControls(); calculate(); null }
    el<HTMLSelectElement>("geoidInterp").onchange = { calculate(); null }
    readBinary("geoidFile") { name, bytes ->
        try {
            val g = GeoidGrid.parse(bytes, name)
            geoidGrid = g
            el<HTMLElement>("geoidInfo").textContent = g.describe() + "; sha256 " + g.sha256.take(16) + "…"
            el<HTMLElement>("calcError").textContent = ""
            val pending = pendingDatumJson
            if (pending != null) loadDatum(pending) else {
                if (el<HTMLSelectElement>("heightModel").value == "plane") el<HTMLSelectElement>("heightModel").value = "geoid_plane"
                updateGeoidControls()
                calculate()
            }
        } catch (e: Throwable) {
            el<HTMLElement>("calcError").textContent = "Не удалось прочитать сетку геоида: ${e.message}"
        }
    }
    updateGeoidControls()

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
    el<HTMLInputElement>("qualityCols").onchange = { if (el<HTMLTextAreaElement>("output").value.isNotBlank()) transform(); null }
    readFile("pairsFile") { pairs.value = it; calculate() }
    readFile("datumFile") { text -> loadDatum(text) }
    calculate()
}

/** Датум из JSON; если он ссылается на сетку геоида — нужна та же сетка (по SHA-256). */
private fun loadDatum(text: String) {
    val err = el<HTMLElement>("calcError")
    try {
        val ref = LocalizationDatum.fromJson(text, requireGeoid = false).geoid
        val d = if (ref == null) LocalizationDatum.fromJson(text) else {
            val g = geoidGrid
            if (g == null || g.sha256 != ref.sha256) {
                pendingDatumJson = text
                err.textContent = "Датум использует сетку геоида ${ref.file} (sha256 ${ref.sha256.take(16)}…): " +
                    (if (g == null) "загрузите этот файл сетки." else "загруженная сетка ${g.name} — другая (SHA-256 не совпадает).")
                return
            }
            LocalizationDatum.fromJson(text, g)
        }
        pendingDatumJson = null
        show(d)
        err.textContent = ""
    } catch (e: Throwable) {
        err.textContent = "Не удалось прочитать датум: ${e.message}"
    }
}

private fun updateGeoidControls() {
    val geoid = el<HTMLSelectElement>("heightModel").value != "plane"
    el<HTMLElement>("geoidRow").classList.toggle("hidden", !geoid)
}

private fun calculate() {
    val err = el<HTMLElement>("calcError")
    try {
        val pairs = Csv.parsePairs(el<HTMLTextAreaElement>("pairs").value)
        val gnss = el<HTMLSelectElement>("gnssDatum").value
        val model = el<HTMLSelectElement>("heightModel").value
        val grid = if (model == "plane") null else geoidGrid
            ?: throw IllegalArgumentException("Модель высоты $model: загрузите сетку геоида (.ggf, .gtx или .isg).")
        val interp = el<HTMLSelectElement>("geoidInterp").value
        val d = localize(pairs, gnssDatum = gnss, heightModel = model, geoid = grid, geoidInterpolation = interp)
        show(d, if (d.residuals.any { it.suspect }) {
            suggestExclusions(pairs, gnssDatum = gnss, heightModel = model, geoid = grid, geoidInterpolation = interp)
        } else emptyList())
        err.textContent = ""
    } catch (e: Throwable) {
        err.textContent = e.message ?: e.toString()
    }
}

private fun mm(v: Double?) = v?.let { (it * 1000).fixed(1) } ?: "—"

private fun show(d: LocalizationDatum, exclusions: List<Exclusion> = emptyList()) {
    datum = d
    d.gnssSystem?.let { el<HTMLSelectElement>("gnssDatum").value = it }
    d.geoid?.let {
        el<HTMLSelectElement>("heightModel").value = if (d.heightModel == "geoid_plane") "geoid_plane" else "geoid"
        el<HTMLSelectElement>("geoidInterp").value = it.interpolation
    }
    if (d.geoid == null) el<HTMLSelectElement>("heightModel").value = "plane"
    updateGeoidControls()
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
        stat("Сетка геоида", d.geoid?.let { escape(it.file) + " (" + it.interpolation + ")" } ?: "нет (H = h + плоскость)"),
        stat("Система ГНСС", d.gnssSystem?.let { Datums.system(it).name + " (" + Datums.system(it).ellipsoid.name + ")" } ?: "не указана"),
        stat("Избыточность план / высота", if (d.redundancyPlan == null) "—" else "${d.redundancyPlan} / ${d.redundancyHeight ?: "—"}"),
        stat("СКО ед. веса план / высота", "${mm(d.s0Plan)} / ${mm(d.s0Height)} мм" +
            (d.sigma0Plan?.let { " (априори ${mm(it)} / ${mm(d.sigma0Height)})" } ?: "")),
    ).joinToString("")

    // Предупреждения датума и предложение исключить точки (только диагностика, расчёт не меняется).
    val notes = d.warnings.map { escape(it.message) }.toMutableList()
    if (d.redundancyPlan == null) notes += "Датум в старом формате: сведений о надёжности нет — пересчитайте его по парам точек."
    if (exclusions.isNotEmpty()) {
        notes += "Итеративно по худшему |w| предлагается исключить: " + exclusions.joinToString(", ") {
            "${escape(it.name)} (${if (it.part == "plan") "план" else "высота"}, |w| = ${it.w.fixed(2)})"
        } + ". Измените <code>use</code> и пересчитайте."
    }
    el<HTMLElement>("warnings").innerHTML =
        if (notes.isEmpty()) "" else "<ul>" + notes.joinToString("") { "<li>$it</li>" } + "</ul>"

    val table = el<HTMLTableElement>("residuals")
    if (d.residuals.isEmpty()) {
        table.innerHTML = ""
    } else {
        // Подсвечиваем по нормированной поправке |w| > порога (тест Баарда), а не по 3·СКО:
        // max|v| ≤ √n·СКО, поэтому при n ≤ 9 такой порог недостижим, а выброс ещё и раздувает СКО.
        val lim = d.wLimit ?: Double.MAX_VALUE
        fun cell(text: String, bad: Boolean, title: String? = null) =
            "<td${if (bad) " class=\"big\"" else ""}${title?.let { " title=\"$it\"" } ?: ""}>$text</td>"
        fun w(v: Double?, na: String) = cell(v?.let { abs(it).fixed(2) } ?: "—", v != null && abs(v) > lim, if (v == null) na else null)
        val noCheck = "нельзя проверить: без точки модель не определена"
        // Использованные априорные СКО точек (свои σ из CSV или глобальные); свои — выделены.
        val sigmas = d.residuals.any { it.sigmaPlan != null }
        fun sigma(v: Double?, p: Double?) =
            "<td${if (p != null && p != 1.0) " class=\"own\"" else ""}${p?.let { " title=\"вес p = ${it.fixed(3)}\"" } ?: ""}>${mm(v)}</td>"
        table.innerHTML = "<tr><th>Точка</th><th>Использование</th><th>dx, мм</th><th>dy, мм</th><th>dH, мм</th>" +
            (if (sigmas) "<th title=\"априорная СКО точки на координату (столбец sigma_plan или глобальная)\">σ план, мм</th>" +
                "<th title=\"априорная СКО высоты точки (столбец sigma_height или глобальная)\">σ выс., мм</th>" else "") +
            "<th title=\"нормированная поправка, план: max(|wx|, |wy|)\">|w| план</th><th title=\"нормированная поправка, высота\">|w| выс.</th>" +
            "<th title=\"ошибка прогноза в точке датумом без неё (для контрольных — сама невязка)\">Без точки план, мм</th>" +
            "<th>Без точки dH, мм</th></tr>" +
            d.residuals.joinToString("") { r ->
                val use = when (r.use) {
                    Use.BOTH -> "план и высота"
                    Use.PLAN -> "план"
                    Use.HEIGHT -> "высота"
                    Use.NONE -> "контроль"
                }
                val badP = r.wPlan?.let { it > lim } == true
                val badH = r.wH?.let { abs(it) > lim } == true
                val cls = listOfNotNull("control".takeIf { r.use == Use.NONE }, "suspect".takeIf { r.suspect })
                "<tr${if (cls.isEmpty()) "" else " class=\"${cls.joinToString(" ")}\""}><td>${escape(r.name)}${if (r.suspect) " ⚠" else ""}</td><td>$use</td>" +
                    cell(mm(r.dx), badP) + cell(mm(r.dy), badP) + cell(mm(r.dH), badH) +
                    (if (sigmas) sigma(r.sigmaPlan, r.pPlan) + sigma(r.sigmaHeight, r.pHeight) else "") +
                    w(r.wPlan, noCheck) + w(r.wH, noCheck) +
                    cell(mm(r.looPlan), badP, if (r.looPlan == null) noCheck else null) +
                    cell(mm(r.looDH), badH, if (r.looDH == null) noCheck else null) + "</tr>"
            }
    }
    el<HTMLElement>("proj").textContent = d.toProjPipeline()
}

private fun transform() {
    val d = datum ?: return
    val err = el<HTMLElement>("transformError")
    val input = el<HTMLTextAreaElement>("input").value
    try {
        val withQuality = el<HTMLInputElement>("qualityCols").checked
        val quality = mutableListOf<Pair<String, PointQuality>>()
        // Система точек ГНСС: пусто — как у датума; иначе пересчёт по ГОСТ 32453-2017.
        val sys = el<HTMLSelectElement>("pointsDatum").value.ifEmpty { null }
        val text = when (el<HTMLSelectElement>("direction").value) {
            "toLocal" -> Csv.parseWgsPoints(input).let { pts ->
                val own = pts.map { (n, p) -> n to d.fromSystem(p, sys) }
                own.forEach { (n, p) -> quality += n to d.quality(p) }
                Csv.formatLocal(own.map { (n, p) -> n to d.toLocal(p) })
            }
            else -> Csv.parseLocalPoints(input).let { pts ->
                pts.forEach { (n, p) -> quality += n to d.quality(p) }
                Csv.formatWgs(pts.map { (n, p) -> n to d.toWgs(p, sys) })
            }
        }
        el<HTMLTextAreaElement>("output").value = if (!withQuality) text else addQualityColumns(text, quality)
        val far = quality.filter { (it.second.outside ?: 0.0) > 1e-3 }
        val own = d.gnssSystem
        val path = if (sys == null || own == null || Datums.system(sys).id == own) "" else
            "Пересчёт по ГОСТ 32453-2017: " + escape(Datums.describePath(Datums.findPath(sys, own))) + ". "
        el<HTMLElement>("transformNote").innerHTML = path + when {
            d.planHull == null -> "Датум в старом формате: экстраполяция не проверяется."
            far.isEmpty() -> ""
            else -> "⚠ ${far.size} из ${quality.size} точек вне выпуклой оболочки опорных пунктов (экстраполяция, точность падает): " +
                far.joinToString(", ") { "${escape(it.first)} (${it.second.outside!!.fixed(0)} м)" }
        }
        err.textContent = ""
    } catch (e: Throwable) {
        err.textContent = e.message ?: e.toString()
    }
}

/** Пересчёт точек между государственными системами (раздел 4). */
private fun transformSystems() {
    val err = el<HTMLElement>("sysError")
    try {
        val from = Datums.system(el<HTMLSelectElement>("sysFrom").value)
        val to = Datums.system(el<HTMLSelectElement>("sysTo").value)
        val fin = el<HTMLSelectElement>("fmtFrom").value
        val fout = el<HTMLSelectElement>("fmtTo").value
        val path = Datums.findPath(from.id, to.id)
        val ef = from.ellipsoid.ellipsoid
        val et = to.ellipsoid.ellipsoid
        val pts = Csv.parseColumns(el<HTMLTextAreaElement>("sysInput").value, FORMATS.getValue(fin).first).map { (n, v) ->
            val xyz = when (fin) {
                "xyz" -> Xyz(v[0], v[1], v[2])
                "gk" -> GaussKruger.inverse(v[0], v[1], ef).let { (b, l) -> Datums.blhToXyz(GeodeticPoint(b, l, v[2]), ef) }
                else -> Datums.blhToXyz(GeodeticPoint(v[0], v[1], v[2]), ef)
            }
            val r = Datums.transformXyz(xyz, from.id, to.id, path = path)
            n to when (fout) {
                "xyz" -> doubleArrayOf(r.x, r.y, r.z)
                "gk" -> Datums.xyzToBlh(r, et).let { g -> GaussKruger.forward(g.lat, g.lon, et).let { doubleArrayOf(it.x, it.y, g.h) } }
                else -> Datums.xyzToBlh(r, et).let { doubleArrayOf(it.lat, it.lon, it.h) }
            }
        }
        val (cols, digits) = FORMATS.getValue(fout)
        el<HTMLTextAreaElement>("sysOutput").value = Csv.formatColumns(pts, cols, digits)
        el<HTMLElement>("sysNote").textContent = "Точек: ${pts.size}; " + Datums.describePath(path) +
            (if (fin == "gk" || fout == "gk") ". Высота H плоских координат — геодезическая." else ".")
        err.textContent = ""
    } catch (e: Throwable) {
        err.textContent = e.message ?: e.toString()
    }
}

/** Результат — во вход, системы и форматы меняются местами. */
private fun swapSystems() {
    val out = el<HTMLTextAreaElement>("sysOutput")
    if (out.value.isBlank()) return
    el<HTMLTextAreaElement>("sysInput").value = out.value
    out.value = ""
    for ((a, b) in listOf("sysFrom" to "sysTo", "fmtFrom" to "fmtTo")) {
        val x = el<HTMLSelectElement>(a)
        val y = el<HTMLSelectElement>(b)
        val t = x.value
        x.value = y.value
        y.value = t
    }
    transformSystems()
}

/** Добавляет к CSV столбцы outside_m (расстояние до оболочки опорных пунктов), m_plan, m_H (СКО прогноза, априори). */
private fun addQualityColumns(csv: String, quality: List<Pair<String, PointQuality>>): String {
    val lines = csv.trimEnd('\n').split("\n")
    fun f(v: Double?, d: Int) = v?.fixed(d) ?: ""
    return lines.first() + ";outside_m;m_plan;m_H\n" + lines.drop(1).mapIndexed { i, line ->
        val q = quality[i].second
        "$line;${f(q.outside, 3)};${f(q.mPlan, 4)};${f(q.mHeight, 4)}\n"
    }.joinToString("")
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

private fun readBinary(inputId: String, onBytes: (String, ByteArray) -> Unit) {
    val input = el<HTMLInputElement>(inputId)
    input.onchange = {
        input.files?.get(0)?.let { file ->
            val reader = FileReader()
            reader.onload = { onBytes(file.name, Int8Array(reader.result as ArrayBuffer).unsafeCast<ByteArray>()); null }
            reader.readAsArrayBuffer(file)
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
