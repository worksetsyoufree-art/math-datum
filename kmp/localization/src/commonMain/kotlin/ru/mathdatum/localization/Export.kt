package ru.mathdatum.localization

import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.atan2
import kotlin.math.floor
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.sin

/*
 * Экспорт датума локализации (те же тексты, что mathdatum/export.py):
 *  wkt2      ISO 19162:2019 — DERIVEDPROJCRS (TM EPSG 9807 + Similarity transformation EPSG 9621) или,
 *            если разворот на объекте < 0.1 мм, PROJCRS со свёрнутым масштабом; высота — BOUNDCRS с методом
 *            «PROJ-based operation method» (плоскость, vgridshift) — точно только для ПО на PROJ ≥ 6;
 *  projjson  то же в PROJJSON;
 *  jxl       Trimble JobXML 6.30: TM с k0·M, PlaneAdjustment (поворот вокруг tx, ty), InclinedPlane /
 *            GeoidModelAndInclinedPlane; знак разворота — по Trimble Access Calculations Reference;
 *  landxml   LandXML 1.2 с WKT2 в ogcWktCode;
 *  proj      строка PROJ-пайплайна.
 * Закрытые форматы — ExportException с объяснением (docs/export.md).
 */

class ExportException(message: String) : IllegalArgumentException(message)

/** Результат экспорта: текст файла и ограничения / оценки погрешности по объекту. */
data class ExportResult(val format: String, val text: String, val warnings: List<String>) {
    val extension: String get() = Export.EXTENSIONS.getValue(format)
}

/** Контрольная точка для проверки на контроллере: B, L → x, y датума. */
data class CheckPoint(val name: String, val lat: Double, val lon: Double, val x: Double, val y: Double)

object Export {
    val FORMATS = listOf("wkt2", "projjson", "jxl", "landxml", "proj")
    val EXTENSIONS = mapOf("wkt2" to ".wkt", "projjson" to ".json", "jxl" to ".jxl", "landxml" to ".xml", "proj" to ".txt")
    const val FOLD_TOL = 1e-4
    const val JXL_TOL = 5e-4
    private const val DEG = "0.0174532925199433"
    private const val RAD_TO_DEG = 180.0 / PI
    val CLOSED = linkedMapOf(
        "cal" to "Trimble .cal (калибровка Trimble Survey Controller / Access) — закрытый двоичный формат",
        "dc" to "Trimble .dc (Survey Controller) — закрытый формат записей",
        "gc3" to "Topcon / Sokkia .gc3 (Magnet Field) — закрытый формат",
        "tp3" to "Topcon .tp3 — закрытый формат",
        "loc" to "Carlson SurvCE / SurvPC .loc — открытого описания нет",
        "hexml" to "Leica HeXML / Captivate .xml — схема с параметрами локализации не опубликована",
        "gsimath" to "проект gsimath — формат не описан",
        "csd" to "Trimble .csd (база систем координат) — закрытый формат",
    )
    private val ELLIPSOID_NAMES = mapOf("krass" to "Krassowsky 1940", "pz90" to "PZ-90", "gsk2011" to "GSK-2011",
        "wgs84" to "WGS 84", "grs80" to "GRS 1980")
    private val DATUM_NAMES = mapOf("SK-42" to "Pulkovo 1942", "SK-95" to "Pulkovo 1995",
        "GSK-2011" to "Geodezicheskaya Sistema Koordinat 2011", "PZ-90" to "Parametry Zemli 1990",
        "PZ-90.02" to "Parametry Zemli 1990.02", "PZ-90.11" to "Parametry Zemli 1990.11",
        "WGS-84" to "World Geodetic System 1984", "ITRF-2008" to "International Terrestrial Reference Frame 2008")
    const val REMARK = "mathdatum localization: x = tx + a*(N-Nc) - b*(E-Ec), y = ty + b*(N-Nc) + a*(E-Ec) " +
        "(N, E - working TM); H = h - N_geoid + c0 + c1*(N-Nc) + c2*(E-Ec). Axes: easting (y), northing (x)."
    private const val HEIGHT_NOTE = "Высота задана методом «PROJ-based operation method» (наклонная плоскость от эллипсоидальной " +
        "высоты в EPSG не описана): её применит только ПО на PROJ ≥ 6; план — стандартные методы EPSG."

    // --- числа: как repr в Python (кратчайшая запись), целые без «.0» ---

    fun fnum(v: Double): String {
        if (v == 0.0) return "0"
        if (v == floor(v) && abs(v) < 1e15) return v.toLong().toString()
        return pyRepr(v)
    }

