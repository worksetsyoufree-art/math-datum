package ru.mathdatum.localization

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray
import kotlin.math.abs
import kotlin.math.ceil
import kotlin.math.cos
import kotlin.math.floor
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin
import kotlin.math.sqrt

/*
 * Проектирование малоискажающей проекции (Low Distortion Projection, LDP) под объект строительства —
 * поперечный Меркатор, те же формулы и порядок операций, что у Python-эталона (mathdatum/ldp.py, type = "tm"):
 *   δ = k(B, L)·R/(R + h) − 1,  R = √(M·N) = a·√(1 − e²)/(1 − e²·sin²B)  (h — эллипсоидальная высота);
 *   выборка: полигон — центры ячеек сетки с шагом step (вес — площадь) и точки контура (вес 0), полилиния — точки
 *   трассы с шагом step (вес — длина); c_i = k_i(k0 = 1)·R_i/(R_i + h_i);
 *   минимакс: k0 = 2/(c_min + c_max); СКО: k0 = Σw·c/Σw·c²; L0 — перебор 121 значения (объект ± 300 км) и
 *   золотое сечение (60 шагов); округление L0, B0 (1′), k0 (1e-6); ложные смещения x0 (кратно 10 км, x ≥ 5 км),
 *   y0 (кратно 100 км, y ≥ 5 км и y > max x + 20 км); зоны — жадно по пикетажу / восточной координате с
 *   бинарным поиском и попыткой n равных зон. Косая проекция (omerc), GeoJSON и изолинии — только в Python.
 */

/** Вершина контура: широта, долгота (градусы) и высота (м) или null. */
data class LdpVertex(val lat: Double, val lon: Double, val h: Double? = null)

/** Контур объекта: kind — polygon | polyline; zType — ellipsoidal | normal (null — по [LdpHeights.heightType]). */
class LdpContour(kind: String, vertices: List<LdpVertex>, val zType: String? = null) {
    val kind: String
    val vertices: List<LdpVertex>

    init {
        if (kind !in Ldp.KINDS) throw LdpException("Вид объекта «$kind»: ожидается polygon или polyline.")
        val closed = vertices.size > 3 && vertices.first().lat == vertices.last().lat && vertices.first().lon == vertices.last().lon
        this.kind = kind
        this.vertices = if (kind == "polygon" && closed) vertices.dropLast(1) else vertices
        val need = if (kind == "polygon") 3 else 2
        if (this.vertices.size < need) {
            throw LdpException("${if (kind == "polygon") "Полигону" else "Полилинии"} нужно не меньше $need вершин.")
        }
    }

    val hasHeights: Boolean get() = vertices.all { it.h != null }

    companion object {
        /**
         * Контур из CSV `name;B;L[;h | ;H]` (порядок строк — порядок вершин; h — эллипсоидальная высота, H — нормальная).
         * [kind] null — polygon, если первая вершина совпадает с последней, иначе polyline.
         */
        fun parseCsv(text: String, kind: String? = null): LdpContour {
            val head = text.removePrefix("﻿").lines().firstOrNull { it.isNotBlank() } ?: throw LdpException("Пустой контур.")
            val delimiter = if (head.count { it == ';' } >= head.count { it == ',' }) ';' else ','
            val cols = head.split(delimiter).map { it.trim() }
            val hc = when { "h" in cols -> "h"; "H" in cols -> "H"; else -> null }
            val names = listOf("B", "L") + listOfNotNull(hc)
            val rows = Csv.parseColumns(text, names)
            val v = rows.map { (_, a) -> LdpVertex(a[0], a[1], if (hc != null) a[2] else null) }
            val closed = v.size > 3 && v.first().lat == v.last().lat && v.first().lon == v.last().lon
            return LdpContour(kind ?: if (closed) "polygon" else "polyline", v,
                hc?.let { if (it == "h") "ellipsoidal" else "normal" })
        }
    }
}

/**
 * Источник высот: [dem] (значения — по [heightType]) → высоты вершин контура (по сторонам — линейно, внутри полигона —
 * обратные расстояния, p = 2) → [constant]. heightType normal: h = H + N(B, L) по сетке [geoid] (без неё N = 0).
 */
class LdpHeights(
    val constant: Double? = null,
    val dem: GeoidGrid? = null,
    val geoid: GeoidGrid? = null,
    val heightType: String = "ellipsoidal",
) {
    init {
        if (heightType !in listOf("ellipsoidal", "normal")) throw LdpException("Тип высот «$heightType»: ожидается ellipsoidal или normal.")
    }
}

class LdpException(message: String) : IllegalArgumentException(message)

/** Подбор: критерий, округление (угловые минуты, k0; 0 — без), заданные параметры (null — подбирать / авто). */
data class LdpOptions(
    val roundAngle: Double = 1.0,
    val roundK0: Double = 1e-6,
    val lon0: Double? = null,
    val lat0: Double? = null,
    val k0: Double? = null,
    val x0: Double? = null,
    val y0: Double? = null,
)

