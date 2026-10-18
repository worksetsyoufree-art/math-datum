package ru.mathdatum.localization

import kotlinx.serialization.EncodeDefault
import kotlinx.serialization.ExperimentalSerializationApi
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.Transient
import kotlinx.serialization.json.Json
import kotlin.math.PI
import kotlin.math.atan2
import kotlin.math.hypot
import kotlin.math.sqrt

/*
 * Локализация ГНСС: пары точек WGS-84 ↔ местная система → датум → пересчёты.
 * Та же модель и тот же формат JSON, что у Python-эталона (mathdatum/localization.py):
 *  1. рабочая проекция — поперечный Меркатор с центром (lat0, lon0): (B, L) → (N, E);
 *  2. план — подобие относительно центроида:  [x, y] = [tx, ty] + [[a, -b], [b, a]]·([N, E] - [Nc, Ec]);
 *  3. высота — плоскость:  H = h + c0 + c1·(N - Nc) + c2·(E - Ec).
 * Подгонки — линейный МНК в замкнутой форме; при малом числе точек модель упрощается до сдвига.
 */

/** Как использовать пару точек в расчёте. */
@Serializable
enum class Use {
    @SerialName("both") BOTH,
    @SerialName("plan") PLAN,
    @SerialName("height") HEIGHT,
    @SerialName("none") NONE;

    val inPlan get() = this == BOTH || this == PLAN
    val inHeight get() = this == BOTH || this == HEIGHT

    companion object {
        fun parse(s: String): Use = entries.firstOrNull { it.name.equals(s.trim(), ignoreCase = true) }
            ?: throw IllegalArgumentException("use: ожидается both/plan/height/none, получено «$s»")
    }
}

/** Пара точек: ГНСС (B, L — градусы WGS-84, h — эллипсоидальная высота) и местные x (север), y (восток), H. */
@Serializable
data class LocalizationPair(
    val name: String,
    @SerialName("B") val lat: Double,
    @SerialName("L") val lon: Double,
    val h: Double,
    val x: Double,
    val y: Double,
    @SerialName("H") val height: Double,
    val use: Use = Use.BOTH,
)

@Serializable
data class Residual(val name: String, val use: Use, val dx: Double, val dy: Double, val dH: Double)

/** Точка в WGS-84: широта, долгота (градусы), эллипсоидальная высота. */
data class WgsPoint(val lat: Double, val lon: Double, val h: Double)

/** Точка в местной системе: x (север), y (восток), H. */
data class LocalPoint(val x: Double, val y: Double, val height: Double)

/** Результат локализации. Совместим по JSON с Python-эталоном. */
@OptIn(ExperimentalSerializationApi::class)
@Serializable
data class LocalizationDatum(
    val lat0: Double,
    val lon0: Double,
    @SerialName("Nc") val nc: Double,
    @SerialName("Ec") val ec: Double,
    val a: Double,
    val b: Double,
    val tx: Double,
    val ty: Double,
    val c0: Double,
    val c1: Double,
    val c2: Double,
    @EncodeDefault val ellipsoid: String = "+ellps=WGS84",
    @SerialName("plan_model") val planModel: String = "similarity",
    @SerialName("height_model") val heightModel: String = "plane",
    val residuals: List<Residual> = emptyList(),
    @SerialName("rms_plan") val rmsPlan: Double? = null,
    @SerialName("rms_height") val rmsHeight: Double? = null,
) {
    @Transient
    private val tm = TransverseMercator(Ellipsoid.fromProj(ellipsoid), lat0, lon0)

    val scale: Double get() = hypot(a, b)
    val scalePpm: Double get() = (scale - 1) * 1e6
    val rotationArcsec: Double get() = atan2(b, a) * 180 * 3600 / PI
    val projection: String get() = "+proj=tmerc +lat_0=$lat0 +lon_0=$lon0 +k=1 +x_0=0 +y_0=0 $ellipsoid +units=m"

    /** WGS-84 → местная система. */
    fun toLocal(p: WgsPoint): LocalPoint {
        val (n, e) = tm.forward(p.lat, p.lon)
        val dN = n - nc
        val dE = e - ec
        return LocalPoint(
            x = tx + a * dN - b * dE,
            y = ty + b * dN + a * dE,
            height = p.h + c0 + c1 * dN + c2 * dE,
        )
    }

    /** Местная система → WGS-84. */
    fun toWgs(p: LocalPoint): WgsPoint {
        val k2 = a * a + b * b
        val u = p.x - tx
        val v = p.y - ty
        val dN = (a * u + b * v) / k2
        val dE = (-b * u + a * v) / k2
        val (lat, lon) = tm.inverse(dN + nc, dE + ec)
        return WgsPoint(lat, lon, p.height - (c0 + c1 * dN + c2 * dE))
    }

    /** Строка PROJ: вход (широта, долгота, h) → выход (x, y, H). */
    fun toProjPipeline(): String {
        val xoff = tx - a * nc + b * ec
        val yoff = ty - b * nc - a * ec
        val zoff = c0 - c1 * nc - c2 * ec
        return "+proj=pipeline +step +proj=axisswap +order=2,1 " +
            "+step +proj=unitconvert +xy_in=deg +xy_out=rad " +
            "+step $projection " +
            "+step +proj=affine +xoff=$xoff +s11=${-b} +s12=$a +s13=0 " +
            "+yoff=$yoff +s21=$a +s22=$b +s23=0 " +
            "+zoff=$zoff +s31=$c2 +s32=$c1 +s33=1"
    }

    fun toJson(): String = JSON.encodeToString(serializer(), this)

    companion object {
        internal val JSON = Json { prettyPrint = true; ignoreUnknownKeys = true; encodeDefaults = true }

        /** Читает датум из JSON (в том числе сохранённый Python-эталоном; поле summary игнорируется). */
        fun fromJson(text: String): LocalizationDatum = JSON.decodeFromString(serializer(), text)
    }
}

