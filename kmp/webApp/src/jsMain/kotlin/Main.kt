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
import ru.mathdatum.localization.Export
import ru.mathdatum.localization.Ldp
import ru.mathdatum.localization.LdpContour
import ru.mathdatum.localization.LdpHeights
import ru.mathdatum.localization.LdpProjection
import ru.mathdatum.localization.LdpResult
import ru.mathdatum.localization.LdpStats
import ru.mathdatum.localization.LocalizationDatum
import ru.mathdatum.localization.PointQuality
import ru.mathdatum.localization.Use
import ru.mathdatum.localization.fixed
import ru.mathdatum.localization.localize
import ru.mathdatum.localization.suggestExclusions
import kotlin.math.abs
import kotlin.math.floor
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

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

private const val EXAMPLE_LDP_SITE = """name;B;L;h
S1;54.99009100;39.12939669;212.0
S2;54.99456334;39.42624329;248.0
S3;55.09785436;39.43447817;236.0
S4;55.16976180;39.39554212;205.0
S5;55.16074290;39.11310774;196.0
S6;55.07090637;39.10563237;221.0
S1;54.99009100;39.12939669;212.0
"""

private const val EXAMPLE_LDP_ROUTE = """name;B;L;H
PK1;55.30327395;37.21906419;160.0
PK2;55.32440814;37.61230151;185.0
PK3;55.31306751;38.08501346;230.0
PK4;55.29099225;38.47870279;210.0
PK5;55.30357789;38.87236807;175.0
PK6;55.31938433;39.26636078;150.0
PK7;55.30327395;39.58093581;140.0
"""

