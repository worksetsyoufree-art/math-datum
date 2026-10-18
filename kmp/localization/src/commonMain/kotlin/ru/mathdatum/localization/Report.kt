package ru.mathdatum.localization

import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.atan2
import kotlin.math.floor
import kotlin.math.hypot
import kotlin.math.log10
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.round
import kotlin.math.sqrt

/**
 * HTML-отчёт о локализации для исполнительной документации — тот же отчёт, что mathdatum/report.py
 * (структура, тексты, формат чисел; ключевые величины помечены data-k для сверки с Python).
 * Один самодостаточный файл без внешних ресурсов, печать в PDF на A4 (@media print, @page с колонтитулами).
 * Разделы: титул с метаданными; 1 — исходные данные; 2 — модель и параметры; 3 — точность; 4 — предупреждения;
 * 5 — схема (inline SVG); 6 — экспорт (ограничения форматов, контрольные точки JobXML).
 * Пользовательский текст (имена точек, объект, …) экранируется.
 */
object Report {
    private val USE_TEXT = mapOf(Use.BOTH to "план и высота", Use.PLAN to "план", Use.HEIGHT to "высота", Use.NONE to "контроль")
    private val FIELD_K = doubleArrayOf(0.5, 0.75, 1.0, 1.5, 2.0)
    private val FIELD_COLORS = listOf("#edf3fa", "#d3e2f2", "#b2cbe7", "#8bb0da", "#6693c9", "#4474b5")

    // --- форматирование (как в report.py) ---

    fun esc(s: String) = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        .replace("\"", "&quot;").replace("'", "&#39;")

    /** Текст для content: "…" в @page. */
    fun cssStr(s0: String, limit: Int = 80): String {
        val s = if (s0.length <= limit) s0 else s0.take(limit - 1) + "…"
        return buildString {
            append('"')
            for (ch in s) when {
                ch == '"' || ch == '\\' -> append('\\').append(ch)
                ch == '<' || ch == '>' || ch.code < 0x20 -> append('\\').append(ch.code.toString(16)).append(' ')
                else -> append(ch)
            }
            append('"')
        }
    }

    fun fx(v: Double?, n: Int): String = if (v == null || v.isNaN()) "—" else v.fixed(n)
    fun mm(v: Double?, n: Int = 1): String = if (v == null || v.isNaN()) "—" else (v * 1000).fixed(n)

    fun trim(v: Double): String {
        val s = fx(v, 6).trimEnd('0').trimEnd('.')
        return if (s == "" || s == "-0") "0" else s
    }

    fun dms(deg: Double): String {
        val sign = if (deg < 0) "-" else ""
        val t = round(abs(deg) * 3600 * 1000).toLong()
        val d = t / 3_600_000
        val rest = t % 3_600_000
        val m = rest / 60_000
        val sec = rest % 60_000
        return "$sign$d°${m.toString().padStart(2, '0')}′${(sec / 1000).toString().padStart(2, '0')}.${(sec % 1000).toString().padStart(3, '0')}″"
    }

    /** Наибольшее 1·10ᵏ, 2·10ᵏ, 5·10ᵏ ≤ v. */
    fun niceFloor(v: Double): Double {
        if (!(v > 0)) return 0.0
        val base = 10.0.pow(floor(log10(v)))
        for (m in intArrayOf(5, 2, 1)) if (m * base <= v * (1 + 1e-12)) return m * base
        return base
    }