/** Спроектированная проекция: поперечный Меркатор (type = tmerc) в системе [datum]; x0 — на север, y0 — на восток. */
data class LdpProjection(
    val datum: String,
    val lat0: Double,
    val lon0: Double,
    val k0: Double,
    val x0: Double = 0.0,
    val y0: Double = 0.0,
    val type: String = "tmerc",
) {
    val system: GeodeticSystem get() = Datums.system(datum)
    val tm: TmProjection get() = TmProjection(system.ellipsoid.ellipsoid, lon0, lat0, k0, x0, y0)

    fun forward(lat: Double, lon: Double): PlanePoint = tm.forward(lat, lon)
    fun scale(lat: Double, lon: Double): Double = tm.scale(lat, lon)

    /** δ, ppm, в точке (h — эллипсоидальная высота). */
    fun distortion(lat: Double, lon: Double, h: Double): Double =
        Ldp.distortionPpm(scale(lat, lon), Ldp.heightFactor(system.ellipsoid.ellipsoid, lat, h))

    /** Строка PROJ (x_0 в PROJ — восток, y_0 — север). */
    val proj: String get() = "+proj=tmerc +lat_0=${num(lat0)} +lon_0=${num(lon0)} +k=${num(k0)} +x_0=${num(y0)} " +
        "+y_0=${num(x0)} ${system.ellipsoid.proj} +units=m"

    internal fun json(stats: LdpStats?): JsonObject = buildJsonObject {
        put("type", type); put("datum", datum); put("ellipsoid", system.ellipsoid.proj)
        put("lat0", lat0); put("lon0", lon0); put("k0", k0); put("x0", x0); put("y0", y0); put("proj", proj)
        stats?.let { put("stats", it.json()) }
    }

    companion object {
        /** Из JSON-объекта проекции (лишние поля игнорируются, недостающие необязательные — по умолчанию). */
        fun fromJson(o: JsonObject): LdpProjection {
            fun d(k: String) = o[k]?.takeIf { it !is JsonNull }?.jsonPrimitive?.doubleOrNull
            val type = o["type"]?.jsonPrimitive?.content ?: "tmerc"
            if (type != "tmerc") throw LdpException("Проекция $type: в Kotlin поддерживается только поперечный Меркатор (tmerc) — возьмите зону TM.")
            return LdpProjection(
                o["datum"]?.jsonPrimitive?.content ?: Ldp.DEFAULT_DATUM,
                d("lat0") ?: throw LdpException("Проекция LDP: нет поля lat0"),
                d("lon0") ?: throw LdpException("Проекция LDP: нет поля lon0"),
                d("k0") ?: 1.0, d("x0") ?: 0.0, d("y0") ?: 0.0,
            )
        }
    }
}

/** Статистика δ (ppm = мм/км): min/max/mean/RMS, max|δ|, доля площади / длины с |δ| ≤ допуска; measure — area | length. */
data class LdpStats(
    val n: Int, val minPpm: Double, val maxPpm: Double, val meanPpm: Double, val rmsPpm: Double,
    val maxAbsPpm: Double, val shareInTolerance: Double, val measure: String,
) {
    internal fun json(): JsonObject = buildJsonObject {
        put("n", n); put("min_ppm", minPpm); put("max_ppm", maxPpm); put("mean_ppm", meanPpm); put("rms_ppm", rmsPpm)
        put("max_abs_ppm", maxAbsPpm); put("share_in_tolerance", shareInTolerance); put("measure", measure)
    }
}

/** Зона: участок key ∈ [start, end] (пикетаж или восточная координата вспомогательной проекции, м). */
class LdpZone(val name: String, val start: Double, val end: Double, val projection: LdpProjection, val stats: LdpStats,
              /** Граница с предыдущей зоной: точка трассы или отрезок поперёк полигона, (широта, долгота). */
              val boundary: List<Pair<Double, Double>>?)

/** Сравнение: зоны и статистика (ГК 6° или UTM). */
class LdpComparison(val zones: List<Int>, val stats: LdpStats)

/** Точки выборки: широта, долгота, h, вес, координаты вспомогательной проекции, пикетаж (полилиния). */
class LdpSamples(
    val lat: DoubleArray, val lon: DoubleArray, val h: DoubleArray, val w: DoubleArray,
    val n: DoubleArray, val e: DoubleArray, val s: DoubleArray?,
) {
    val size: Int get() = lat.size

    fun subset(idx: List<Int>) = LdpSamples(
        DoubleArray(idx.size) { lat[idx[it]] }, DoubleArray(idx.size) { lon[idx[it]] }, DoubleArray(idx.size) { h[idx[it]] },
        DoubleArray(idx.size) { w[idx[it]] }, DoubleArray(idx.size) { n[idx[it]] }, DoubleArray(idx.size) { e[idx[it]] },
        s?.let { a -> DoubleArray(idx.size) { a[idx[it]] } },
    )
}

/** Карта искажений: ny × nx узлов (строка 0 — северная), значения по строкам. zone 0 — одна проекция. */
class LdpMap(
    val rows: Int, val cols: Int, val lat: DoubleArray, val lon: DoubleArray, val h: DoubleArray, val zone: IntArray,
    val k: DoubleArray, val heightFactor: DoubleArray, val ppm: DoubleArray, val dist: DoubleArray,
    /** Узлы во вспомогательной проекции: север (по строкам) и восток (по столбцам), м. */
    val north: DoubleArray, val east: DoubleArray,
)