    /** Запись числа как repr(float) в Python: кратчайшие цифры, экспонента при порядке < −4 или ≥ 16. */
    fun pyRepr(v: Double): String {
        if (v.isNaN()) return "nan"
        if (v.isInfinite()) return if (v > 0) "inf" else "-inf"
        if (v == 0.0) return if (1.0 / v < 0) "-0.0" else "0.0"
        val s = abs(v).toString()
        val mant = s.substringBefore('E').substringBefore('e')
        var exp = if (s.contains('E') || s.contains('e')) s.substring(mant.length + 1).removePrefix("+").toInt() else 0
        val intPart = mant.substringBefore('.')
        val frac = if ('.' in mant) mant.substringAfter('.') else ""
        var digits = intPart + frac
        exp += intPart.length - 1
        val lead = digits.indexOfFirst { it != '0' }
        digits = digits.substring(lead)
        exp -= lead
        digits = digits.trimEnd('0').ifEmpty { "0" }
        val sign = if (v < 0) "-" else ""
        if (exp < -4 || exp >= 16) {
            val m = digits.first() + (if (digits.length > 1) "." + digits.substring(1) else "")
            val e = abs(exp).toString().padStart(2, '0')
            return "$sign${m}e${if (exp < 0) "-" else "+"}$e"
        }
        if (exp < 0) return sign + "0." + "0".repeat(-exp - 1) + digits
        val ip = if (digits.length > exp + 1) digits.substring(0, exp + 1) else digits.padEnd(exp + 1, '0')
        val fp = if (digits.length > exp + 1) digits.substring(exp + 1) else "0"
        return "$sign$ip.$fp"
    }

    // --- эллипсоид и система ---

    data class EllipsoidInfo(val name: String, val a: Double, val rf: Double)

    fun ellipsoidOf(d: LocalizationDatum): EllipsoidInfo {
        Datums.ELLIPSOIDS.firstOrNull { d.ellipsoid.trim() == it.proj }?.let {
            return EllipsoidInfo(ELLIPSOID_NAMES.getValue(it.key), it.a, it.rf)
        }
        val kv = Regex("\\+(a|rf)=([-+0-9.eE]+)").findAll(d.ellipsoid).associate { it.groupValues[1] to it.groupValues[2] }
        val a = kv["a"]; val rf = kv["rf"]
        if (a != null && rf != null) return EllipsoidInfo("unknown", a.toDouble(), rf.toDouble())
        throw ExportException("Эллипсоид рабочей проекции «${d.ellipsoid}» не распознан: нужен +ellps= из " +
            Datums.ELLIPSOIDS.joinToString(", ") { it.proj } + " или +a= +rf=.")
    }

    fun datumName(d: LocalizationDatum): String {
        val sys = d.gnssSystem ?: return "Unknown based on ${ellipsoidOf(d).name} ellipsoid"
        return DATUM_NAMES.getValue(sys)
    }

    // --- геометрия объекта и оценки ---

    fun objectRadius(d: LocalizationDatum): Double? {
        val hull = d.planHull?.takeIf { it.isNotEmpty() } ?: return null
        return hull.maxOf { hypot(it[0] - d.nc, it[1] - d.ec) }
    }

    fun rotation(d: LocalizationDatum): Double = atan2(d.b, d.a)
    fun scale(d: LocalizationDatum): Double = hypot(d.a, d.b)

    fun foldError(d: LocalizationDatum): Double? {
        if (d.b == 0.0) return 0.0
        val r = objectRadius(d) ?: return null
        return 2 * scale(d) * r * sin(abs(rotation(d)) / 2)
    }

    fun folds(d: LocalizationDatum): Boolean = foldError(d)?.let { it < FOLD_TOL } ?: false

    private fun deg(rad: Double) = rad * RAD_TO_DEG

    /** EPSG 9621 для осей (восток, север): XT0, YT0, масштаб, разворот (градусы). */
    fun similarityParams(d: LocalizationDatum): List<Double> =
        listOf(d.ty - d.a * d.ec - d.b * d.nc, d.tx - d.a * d.nc + d.b * d.ec, scale(d), deg(rotation(d)))

    /** TM со свёрнутым масштабом подобия: k0·M, ложное восточное, ложное северное. */
    fun foldedTm(d: LocalizationDatum): List<Double> {
        val m = scale(d)
        return listOf(d.k0 * m, d.ty + m * (d.y0 - d.ec), d.tx + m * (d.x0 - d.nc))
    }

    private fun tmProj(d: LocalizationDatum, inv: Boolean = false) = (if (inv) "+inv " else "") +
        "+proj=tmerc +lat_0=${fnum(d.lat0)} +lon_0=${fnum(d.lon0)} +k=${fnum(d.k0)} +x_0=${fnum(d.y0)} +y_0=${fnum(d.x0)} ${d.ellipsoid}"