class LocalizationException(message: String) : IllegalArgumentException(message)

/**
 * Вычисляет датум локализации по парам точек.
 * [lat0], [lon0] — центр рабочей проекции; по умолчанию — среднее по используемым точкам.
 */
fun localize(
    pairs: List<LocalizationPair>,
    lat0: Double? = null,
    lon0: Double? = null,
    ellipsoid: String = "+ellps=WGS84",
): LocalizationDatum {
    val plan = pairs.filter { it.use.inPlan }
    val height = pairs.filter { it.use.inHeight }
    if (plan.isEmpty()) throw LocalizationException("Нет ни одной точки для плана (use = both/plan).")
    val used = pairs.filter { it.use != Use.NONE }
    val cLat = lat0 ?: used.map { it.lat }.average()
    val cLon = lon0 ?: used.map { it.lon }.average()
    val tm = TransverseMercator(Ellipsoid.fromProj(ellipsoid), cLat, cLon)

    // План: подобие в комплексной форме w = t + k·(z - zc), z = N + iE, w = x + iy.
    val zp = plan.map { tm.forward(it.lat, it.lon) }
    val nc = zp.map { it.first }.average()
    val ec = zp.map { it.second }.average()
    val xc = plan.map { it.x }.average()
    val yc = plan.map { it.y }.average()
    var a = 1.0
    var b = 0.0
    val planModel: String
    if (plan.size >= 2) {
        var sRe = 0.0
        var sIm = 0.0
        var denom = 0.0
        plan.forEachIndexed { i, p ->
            val zn = zp[i].first - nc
            val ze = zp[i].second - ec
            val wx = p.x - xc
            val wy = p.y - yc
            // conj(z)·w = (zn - i·ze)(wx + i·wy)
            sRe += zn * wx + ze * wy
            sIm += zn * wy - ze * wx
            denom += zn * zn + ze * ze
        }
        if (denom < 1e-6) throw LocalizationException("Точки для плана совпадают: нельзя определить разворот и масштаб.")
        a = sRe / denom
        b = sIm / denom
        planModel = "similarity"
    } else {
        planModel = "shift"
    }

    // Высота: плоскость относительно центроида плана; решаем по центрированным данным (устойчиво).
    var c0 = 0.0
    var c1 = 0.0
    var c2 = 0.0
    val heightModel: String
    if (height.isEmpty()) {
        heightModel = "none"
    } else {
        val zh = height.map { tm.forward(it.lat, it.lon) }
        val dn = zh.map { it.first - nc }
        val de = zh.map { it.second - ec }
        val dh = height.map { it.height - it.h }
        val mn = dn.average()
        val me = de.average()
        val mh = dh.average()
        var snn = 0.0; var see = 0.0; var sne = 0.0; var snh = 0.0; var seh = 0.0
        for (i in height.indices) {
            val u = dn[i] - mn
            val v = de[i] - me
            val w = dh[i] - mh
            snn += u * u; see += v * v; sne += u * v; snh += u * w; seh += v * w
        }
        val det = snn * see - sne * sne
        val trace = snn + see
        if (height.size >= 3 && trace > 0 && det > 1e-12 * trace * trace) {
            c1 = (snh * see - seh * sne) / det
            c2 = (seh * snn - snh * sne) / det
            c0 = mh - c1 * mn - c2 * me
            heightModel = "plane"
        } else {
            c0 = mh
            heightModel = "shift"
        }
    }

    val datum = LocalizationDatum(
        lat0 = cLat, lon0 = cLon, nc = nc, ec = ec, a = a, b = b, tx = xc, ty = yc,
        c0 = c0, c1 = c1, c2 = c2, ellipsoid = ellipsoid, planModel = planModel, heightModel = heightModel,
    )
    // Невязки (каталог − вычисленное) по всем точкам; точки use = none — контроль, в СКО не входят.
    val residuals = pairs.map { p ->
        val r = datum.toLocal(WgsPoint(p.lat, p.lon, p.h))
        Residual(p.name, p.use, p.x - r.x, p.y - r.y, p.height - r.height)
    }
    val sp = residuals.filter { it.use.inPlan }.map { it.dx * it.dx + it.dy * it.dy }
    val sh = residuals.filter { it.use.inHeight }.map { it.dH * it.dH }
    return datum.copy(
        residuals = residuals,
        rmsPlan = if (sp.isEmpty()) null else sqrt(sp.average()),
        rmsHeight = if (sh.isEmpty()) null else sqrt(sh.average()),
    )
}