class LdpResult internal constructor(
    val contour: LdpContour,
    val datum: String,
    val tolerance: Double,
    val criterion: String,
    val step: Double,
    val projection: LdpProjection,
    val stats: LdpStats,
    val gk: LdpComparison,
    val utm: LdpComparison,
    val zones: List<LdpZone>,
    /** chainage | easting | null. */
    val zoneKey: String?,
    val warnings: List<String>,
    val objectInfo: Map<String, Any>,
    val samples: LdpSamples,
    internal val site: LdpSite,
) {
    val fits: Boolean get() = stats.maxAbsPpm <= tolerance + 1e-9

    /** Карта искажений по сетке вокруг объекта (длинная сторона — [size] узлов, запас [margin] габарита). */
    fun distortionMap(size: Int = 60, margin: Double = 0.05): LdpMap = Ldp.distortionMap(this, size, margin)

    /** Точка (широта, долгота) во вспомогательной проекции карты: (север, восток), м. */
    fun toMapPlane(lat: Double, lon: Double): Pair<Double, Double> = site.aux.forward(lat, lon)

    /** Вершины контура во вспомогательной проекции (север, восток), м — для рисования карты. */
    val outline: List<Pair<Double, Double>> get() = site.vn.indices.map { site.vn[it] to site.ve[it] }

    /** JSON проекции — тот же формат, что у Python (`mathdatum-ldp`, версия 1). */
    fun toJson(): String {
        val o = buildJsonObject {
            put("format", Ldp.FORMAT); put("version", Ldp.VERSION); put("datum", datum)
            put("ellipsoid", Datums.system(datum).ellipsoid.proj); put("tolerance_ppm", tolerance); put("criterion", criterion)
            put("type_requested", "tm"); put("step_m", step)
            put("object", buildJsonObject {
                objectInfo.forEach { (k, v) ->
                    when (v) { is Int -> put(k, v); is Number -> put(k, v.toDouble()); else -> put(k, v.toString()) }
                }
            })
            put("fits_tolerance", fits)
            put("projection", projection.json(stats))
            putJsonArray("alternatives") {}
            put("comparison", buildJsonObject {
                for ((name, c) in listOf("gk" to gk, "utm" to utm)) put(name, buildJsonObject {
                    put("zones", JsonArray(c.zones.map { JsonPrimitive(it) })); put("stats", c.stats.json())
                })
            })
            put("zones", JsonArray(zones.map { z ->
                buildJsonObject {
                    put("name", z.name); put("from_m", z.start); put("to_m", z.end); put("key", zoneKey)
                    put("boundary", z.boundary?.let { b -> JsonArray(b.map { JsonArray(listOf(JsonPrimitive(it.first), JsonPrimitive(it.second))) }) } ?: JsonNull)
                    put("projection", z.projection.json(z.stats))
                }
            }))
            put("warnings", JsonArray(warnings.map { JsonPrimitive(it) }))
        }
        return JSON.encodeToString(JsonObject.serializer(), o)
    }

    private companion object {
        val JSON = Json { prettyPrint = true }
    }
}

/** Вспомогательная проекция объекта (TM в центре вершин), выборка и высоты — как _Site в Python. */
internal class LdpSite(val c: LdpContour, val hs: LdpHeights, val el: Ellipsoid, step: Double?) {
    val aux = TransverseMercator(el, mean(c.vertices.map { it.lat }), mean(c.vertices.map { it.lon }))
    val vn: DoubleArray
    val ve: DoubleArray
    val notes = mutableListOf<String>()
    val vz: DoubleArray?
    val step: Double
    var area = 0.0
    var perimeter = 0.0
    var length = 0.0
    var chain = DoubleArray(0)
    val polygon get() = c.kind == "polygon"

    init {
        val ne = c.vertices.map { aux.forward(it.lat, it.lon) }
        vn = DoubleArray(ne.size) { ne[it].first }
        ve = DoubleArray(ne.size) { ne[it].second }
        vz = if (c.hasHeights) DoubleArray(c.vertices.size) {
            val v = c.vertices[it]
            ellipsoidal(v.h!!, v.lat, v.lon, c.zType ?: hs.heightType, "вершин")
        } else null
        if (hs.dem == null && vz == null && hs.constant == null) {
            throw LdpException("Нет высот: задайте среднюю высоту, высоты вершин (столбец h или H) или сетку рельефа.")
        }
        val m = vn.size
        if (polygon) {
            for (i in 0 until m) {
                val j = (i + 1) % m
                perimeter += hypot(vn[j] - vn[i], ve[j] - ve[i])
            }
            var s1 = 0.0
            var s2 = 0.0
            for (i in 0 until m) {
                val j = (i + 1) % m
                s1 += ve[i] * vn[j]
                s2 += vn[i] * ve[j]
            }
            area = abs(s1 - s2) / 2
            val ext = max(vn.max() - vn.min(), ve.max() - ve.min())
            this.step = step ?: max(ext / 50, 1.0)
        } else {
            chain = DoubleArray(m)
            for (i in 1 until m) chain[i] = chain[i - 1] + hypot(vn[i] - vn[i - 1], ve[i] - ve[i - 1])
            length = chain[m - 1]
            if (!(length > 0)) throw LdpException("Полилиния нулевой длины.")
            this.step = step ?: max(length / 200, 1.0)
        }
        if (!(this.step > 0)) throw LdpException("Шаг выборки должен быть > 0.")
    }

    fun ellipsoidal(h: Double, lat: Double, lon: Double, kind: String, what: String): Double {
        if (kind == "ellipsoidal") return h
        val g = hs.geoid
        if (g == null) {
            val note = "Высоты $what нормальные, сетки геоида нет — приняты за эллипсоидальные (N = 0): ошибка 0.157 ppm на каждый метр N."
            if (note !in notes) notes += note
            return h
        }
        return h + g.value(lat, lon)
    }