    /** PROJ-пайплайн H → h (вход — долгота, широта в радианах). */
    fun heightPipeline(d: LocalizationDatum, gridFile: String?): String {
        val zoff = d.c0 - d.c1 * d.nc - d.c2 * d.ec
        var out = "+proj=pipeline +step ${tmProj(d)} " +
            "+step +proj=affine +zoff=${fnum(-zoff)} +s31=${fnum(-d.c2)} +s32=${fnum(-d.c1)} +s33=1 " +
            "+step ${tmProj(d, true)}"
        if (!gridFile.isNullOrEmpty()) out += " +step +proj=vgridshift +grids=$gridFile +multiplier=1"
        return out
    }

    private fun stemOf(file: String) = file.substringBeforeLast('.', "").ifEmpty { file }

    private fun geoidTarget(d: LocalizationDatum, geoidFile: String?, w: MutableList<String>): String? {
        val ref = d.geoid ?: return null
        val src = ref.file
        val ext = if ('.' in src) src.substringAfterLast('.') else ""
        val target = when {
            !geoidFile.isNullOrEmpty() -> geoidFile
            ext.lowercase() in listOf("gtx", "tif", "tiff") -> src
            else -> {
                val t = stemOf(src) + ".gtx"
                w += "Сетка $src: PROJ не читает ${ext.uppercase().ifEmpty { "этот формат" }} — в файле указана $t. " +
                    "Переведите: python -m mathdatum geoid $src -o $t (узлы те же, float32)."
                t
            }
        }
        if (ref.interpolation != "bilinear") {
            val est = interpDifference(d)
            w += "Датум использует интерполяцию ${ref.interpolation}, PROJ vgridshift — билинейную" +
                (if (est != null) ": разница на объекте до ${(est * 1000).fixed(1)} мм."
                else " (сетка не загружена — разницу на объекте не оценить).")
        }
        return target
    }

    private fun samplePoints(d: LocalizationDatum): List<Pair<Double, Double>> {
        val pts = mutableListOf(d.nc to d.ec)
        val hull = d.planHull
        if (!hull.isNullOrEmpty()) {
            hull.forEach { pts += it[0] to it[1] }
            for (i in hull.indices) {
                val p = hull[i]; val q = hull[(i + 1) % hull.size]
                pts += (p[0] + q[0]) / 2 to (p[1] + q[1]) / 2
            }
        }
        return pts
    }

    private fun workTm(d: LocalizationDatum): WorkProjection {
        val e = ellipsoidOf(d)
        return WorkProjection(Ellipsoid(e.a, 1 / e.rf), d.lat0, d.lon0, d.k0, d.x0, d.y0)
    }

    /** max |N_bicubic − N_bilinear| по точкам объекта, м (null — сетка не загружена). */
    fun interpDifference(d: LocalizationDatum): Double? {
        val g = d.geoidGrid ?: return null
        val tm = workTm(d)
        var out = 0.0
        for ((n, e) in samplePoints(d)) {
            val (lat, lon) = tm.inverse(n, e)
            try {
                out = max(out, abs(g.value(lat, lon, "bicubic") - g.value(lat, lon, "bilinear")))
            } catch (_: GeoidException) {
            }
        }
        return out
    }

    // --- WKT2 ---

    private class W(val kw: String, vararg items: Any?) {
        val items: MutableList<Any> = items.filterNotNull().toMutableList()

        fun render(indent: Int = 0): String {
            val pad = " ".repeat(indent + 4)
            val sb = StringBuilder(kw).append('[')
            items.forEachIndexed { i, it ->
                if (i > 0) sb.append(',')
                when (it) {
                    is W -> sb.append('\n').append(pad).append(it.render(indent + 4))
                    is String -> sb.append(q(it))
                    is Raw -> sb.append(it.raw)
                    is Int -> sb.append(it.toString())
                    is Double -> sb.append(fnum(it))
                    else -> error("WKT: $it")
                }
            }
            return sb.append(']').toString()
        }
    }

    private class Raw(val raw: String)

    private fun q(s: String) = "\"" + s.replace("\"", "\"\"") + "\""

    private fun unit(kind: String) = when (kind) {
        "deg" -> W("ANGLEUNIT", "degree", Raw(DEG))
        "m" -> W("LENGTHUNIT", "metre", 1)
        else -> W("SCALEUNIT", "unity", 1)
    }

    private fun param(name: String, value: Double, unit: String, code: Int) =
        W("PARAMETER", name, value, unit(unit), W("ID", "EPSG", code))

    private fun geog(d: LocalizationDatum, name: String, threeD: Boolean): W {
        val e = ellipsoidOf(d)
        val datum = W("DATUM", datumName(d), W("ELLIPSOID", e.name, e.a, e.rf, unit("m")))
        val prime = W("PRIMEM", "Greenwich", 0, unit("deg"))
        if (!threeD) return W("BASEGEOGCRS", name, datum, prime)
        return W("GEOGCRS", name, datum, prime, W("CS", Raw("ellipsoidal"), 3),
            W("AXIS", "geodetic latitude (Lat)", Raw("north"), W("ORDER", 1), unit("deg")),
            W("AXIS", "geodetic longitude (Lon)", Raw("east"), W("ORDER", 2), unit("deg")),
            W("AXIS", "ellipsoidal height (h)", Raw("up"), W("ORDER", 3), unit("m")))
    }