    private fun k(key: String, text: String, cls: String = "") =
        "<span data-k=\"${esc(key)}\"${if (cls.isNotEmpty()) " class=\"$cls\"" else ""}>$text</span>"

    private fun row(cells: List<String>, cls: String = "") =
        "<tr${if (cls.isNotEmpty()) " class=\"$cls\"" else ""}>" + cells.joinToString("") + "</tr>"

    private fun td(key: String?, text: String, cls: String = "") =
        "<td${if (key != null) " data-k=\"${esc(key)}\"" else ""}${if (cls.isNotEmpty()) " class=\"$cls\"" else ""}>$text</td>"

    private fun table(head: List<String>, rows: List<String>, cls: String = "") =
        "<div class=\"tw\"><table${if (cls.isNotEmpty()) " class=\"$cls\"" else ""}><thead><tr>" +
            head.joinToString("") { "<th>$it</th>" } + "</tr></thead><tbody>" + rows.joinToString("") + "</tbody></table></div>"

    private fun kv(rows: List<Triple<String, String, String?>>) =
        "<table class=\"kv\"><tbody>" + rows.joinToString("") { (k, v, key) -> "<tr><th>$k</th>${td(key, v)}</tr>" } + "</tbody></table>"

    private fun opt(v: String?) = if (v.isNullOrEmpty()) "—" else esc(v)
    private fun fxInt(v: Int?) = v?.toString() ?: "—"

    private fun systemName(d: LocalizationDatum): String {
        val s = d.gnssSystem ?: return "не указана (старый датум)"
        val sy = Datums.system(s)
        return "${sy.name} (эллипсоид ${sy.ellipsoid.name})"
    }

    private fun hullLocal(d: LocalizationDatum): List<Pair<Double, Double>> = d.planHull.orEmpty().map { (n, e) ->
        val dn = n - d.nc
        val de = e - d.ec
        (d.tx + d.a * dn - d.b * de) to (d.ty + d.b * dn + d.a * de)
    }

    /** СКО параметров по априорной σ0: tx, ty (м), масштаб (ppm), разворот (″), c0 (м), c1, c2. */
    private fun paramSigmas(d: LocalizationDatum): Map<String, Double> {
        val out = mutableMapOf<String, Double>()
        d.covariancePlan()?.let { cp ->
            out["s_tx"] = sqrt(cp[0][0]); out["s_ty"] = sqrt(cp[1][1])
            if (d.planModel == "similarity") {
                out["s_scale_ppm"] = sqrt(cp[2][2]) * 1e6
                out["s_rot_arcsec"] = sqrt(cp[3][3]) / d.scale * 180 * 3600 / PI
            }
        }
        d.covarianceHeight()?.let { ch ->
            out["s_c0"] = sqrt(ch[0][0])
            if (d.heightModel == "plane" || d.heightModel == "geoid_plane") {
                out["s_c1"] = sqrt(ch[1][1]); out["s_c2"] = sqrt(ch[2][2])
            }
        }
        return out
    }

    /** Сверка контрольной суммы: (ok | mismatch | none, текст). */
    fun checksumStatus(d: LocalizationDatum): Pair<String, String> = when (d.verifyChecksum()) {
        null -> "none" to "сверить нельзя: в датуме нет исходных данных или суммы (старый формат)"
        true -> "ok" to "совпадает с исходными данными датума"
        false -> "mismatch" to "НЕ СОВПАДАЕТ: исходные данные или параметры в файле изменены после расчёта"
    }

    // --- схема (SVG) ---

    private class Pt(val i: Int, val name: String, val x: Double, val y: Double, val use: Use, val dx: Double, val dy: Double, val sus: Boolean)

    /** Схема расположения пунктов в местной системе (x — север вверх, y — восток вправо). */
    fun schemeSvg(d: LocalizationDatum, pairs: List<LocalizationPair>): String {
        val pts = pairs.zip(d.residuals).mapIndexed { i, (p, r) -> Pt(i, p.name, p.x, p.y, p.use, r.dx, r.dy, r.suspect) }
        val hull = hullLocal(d)
        val xs = pts.map { it.x } + hull.map { it.first }
        val ys = pts.map { it.y } + hull.map { it.second }
        val extN = max(xs.max() - xs.min(), 1.0)
        val extE = max(ys.max() - ys.min(), 1.0)
        val pad = 0.1 * max(extN, extE)
        val n0 = xs.min() - pad; val n1 = xs.min() + extN + pad
        val e0 = ys.min() - pad; val e1 = ys.min() + extE + pad
        val s = min(640 / (e1 - e0), 560 / (n1 - n0))
        val pw = (e1 - e0) * s; val ph = (n1 - n0) * s
        val ox = 20 + (640 - pw) / 2; val oy = 20.0
        val w = 680.0; val h = oy + ph + 120
        fun X(e: Double) = ox + (e - e0) * s
        fun Y(n: Double) = oy + (n1 - n) * s
        fun f(v: Double) = fx(v, 1)

        val o = StringBuilder()
        o.append("<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 ${f(w)} ${f(h)}\" ")
            .append("width=\"680\" height=\"${fx(h, 0)}\" font-family=\"Arial, Helvetica, sans-serif\" font-size=\"11\" ")
            .append("role=\"img\" aria-label=\"Схема расположения пунктов\">")
            .append("<defs><marker id=\"arr\" viewBox=\"0 0 10 10\" refX=\"9\" refY=\"5\" markerWidth=\"7\" markerHeight=\"7\" ")
            .append("orient=\"auto-start-reverse\"><path d=\"M0,0 L10,5 L0,10 z\" fill=\"#c0392b\"/></marker></defs>")
            .append("<rect x=\"${f(ox)}\" y=\"${f(oy)}\" width=\"${f(pw)}\" height=\"${f(ph)}\" fill=\"#ffffff\" ")
            .append("stroke=\"#999999\" stroke-width=\"0.8\"/>")

        // СКО прогноза в плане (априори) — цветом по классам σ0·(0.5, 0.75, 1, 1.5, 2).
        val s0 = d.sigma0Plan
        val field = d.qPlan != null && s0 != null && d.planModel == "similarity"
        val edges = if (field) FIELD_K.map { s0!! * it } else emptyList()
        if (field) {
            val cols = 48
            val rows = max(8, min(64, round(cols * ph / pw).toInt()))
            val cw = pw / cols; val chh = ph / rows
            o.append("<g fill-opacity=\"0.7\" data-k=\"field\">")
            for (j in 0 until rows) {
                val n = n1 - (j + 0.5) * (n1 - n0) / rows
                val cls = IntArray(cols) { i ->
                    val m = d.quality(LocalPoint(n, e0 + (i + 0.5) * (e1 - e0) / cols, 0.0)).mPlan
                    if (m == null || m.isNaN()) 0 else edges.count { m > it }
                }
                var i = 0
                while (i < cols) {
                    var q = i
                    while (q + 1 < cols && cls[q + 1] == cls[i]) q++
                    o.append("<rect x=\"${f(ox + i * cw)}\" y=\"${f(oy + j * chh)}\" width=\"${f((q - i + 1) * cw + 0.3)}\" ")
                        .append("height=\"${f(chh + 0.3)}\" fill=\"${FIELD_COLORS[cls[i]]}\"/>")
                    i = q + 1
                }
            }
            o.append("</g>")
        }

        if (hull.size >= 3) {
            o.append("<polygon points=\"" + hull.joinToString(" ") { (n, e) -> "${f(X(e))},${f(Y(n))}" } +
                "\" fill=\"none\" stroke=\"#333333\" stroke-width=\"1.2\" stroke-dasharray=\"6 4\"/>")
        } else if (hull.size == 2) {
            val (a, b) = hull
            o.append("<line x1=\"${f(X(a.second))}\" y1=\"${f(Y(a.first))}\" x2=\"${f(X(b.second))}\" y2=\"${f(Y(b.first))}\" ")
                .append("stroke=\"#333333\" stroke-width=\"1.2\" stroke-dasharray=\"6 4\"/>")
        }

        // Векторы невязок (каталог − вычисленное) в увеличенном масштабе.
        val maxv = pts.filter { it.use != Use.HEIGHT }.maxOfOrNull { hypot(it.dx, it.dy) } ?: 0.0
        val exag = if (maxv > 1e-6) niceFloor(0.12 * max(n1 - n0, e1 - e0) / maxv) else 0.0
        if (exag > 0) for (p in pts) {
            if (p.use == Use.HEIGHT || hypot(p.dx, p.dy) * exag * s < 0.5) continue
            o.append("<line x1=\"${f(X(p.y))}\" y1=\"${f(Y(p.x))}\" x2=\"${f(X(p.y + p.dy * exag))}\" ")
                .append("y2=\"${f(Y(p.x + p.dx * exag))}\" stroke=\"#c0392b\" stroke-width=\"1.6\" marker-end=\"url(#arr)\"/>")
        }

        for (p in pts) {
            val cx = X(p.y); val cy = Y(p.x)
            if (p.use == Use.NONE) {
                o.append("<circle cx=\"${f(cx)}\" cy=\"${f(cy)}\" r=\"5\" fill=\"#ffffff\" stroke=\"#1d1d1b\" stroke-width=\"1.6\"/>")
            } else {
                o.append("<polygon points=\"${f(cx)},${f(cy - 6)} ${f(cx + 5.5)},${f(cy + 4)} ${f(cx - 5.5)},${f(cy + 4)}\" fill=\"#1d1d1b\"/>")
            }
            if (p.sus) o.append("<circle cx=\"${f(cx)}\" cy=\"${f(cy)}\" r=\"10\" fill=\"none\" stroke=\"#c0392b\" stroke-width=\"1.6\"/>")
            o.append("<text x=\"${f(cx + 8)}\" y=\"${f(cy - 7)}\" data-k=\"svg.${p.i}\">${esc(p.name)}</text>")
        }

        // Север (ось x) — справа вверху.
        val ax = ox + pw - 22; val ay = oy + 14
        o.append("<g stroke=\"#1d1d1b\" fill=\"#1d1d1b\"><line x1=\"${f(ax)}\" y1=\"${f(ay + 40)}\" x2=\"${f(ax)}\" ")
            .append("y2=\"${f(ay + 6)}\" stroke-width=\"1.6\"/><polygon points=\"${f(ax)},${f(ay)} ${f(ax + 6)},")
            .append("${f(ay + 12)} ${f(ax - 6)},${f(ay + 12)}\" stroke=\"none\"/></g>")
            .append("<text x=\"${f(ax)}\" y=\"${f(ay + 54)}\" text-anchor=\"middle\" font-weight=\"bold\">С (x)</text>")

        // Масштабная линейка.
        val len = niceFloor(0.25 * (e1 - e0))
        val lp = len * s
        val by = oy + ph + 26
        o.append("<g data-k=\"scalebar\"><rect x=\"20\" y=\"${f(by)}\" width=\"${f(lp / 2)}\" height=\"6\" fill=\"#1d1d1b\"/>")
            .append("<rect x=\"${f(20 + lp / 2)}\" y=\"${f(by)}\" width=\"${f(lp / 2)}\" height=\"6\" fill=\"#ffffff\" ")
            .append("stroke=\"#1d1d1b\" stroke-width=\"1\"/>")
            .append("<text x=\"20\" y=\"${f(by - 4)}\">0</text>")
            .append("<text x=\"${f(20 + lp)}\" y=\"${f(by - 4)}\" text-anchor=\"middle\">${dist(len)}</text></g>")
        val lx = 40 + lp + 30
        if (exag > 0) {
            val ref = niceFloor(maxv)
            val rl = ref * exag * s
            o.append("<line x1=\"${f(lx)}\" y1=\"${f(by + 3)}\" x2=\"${f(lx + rl)}\" y2=\"${f(by + 3)}\" ")
                .append("stroke=\"#c0392b\" stroke-width=\"1.6\" marker-end=\"url(#arr)\"/>")
                .append("<text x=\"${f(lx + rl + 8)}\" y=\"${f(by + 7)}\">невязка ${trim(ref * 1000)} мм ")
                .append("(векторы увеличены в ${trim(exag)} раз)</text>")
        } else {
            o.append("<text x=\"${f(lx)}\" y=\"${f(by + 7)}\">невязки в плане нулевые (нет избыточности)</text>")
        }

        val ly = by + 34
        o.append("<polygon points=\"26,${f(ly - 6)} 31.5,${f(ly + 4)} 20.5,${f(ly + 4)}\" fill=\"#1d1d1b\"/>")
            .append("<text x=\"38\" y=\"${f(ly + 4)}\">опорный пункт</text>")
            .append("<circle cx=\"146\" cy=\"${f(ly)}\" r=\"5\" fill=\"#ffffff\" stroke=\"#1d1d1b\" stroke-width=\"1.6\"/>")
            .append("<text x=\"156\" y=\"${f(ly + 4)}\">контрольный пункт</text>")
            .append("<circle cx=\"286\" cy=\"${f(ly)}\" r=\"8\" fill=\"none\" stroke=\"#c0392b\" stroke-width=\"1.6\"/>")
            .append("<text x=\"298\" y=\"${f(ly + 4)}\">подозрение на грубую ошибку</text>")
            .append("<line x1=\"480\" y1=\"${f(ly)}\" x2=\"510\" y2=\"${f(ly)}\" stroke=\"#333333\" stroke-width=\"1.2\" ")
            .append("stroke-dasharray=\"6 4\"/><text x=\"516\" y=\"${f(ly + 4)}\">выпуклая оболочка</text>")
        if (field) {
            val fy = ly + 26
            o.append("<text x=\"20\" y=\"${f(fy + 4)}\">СКО прогноза в плане, мм:</text>")
            val labels = listOf("≤ ${mm(edges[0], 0)}") + edges.zipWithNext { a, b -> "${mm(a, 0)}–${mm(b, 0)}" } +
                listOf("&gt; ${mm(edges.last(), 0)}")
            FIELD_COLORS.zip(labels).forEachIndexed { q, (c, t) ->
                val x = 180 + q * 80
                o.append("<rect x=\"$x\" y=\"${f(fy - 6)}\" width=\"16\" height=\"12\" fill=\"$c\" stroke=\"#999999\" ")
                    .append("stroke-width=\"0.5\"/><text x=\"${x + 21}\" y=\"${f(fy + 4)}\">$t</text>")
            }
        }
        o.append("</svg>")
        return o.toString()
    }

    private fun dist(m: Double) = if (m >= 1000) "${trim(m / 1000)} км" else "${trim(m)} м"

    private val CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; background: #ecebe7; color: #1d1d1b; font: 10pt/1.45 Arial, Helvetica, sans-serif; }