    /** Эллипсоидальная высота в точке: сетка рельефа, иначе [base] (по вершинам), иначе constant. */
    fun height(lat: Double, lon: Double, base: Double?): Double {
        hs.dem?.let { return ellipsoidal(it.value(lat, lon), lat, lon, hs.heightType, "сетки рельефа") }
        if (base != null) return base
        return ellipsoidal(hs.constant!!, lat, lon, hs.heightType, "(средняя)")
    }

    fun idw(n: Double, e: Double): Double {
        var sw = 0.0
        var sz = 0.0
        for (k in vn.indices) {
            val dn = n - vn[k]
            val de = e - ve[k]
            val w = 1.0 / max(dn * dn + de * de, 1e-12)
            sw += w
            sz += w * vz!![k]
        }
        return sz / sw
    }

    private class Dense(val n: List<Double>, val e: List<Double>, val z: List<Double>?, val s: List<Double>)

    private fun densify(closed: Boolean): Dense {
        val m = vn.size
        val idx = (0 until m).toList() + if (closed) listOf(0) else emptyList()
        val ns = mutableListOf<Double>(); val es = mutableListOf<Double>(); val zs = mutableListOf<Double>(); val ss = mutableListOf<Double>()
        var acc = 0.0
        for (q in 0 until idx.size - 1) {
            val a = idx[q]
            val b = idx[q + 1]
            val dn = vn[b] - vn[a]
            val de = ve[b] - ve[a]
            val ln = hypot(dn, de)
            val k = max(1, ceil(ln / step - 1e-9).toInt())
            for (j in 0 until k) {
                val t = j.toDouble() / k
                ns += vn[a] + t * dn; es += ve[a] + t * de; ss += acc + t * ln
                vz?.let { zs += it[a] + t * (it[b] - it[a]) }
            }
            acc += ln
        }
        if (!closed) {
            ns += vn[m - 1]; es += ve[m - 1]; ss += acc
            vz?.let { zs += it[m - 1] }
        }
        return Dense(ns, es, if (vz != null) zs else null, ss)
    }

    fun samples(): LdpSamples {
        val n: DoubleArray
        val e: DoubleArray
        val w: DoubleArray
        val base: DoubleArray?
        var s: DoubleArray? = null
        if (polygon) {
            val n0 = vn.min(); val n1 = vn.max(); val e0 = ve.min(); val e1 = ve.max()
            val nx = max(1, ceil((e1 - e0) / step - 1e-9).toInt())
            val ny = max(1, ceil((n1 - n0) / step - 1e-9).toInt())
            val sx = (e1 - e0) / nx
            val sy = (n1 - n0) / ny
            val gn = mutableListOf<Double>(); val ge = mutableListOf<Double>()
            for (j in 0 until ny) for (i in 0 until nx) {
                val pn = n0 + (j + 0.5) * sy
                val pe = e0 + (i + 0.5) * sx
                if (Ldp.pointInPolygon(vn, ve, pn, pe)) { gn += pn; ge += pe }
            }
            val d = densify(true)
            n = (gn + d.n).toDoubleArray()
            e = (ge + d.e).toDoubleArray()
            w = DoubleArray(n.size) { if (it < gn.size) sx * sy else 0.0 }
            if (gn.isEmpty()) {  // объект меньше ячейки — по контуру с весом длины
                val m = d.n.size
                val seg = DoubleArray(m) { hypot(d.n[(it + 1) % m] - d.n[it], d.e[(it + 1) % m] - d.e[it]) }
                for (i in 0 until m) w[i] = (seg[i] + seg[(i - 1 + m) % m]) / 2
            }
            base = vz?.let { DoubleArray(n.size) { i -> if (i < gn.size) idw(gn[i], ge[i]) else d.z!![i - gn.size] } }
        } else {
            val d = densify(false)
            n = d.n.toDoubleArray(); e = d.e.toDoubleArray(); s = d.s.toDoubleArray()
            w = DoubleArray(n.size)
            for (i in 0 until n.size - 1) {
                val ds = s[i + 1] - s[i]
                w[i] += ds / 2
                w[i + 1] += ds / 2
            }
            base = d.z?.toDoubleArray()
        }
        val lat = DoubleArray(n.size)
        val lon = DoubleArray(n.size)
        val h = DoubleArray(n.size)
        for (i in n.indices) {
            val (b, l) = aux.inverse(n[i], e[i])
            lat[i] = b; lon[i] = l
            h[i] = height(b, l, base?.get(i))
        }
        return LdpSamples(lat, lon, h, w, n, e, s)
    }

    /** Пикетаж ближайшей точки полилинии и расстояние до неё, м. */
    fun nearestOnLine(n: Double, e: Double): Pair<Double, Double> {
        var bd = Double.POSITIVE_INFINITY
        var bs = 0.0
        for (i in 0 until vn.size - 1) {
            val dn = vn[i + 1] - vn[i]
            val de = ve[i + 1] - ve[i]
            val ln2 = dn * dn + de * de
            val t = (((n - vn[i]) * dn + (e - ve[i]) * de) / ln2).coerceIn(0.0, 1.0)
            val d = hypot(n - vn[i] - t * dn, e - ve[i] - t * de)
            if (d < bd) { bd = d; bs = chain[i] + t * sqrt(ln2) }
        }
        return bs to bd
    }