    private fun tmConversion(name: String, lat0: Double, lon0: Double, k0: Double, fe: Double, fn: Double) =
        W("CONVERSION", name, W("METHOD", "Transverse Mercator", W("ID", "EPSG", 9807)),
            param("Latitude of natural origin", lat0, "deg", 8801),
            param("Longitude of natural origin", lon0, "deg", 8802),
            param("Scale factor at natural origin", k0, "1", 8805),
            param("False easting", fe, "m", 8806),
            param("False northing", fn, "m", 8807))

    private fun csEN() = arrayOf(
        W("CS", Raw("Cartesian"), 2),
        W("AXIS", "easting (Y)", Raw("east"), W("ORDER", 1), unit("m")),
        W("AXIS", "northing (X)", Raw("north"), W("ORDER", 2), unit("m")),
    )

    private fun foldNote(d: LocalizationDatum) = "Разворот ${(deg(rotation(d)) * 3600).fixed(3)}″ свёрнут в TM без поворота: " +
        "погрешность на объекте ≤ ${(foldError(d)!! * 1000).fixed(3)} мм."

    private fun planCrs(d: LocalizationDatum, name: String, w: MutableList<String>): W {
        val base = geog(d, "$name GNSS", false)
        if (folds(d)) {
            val (k0, fe, fn) = foldedTm(d)
            if (d.b != 0.0) w += foldNote(d)
            return W("PROJCRS", "$name plan", base, tmConversion("$name TM (similarity folded)", d.lat0, d.lon0, k0, fe, fn), *csEN())
        }
        val (xt0, yt0, m, theta) = similarityParams(d)
        return W("DERIVEDPROJCRS", "$name plan",
            W("BASEPROJCRS", "$name working TM", base, tmConversion("$name working TM", d.lat0, d.lon0, d.k0, d.y0, d.x0)),
            W("DERIVINGCONVERSION", "$name similarity",
                W("METHOD", "Similarity transformation", W("ID", "EPSG", 9621)),
                param("Ordinate 1 of evaluation point in target CRS", xt0, "m", 8621),
                param("Ordinate 2 of evaluation point in target CRS", yt0, "m", 8622),
                param("Scale factor for source coordinate reference system axes", m, "1", 1061),
                param("Rotation angle of source coordinate reference system axes", theta, "deg", 8614)),
            *csEN())
    }

    /** Пайплайн высоты или null (модели высоты нет — экспортируется только план). */
    private fun heightPart(d: LocalizationDatum, geoidFile: String?, w: MutableList<String>): String? {
        if (d.heightModel == "none") {
            w += "Модели высоты нет (не было точек для высоты): экспортирован только план."
            return null
        }
        return heightPipeline(d, geoidTarget(d, geoidFile, w))
    }

    fun toWkt2(d: LocalizationDatum, name: String = "Localization", geoidFile: String? = null): ExportResult {
        val w = mutableListOf<String>()
        val plan = planCrs(d, name, w)
        val pipe = heightPart(d, geoidFile, w)
        if (pipe == null) {
            plan.items += W("REMARK", REMARK)
            return ExportResult("wkt2", plan.render() + "\n", w)
        }
        val vert = W("BOUNDCRS",
            W("SOURCECRS", W("VERTCRS", "$name height", W("VDATUM", "$name local height"),
                W("CS", Raw("vertical"), 1), W("AXIS", "gravity-related height (H)", Raw("up"), unit("m")))),
            W("TARGETCRS", geog(d, "$name GNSS", true)),
            W("ABRIDGEDTRANSFORMATION", "$name height to ellipsoidal height",
                W("METHOD", "PROJ-based operation method: $pipe")))
        val crs = W("COMPOUNDCRS", name, plan, vert, W("REMARK", REMARK))
        w += HEIGHT_NOTE
        return ExportResult("wkt2", crs.render() + "\n", w)
    }

    // --- PROJJSON ---

    private fun jdump(v: Any?, indent: Int = 0): String {
        val pad = " ".repeat(indent); val pad1 = " ".repeat(indent + 2)
        return when (v) {
            is Map<*, *> -> if (v.isEmpty()) "{}" else
                "{\n" + v.entries.joinToString(",\n") { "$pad1${jstr(it.key as String)}: ${jdump(it.value, indent + 2)}" } + "\n$pad}"
            is List<*> -> if (v.isEmpty()) "[]" else "[\n" + v.joinToString(",\n") { pad1 + jdump(it, indent + 2) } + "\n$pad]"
            is String -> jstr(v)
            is Boolean -> v.toString()
            is Int -> v.toString()
            is Double -> fnum(v)
            else -> error("JSON: $v")
        }
    }