.page { max-width: 210mm; margin: 0 auto; background: #ffffff; padding: 14mm 14mm 18mm; }
h1 { font-size: 18pt; margin: 2mm 0 4mm; overflow-wrap: anywhere; }
h2 { font-size: 13pt; margin: 8mm 0 3mm; border-bottom: 1.5px solid #1d1d1b; padding-bottom: 1mm; break-after: avoid; }
h3 { font-size: 11pt; margin: 5mm 0 2mm; break-after: avoid; }
p { margin: 0 0 2.5mm; }
.kicker { text-transform: uppercase; letter-spacing: .08em; color: #555; font-size: 9pt; }
.hint { color: #555; font-size: 8.5pt; }
.tw { overflow-x: auto; margin: 0 0 3mm; }
table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
th, td { border: 0.6pt solid #b8b6ae; padding: 1.2mm 1.6mm; text-align: right; vertical-align: top; }
thead th { background: #f0efea; font-weight: bold; text-align: center; }
td.l, th.l { text-align: left; }
td.nw { white-space: nowrap; }
tr.ctl td { color: #555; }
table.data { font-size: 8pt; }
table.data td:nth-child(2) { text-align: left; overflow-wrap: anywhere; }
table.kv th { text-align: left; font-weight: normal; color: #444; width: 42%; background: #f7f6f2; }
table.kv td { text-align: left; overflow-wrap: anywhere; }
tr { break-inside: avoid; }
thead { display: table-header-group; }
tr.sus td { background: #fbe9e7; }
tr.sus td.flag { color: #b3261e; font-weight: bold; }
td.bad { color: #b3261e; font-weight: bold; }
.mono { font-family: "Courier New", monospace; font-size: 8pt; overflow-wrap: anywhere; word-break: break-all; }
.summary { display: grid; grid-template-columns: repeat(4, 1fr); gap: 2mm; margin: 4mm 0; }
.summary div { border: 0.6pt solid #b8b6ae; padding: 2mm; }
.summary b { display: block; font-size: 12pt; }
.summary span.k { color: #555; font-size: 8pt; }
.alert { border: 1.5pt solid #b3261e; background: #fdf1ef; padding: 3mm; margin: 3mm 0; break-inside: avoid; }
.ok { color: #1e7a3c; font-weight: bold; }
.badtxt { color: #b3261e; font-weight: bold; }
ul.warn { margin: 0 0 3mm; padding-left: 6mm; }
ul.warn li { margin: 1mm 0; overflow-wrap: anywhere; }
figure { margin: 0; break-inside: avoid; }
figure svg { display: block; width: 100%; height: auto; max-height: 230mm; }
figcaption { font-size: 8.5pt; color: #444; margin-top: 2mm; }
.title { break-after: page; }
.sign { margin-top: 10mm; break-inside: avoid; }
.sign td, .sign th { border: none; text-align: left; padding: 3mm 2mm; }
.newpage { break-before: page; }
.foot { margin-top: 8mm; font-size: 8pt; color: #666; border-top: 0.6pt solid #b8b6ae; padding-top: 2mm; overflow-wrap: anywhere; }
@media (max-width: 600px) {
  .page { padding: 16px; }
  .summary { grid-template-columns: repeat(2, 1fr); }
}
@media print {
  body { background: #ffffff; font-size: 9.5pt; }
  .page { max-width: none; padding: 0; margin: 0; }
  .tw { overflow: visible; }
  table.data { font-size: 7.5pt; }
  th, td { padding: 0.8mm 1.2mm; }
  a { color: inherit; text-decoration: none; }
}
"""

    private fun pageCss(d: LocalizationDatum): String {
        val m = d.meta
        val obj = m?.objectName?.takeIf { it.isNotEmpty() } ?: "Объект не указан"
        val did = m?.datumId?.takeIf { it.isNotEmpty() } ?: "без идентификатора"
        val rev = m?.revision?.takeIf { it != 0 }?.let { ", ревизия $it" } ?: ""
        return "@page { size: A4; margin: 16mm 14mm 18mm 16mm;" +
            " @top-left { content: \"Отчёт о локализации ГНСС\"; font: 8pt Arial, sans-serif; color: #666; }" +
            " @top-right { content: ${cssStr(obj)}; font: 8pt Arial, sans-serif; color: #666; }" +
            " @bottom-left { content: ${cssStr("Датум $did$rev")}; font: 7.5pt Arial, sans-serif; color: #666; }" +
            " @bottom-right { content: \"стр. \" counter(page) \" из \" counter(pages); font: 8pt Arial, sans-serif; color: #666; } }"
    }

    /**
     * HTML-отчёт по датуму [d]. [pairs] — исходные пары (по умолчанию [LocalizationDatum.pairs]; для старого датума —
     * из CSV); [generatedAt] — время формирования (UTC, ISO 8601), по умолчанию — текущее.
     */
    fun html(d: LocalizationDatum, pairs: List<LocalizationPair>? = null, generatedAt: String? = null,
             library: String = MATHDATUM_LIBRARY): String {
        var ps = pairs ?: d.pairs
        val notes = mutableListOf<String>()
        if (ps != null && ps.map { it.name } != d.residuals.map { it.name }) {
            notes += "Пары точек не соответствуют невязкам датума (другие имена или порядок) — исходные данные и схема не показаны."
            ps = null
        }
        if (ps == null && d.pairs == null) {
            notes += "В датуме нет исходных пар точек (старый формат): разделы «Исходные данные» и «Схема» неполные — " +
                "укажите исходные пары (CSV) или пересчитайте датум."
        }
        val m = d.meta
        val gen = generatedAt ?: DatumChecksum.nowUtc()
        val (csCode, csText) = checksumStatus(d)
        if (csCode == "mismatch") notes += "Контрольная сумма исходных данных не совпадает: файл датума изменён после расчёта."
        val obj = m?.objectName?.takeIf { it.isNotEmpty() }
        val res = d.residuals
        val ref = res.filter { it.use != Use.NONE }
        val ctl = res.withIndex().filter { it.value.use == Use.NONE }
        val o = mutableListOf(
            "<!DOCTYPE html>", "<html lang=\"ru\"><head><meta charset=\"utf-8\">",
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
            "<title>Отчёт о локализации ГНСС — ${esc(obj ?: "объект не указан")}</title>",
            "<style>$CSS${pageCss(d)}</style></head><body><div class=\"page\">",
        )

        // --- титул ---
        o += "<header class=\"title\"><div class=\"kicker\">Отчёт о локализации ГНСС</div>"
        o += "<h1>${k("object", if (obj != null) esc(obj) else "Объект не указан")}</h1>"
        val rev = if (m?.revision != null && m.revision != 0) {
            k("revision", m.revision.toString()) +
                (m.previousId?.takeIf { it.isNotEmpty() }?.let { " (предыдущая ревизия: ${k("previous_id", esc(it), "mono")})" } ?: "")
        } else "—"
        val csCls = when (csCode) { "ok" -> "ok"; "mismatch" -> "badtxt"; else -> "hint" }
        o += kv(listOf(
            Triple("Организация", opt(m?.organization), "organization"),
            Triple("Исполнитель", opt(m?.author), "author"),
            Triple("Дата и время расчёта (UTC)", opt(m?.computedAt), "computed_at"),
            Triple("Отчёт сформирован (UTC)", esc(gen), null),
            Triple("Идентификатор датума (UUID)", k("datum_id", opt(m?.datumId), "mono"), null),
            Triple("Ревизия", rev, null),
            Triple("Источник каталога пунктов", opt(m?.catalogSource), "catalog_source"),
            Triple("Система ГНСС, оборудование, базовая станция", opt(m?.gnssEquipment), "gnss_equipment"),
            Triple("Система ГНСС-координат пар", esc(systemName(d)), null),
            Triple("Расчёт выполнен", opt(m?.libraryVersion), "library_version"),
            Triple("Отчёт составлен", esc(library), null),
            Triple("Контрольная сумма исходных данных (SHA-256 пар и параметров)",
                k("inputs_sha256", opt(m?.inputsSha256), "mono") + "<br>" + k("checksum_status", esc(csText), csCls), null),
            Triple("Примечание", opt(m?.note), "note"),
        ))
        val nSus = res.count { it.suspect }
        o += "<div class=\"summary\">" +
            "<div><span class=\"k\">СКО в плане</span><b>${k("rms_plan_mm", mm(d.rmsPlan))} мм</b></div>" +
            "<div><span class=\"k\">СКО по высоте</span><b>${k("rms_height_mm", mm(d.rmsHeight))} мм</b></div>" +
            "<div><span class=\"k\">Масштаб</span><b>${k("scale_ppm", fx(d.scalePpm, 3))} ppm</b></div>" +
            "<div><span class=\"k\">Разворот</span><b>${k("rotation_arcsec", fx(d.rotationArcsec, 3))}″</b></div>" +
            "<div><span class=\"k\">Опорных пунктов</span><b>${k("n_ref", ref.size.toString())}</b></div>" +
            "<div><span class=\"k\">Контрольных пунктов</span><b>${k("n_control", ctl.size.toString())}</b></div>" +
            "<div><span class=\"k\">Подозрительных точек</span><b>${k("n_suspect", nSus.toString())}</b></div>" +
            "<div><span class=\"k\">Предупреждений</span><b>${k("n_warnings", d.warnings.size.toString())}</b></div></div>"
        if (notes.isNotEmpty()) o += "<div class=\"alert\">" + notes.joinToString("<br>") { esc(it) } + "</div>"
        o += "<p class=\"hint\">Единицы: координаты и высоты — м, невязки и СКО в таблицах — мм, B и L — градусы, " +
            "масштаб — ppm (мм/км), разворот — угловые секунды. x — север, y — восток. Невязка = каталог − вычисленное.</p>"
        o += "</header>"

        // --- 1. исходные данные ---
        val inp = d.inputs
        o += "<section><h2>1. Исходные данные</h2><h3>1.1. Параметры расчёта</h3>"
        o += kv(listOf(
            Triple("Система ГНСС-координат", esc(systemName(d)), null),
            Triple("Априорная СКО координаты в плане σ0 (единица веса), мм", mm(d.sigma0Plan), "sigma0_plan_mm"),
            Triple("Априорная СКО высоты σ0, мм", mm(d.sigma0Height), "sigma0_height_mm"),
            Triple("Порог нормированной поправки |w| (тест Баарда)", fx(d.wLimit, 2), "w_limit"),
            Triple("Пределы правдоподобия: масштаб, ppm / разворот, °",
                if (inp == null) "—" else "${fx(inp.maxScalePpm, 0)} / ${fx(inp.maxRotationDeg, 1)}", null),
            Triple("Запрошенная модель высоты", if (inp == null) "—" else esc(inp.heightModel), null),
        ))
        o += "<h3>1.2. Пары точек</h3>"
        if (ps == null) {
            o += "<p class=\"hint\">Исходные пары в датуме не сохранены.</p>"
        } else {
            val rows = ps.mapIndexed { i, p ->
                val ownP = p.sigmaPlan != null
                val ownH = p.sigmaHeight != null
                row(listOf(
                    td(null, "${i + 1}"), td("p$i.name", esc(p.name)), td("p$i.B", fx(p.lat, 10)),
                    td("p$i.L", fx(p.lon, 10)), td("p$i.h", fx(p.h, 4)), td("p$i.x", fx(p.x, 4)),
                    td("p$i.y", fx(p.y, 4)), td("p$i.H", fx(p.height, 4)), td("p$i.use", USE_TEXT.getValue(p.use), "l"),
                    td("p$i.sp", mm(if (ownP) p.sigmaPlan else d.sigma0Plan) + if (ownP) "*" else ""),
                    td("p$i.sh", mm(if (ownH) p.sigmaHeight else d.sigma0Height) + if (ownH) "*" else ""),
                ), if (p.use == Use.NONE) "ctl" else "")
            }
            o += table(listOf("№", "Пункт", "B, °", "L, °", "h, м", "x, м", "y, м", "H, м", "Использование",
                "σ план, мм", "σ выс., мм"), rows, "data")
            o += "<p class=\"hint\">B, L, h — ГНСС (h — эллипсоидальная высота); x, y, H — каталог местной системы. " +
                "σ — априорная СКО точки (план — на одну координату); * — своя σ точки (вес p = σ0²/σ²), без * — σ0. " +
                "«Контроль» — точка не участвует в расчёте, по ней оценивается датум.</p>"
        }
        o += "</section>"

        // --- 2. модель ---
        val sg = paramSigmas(d)
        val defaultTm = d.k0 == 1.0 && d.x0 == 0.0 && d.y0 == 0.0
        o += "<section><h2>2. Модель и параметры</h2><h3>2.1. Рабочая проекция</h3>"
        o += kv(listOf(
            Triple("Тип", if (defaultTm) "поперечная Меркатора по центру точек, k = 1"
                else "поперечная Меркатора с заданными параметрами (малоискажающая проекция, LDP)", null),
            Triple("Широта начала B0, °", fx(d.lat0, 9), "lat0"),
            Triple("Осевой меридиан L0, °", fx(d.lon0, 9), "lon0"),
            Triple("Масштаб на осевом меридиане k0", fx(d.k0, 9), "k0"),
            Triple("Ложные смещения x0 (север) / y0 (восток), м", "${k("x0", fx(d.x0, 3))} / ${k("y0", fx(d.y0, 3))}", null),
            Triple("Эллипсоид (PROJ)", esc(d.ellipsoid), null),
            Triple("Строка PROJ", "<span class=\"mono\">${esc(d.projection)}</span>", null),
        ))
        o += "<h3>2.2. План: преобразование подобия</h3><p class=\"hint\">x = tx + a·(N − Nc) − b·(E − Ec), " +
            "y = ty + b·(N − Nc) + a·(E − Ec); N, E — рабочая проекция, Nc, Ec — взвешенный центроид. " +
            "СКО параметров — по априорной σ0.</p>"
        o += kv(listOf(
            Triple("Модель", if (d.planModel == "similarity") "подобие (4 параметра)" else "только сдвиг (1 точка)", "plan_model"),
            Triple("Масштаб m = √(a² + b²)", "${k("scale", fx(d.scale, 10))} (${k("scale_ppm2", fx(d.scalePpm, 3))} ppm; " +
                "СКО ${k("s_scale_ppm", fx(sg["s_scale_ppm"], 3))} ppm)", null),
            Triple("Разворот θ = atan2(b, a)", "${k("rotation_arcsec2", fx(d.rotationArcsec, 3))}″ = ${dms(d.rotationArcsec / 3600)} " +
                "(СКО ${k("s_rot_arcsec", fx(sg["s_rot_arcsec"], 3))}″)", null),
            Triple("a / b", "${k("a", fx(d.a, 12))} / ${k("b", fx(d.b, 12))}", null),
            Triple("Сдвиг tx (север), м", "${k("tx", fx(d.tx, 4))} (СКО ${k("s_tx_mm", mm(sg["s_tx"]))} мм)", null),
            Triple("Сдвиг ty (восток), м", "${k("ty", fx(d.ty, 4))} (СКО ${k("s_ty_mm", mm(sg["s_ty"]))} мм)", null),
            Triple("Центроид Nc / Ec, м", "${k("Nc", fx(d.nc, 4))} / ${k("Ec", fx(d.ec, 4))}", null),
        ))
        val hmText = when (d.heightModel) {
            "plane" -> "наклонная плоскость: H = h + c0 + c1·dN + c2·dE"
            "shift" -> "сдвиг: H = h + c0 (мало точек для плоскости)"
            "geoid" -> "геоид и сдвиг: H = h − N(B, L) + c0"
            "geoid_plane" -> "геоид и остаточная плоскость: H = h − N(B, L) + c0 + c1·dN + c2·dE"
            "none" -> "нет (не было точек для высоты)"
            else -> d.heightModel
        }
        o += "<h3>2.3. Высота</h3>"
        val hrows = mutableListOf(Triple("Модель", esc(hmText), "height_model" as String?))
        if (d.heightModel != "none") {
            hrows += Triple("Сдвиг c0, м", "${k("c0", fx(d.c0, 4))} (СКО ${k("s_c0_mm", mm(sg["s_c0"]))} мм)", null)
            hrows += Triple("Наклон по северу c1, мм/км", "${k("c1_mmkm", fx(d.c1 * 1e6, 3))} (СКО ${k("s_c1_mmkm", fx(sg["s_c1"]?.times(1e6), 3))})", null)
            hrows += Triple("Наклон по востоку c2, мм/км", "${k("c2_mmkm", fx(d.c2 * 1e6, 3))} (СКО ${k("s_c2_mmkm", fx(sg["s_c2"]?.times(1e6), 3))})", null)
        }
        d.geoid?.let { g ->
            hrows += Triple("Сетка геоида", esc(g.file), "geoid_file")
            hrows += Triple("SHA-256 сетки", k("geoid_sha256", esc(g.sha256), "mono"), null)
            hrows += Triple("Интерполяция", if (g.interpolation == "bilinear") "билинейная" else "бикубическая", "geoid_interp")
        }
        o += kv(hrows) + "</section>"

        // --- 3. точность ---
        o += "<section><h2>3. Точность</h2>"
        o += kv(listOf(
            Triple("СКО в плане (радиальная) / по высоте, мм", "${k("rms_plan_mm2", mm(d.rmsPlan))} / ${k("rms_height_mm2", mm(d.rmsHeight))}", null),
            Triple("Избыточность: план / высота", "${k("redundancy_plan", fxInt(d.redundancyPlan))} / " +
                k("redundancy_height", fxInt(d.redundancyHeight)), null),
            Triple("СКО единицы веса s0 (апостериори, на координату): план / высота, мм",
                "${k("s0_plan_mm", mm(d.s0Plan))} / ${k("s0_height_mm", mm(d.s0Height))}", null),
        ))
        val lim = d.wLimit ?: Double.POSITIVE_INFINITY
        val rrows = res.mapIndexedNotNull { i, r ->
            if (r.use == Use.NONE) return@mapIndexedNotNull null
            val bp = r.wPlan?.let { it > lim } == true
            val bh = r.wH?.let { abs(it) > lim } == true
            val cp = if (bp) "bad" else ""
            val chh = if (bh) "bad" else ""
            row(listOf(
                td(null, "${i + 1}"), td("r$i.name", esc(r.name)), td(null, USE_TEXT.getValue(r.use), "l nw"),
                td("r$i.dx", mm(r.dx), cp), td("r$i.dy", mm(r.dy), cp),
                td("r$i.dp", mm(hypot(r.dx, r.dy)), cp), td("r$i.dH", mm(r.dH), chh),
                td("r$i.wp", fx(r.wPlan, 2), cp), td("r$i.wH", fx(r.wH?.let(::abs), 2), chh),
                td("r$i.loop", mm(r.looPlan)), td("r$i.looH", mm(r.looDH?.let(::abs))),
                td("r$i.flag", if (r.suspect) "⚠ подозрение" else "", "flag l"),
            ), if (r.suspect) "sus" else "")
        }
        o += "<h3>3.1. Невязки на опорных пунктах</h3>"
        o += if (rrows.isNotEmpty()) table(listOf("№", "Пункт", "Исп.", "dx, мм", "dy, мм", "Δплан, мм", "dH, мм", "|w| план",
            "|w| выс.", "Без точки: план, мм", "Без точки: |dH|, мм", "Отметка"), rrows, "data")
        else "<p class=\"hint\">Опорных пунктов нет.</p>"
        o += "<p class=\"hint\">|w| — нормированная поправка (тест Баарда), план — max(|wx|, |wy|); порог ${fx(d.wLimit, 2)} " +
            "(α ≈ 0.001): выше — вероятна грубая ошибка («⚠», точки автоматически не исключаются). «Без точки» — " +
            "ошибка прогноза в точке датумом, рассчитанным без неё (leave-one-out); «—» — проверить нельзя.</p>"

        o += "<h3>3.2. Контрольные пункты</h3>"
        if (ctl.isEmpty()) {
            o += "<p class=\"hint\">Контрольных пунктов (use = none) нет — независимой проверки датума нет.</p>"
        } else {
            val crows = ctl.map { (i, r) ->
                val bp = r.wPlan?.let { it > lim } == true
                val bh = r.wH?.let { abs(it) > lim } == true
                val cp = if (bp) "bad" else ""
                val chh = if (bh) "bad" else ""
                val q = ps?.get(i)?.let { d.quality(WgsPoint(it.lat, it.lon, it.h)) }
                row(listOf(
                    td(null, "${i + 1}"), td("c$i.name", esc(r.name)),
                    td("c$i.dx", mm(r.dx), cp), td("c$i.dy", mm(r.dy), cp),
                    td("c$i.dp", mm(hypot(r.dx, r.dy)), cp), td("c$i.dH", mm(r.dH), chh),
                    td("c$i.wp", fx(r.wPlan, 2), cp), td("c$i.wH", fx(r.wH?.let(::abs), 2), chh),
                    td("c$i.mp", mm(q?.mPlan)), td("c$i.mH", mm(q?.mHeight)),
                    td("c$i.out", fx(q?.outside, 1)),
                    td("c$i.flag", if (r.suspect) "⚠ превышение" else "норма", "flag l"),
                ), if (r.suspect) "sus" else "")
            }
            o += table(listOf("№", "Пункт", "dx, мм", "dy, мм", "Δплан, мм", "dH, мм", "|w| план", "|w| выс.",
                "СКО прогноза план, мм", "СКО прогноза H, мм", "Вне оболочки, м", "Оценка"), crows, "data")
            o += "<p class=\"hint\">Для контрольных пунктов невязка — ошибка прогноза датума; |w| — она же, нормированная " +
                "по ожидаемой СКО (σ0 точки и прогноза); «Вне оболочки» — расстояние до выпуклой оболочки опорных пунктов " +
                "(0 — внутри, иначе экстраполяция). СКО прогноза — по априорной σ0.</p>"
        }
        o += "</section>"

        // --- 4. предупреждения ---
        o += "<section><h2>4. Предупреждения</h2>"
        o += if (d.warnings.isNotEmpty() || notes.isNotEmpty()) {
            "<ul class=\"warn\" data-k=\"warnings\">" + d.warnings.joinToString("") { "<li>${esc(it.message)}</li>" } +
                notes.joinToString("") { "<li>${esc(it)}</li>" } + "</ul>"
        } else "<p data-k=\"warnings\">Предупреждений нет.</p>"
        o += "</section>"

        // --- 5. схема ---
        o += "<section class=\"newpage\"><h2>5. Схема расположения пунктов</h2>"
        o += if (ps == null) "<p class=\"hint\">Схема не построена: нет координат пунктов (исходных пар).</p>"
        else "<figure>" + schemeSvg(d, ps) + "<figcaption>Местная система: x — север (вверх), y — восток. " +
            "Векторы — невязки в плане (каталог − вычисленное) в увеличенном масштабе; фон — ожидаемая СКО " +
            "прогноза в плане по априорной σ0 (растёт при удалении от опорных пунктов и за оболочкой).</figcaption></figure>"
        o += "</section>"

        // --- 6. экспорт ---
        o += exportSection(d)

        // --- подписи ---
        o += "<table class=\"sign\"><tbody>" +
            "<tr><th>Исполнитель</th><td>_______________ / ${opt(m?.author)} /</td><td>Дата: ____________</td></tr>" +
            "<tr><th>Проверил</th><td>_______________ / ____________________ /</td><td>Дата: ____________</td></tr>" +
            "</tbody></table>"
        o += "<div class=\"foot\">Датум ${opt(m?.datumId)}; SHA-256 исходных данных ${opt(m?.inputsSha256)}. " +
            "Отчёт сформирован ${esc(gen)} (${esc(library)}).</div>"
        o += "</div></body></html>\n"
        return o.joinToString("\n")
    }

    private val EXPORT_DESC = listOf(
        "wkt2" to ("WKT2 (ISO 19162:2019)" to "План — стандартные методы EPSG (TM + подобие EPSG 9621; при развороте " +
            "< 0.1 мм на объекте — обычный PROJCRS). Высота — «PROJ-based operation method»: применит только ПО на " +
            "PROJ ≥ 6 (QGIS, GDAL, pyproj)."),
        "projjson" to ("PROJJSON" to "То же, что WKT2, в JSON (схема PROJ 0.7)."),
        "jxl" to ("Trimble JobXML 6.30" to "TM с масштабом подобия, горизонтальная корректировка (разворот вокруг tx, ty), " +
            "вертикальная — наклонная плоскость / геоид и плоскость. Знак разворота — по документации Trimble."),
        "landxml" to ("LandXML 1.2" to "Параметров локализации в схеме нет: WKT2 передаётся строкой в ogcWktCode."),
        "proj" to ("Строка PROJ" to "Пайплайн для cs2cs / pyproj / QGIS — точно."),
    )

    private fun exportSection(d: LocalizationDatum): String {
        val o = StringBuilder()
        o.append("<section class=\"newpage\"><h2>6. Экспорт датума</h2>")
            .append("<p class=\"hint\">Датум можно передать в ПО командой <code>python -m mathdatum export datum.json --format …</code> ")
            .append("(или кнопками веб-приложения). Ограничения форматов и оценки по объекту:</p>")
        val rows = EXPORT_DESC.map { (f, nt) ->
            val (name, text) = nt
            val w = try {
                Export.export(d, f).warnings
            } catch (e: ExportException) {
                listOf("Экспорт невозможен: ${e.message}")
            }
            val items = w.joinToString("") { "<li>${esc(it)}</li>" }
            row(listOf(td(null, "<b>$name</b>", "l"),
                td("export.$f", esc(text) + if (items.isNotEmpty()) "<ul class=\"warn\">$items</ul>" else "", "l")))
        }
        o.append(table(listOf("Формат", "Ограничения и оценки по объекту"), rows, "data exp"))
        o.append("<p class=\"hint\">Закрытые форматы (Trimble .cal/.dc, Topcon .gc3/.tp3, Carlson .loc, Leica HeXML, gsimath) ")
            .append("не поддерживаются — что нужно для их поддержки, см. docs/export.md.</p>")
        val th = atan2(d.b, d.a) * 180 / PI * 3600
        o.append("<div class=\"alert\" data-k=\"jxl_alert\"><b>ВНИМАНИЕ (Trimble JobXML).</b> Знак разворота в JobXML не ")
            .append("подтверждён на контроллере: он взят по Trimble Access Calculations Reference, образца JobXML с калибровкой ")
            .append("в открытом доступе нет. Разворот датума ${fx(th, 3)}″. Перед работой введите на контроллере B, L ")
            .append("контрольных точек из таблицы ниже и сравните полученные x, y. Совпали x, y — экспорт верен; совпали x′, y′ ")
            .append("(обратный знак разворота) — файл JobXML не использовать.")
            .append(if (d.b == 0.0) " Разворот равен 0 — знак на результат не влияет, проверка всё равно рекомендуется." else "")
            .append("</div>")
        val (cp, cf) = try {
            Export.checkPoints(d) to Export.checkPoints(d, -1)
        } catch (e: Exception) {
            o.append("<p class=\"hint\">Контрольные точки не вычислены: ${esc(e.message ?: e.toString())}</p>")
            emptyList<CheckPoint>() to emptyList()
        }
        if (cp.isNotEmpty()) {
            val rows2 = cp.zip(cf).mapIndexed { q, (p, f) ->
                row(listOf(td("chk$q.name", esc(p.name), "l"), td("chk$q.B", fx(p.lat, 10)), td("chk$q.L", fx(p.lon, 10)),
                    td("chk$q.x", fx(p.x, 3)), td("chk$q.y", fx(p.y, 3)), td("chk$q.x2", fx(f.x, 3)), td("chk$q.y2", fx(f.y, 3))))
            }
            o.append(table(listOf("Точка", "B, °", "L, °", "x, м", "y, м", "x′, м", "y′, м"), rows2, "data"))
            o.append("<p class=\"hint\">C — центроид опорных пунктов, V1… — вершины их выпуклой оболочки; B, L — в системе ГНСС ")
                .append("датума; x, y — по датуму; x′, y′ — что покажет контроллер при обратной трактовке знака разворота.</p>")
        }
        o.append("<h3>Строка PROJ (ГНСС → местная)</h3><p class=\"mono\">${esc(d.toProjPipeline())}</p></section>")
        return o.toString()
    }
}