    fun lineHeight(s: Double): Double {
        val z = vz!!
        if (s <= chain[0]) return z[0]
        for (i in 1 until chain.size) {
            if (s <= chain[i]) return z[i - 1] + (s - chain[i - 1]) / (chain[i] - chain[i - 1]) * (z[i] - z[i - 1])
        }
        return z[z.size - 1]
    }

    fun boundaryDistance(n: Double, e: Double): Double {
        var d = Double.POSITIVE_INFINITY
        val m = vn.size
        for (i in 0 until m) {
            val j = (i + 1) % m
            val dn = vn[j] - vn[i]
            val de = ve[j] - ve[i]
            val t = (((n - vn[i]) * dn + (e - ve[i]) * de) / (dn * dn + de * de)).coerceIn(0.0, 1.0)
            d = min(d, hypot(n - vn[i] - t * dn, e - ve[i] - t * de))
        }
        return d
    }

    private companion object {
        fun mean(v: List<Double>): Double {
            var acc = 0.0
            for (x in v) acc += x
            return acc / v.size
        }
    }
}

object Ldp {
    const val FORMAT = "mathdatum-ldp"
    const val VERSION = 1
    const val DEFAULT_DATUM = "GSK-2011"
    val KINDS = listOf("polygon", "polyline")
    val CRITERIA = listOf("minimax", "rms")
    private const val SEARCH_KM = 300.0
    private const val SCAN = 121
    private const val GOLDEN = 60
    private const val MARGIN = 5000.0
    private const val GAP = 20000.0
    private const val MAX_ZONES = 50

    /** Средний радиус кривизны R = √(M·N) = a·√(1 − e²)/(1 − e²·sin²B), м. */
    fun gaussRadius(e: Ellipsoid, lat: Double): Double {
        val e2 = e.f * (2 - e.f)
        val s = sin(lat.toRadians())
        return e.a * sqrt(1 - e2) / (1 - e2 * s * s)
    }

    /** Высотный множитель R/(R + h). */
    fun heightFactor(e: Ellipsoid, lat: Double, h: Double): Double {
        val r = gaussRadius(e, lat)
        return r / (r + h)
    }

    /** δ = k·R/(R + h) − 1, ppm (= мм/км). */
    fun distortionPpm(scale: Double, heightFactor: Double): Double = (scale * heightFactor - 1) * 1e6

    /** Лучевой тест (чётность пересечений). */
    fun pointInPolygon(pn: DoubleArray, pe: DoubleArray, n: Double, e: Double): Boolean {
        var inside = false
        val m = pn.size
        for (i in 0 until m) {
            val j = (i - 1 + m) % m
            if ((pn[i] > n) != (pn[j] > n)) {
                val ex = (pe[j] - pe[i]) * (n - pn[i]) / (pn[j] - pn[i]) + pe[i]
                if (e < ex) inside = !inside
            }
        }
        return inside
    }

    private fun k0Dev(c: DoubleArray, w: DoubleArray, criterion: String): Pair<Double, Double> {
        if (criterion == "minimax") {
            val lo = c.min()
            val hi = c.max()
            return 2 / (lo + hi) to (hi - lo) / (hi + lo)
        }
        var swc = 0.0; var swcc = 0.0; var sw = 0.0
        for (i in c.indices) { swc += w[i] * c[i]; swcc += w[i] * c[i] * c[i]; sw += w[i] }
        val k = swc / swcc
        var s = 0.0
        for (i in c.indices) { val d = k * c[i] - 1; s += w[i] * d * d }
        return k to sqrt(s / sw)
    }

    private fun rmsWeights(s: LdpSamples): DoubleArray = if (s.w.sum() > 0) s.w else DoubleArray(s.size) { 1.0 }

    private fun search(f: (Double) -> Double, lo: Double, hi: Double): Double {
        val xs = DoubleArray(SCAN) { lo + (hi - lo) * it / (SCAN - 1) }
        val fs = DoubleArray(SCAN) { f(xs[it]) }
        var ib = 0
        for (i in 1 until SCAN) if (fs[i] < fs[ib]) ib = i
        var a = xs[max(ib - 1, 0)]
        var b = xs[min(ib + 1, SCAN - 1)]
        val g = (sqrt(5.0) - 1) / 2
        var c = b - g * (b - a)
        var d = a + g * (b - a)
        var fc = f(c)
        var fd = f(d)
        repeat(GOLDEN) {
            if (fc < fd) {
                b = d; d = c; fd = fc
                c = b - g * (b - a); fc = f(c)
            } else {
                a = c; c = d; fc = fd
                d = a + g * (b - a); fd = f(d)
            }
        }
        val x = (a + b) / 2
        return if (f(x) <= fs[ib]) x else xs[ib]
    }

    private fun roundK0(k: Double, q: Double): Double {
        if (q == 0.0) return k
        val inv = kotlin.math.round(1 / q)
        return floor(k * inv + 0.5) / inv
    }

    private fun offsets(n: DoubleArray, e: DoubleArray, x0: Double?, y0: Double?): Pair<Double, Double> {
        val x = x0 ?: (max(0.0, ceil((MARGIN - n.min()) / 10000) * 10000.0) + 0.0)
        val y = y0 ?: (max(0.0, ceil(max(MARGIN - e.min(), x + n.max() + GAP - e.min()) / 100000) * 100000.0) + 0.0)
        return x to y
    }