    private fun jstr(s: String): String = buildString {
        append('"')
        for (ch in s) when {
            ch == '"' || ch == '\\' -> append('\\').append(ch)
            ch == '\n' -> append("\\n")
            ch.code < 0x20 -> append("\\u" + ch.code.toString(16).padStart(4, '0'))
            else -> append(ch)
        }
        append('"')
    }

    private fun jp(name: String, value: Double, unit: String, code: Int) = linkedMapOf(
        "name" to name, "value" to value,
        "unit" to when (unit) { "deg" -> "degree"; "m" -> "metre"; else -> "unity" },
        "id" to linkedMapOf("authority" to "EPSG", "code" to code),
    )

    private fun axis(name: String, abbr: String, dir: String, unit: String) =
        linkedMapOf("name" to name, "abbreviation" to abbr, "direction" to dir, "unit" to unit)

    private fun jgeog(d: LocalizationDatum, name: String, threeD: Boolean): Map<String, Any?> {
        val e = ellipsoidOf(d)
        val axes = mutableListOf(axis("Geodetic latitude", "Lat", "north", "degree"), axis("Geodetic longitude", "Lon", "east", "degree"))
        if (threeD) axes += axis("Ellipsoidal height", "h", "up", "metre")
        return linkedMapOf(
            "type" to "GeographicCRS", "name" to name,
            "datum" to linkedMapOf("type" to "GeodeticReferenceFrame", "name" to datumName(d),
                "ellipsoid" to linkedMapOf("name" to e.name, "semi_major_axis" to e.a, "inverse_flattening" to e.rf)),
            "coordinate_system" to linkedMapOf("subtype" to "ellipsoidal", "axis" to axes),
        )
    }

    private fun jtm(name: String, lat0: Double, lon0: Double, k0: Double, fe: Double, fn: Double) = linkedMapOf(
        "name" to name, "method" to linkedMapOf("name" to "Transverse Mercator", "id" to linkedMapOf("authority" to "EPSG", "code" to 9807)),
        "parameters" to listOf(jp("Latitude of natural origin", lat0, "deg", 8801), jp("Longitude of natural origin", lon0, "deg", 8802),
            jp("Scale factor at natural origin", k0, "1", 8805), jp("False easting", fe, "m", 8806), jp("False northing", fn, "m", 8807)),
    )

    private fun jcsEN() = linkedMapOf("subtype" to "Cartesian",
        "axis" to listOf(axis("Easting", "Y", "east", "metre"), axis("Northing", "X", "north", "metre")))

    fun toProjJson(d: LocalizationDatum, name: String = "Localization", geoidFile: String? = null): ExportResult {
        val w = mutableListOf<String>()
        val base = jgeog(d, "$name GNSS", false)
        val plan: Map<String, Any?> = if (folds(d)) {
            val (k0, fe, fn) = foldedTm(d)
            if (d.b != 0.0) w += foldNote(d)
            linkedMapOf("type" to "ProjectedCRS", "name" to "$name plan", "base_crs" to base,
                "conversion" to jtm("$name TM (similarity folded)", d.lat0, d.lon0, k0, fe, fn), "coordinate_system" to jcsEN())
        } else {
            val (xt0, yt0, m, theta) = similarityParams(d)
            linkedMapOf("type" to "DerivedProjectedCRS", "name" to "$name plan",
                "base_crs" to linkedMapOf("type" to "ProjectedCRS", "name" to "$name working TM", "base_crs" to base,
                    "conversion" to jtm("$name working TM", d.lat0, d.lon0, d.k0, d.y0, d.x0), "coordinate_system" to jcsEN()),
                "conversion" to linkedMapOf("name" to "$name similarity",
                    "method" to linkedMapOf("name" to "Similarity transformation", "id" to linkedMapOf("authority" to "EPSG", "code" to 9621)),
                    "parameters" to listOf(
                        jp("Ordinate 1 of evaluation point in target CRS", xt0, "m", 8621),
                        jp("Ordinate 2 of evaluation point in target CRS", yt0, "m", 8622),
                        jp("Scale factor for source coordinate reference system axes", m, "1", 1061),
                        jp("Rotation angle of source coordinate reference system axes", theta, "deg", 8614))),
                "coordinate_system" to jcsEN())
        }
        val pipe = heightPart(d, geoidFile, w)
        val schema = "https://proj.org/schemas/v0.7/projjson.schema.json"
        if (pipe == null) {
            val out = linkedMapOf<String, Any?>("\$schema" to schema)
            out.putAll(plan)
            out["remarks"] = REMARK
            return ExportResult("projjson", jdump(out) + "\n", w)
        }
        val vert = linkedMapOf("type" to "BoundCRS",
            "source_crs" to linkedMapOf("type" to "VerticalCRS", "name" to "$name height",
                "datum" to linkedMapOf("type" to "VerticalReferenceFrame", "name" to "$name local height"),
                "coordinate_system" to linkedMapOf("subtype" to "vertical",
                    "axis" to listOf(axis("Gravity-related height", "H", "up", "metre")))),
            "target_crs" to jgeog(d, "$name GNSS", true),
            "transformation" to linkedMapOf("name" to "$name height to ellipsoidal height",
                "method" to linkedMapOf("name" to "PROJ-based operation method: $pipe"), "parameters" to emptyList<Any>()))
        val out = linkedMapOf("\$schema" to schema, "type" to "CompoundCRS", "name" to name,
            "components" to listOf(plan, vert), "remarks" to REMARK)
        w += HEIGHT_NOTE
        return ExportResult("projjson", jdump(out) + "\n", w)
    }