private var datum: LocalizationDatum? = null
/** Последняя спроектированная LDP (раздел 5) и проекции, доступные как рабочие в локализации. */
private var ldpResult: LdpResult? = null
private var workProjections: List<Pair<String, LdpProjection>> = emptyList()
/** Обработчик подсказки карты искажений (обновляется при перерисовке). */
private var mapHover: ((org.w3c.dom.events.Event) -> Unit)? = null
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
    initLdp()
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
    for (f in listOf("wkt2", "projjson", "jxl", "landxml")) {
        el<HTMLButtonElement>("export-$f").onclick = { exportDatum(f); null }
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
        // Рабочая проекция: по умолчанию TM в центре точек (k = 1), либо спроектированная LDP (раздел 5).
        val wp = el<HTMLSelectElement>("workProj").value.toIntOrNull()?.let { workProjections.getOrNull(it)?.second }
        val d = localize(
            pairs, wp?.lat0, wp?.lon0, wp?.system?.ellipsoid?.proj, gnssDatum = gnss, heightModel = model, geoid = grid,
            geoidInterpolation = interp, k0 = wp?.k0 ?: 1.0, x0 = wp?.x0 ?: 0.0, y0 = wp?.y0 ?: 0.0,
        )
        show(d, if (d.residuals.any { it.suspect }) {
            suggestExclusions(
                pairs, gnssDatum = gnss, heightModel = model, geoid = grid, geoidInterpolation = interp, ellipsoid = wp?.system?.ellipsoid?.proj,
                lat0 = wp?.lat0, lon0 = wp?.lon0, k0 = wp?.k0 ?: 1.0, x0 = wp?.x0 ?: 0.0, y0 = wp?.y0 ?: 0.0,
            )
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
        stat("Рабочая проекция", if (d.k0 == 1.0 && d.x0 == 0.0 && d.y0 == 0.0) "TM по центру точек, k = 1"
            else "TM: L0 = ${d.lon0}°, k0 = ${d.k0}, x0 = ${d.x0.fixed(0)}, y0 = ${d.y0.fixed(0)}"),
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
    el<HTMLElement>("exportNotes").innerHTML = ""
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

// --- 5. Проектирование малоискажающей проекции (LDP) ---

private fun initLdp() {
    el<HTMLTextAreaElement>("ldpContour").value = EXAMPLE_LDP_SITE
    fillSystems("ldpDatum", Ldp.DEFAULT_DATUM)
    el<HTMLButtonElement>("ldpCalc").onclick = { designLdp(); null }
    el<HTMLButtonElement>("ldpExSite").onclick = {
        el<HTMLTextAreaElement>("ldpContour").value = EXAMPLE_LDP_SITE; el<HTMLInputElement>("ldpHeight").value = ""; designLdp(); null
    }
    el<HTMLButtonElement>("ldpExRoute").onclick = {
        el<HTMLTextAreaElement>("ldpContour").value = EXAMPLE_LDP_ROUTE; el<HTMLInputElement>("ldpHeight").value = ""; designLdp(); null
    }
    readFile("ldpFile") { el<HTMLTextAreaElement>("ldpContour").value = it; designLdp() }
    el<HTMLButtonElement>("ldpSave").onclick = { ldpResult?.let { download("ldp.json", it.toJson(), "application/json") }; null }
    el<HTMLButtonElement>("ldpCopy").onclick = {
        ldpResult?.let { r -> window.navigator.clipboard.writeText(selectedLdp(r).proj) }; null
    }
    el<HTMLButtonElement>("ldpUse").onclick = { useLdp(); null }
    el<HTMLSelectElement>("ldpUseZone").onchange = { ldpResult?.let { el<HTMLElement>("ldpProj").textContent = selectedLdp(it).proj }; null }
    // Тёмная тема: цвета карты берутся из CSS-переменных — перерисовать при смене схемы.
    window.matchMedia("(prefers-color-scheme: dark)").addListener { ldpResult?.let { drawLdpMap(it) } }
}

/** Проекция для копирования / локализации: основная, а если она не укладывается — выбранная зона. */
private fun selectedLdp(r: LdpResult): LdpProjection {
    if (r.zones.isEmpty() || r.fits) return r.projection
    val i = el<HTMLSelectElement>("ldpUseZone").value.toIntOrNull() ?: 0
    return r.zones.getOrNull(i)?.projection ?: r.zones[0].projection
}

private fun designLdp() {
    val err = el<HTMLElement>("ldpError")
    try {
        val kind = el<HTMLSelectElement>("ldpKind").value.ifEmpty { null }
        val contour = LdpContour.parseCsv(el<HTMLTextAreaElement>("ldpContour").value, kind)
        val hText = el<HTMLInputElement>("ldpHeight").value.trim().replace(',', '.')
        val h = if (hText.isEmpty()) null else hText.toDoubleOrNull() ?: throw IllegalArgumentException("Средняя высота «$hText» — не число.")
        val tol = el<HTMLInputElement>("ldpTol").value.replace(',', '.').toDoubleOrNull() ?: throw IllegalArgumentException("Допуск — не число.")
        // Высоты вершин из файла важнее средней; средняя — если столбца нет.
        val heights = LdpHeights(constant = h)
        val src = if (contour.hasHeights) contour else LdpContour(contour.kind, contour.vertices.map { it.copy(h = null) })
        val r = Ldp.design(src, heights, el<HTMLSelectElement>("ldpDatum").value, tol, el<HTMLSelectElement>("ldpCriterion").value)
        ldpResult = r
        showLdp(r)
        err.textContent = ""
    } catch (e: Throwable) {
        err.textContent = e.message ?: e.toString()
    }
}

private fun dms(v: Double): String {
    val s = if (v < 0) "−" else ""
    val t = (abs(v) * 360000).roundToInt()
    val d = t / 360000
    val m = (t % 360000) / 6000
    val sec = (t % 6000) / 100.0
    return "$s$d°${m.toString().padStart(2, '0')}′${sec.fixed(2).padStart(5, '0')}″"
}

private fun ppm(v: Double) = (if (v > 0) "+" else "") + v.fixed(2)

private fun showLdp(r: LdpResult) {
    el<HTMLElement>("ldpResult").classList.remove("hidden")
    val p = r.projection
    val o = r.objectInfo
    fun stat(k: String, v: String) = "<div class=\"stat\"><div class=\"k\">$k</div><div class=\"v\">$v</div></div>"
    val size = if (r.contour.kind == "polygon") "${((o["area_m2"] as Double) / 1e6).fixed(2)} км²" else "${((o["length_m"] as Double) / 1e3).fixed(2)} км"
    el<HTMLElement>("ldpStats").innerHTML = listOf(
        stat("Итог", if (r.fits) "укладывается в ±${r.tolerance.fixed(1)} ppm" else "одна проекция не укладывается — ${r.zones.size} зон(ы)"),
        stat("Осевой меридиан L0", "${p.lon0.fixed(6)}° (${dms(p.lon0)})"),
        stat("Широта начала B0", "${p.lat0.fixed(6)}° (${dms(p.lat0)})"),
        stat("Масштаб k0", "${p.k0} (${ppm((p.k0 - 1) * 1e6).replace(".00", ".0")} ppm)"),
        stat("Ложные x0 (север) / y0 (восток)", "${p.x0.fixed(0)} / ${p.y0.fixed(0)} м"),
        stat("max|δ| / RMS", "${r.stats.maxAbsPpm.fixed(2)} / ${r.stats.rmsPpm.fixed(2)} ppm"),
        stat("Доля ${if (r.stats.measure == "area") "площади" else "длины"} в допуске", "${(r.stats.shareInTolerance * 100).fixed(1)} %"),
        stat("Объект", "${if (r.contour.kind == "polygon") "площадка" else "трасса"}, $size, h ${(o["h_min"] as Double).fixed(0)}…${(o["h_max"] as Double).fixed(0)} м"),
        stat("Система", Datums.system(r.datum).name + " (" + Datums.system(r.datum).ellipsoid.name + ")"),
    ).joinToString("")
    el<HTMLElement>("ldpWarnings").innerHTML =
        if (r.warnings.isEmpty()) "" else "<ul>" + r.warnings.joinToString("") { "<li>${escape(it)}</li>" } + "</ul>"
    fun row(name: String, s: LdpStats) = "<tr><td>${escape(name)}</td><td>${ppm(s.minPpm)}</td><td>${ppm(s.maxPpm)}</td><td>${ppm(s.meanPpm)}</td>" +
        "<td>${s.rmsPpm.fixed(2)}</td><td${if (s.maxAbsPpm <= r.tolerance) " class=\"fit\"" else " class=\"big\""}>${s.maxAbsPpm.fixed(2)}</td>" +
        "<td>${(s.shareInTolerance * 100).fixed(1)} %</td></tr>"
    el<HTMLTableElement>("ldpCompare").innerHTML = "<tr><th>Проекция</th><th>min</th><th>max</th><th>mean</th><th>RMS</th><th>max|δ|</th><th>в допуске</th></tr>" +
        row("LDP" + if (r.fits) "" else " (одна зона)", r.stats) +
        r.zones.joinToString("") { row("LDP: ${it.name}", it.stats) } +
        row("ГК 6°, зона " + r.gk.zones.joinToString(","), r.gk.stats) +
        row("UTM, зона " + r.utm.zones.joinToString(","), r.utm.stats)
    el<HTMLElement>("ldpZones").innerHTML = if (r.zones.isEmpty()) "" else {
        val unit = if (r.zoneKey == "chainage") "пикетаж" else "восток (вспом.)"
        "<p class=\"hint\" style=\"margin-top:10px\">Предлагаемые зоны (минимакс, каждая ≤ ±${r.tolerance.fixed(1)} ppm):</p><ul>" +
            r.zones.joinToString("") { z ->
                val q = z.projection
                "<li>${z.name}: $unit ${(z.start / 1e3).fixed(2)}…${(z.end / 1e3).fixed(2)} км; L0 = ${q.lon0.fixed(6)}°, k0 = ${q.k0}, " +
                    "x0 = ${q.x0.fixed(0)}, y0 = ${q.y0.fixed(0)}; δ ${ppm(z.stats.minPpm)}…${ppm(z.stats.maxPpm)} ppm" +
                    (z.boundary?.let { b -> "; граница: " + b.joinToString("; ") { "B ${it.first.fixed(6)}, L ${it.second.fixed(6)}" } } ?: "") + "</li>"
            } + "</ul>"
    }
    val zs = el<HTMLSelectElement>("ldpUseZone")
    zs.innerHTML = r.zones.mapIndexed { i, z -> "<option value=\"$i\">${z.name}</option>" }.joinToString("")
    zs.classList.toggle("hidden", r.zones.isEmpty() || r.fits)
    el<HTMLElement>("ldpProj").textContent = selectedLdp(r).proj
    el<HTMLElement>("ldpUseNote").textContent = ""
    drawLdpMap(r)
}

/** Рабочая проекция для раздела 1: основная LDP или выбранная зона. */
private fun useLdp() {
    val r = ldpResult ?: return
    val p = selectedLdp(r)
    val label = if (r.zones.isEmpty() || r.fits) "LDP" else "LDP, " + r.zones[el<HTMLSelectElement>("ldpUseZone").value.toIntOrNull() ?: 0].name
    workProjections = workProjections.filter { it.first != label } + (label to p)
    val s = el<HTMLSelectElement>("workProj")
    s.innerHTML = "<option value=\"\">TM по центру точек, k = 1</option>" + workProjections.mapIndexed { i, (n, q) ->
        "<option value=\"$i\">${escape(n)}: L0 = ${q.lon0.fixed(4)}°, k0 = ${q.k0}</option>"
    }.joinToString("")
    s.value = (workProjections.size - 1).toString()
    el<HTMLElement>("ldpUseNote").textContent = "Выбрана рабочей проекцией в разделе 1 ($label); датум пересчитан."
    calculate()
}

private fun cssColor(name: String): IntArray {
    val v = window.getComputedStyle(document.documentElement!!).getPropertyValue(name).trim().removePrefix("#")
    if (v.length != 6) return intArrayOf(128, 128, 128)
    return IntArray(3) { v.substring(2 * it, 2 * it + 2).toInt(16) }
}

/**
 * Цвет δ: серый в нуле → синий (план короче местности) / красный (длиннее). Если вся карта в допуске (lim ≤ tol),
 * шкала растягивается на ±lim и не доходит до полной насыщенности (75 %); иначе в допуске — до 55 %, к 2·допуска — полная.
 */
private fun mapColor(v: Double, tol: Double, neg: IntArray, pos: IntArray, mid: IntArray, lim: Double = 2 * tol): String {
    val f = if (lim <= tol) 0.75 * min(abs(v) / lim, 1.0) else {
        val t = min(abs(v) / tol, 2.0)
        if (t <= 1) 0.55 * t else 0.55 + 0.45 * (t - 1)
    }
    val pole = if (v < 0) neg else pos
    val c = IntArray(3) { (mid[it] + (pole[it] - mid[it]) * f).roundToInt() }
    return "#" + c.joinToString("") { it.toString(16).padStart(2, '0') }
}

private fun drawLdpMap(r: LdpResult) {
    val m = r.distortionMap(if (r.contour.kind == "polygon") 56 else 90)
    val neg = cssColor("--map-neg"); val pos = cssColor("--map-pos"); val mid = cssColor("--map-mid")
    val tol = r.tolerance
    val lim = max(m.ppm.maxOf { abs(it) }, 0.5).let { if (it <= tol) it else 2 * tol }
    val dn = (m.north[0] - m.north[m.rows - 1]) / (m.rows - 1)
    val de = (m.east[m.cols - 1] - m.east[0]) / (m.cols - 1)
    val e0 = m.east[0] - de / 2
    val n1 = m.north[0] + dn / 2
    val w = m.cols * de
    val h = m.rows * dn
    val sb = StringBuilder()
    for (j in 0 until m.rows) for (i in 0 until m.cols) {
        val q = j * m.cols + i
        // Ячейки с небольшим перекрытием — без щелей при масштабировании.
        sb.append("<rect x=\"${(i * de).fixed(1)}\" y=\"${(j * dn).fixed(1)}\" width=\"${(de * 1.02).fixed(1)}\" height=\"${(dn * 1.02).fixed(1)}\" fill=\"${mapColor(m.ppm[q], tol, neg, pos, mid, lim)}\"/>")
    }
    fun pt(n: Double, e: Double) = "${(e - e0).fixed(1)},${(n1 - n).fixed(1)}"
    val outline = r.outline.joinToString(" ") { pt(it.first, it.second) }
    sb.append(if (r.contour.kind == "polygon") "<polygon class=\"outline\" points=\"$outline\"/>" else "<polyline class=\"outline\" points=\"$outline\"/>")
    if (!r.fits) for (z in r.zones) {
        val b = z.boundary ?: continue
        val pts = b.map { r.toMapPlane(it.first, it.second) }
        if (pts.size == 2) {
            sb.append("<line class=\"zb\" x1=\"${(pts[0].second - e0).fixed(1)}\" y1=\"${(n1 - pts[0].first).fixed(1)}\" " +
                "x2=\"${(pts[1].second - e0).fixed(1)}\" y2=\"${(n1 - pts[1].first).fixed(1)}\"/>")
        } else {
            // Граница на трассе — поперечная черта через всю карту.
            val x = (pts[0].second - e0).fixed(1)
            sb.append("<line class=\"zb\" x1=\"$x\" y1=\"0\" x2=\"$x\" y2=\"${h.fixed(1)}\"/>")
            sb.append("<circle class=\"zbp\" cx=\"$x\" cy=\"${(n1 - pts[0].first).fixed(1)}\" r=\"${(min(w, h) / 60).fixed(1)}\"/>")
        }
    }
    val svg = document.getElementById("ldpMap")!!
    svg.setAttribute("viewBox", "0 0 ${w.fixed(1)} ${h.fixed(1)}")
    svg.setAttribute("preserveAspectRatio", "xMidYMid meet")
    svg.innerHTML = sb.toString()
    // Подсказка: δ в ближайшем узле.
    val tip = el<HTMLElement>("ldpTip")
    val move: (org.w3c.dom.events.Event) -> Unit = { ev ->
        val me = ev.asDynamic()
        val rect = svg.getBoundingClientRect()
        val sc = min(rect.width / w, rect.height / h)
        val ox = (rect.width - w * sc) / 2
        val oy = (rect.height - h * sc) / 2
        val cx = (me.clientX as Double) - rect.left
        val cy = (me.clientY as Double) - rect.top
        val i = floor(((cx - ox) / sc) / de).toInt()
        val j = floor(((cy - oy) / sc) / dn).toInt()
        if (i in 0 until m.cols && j in 0 until m.rows) {
            val q = j * m.cols + i
            tip.innerHTML = "δ = <b>${ppm(m.ppm[q])} ppm</b> (мм/км)<br>h = ${m.h[q].fixed(1)} м" +
                (if (m.zone[q] > 0) ", зона ${m.zone[q]}" else "") + "<br>B ${m.lat[q].fixed(5)}, L ${m.lon[q].fixed(5)}"
            tip.style.display = "block"
            val tx = cx + 12
            tip.style.left = "${min(tx, rect.width - 170).coerceAtLeast(0.0)}px"
            tip.style.top = "${max(cy - 54, 0.0)}px"
        } else tip.style.display = "none"
    }
    if (svg.getAttribute("data-hover") == null) {
        svg.setAttribute("data-hover", "1")
        svg.addEventListener("pointermove", { mapHover?.invoke(it) })
        svg.addEventListener("pointerdown", { mapHover?.invoke(it) })
        svg.addEventListener("pointerleave", { tip.style.display = "none" })
    }
    mapHover = move
    // Легенда: градиент −lim … +lim (вся карта в допуске) или −2·допуск … +2·допуск.
    val stops = (-8..8).joinToString(",") { k -> val v = k * lim / 8; "${mapColor(v, tol, neg, pos, mid, lim)} ${((k + 8) * 100 / 16.0).fixed(1)}%" }
    val lo = m.ppm.min()
    val hi = m.ppm.max()
    el<HTMLElement>("ldpLegend").innerHTML = "<span>${ppm(-lim)}</span><div class=\"bar\" style=\"background:linear-gradient(90deg,$stops)\"></div>" +
        "<span>${ppm(lim)} ppm</span><span>синий — план короче местности, красный — длиннее; " +
        (if (lim <= tol) "вся карта в допуске ±${tol.fixed(1)}, шкала растянута; " else "бледнее — в допуске ±${tol.fixed(1)}, насыщенно — вне; ") +
        "на карте ${ppm(lo)} … ${ppm(hi)}</span>"
}

/** Экспорт датума: файл и под кнопками — ограничения формата, оценки по объекту, контрольные точки для JobXML. */
private fun exportDatum(format: String) {
    val d = datum ?: return
    val box = el<HTMLElement>("exportNotes")
    try {
        val ts = js("new Date().toISOString().substring(0, 19)") as String
        val r = Export.export(d, format, timestamp = ts)
        download("datum" + r.extension, r.text, if (format == "projjson") "application/json" else if (format == "wkt2") "text/plain" else "application/xml")
        val items = r.warnings.map { escape(it) }.toMutableList()
        if (format == "jxl" && d.b != 0.0) {
            val flipped = Export.checkPoints(d, -1)
            items += "Контрольные точки (ввести B, L на контроллере, сравнить x, y; x′, y′ — при обратном знаке разворота):<br>" +
                Export.checkPoints(d).zip(flipped).joinToString("<br>") { (p, q) ->
                    "${p.name}: B ${p.lat.fixed(9)}, L ${p.lon.fixed(9)} → x ${p.x.fixed(3)}, y ${p.y.fixed(3)} (x′ ${q.x.fixed(3)}, y′ ${q.y.fixed(3)})"
                }
        }
        box.innerHTML = "<ul><li><b>Скачан datum${r.extension}</b></li>" + items.joinToString("") { "<li>$it</li>" } + "</ul>"
    } catch (e: Throwable) {
        box.innerHTML = "<ul><li>Экспорт ${escape(format)}: ${escape(e.message ?: e.toString())}</li></ul>"
    }
}

private fun escape(s: String) = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