    /** Поперечный Меркатор под выборку: L0 (перебор + золотое сечение), k0 (замкнутая форма), округление. */
    fun fitTm(s: LdpSamples, datum: String, criterion: String, opt: LdpOptions): LdpProjection {
        val system = Datums.system(datum)
        val el = system.ellipsoid.ellipsoid
        val hf = DoubleArray(s.size) { heightFactor(el, s.lat[it], s.h[it]) }
        val w = rmsWeights(s)
        val kernel = TransverseMercator.ScaleKernel(TransverseMercator(el, 0.0, 0.0), s.lat)
        fun cOf(l0: Double): DoubleArray {
            val c = DoubleArray(s.size)
            TransverseMercator(el, 0.0, l0).scales(kernel, s.lon, c)
            for (i in c.indices) c[i] *= hf[i]
            return c
        }
        fun obj(l0: Double): Double {
            val c = cOf(l0)
            val k = opt.k0 ?: return k0Dev(c, w, criterion).second
            if (criterion == "minimax") return c.maxOf { abs(k * it - 1) }
            var sd = 0.0
            for (i in c.indices) { val d = k * c[i] - 1; sd += w[i] * d * d }
            return sqrt(sd / w.sum())
        }
        val lon0 = opt.lon0 ?: run {
            val bc = (s.lat.min() + s.lat.max()) / 2
            val pad = (SEARCH_KM * 1000 / (el.a * cos(bc.toRadians()))).toDegrees()
            var l = search(::obj, s.lon.min() - pad, s.lon.max() + pad)
            if (opt.roundAngle != 0.0) {
                val m = floor(l * 60 / opt.roundAngle)
                val lo = m * opt.roundAngle / 60
                val hi = (m + 1) * opt.roundAngle / 60
                l = if (obj(lo) <= obj(hi)) lo else hi
            }
            l
        }
        val lat0 = opt.lat0 ?: run {
            val c = (s.lat.min() + s.lat.max()) / 2
            if (opt.roundAngle != 0.0) floor(c * 60 / opt.roundAngle + 0.5) * opt.roundAngle / 60 else c
        }
        val k0 = opt.k0 ?: roundK0(k0Dev(cOf(lon0), w, criterion).first, opt.roundK0)
        val tm = TmProjection(el, lon0, lat0, k0)
        val pts = s.lat.indices.map { tm.forward(s.lat[it], s.lon[it]) }
        val (x0, y0) = offsets(DoubleArray(pts.size) { pts[it].x }, DoubleArray(pts.size) { pts[it].y }, opt.x0, opt.y0)
        return LdpProjection(system.id, lat0, lon0, k0, x0, y0)
    }

    fun stats(ppm: DoubleArray, w0: DoubleArray, tol: Double, measure: String): LdpStats {
        val w = if (w0.sum() > 0) w0 else DoubleArray(ppm.size) { 1.0 }
        val sw = w.sum()
        var sm = 0.0; var sq = 0.0; var share = 0.0
        for (i in ppm.indices) {
            sm += w[i] * ppm[i]; sq += w[i] * ppm[i] * ppm[i]
            if (abs(ppm[i]) <= tol) share += w[i]
        }
        return LdpStats(ppm.size, ppm.min(), ppm.max(), sm / sw, sqrt(sq / sw), ppm.maxOf { abs(it) }, share / sw, measure)
    }

    private fun distortions(p: LdpProjection, s: LdpSamples): DoubleArray {
        val tm = p.tm
        val el = p.system.ellipsoid.ellipsoid
        return DoubleArray(s.size) { distortionPpm(tm.scale(s.lat[it], s.lon[it]), heightFactor(el, s.lat[it], s.h[it])) }
    }

    private fun zoned(s: LdpSamples, el: Ellipsoid, zoneOf: (Double) -> Int, lon0: (Int) -> Double, k0: Double): Pair<DoubleArray, List<Int>> {
        val zones = s.lon.map(zoneOf)
        val tms = zones.distinct().associateWith { TransverseMercator(el, 0.0, lon0(it)) }
        val ppm = DoubleArray(s.size) {
            distortionPpm(k0 * tms.getValue(zones[it]).scale(s.lat[it], s.lon[it]), heightFactor(el, s.lat[it], s.h[it]))
        }
        return ppm to zones.distinct().sorted()
    }

    private fun gkZone(lon: Double) = floor((((lon % 360.0) + 360.0) % 360.0) / 6).toInt() + 1
    private fun utmZone(lon: Double) = floor(((((lon + 180) % 360.0) + 360.0) % 360.0) / 6).toInt() + 1