    // --- Trimble JobXML ---

    /** Параметры JobXML: масштаб TM (k0·M), ложные смещения, центр и разворот корректировки, наклоны, постоянная. */
    data class JxlParameters(
        val scale: Double, val falseEasting: Double, val falseNorthing: Double, val originNorth: Double,
        val originEast: Double, val rotationDeg: Double, val slopeNorth: Double, val slopeEast: Double, val constant: Double,
    )

    fun jxlParameters(d: LocalizationDatum): JxlParameters {
        val (k0, fe, fn) = foldedTm(d)
        val m = scale(d)
        return JxlParameters(k0, fe, fn, d.tx, d.ty, deg(rotation(d)), d.c1 / m, d.c2 / m, d.c0)
    }

    private fun xesc(s: String) = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    private fun xattr(s: String) = s.replace("&", "&amp;").replace("\"", "&quot;").replace("<", "&lt;").replace(">", "&gt;")

    private fun x(tag: String, value: Any?, indent: Int): String {
        val pad = "  ".repeat(indent)
        val v = when (value) {
            null -> ""
            is String -> value
            is Int -> value.toString()
            is Double -> fnum(value)
            else -> value.toString()
        }
        return if (v.isEmpty()) "$pad<$tag/>\n" else "$pad<$tag>${xesc(v)}</$tag>\n"
    }

    private fun xc(tag: String, indent: Int, vararg children: String): String {
        val pad = "  ".repeat(indent)
        return "$pad<$tag>\n" + children.joinToString("") + "$pad</$tag>\n"
    }

    fun jxlWarnings(d: LocalizationDatum): List<String> {
        val w = mutableListOf<String>()
        val r = objectRadius(d)
        val th = rotation(d)
        if (th != 0.0) {
            if (r == null) {
                w += "Нет оболочки опорных пунктов (старый датум): влияние знака разворота не оценить — проверьте контрольной точкой."
            } else {
                val wrong = 2 * r * sin(abs(th))
                if (wrong >= JXL_TOL) w += "Знак разворота (${(deg(th) * 3600).fixed(2)}″, по часовой стрелке) взят по Trimble Access " +
                    "Calculations Reference (N′E′ — сетка, NE — опорные, a = k·cos φ, b = k·sin φ); если " +
                    "контроллер трактует его наоборот, ошибка в плане до ${wrong.fixed(3)} м — проверьте контрольной " +
                    "точкой (export печатает их)."
            }
            if (d.heightModel in listOf("plane", "geoid_plane") && r != null) {
                val dv = hypot(d.c1, d.c2) * 2 * r * sin(abs(th) / 2)
                if (dv >= JXL_TOL) w += "Наклон высот задан в сетке до горизонтальной корректировки; если Trimble берёт " +
                    "координаты после неё, ошибка высоты до ${(dv * 1000).fixed(1)} мм."
            }
        }
        d.geoid?.let { ref ->
            val src = ref.file
            if (!src.lowercase().endsWith(".ggf")) w += "Trimble читает геоид только в GGF: в файле указано имя ${stemOf(src)}; " +
                "переведите: python -m mathdatum geoid $src -o ${stemOf(src)}.ggf."
            w += "Интерполяцию сетки геоида Trimble не документирует (у датума — ${ref.interpolation}): сверьте высоту на контрольной точке."
        }
        val sys = d.gnssSystem
        if (sys != null && sys != "WGS-84") w += "Преобразование датума — нулевое, эллипсоид ${ellipsoidOf(d).name}: координаты ГНСС на контроллере " +
            "должны быть в $sys (базовая станция в этой системе), как при расчёте датума."
        return w
    }