    /**
     * Проектирует LDP (поперечный Меркатор) под объект; если допуск не выполнен — предлагает зоны (минимакс).
     * [datum] — система (эллипсоид) проекции, по умолчанию ГСК-2011; [tolerance] — допуск |δ|, ppm;
     * [criterion] — minimax | rms; [step] — шаг выборки, м (null — авто).
     */
    fun design(
        contour: LdpContour, heights: LdpHeights, datum: String = DEFAULT_DATUM, tolerance: Double = 20.0,
        criterion: String = "minimax", step: Double? = null, options: LdpOptions = LdpOptions(),
    ): LdpResult {
        if (criterion !in CRITERIA) throw LdpException("Критерий «$criterion»: ожидается minimax или rms.")
        if (!(tolerance > 0)) throw LdpException("Допуск должен быть > 0 ppm.")
        val system = Datums.system(datum)
        val el = system.ellipsoid.ellipsoid
        val site = LdpSite(contour, heights, el, step)
        val s = site.samples()
        val measure = if (site.polygon && s.w.sum() > 0 && s.w.count { it > 0 } < s.size) "area" else "length"
        val warns = site.notes.toMutableList()
        val best = fitTm(s, system.id, criterion, options)
        val bestSt = stats(distortions(best, s), s.w, tolerance, measure)
        val hf = DoubleArray(s.size) { heightFactor(el, s.lat[it], s.h[it]) }
        val hspread = (hf.max() - hf.min()) / (hf.max() + hf.min()) * 1e6
        if (hspread > tolerance) {
            warns += "Перепад высот ${(s.h.max() - s.h.min()).fixed(0)} м сам по себе даёт ±${hspread.fixed(1)} ppm — больше допуска: " +
                "одна проекция не уложится; нужны зоны по высоте (участки с меньшим перепадом)."
        }
        val (gkPpm, gkZ) = zoned(s, el, ::gkZone, { 6.0 * it - 3 }, 1.0)
        val (utmPpm, utmZ) = zoned(s, el, ::utmZone, { 6.0 * it - 183 }, 0.9996)
        val zones = mutableListOf<LdpZone>()
        var keyName: String? = null
        if (bestSt.maxAbsPpm > tolerance) {
            val key = if (site.polygon) s.e else s.s!!
            keyName = if (site.polygon) "easting" else "chainage"
            val zopt = options.copy(lon0 = null, lat0 = null, x0 = null, y0 = null)
            val res = splitZones(s, key, { fitTm(it, system.id, "minimax", zopt) }, tolerance, measure)
            if (res == null) {
                warns += "Допуск недостижим даже на отрезке длиной в шаг выборки (перепад высот): зоны не предложены."
            } else if (res.size > 1) {
                res.forEachIndexed { i, z ->
                    zones += LdpZone("Зона ${i + 1}", z.start, z.end, z.projection, z.stats, if (i == 0) null else boundary(site, z.start, keyName))
                }
            } else {
                warns += "По минимаксу объект укладывается в допуск одной зоной (критерий СКО допускает превышение на краях): проекция зоны 1."
                zones += LdpZone("Зона 1", res[0].start, res[0].end, res[0].projection, res[0].stats, null)
            }
        }
        val w = rmsWeights(s)
        val info = linkedMapOf<String, Any>(
            "kind" to contour.kind, "vertices" to site.vn.size, "samples" to s.size,
            "B_center" to (s.lat.min() + s.lat.max()) / 2, "L_center" to (s.lon.min() + s.lon.max()) / 2,
            "extent_north_m" to s.n.max() - s.n.min(), "extent_east_m" to s.e.max() - s.e.min(),
            "h_min" to s.h.min(), "h_max" to s.h.max(), "h_mean" to s.h.indices.sumOf { w[it] * s.h[it] } / w.sum(),
            "height_source" to when { heights.dem != null -> "сетка рельефа"; site.vz != null -> "высоты вершин"; else -> "средняя высота" },
        )
        if (site.polygon) { info["area_m2"] = site.area; info["perimeter_m"] = site.perimeter } else info["length_m"] = site.length
        return LdpResult(
            contour, system.id, tolerance, criterion, site.step, best, bestSt,
            LdpComparison(gkZ, stats(gkPpm, s.w, tolerance, measure)), LdpComparison(utmZ, stats(utmPpm, s.w, tolerance, measure)),
            zones, keyName, warns, info, s, site,
        )
    }

    private class ZoneFit(val start: Double, val end: Double, val projection: LdpProjection, val stats: LdpStats)

    /** Деление по key: жадно по уникальным значениям (бинарный поиск конца зоны), затем попытка n равных зон. */
    private fun splitZones(s: LdpSamples, key: DoubleArray, fit: (LdpSamples) -> LdpProjection, tol: Double, measure: String): List<ZoneFit>? {
        val uk = key.distinct().sorted()
        val cache = HashMap<Pair<Int, Int>, Triple<Boolean, LdpProjection, LdpStats>>()
        fun check(i: Int, j: Int) = cache.getOrPut(i to j) {
            val idx = key.indices.filter { key[it] >= uk[i] && key[it] <= uk[j] }
            val sub = s.subset(idx)
            val p = fit(sub)
            val st = stats(distortions(p, sub), sub.w, tol, measure)
            Triple(st.maxAbsPpm <= tol + 1e-9, p, st)
        }
        if (uk.size == 1) {
            val (ok, p, st) = check(0, 0)
            return if (ok) listOf(ZoneFit(uk[0], uk[0], p, st)) else null
        }
        var cuts = mutableListOf<Pair<Int, Int>>()
        var i = 0
        while (i < uk.size - 1) {
            if (!check(i, i + 1).first) return null
            var lo = i + 1
            var hi = uk.size - 1
            while (lo < hi) {
                val mid = (lo + hi + 1) / 2
                if (check(i, mid).first) lo = mid else hi = mid - 1
            }
            cuts += i to lo
            i = lo
            if (cuts.size > MAX_ZONES) return null
        }
        val n = cuts.size
        if (n > 1) {
            val span = uk.last() - uk.first()
            val idx = mutableListOf(0)
            for (m in 1 until n) {
                val t = uk.first() + span * m / n
                var best = 0
                for (q in uk.indices) if (abs(uk[q] - t) < abs(uk[best] - t)) best = q
                idx += best
            }
            idx += uk.size - 1
            if ((1 until idx.size).all { idx[it] > idx[it - 1] }) {
                val eq = (0 until idx.size - 1).map { idx[it] to idx[it + 1] }
                if (eq.all { (a, b) -> check(a, b).first }) cuts = eq.toMutableList()
            }
        }
        return cuts.map { (a, b) -> check(a, b).let { ZoneFit(uk[a], uk[b], it.second, it.third) } }
    }