    fun toJxl(d: LocalizationDatum, name: String = "Localization", timestamp: String = "2000-01-01T00:00:00"): ExportResult {
        if (d.gnssSystem == null && ellipsoidOf(d).name == "unknown")
            throw ExportException("Датум без системы ГНСС и с нестандартным эллипсоидом: JobXML не составить.")
        val p = jxlParameters(d)
        val e = ellipsoidOf(d)
        val wgs = Datums.ellipsoid("wgs84")
        val vert = if (d.heightModel == "none") listOf(x("Type", "NoAdjustment", 4)) else buildList {
            add(x("Type", if (d.geoid != null) "GeoidModelAndInclinedPlane" else "InclinedPlane", 4))
            add(x("OriginNorth", p.originNorth, 4)); add(x("OriginEast", p.originEast, 4))
            add(x("SlopeNorthPerUnit", p.slopeNorth, 4)); add(x("SlopeEastPerUnit", p.slopeEast, 4))
            add(x("ConstantAdjustment", p.constant, 4))
            d.geoid?.let { add(x("GeoidName", stemOf(it.file), 4)) }
        }
        val horiz = if (d.b == 0.0) listOf(x("Type", "NoAdjustment", 4)) else listOf(
            x("Type", "PlaneAdjustment", 4), x("OriginNorth", p.originNorth, 4), x("OriginEast", p.originEast, 4),
            x("TranslationNorth", 0, 4), x("TranslationEast", 0, 4), x("Rotation", p.rotationDeg, 4), x("ScaleFactor", 1, 4))
        val cs = arrayOf(
            x("SystemName", name, 3), x("ZoneName", name, 3), x("DatumName", datumName(d), 3),
            x("ZoneID", "", 3), x("ProjectedCoordinateReferenceSystemEPSG", "", 3), x("CompoundCoordinateReferenceSystemEPSG", "", 3),
            xc("Ellipsoid", 3, x("EarthRadius", e.a, 4), x("Flattening", 1 / e.rf, 4)),
            xc("Projection", 3, x("Type", "TransverseMercator", 4), x("Scale", p.scale, 4),
                x("CentralLatitude", d.lat0, 4), x("CentralLongitude", d.lon0, 4),
                x("FalseNorthing", p.falseNorthing, 4), x("FalseEasting", p.falseEasting, 4),
                x("SouthAzimuth", "false", 4), x("GridOrientation", "IncreasingNorthEast", 4), x("ApplySeaLevelCorrection", "true", 4)),
            xc("LocalSite", 3, x("Type", "Grid", 4), x("ProjectLocationLatitude", "", 4), x("ProjectLocationLongitude", "", 4),
                x("ProjectLocationHeight", "", 4)),
            xc("Datum", 3, x("Type", "SevenParameter", 4), x("Direction", "WGS84ToLocal", 4),
                x("EarthRadius", wgs.a, 4), x("Flattening", 1 / wgs.rf, 4),
                x("RotationX", 0, 4), x("RotationY", 0, 4), x("RotationZ", 0, 4),
                x("TranslationX", 0, 4), x("TranslationY", 0, 4), x("TranslationZ", 0, 4), x("Scale", 1, 4)),
            xc("HorizontalAdjustment", 3, *horiz.toTypedArray()),
            xc("VerticalAdjustment", 3, *vert.toTypedArray()),
            xc("CombinedScaleFactor", 3, xc("Location", 4, x("Latitude", "", 5), x("Longitude", "", 5), x("Height", "", 5)),
                x("Scale", "", 4)),
        )
        val display = listOf("DistanceUnits" to "Metres", "HeightUnits" to "Metres", "AngleUnits" to "DMSDegrees",
            "AzimuthFormat" to "Azimuth", "LatitudeLongitudeUnits" to "DMSDegrees", "CoordinateOrder" to "North-East-Elevation",
            "TemperatureUnits" to "Celsius", "PressureUnits" to "MilliBar", "GradeUnits" to "Percentage",
            "AreaUnits" to "SquareMetres", "VolumeUnits" to "CubicMetres", "MassUnits" to "Kilograms",
            "StationingFormat" to "1+000.0", "StationIndexIncrement" to "", "PrecisionUnits" to "1Sigma",
            "DistanceDisplayDPs" to "3", "CoordinateDisplayDPs" to "3", "AreaDisplayDPs" to "3", "VolumeDisplayDPs" to "3",
            "MassDisplayDPs" to "3", "AngleDisplayDPs" to "1", "LaserVADisplay" to "VerticalAngle", "TimeFormat" to "Local",
        ).map { x(it.first, it.second, 3) }
        val props = listOf("Reference" to "", "Description" to "mathdatum localization export", "Operator" to "", "JobNote" to "",
            "TectonicPlate" to "Unknown", "ApplyJobPointNameRange" to "false", "MinimumJobPointName" to "", "MaximumJobPointName" to "",
        ).map { x(it.first, it.second, 3) }
        val env = arrayOf(
            xc("DisplaySettings", 2, *display.toTypedArray()),
            xc("CoordinateSystem", 2, *cs),
            xc("JobProperties", 2, *props.toTypedArray()),
            xc("JobSettings", 2, xc("NeighbourhoodAdjustment", 3, x("Applied", "false", 4), x("WeightExponent", 0.5, 4)),
                x("Averaging", "Weighted", 3), x("UseAttributesOfBaseCode", "false", 3)),
            xc("TimeZone", 2, x("ZoneName", "UTC", 3), x("HoursToUTC", 0, 3)),
        )
        val job = name.map { if (it.isLetterOrDigit() || it == '_' || it == '-') it else '_' }.joinToString("").ifEmpty { "Localization" }
        val text = "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n" +
            "<JOBFile jobName=\"$job\" version=\"6.30\" product=\"mathdatum\" productVersion=\"1\" TimeStamp=\"$timestamp\">\n" +
            "  <FieldBook/>\n  <Reductions/>\n" + xc("Environment", 1, *env) + "</JOBFile>\n"
        return ExportResult("jxl", text, jxlWarnings(d))
    }