    private fun boundary(site: LdpSite, k: Double, keyName: String): List<Pair<Double, Double>> {
        if (keyName == "chainage") {
            val c = site.chain
            var i = 1
            while (i < c.size - 1 && k > c[i]) i++
            val t = if (c[i] == c[i - 1]) 0.0 else (k - c[i - 1]) / (c[i] - c[i - 1])
            return listOf(site.aux.inverse(site.vn[i - 1] + t * (site.vn[i] - site.vn[i - 1]), site.ve[i - 1] + t * (site.ve[i] - site.ve[i - 1])))
        }
        return listOf(site.aux.inverse(site.vn.min(), k), site.aux.inverse(site.vn.max(), k))
    }

    internal fun distortionMap(r: LdpResult, size: Int, margin: Double): LdpMap {
        val site = r.site
        val el = Datums.system(r.datum).ellipsoid.ellipsoid
        var n0 = site.vn.min(); var n1 = site.vn.max(); var e0 = site.ve.min(); var e1 = site.ve.max()
        val pad = max(margin * max(n1 - n0, e1 - e0), 100.0)
        n0 -= pad; n1 += pad; e0 -= pad; e1 += pad
        val nx: Int
        val ny: Int
        if (e1 - e0 >= n1 - n0) {
            nx = size; ny = max(4, floor(size * (n1 - n0) / (e1 - e0) + 0.5).toInt())
        } else {
            ny = size; nx = max(4, floor(size * (e1 - e0) / (n1 - n0) + 0.5).toInt())
        }
        val north = DoubleArray(ny) { n0 + (n1 - n0) * (ny - 1 - it) / (ny - 1) }
        val east = DoubleArray(nx) { e0 + (e1 - e0) * it / (nx - 1) }
        val total = nx * ny
        val lat = DoubleArray(total); val lon = DoubleArray(total); val h = DoubleArray(total); val zone = IntArray(total)
        val k = DoubleArray(total); val hfa = DoubleArray(total); val ppm = DoubleArray(total); val dist = DoubleArray(total)
        val useZones = r.zones.isNotEmpty() && !r.fits
        val tms = r.zones.map { it.projection.tm }
        val main = r.projection.tm
        for (j in 0 until ny) for (i in 0 until nx) {
            val q = j * nx + i
            val fn = north[j]
            val fe = east[i]
            val (b, l) = site.aux.inverse(fn, fe)
            lat[q] = b; lon[q] = l
            var s = 0.0
            val base: Double?
            if (site.polygon) {
                dist[q] = if (pointInPolygon(site.vn, site.ve, fn, fe)) 0.0 else site.boundaryDistance(fn, fe)
                base = site.vz?.let { site.idw(fn, fe) }
            } else {
                val (ss, dd) = site.nearestOnLine(fn, fe)
                s = ss; dist[q] = dd
                base = site.vz?.let { site.lineHeight(ss) }
            }
            h[q] = site.height(b, l, base)
            if (useZones) {
                val key = if (r.zoneKey == "chainage") s else fe
                var z = r.zones.size
                for (m in r.zones.indices) if (key <= r.zones[m].end) { z = m + 1; break }
                zone[q] = z
                k[q] = tms[z - 1].scale(b, l)
            } else {
                k[q] = main.scale(b, l)
            }
            hfa[q] = heightFactor(el, b, h[q])
            ppm[q] = distortionPpm(k[q], hfa[q])
        }
        return LdpMap(ny, nx, lat, lon, h, zone, k, hfa, ppm, dist, north, east)
    }

    /**
     * Проекция из JSON ldp (Python или Kotlin): основная или зона [zone] (1…n). Если в файле есть зоны, а основная
     * не укладывается в допуск, нужна зона. Понимает и «голую» запись проекции (type, lat0, lon0, …).
     */
    fun loadProjection(json: String, zone: Int? = null): LdpProjection {
        val o = Json.parseToJsonElement(json).jsonObject
        if ("lat0" in o && "projection" !in o) return LdpProjection.fromJson(o)
        val fmt = o["format"]?.jsonPrimitive?.content
        if (fmt != null && fmt != FORMAT) throw LdpException("Файл не ldp-проекция (format = $fmt).")
        val zones = (o["zones"] as? JsonArray)?.map { it.jsonObject } ?: emptyList()
        if (zone != null) {
            if (zone !in 1..zones.size) throw LdpException("Зона $zone: в файле зон ${zones.size}.")
            return LdpProjection.fromJson(zones[zone - 1].getValue("projection").jsonObject)
        }
        val fits = o["fits_tolerance"]?.jsonPrimitive?.booleanOrNull ?: true
        if (zones.size > 1 && !fits) throw LdpException("Одна проекция не укладывается в допуск, в файле ${zones.size} зон — укажите зону.")
        return LdpProjection.fromJson((o["projection"] ?: throw LdpException("Нет поля projection")).jsonObject)
    }
}

/** Число для строки PROJ: целое — без дробной части, иначе кратчайшая запись (как в Python). */
internal fun num(v: Double): String = if (v == floor(v) && abs(v) < 1e15) v.toLong().toString() else v.toString()