    // --- LandXML ---

    fun toLandXml(d: LocalizationDatum, name: String = "Localization", geoidFile: String? = null,
                  timestamp: String = "2000-01-01T00:00:00"): ExportResult {
        val wk = toWkt2(d, name, geoidFile)
        val oneLine = wk.text.replace(Regex("\n\\s*"), "")
        val date = timestamp.substringBefore('T')
        val time = timestamp.substringAfter('T', "").ifEmpty { "00:00:00" }
        val text = "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n" +
            "<LandXML xmlns=\"http://www.landxml.org/schema/LandXML-1.2\" version=\"1.2\" date=\"$date\" time=\"$time\">\n" +
            "  <Units><Metric linearUnit=\"meter\" areaUnit=\"squareMeter\" volumeUnit=\"cubicMeter\" " +
            "temperatureUnit=\"celsius\" pressureUnit=\"milliBars\" angularUnit=\"decimal degrees\" directionUnit=\"decimal degrees\"/></Units>\n" +
            "  <CoordinateSystem name=\"${xattr(name)}\" desc=\"mathdatum localization (WKT2 in ogcWktCode)\" " +
            "ogcWktCode=\"${xattr(oneLine)}\"/>\n" +
            "  <Application name=\"mathdatum\" manufacturer=\"math-datum\" version=\"1\"/>\n" +
            "</LandXML>\n"
        val w = listOf("LandXML 1.2 не описывает проекцию + подобие + плоскость высот: датум передан строкой WKT2 в ogcWktCode " +
            "(атрибут рассчитан на WKT1) — поймёт только ПО, отдающее его в PROJ; Civil 3D / TBC его, вероятно, " +
            "проигнорируют.") + wk.warnings
        return ExportResult("landxml", text, w)
    }

    /** Экспорт датума в формат [format] ([FORMATS]); закрытые форматы — [ExportException] с объяснением. */
    fun export(d: LocalizationDatum, format: String, name: String = "Localization", geoidFile: String? = null,
               timestamp: String = "2000-01-01T00:00:00"): ExportResult {
        val f = format.lowercase().trimStart('.')
        CLOSED[f]?.let {
            throw ExportException("$it: экспорт не поддерживается — угадывать байты нельзя. Что нужно для " +
                "поддержки (образцы файлов, документация) — docs/export.md.")
        }
        return when (f) {
            "wkt2" -> toWkt2(d, name, geoidFile)
            "projjson" -> toProjJson(d, name, geoidFile)
            "jxl" -> toJxl(d, name, timestamp)
            "landxml" -> toLandXml(d, name, geoidFile, timestamp)
            "proj" -> ExportResult("proj", d.toProjPipeline() + "\n", emptyList())
            else -> throw ExportException("Формат «$format»: ожидается ${FORMATS.joinToString(", ")}.")
        }
    }

    /** Контрольные точки: центроид и вершины оболочки → (B, L) и (x, y); rotationSign = −1 — при обратном знаке разворота. */
    fun checkPoints(d: LocalizationDatum, rotationSign: Int = 1): List<CheckPoint> {
        val tm = workTm(d)
        val a = d.a; val b = d.b * rotationSign
        val pts = samplePoints(d).take(1 + (d.planHull?.size ?: 0))
        return pts.mapIndexed { i, (n, e) ->
            val (lat, lon) = tm.inverse(n, e)
            val dn = n - d.nc; val de = e - d.ec
            CheckPoint(if (i == 0) "C" else "V$i", lat, lon, d.tx + a * dn - b * de, d.ty + b * dn + a * de)
        }
    }
}
