package ru.mathdatum.localization

import kotlinx.serialization.EncodeDefault
import kotlinx.serialization.ExperimentalSerializationApi
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.Transient
import kotlinx.serialization.json.Json
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.atan2
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sqrt

/*
 * Локализация ГНСС: пары точек WGS-84 ↔ местная система → датум → пересчёты.
 * Та же модель и тот же формат JSON, что у Python-эталона (mathdatum/localization.py):
 *  1. рабочая проекция — поперечный Меркатор с центром (lat0, lon0): (B, L) → (N, E);
 *  2. план — подобие относительно центроида:  [x, y] = [tx, ty] + [[a, -b], [b, a]]·([N, E] - [Nc, Ec]);
 *  3. высота — плоскость:  H = h + c0 + c1·(N - Nc) + c2·(E - Ec).
 * Подгонки — линейный МНК в замкнутой форме; при малом числе точек модель упрощается до сдвига.
 *
 * Надёжность (только диагностика, точки автоматически не исключаются):
 *  избыточность r_plan = 2n − 4 (сдвиг 2n − 2), r_height = n − 3 (сдвиг n − 1);
 *  кофакторы Q = (AᵀA)⁻¹, ковариация σ²·Q (σ — априорная или апостериорная s0 = sqrt(Σv²/r));
 *  q_vv = 1 − aᵀQa (для точек вне подгонки 1 + aᵀQa); нормированная поправка w = v / (σ·sqrt(q_vv));
 *  ошибка с исключением (leave-one-out) — прогноз датумом без точки, v / q_vv;
 *  СКО прогноза m = σ·sqrt(aᵀQa); экстраполяция — расстояние до выпуклой оболочки опорных пунктов.
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

/** Невязка (каталог − вычисленное) и диагностика точки; null — не определено (см. Python-эталон). */
@Serializable
data class Residual(
    val name: String,
    val use: Use,
    val dx: Double,
    val dy: Double,
    val dH: Double,
    @SerialName("qvv_plan") val qvvPlan: Double? = null,
    @SerialName("qvv_height") val qvvHeight: Double? = null,
    val wx: Double? = null,
    val wy: Double? = null,
    @SerialName("wH") val wH: Double? = null,
    @SerialName("loo_dx") val looDx: Double? = null,
    @SerialName("loo_dy") val looDy: Double? = null,
    @SerialName("loo_dH") val looDH: Double? = null,
    val suspect: Boolean = false,
) {
    /** max(|wx|, |wy|). */
    val wPlan: Double? get() = if (wx == null || wy == null) null else max(abs(wx), abs(wy))
    /** Радиальная ошибка с исключением в плане. */
    val looPlan: Double? get() = if (looDx == null || looDy == null) null else hypot(looDx, looDy)
}

/** Предупреждение о качестве датума: code — для программ, message — для человека. */
@Serializable
data class DatumWarning(val code: String, val message: String, val point: String? = null)

/** Точность в точке пересчёта: расстояние до оболочки опорных пунктов (0 — внутри) и СКО прогноза, м. */
data class PointQuality(val outside: Double?, val mPlan: Double?, val mHeight: Double?)

/** Предложение исключить компонент точки: part — "plan" или "height". */
data class Exclusion(val name: String, val part: String, val w: Double)

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
    @SerialName("redundancy_plan") val redundancyPlan: Int? = null,
    @SerialName("redundancy_height") val redundancyHeight: Int? = null,
    /** Априорная СКО одной координаты в плане и высоты, м. */
    @SerialName("sigma0_plan") val sigma0Plan: Double? = null,
    @SerialName("sigma0_height") val sigma0Height: Double? = null,
    /** Апостериорная СКО (на координату), null при нулевой избыточности. */
    @SerialName("s0_plan") val s0Plan: Double? = null,
    @SerialName("s0_height") val s0Height: Double? = null,
    @SerialName("w_limit") val wLimit: Double? = null,
    /** Кофакторы (tx, ty, a, b) 4×4 и (c0, c1, c2) 3×3. */
    @SerialName("q_plan") val qPlan: List<List<Double>>? = null,
    @SerialName("q_height") val qHeight: List<List<Double>>? = null,
    /** Выпуклая оболочка опорных пунктов плана, [N, E] рабочей проекции. */
    @SerialName("plan_hull") val planHull: List<List<Double>>? = null,
    val warnings: List<DatumWarning> = emptyList(),
) {
    @Transient
    private val tm = TransverseMercator(Ellipsoid.fromProj(ellipsoid), lat0, lon0)

    internal fun forwardNE(lat: Double, lon: Double) = tm.forward(lat, lon)

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

    private fun sigmas(posterior: Boolean) = if (posterior) s0Plan to s0Height else sigma0Plan to sigma0Height

    /** Ковариация параметров плана (tx, ty, a, b): σ²·Q. */
    fun covariancePlan(posterior: Boolean = false): List<List<Double>>? {
        val s = sigmas(posterior).first ?: return null
        return qPlan?.map { row -> row.map { it * s * s } }
    }

    /** Ковариация параметров высоты (c0, c1, c2): σ²·Q. */
    fun covarianceHeight(posterior: Boolean = false): List<List<Double>>? {
        val s = sigmas(posterior).second ?: return null
        return qHeight?.map { row -> row.map { it * s * s } }
    }

    private fun quality(dN: Double, dE: Double, posterior: Boolean): PointQuality {
        val (sp, sh) = sigmas(posterior)
        val mPlan = qPlan?.let { q -> sp?.let { it * sqrt(qform(q, 1.0, 0.0, dN, -dE) + qform(q, 0.0, 1.0, dE, dN)) } }
        val mH = qHeight?.let { q -> sh?.let { it * sqrt(qform(q, 1.0, dN, dE)) } }
        val out = planHull?.takeIf { it.isNotEmpty() }?.let { outsideHull(it, dN + nc, dE + ec) }
        return PointQuality(out, mPlan, mH)
    }

    /** Точность пересчёта в точке WGS-84 (экстраполяция и СКО прогноза по априорной или апостериорной σ). */
    fun quality(p: WgsPoint, posterior: Boolean = false): PointQuality {
        val (n, e) = tm.forward(p.lat, p.lon)
        return quality(n - nc, e - ec, posterior)
    }

    /** То же для точки в местной системе. */
    fun quality(p: LocalPoint, posterior: Boolean = false): PointQuality {
        val k2 = a * a + b * b
        val u = p.x - tx
        val v = p.y - ty
        return quality((a * u + b * v) / k2, (-b * u + a * v) / k2, posterior)
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
 * [sigmaPlan], [sigmaHeight] — априорные СКО (м) координаты плана и высоты; [wLimit] — порог |w| теста Баарда;
 * [maxScalePpm], [maxRotationDeg] — пределы правдоподобия масштаба и разворота.
 */
fun localize(
    pairs: List<LocalizationPair>,
    lat0: Double? = null,
    lon0: Double? = null,
    ellipsoid: String = "+ellps=WGS84",
    sigmaPlan: Double = 0.02,
    sigmaHeight: Double = 0.03,
    wLimit: Double = 3.29,
    maxScalePpm: Double = 200.0,
    maxRotationDeg: Double = 1.0,
): LocalizationDatum =
    diagnose(fit(pairs, lat0, lon0, ellipsoid), pairs, sigmaPlan, sigmaHeight, wLimit, maxScalePpm, maxRotationDeg)

/** Подгонка параметров и невязки, без диагностики. */
private fun fit(pairs: List<LocalizationPair>, lat0: Double?, lon0: Double?, ellipsoid: String): LocalizationDatum {
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

/** q_vv меньше — у точки нет контроля (без неё модель вырождается). */
private const val Q_EPS = 1e-8

/** aᵀ·Q·a. */
internal fun qform(q: List<List<Double>>, vararg a: Double): Double {
    var s = 0.0
    for (i in a.indices) for (j in a.indices) s += q[i][j] * a[i] * a[j]
    return s
}

/**
 * Кофакторы Q = (AᵀA)⁻¹ в замкнутой форме (как в Python-эталоне).
 * План: AᵀA = diag(n, n, S, S), S = Σ(dN² + dE²); сдвиг — diag(1/n, 1/n, 0, 0).
 * Высота: m — средние (dN, dE), K — ковариация отклонений от m:
 *   Q[c1,c2] = K⁻¹, Q[c0,c·] = −K⁻¹m, Q[c0,c0] = 1/n + mᵀK⁻¹m; сдвиг — Q[c0,c0] = 1/n.
 */
private fun cofactors(d: LocalizationDatum, pairs: List<LocalizationPair>): Pair<List<List<Double>>, List<List<Double>>?> {
    val plan = pairs.filter { it.use.inPlan }
    val n = plan.size.toDouble()
    val qp = if (d.planModel == "similarity") {
        var s = 0.0
        for (p in plan) {
            val (pn, pe) = d.forwardNE(p.lat, p.lon)
            s += (pn - d.nc) * (pn - d.nc) + (pe - d.ec) * (pe - d.ec)
        }
        listOf(listOf(1 / n, 0.0, 0.0, 0.0), listOf(0.0, 1 / n, 0.0, 0.0), listOf(0.0, 0.0, 1 / s, 0.0), listOf(0.0, 0.0, 0.0, 1 / s))
    } else {
        listOf(listOf(1 / n, 0.0, 0.0, 0.0), listOf(0.0, 1 / n, 0.0, 0.0), listOf(0.0, 0.0, 0.0, 0.0), listOf(0.0, 0.0, 0.0, 0.0))
    }
    val height = pairs.filter { it.use.inHeight }
    if (height.isEmpty()) return qp to null
    val nh = height.size.toDouble()
    if (d.heightModel != "plane") {
        return qp to listOf(listOf(1 / nh, 0.0, 0.0), listOf(0.0, 0.0, 0.0), listOf(0.0, 0.0, 0.0))
    }
    val ne = height.map { d.forwardNE(it.lat, it.lon) }
    val dn = ne.map { it.first - d.nc }
    val de = ne.map { it.second - d.ec }
    val mn = dn.average()
    val me = de.average()
    var snn = 0.0; var see = 0.0; var sne = 0.0
    for (i in dn.indices) {
        val u = dn[i] - mn
        val v = de[i] - me
        snn += u * u; see += v * v; sne += u * v
    }
    val det = snn * see - sne * sne
    val k11 = see / det
    val k22 = snn / det
    val k12 = -sne / det
    val g1 = k11 * mn + k12 * me
    val g2 = k12 * mn + k22 * me
    return qp to listOf(listOf(1 / nh + mn * g1 + me * g2, -g1, -g2), listOf(-g1, k11, k12), listOf(-g2, k12, k22))
}

/** Копия пар, где точка i исключена из плана (part = "plan") или из высоты. */
private fun without(pairs: List<LocalizationPair>, i: Int, part: String): List<LocalizationPair> {
    val p = pairs[i]
    val use = if (part == "plan") (if (p.use.inHeight) Use.HEIGHT else Use.NONE) else (if (p.use.inPlan) Use.PLAN else Use.NONE)
    return pairs.mapIndexed { j, q -> if (j == i) q.copy(use = use) else q }
}

/** Датум без точки i (та же рабочая проекция); null — модель этой части вырождается или меняется. */
private fun looFit(d: LocalizationDatum, pairs: List<LocalizationPair>, i: Int, part: String): Residual? {
    val r = try {
        fit(without(pairs, i, part), d.lat0, d.lon0, d.ellipsoid)
    } catch (e: LocalizationException) {
        return null
    }
    val same = if (part == "plan") r.planModel == d.planModel else r.heightModel == d.heightModel
    return if (same) r.residuals[i] else null
}

private fun g(v: Double): String = if (v == kotlin.math.floor(v) && abs(v) < 1e15) v.toLong().toString() else v.toString()

private fun diagnose(
    d: LocalizationDatum, pairs: List<LocalizationPair>,
    sigmaPlan: Double, sigmaHeight: Double, wLimit: Double, maxScalePpm: Double, maxRotationDeg: Double,
): LocalizationDatum {
    val plan = pairs.filter { it.use.inPlan }
    val nh = pairs.count { it.use.inHeight }
    val rp = 2 * plan.size - if (d.planModel == "similarity") 4 else 2
    val rh = if (nh == 0) null else nh - if (d.heightModel == "plane") 3 else 1
    val (qp, qh) = cofactors(d, pairs)
    val hull = convexHull(plan.map { d.forwardNE(it.lat, it.lon) })

    var vp = 0.0
    var vh = 0.0
    pairs.forEachIndexed { i, p ->
        val r = d.residuals[i]
        if (p.use.inPlan) vp += r.dx * r.dx + r.dy * r.dy
        if (p.use.inHeight) vh += r.dH * r.dH
    }
    val warnings = mutableListOf<DatumWarning>()
    if (rp == 0) warnings += DatumWarning("plan_no_redundancy", "План: избыточность 0 — невязки нулевые, контроля нет.")
    if (rh == 0) warnings += DatumWarning("height_no_redundancy", "Высота: избыточность 0 — невязки нулевые, контроля нет.")
    if (d.planModel == "similarity") {
        val rotDeg = d.rotationArcsec / 3600
        if (abs(d.scalePpm) > maxScalePpm) warnings += DatumWarning(
            "scale_implausible",
            "Масштаб ${signed(d.scalePpm, 1)} ppm (предел ${g(maxScalePpm)}): вероятно, " +
                "перепутаны оси x/y, системы координат или единицы.",
        )
        if (abs(rotDeg) > maxRotationDeg) warnings += DatumWarning(
            "rotation_implausible",
            "Разворот ${signed(rotDeg, 3)}° (предел ${g(maxRotationDeg)}°): проверьте оси x/y и системы координат; " +
                "до ~1.5° бывает при удалённом осевом меридиане местной системы (сближение меридианов).",
        )
    }

    val residuals = pairs.mapIndexed { i, p ->
        var r = d.residuals[i]
        val (pn, pe) = d.forwardNE(p.lat, p.lon)
        val dN = pn - d.nc
        val dE = pe - d.ec
        // План: кофактор поправки по x и по y одинаков, q_vv = 1 ∓ aᵀQa.
        val hp = qform(qp, 1.0, 0.0, dN, -dE)
        val qvvP = if (p.use.inPlan) 1 - hp else 1 + hp
        r = r.copy(qvvPlan = qvvP)
        if (qvvP > Q_EPS) {
            val s = sigmaPlan * sqrt(qvvP)
            r = r.copy(wx = r.dx / s, wy = r.dy / s)
        }
        r = if (p.use.inPlan) {
            val l = if (qvvP > Q_EPS) looFit(d, pairs, i, "plan") else null
            r.copy(looDx = l?.dx, looDy = l?.dy)
        } else {
            r.copy(looDx = r.dx, looDy = r.dy)
        }
        if (qh != null) {
            val hh = qform(qh, 1.0, dN, dE)
            val qvvH = if (p.use.inHeight) 1 - hh else 1 + hh
            r = r.copy(qvvHeight = qvvH)
            if (qvvH > Q_EPS) r = r.copy(wH = r.dH / (sigmaHeight * sqrt(qvvH)))
            r = if (p.use.inHeight) {
                r.copy(looDH = if (qvvH > Q_EPS) looFit(d, pairs, i, "height")?.dH else null)
            } else {
                r.copy(looDH = r.dH)
            }
        }
        val checks = listOf(
            Triple("plan", r.wPlan, r.looPlan) to p.use.inPlan,
            Triple("height", r.wH?.let(::abs), r.looDH?.let(::abs)) to p.use.inHeight,
        )
        for ((t, inside) in checks) {
            val (part, w, loo) = t
            if (w == null || w <= wLimit) continue
            r = r.copy(suspect = true)
            val what = if (part == "plan") "план" else "высота"
            val kind = if (inside) "нормированная поправка" else "контроль: нормированная ошибка"
            val looTxt = if (loo == null) "" else ", ошибка без точки ${loo.fixed(3)} м"
            warnings += DatumWarning(
                "suspect_$part",
                "${p.name} ($what): $kind |w| = ${w.fixed(2)} > ${g(wLimit)}$looTxt — вероятна грубая ошибка.",
                p.name,
            )
        }
        r
    }
    return d.copy(
        residuals = residuals,
        redundancyPlan = rp, redundancyHeight = rh,
        sigma0Plan = sigmaPlan, sigma0Height = sigmaHeight,
        s0Plan = if (rp > 0) sqrt(vp / rp) else null,
        s0Height = if (rh != null && rh > 0) sqrt(vh / rh) else null,
        wLimit = wLimit, qPlan = qp, qHeight = qh,
        planHull = hull.map { listOf(it.first, it.second) },
        warnings = warnings,
    )
}

/** Выпуклая оболочка (монотонная цепь Эндрю), против часовой стрелки в осях (N, E); 1–2 точки — точка или отрезок. */
fun convexHull(points: List<Pair<Double, Double>>): List<Pair<Double, Double>> {
    val pts = points.distinct().sortedWith(compareBy({ it.first }, { it.second }))
    if (pts.size <= 2) return pts
    fun cross(o: Pair<Double, Double>, a: Pair<Double, Double>, b: Pair<Double, Double>) =
        (a.first - o.first) * (b.second - o.second) - (a.second - o.second) * (b.first - o.first)
    val lower = mutableListOf<Pair<Double, Double>>()
    for (p in pts) {
        while (lower.size >= 2 && cross(lower[lower.size - 2], lower.last(), p) <= 0) lower.removeAt(lower.size - 1)
        lower += p
    }
    val upper = mutableListOf<Pair<Double, Double>>()
    for (p in pts.asReversed()) {
        while (upper.size >= 2 && cross(upper[upper.size - 2], upper.last(), p) <= 0) upper.removeAt(upper.size - 1)
        upper += p
    }
    return lower.dropLast(1) + upper.dropLast(1)
}

/** Расстояние от (n, e) до выпуклой оболочки [hull] (вершины [N, E]); 0 внутри и на границе. */
fun outsideHull(hull: List<List<Double>>, n: Double, e: Double): Double {
    val m = hull.size
    if (m == 1) return hypot(n - hull[0][0], e - hull[0][1])
    var dist = Double.POSITIVE_INFINITY
    var inside = m > 2
    for (k in 0 until (if (m > 2) m else 1)) {
        val p0 = hull[k]
        val p1 = hull[(k + 1) % m]
        val ex = p1[0] - p0[0]
        val ey = p1[1] - p0[1]
        val px = n - p0[0]
        val py = e - p0[1]
        val t = min(1.0, max(0.0, (px * ex + py * ey) / (ex * ex + ey * ey)))
        dist = min(dist, hypot(px - t * ex, py - t * ey))
        if (ex * py - ey * px < 0) inside = false
    }
    return if (inside) 0.0 else dist
}

/**
 * Итеративно предлагает исключить худшую точку: на каждом шаге — компонент (план или высота) с наибольшим
 * |w| > wLimit среди участвующих; он исключается и датум пересчитывается. Исходные пары не меняются.
 */
fun suggestExclusions(
    pairs: List<LocalizationPair>,
    sigmaPlan: Double = 0.02,
    sigmaHeight: Double = 0.03,
    wLimit: Double = 3.29,
    ellipsoid: String = "+ellps=WGS84",
): List<Exclusion> {
    var d = localize(pairs, ellipsoid = ellipsoid, sigmaPlan = sigmaPlan, sigmaHeight = sigmaHeight, wLimit = wLimit)
    val lat0 = d.lat0
    val lon0 = d.lon0
    var cur = pairs
    val out = mutableListOf<Exclusion>()
    while (true) {
        var worst: Triple<Int, String, Double>? = null
        cur.forEachIndexed { i, p ->
            val r = d.residuals[i]
            for ((part, w, inside) in listOf(Triple("plan", r.wPlan, p.use.inPlan), Triple("height", r.wH?.let(::abs), p.use.inHeight))) {
                if (inside && w != null && w > wLimit && (worst == null || w > worst!!.third)) worst = Triple(i, part, w)
            }
        }
        val (i, part, w) = worst ?: return out
        out += Exclusion(cur[i].name, part, w)
        cur = without(cur, i, part)
        d = try {
            localize(cur, lat0, lon0, ellipsoid, sigmaPlan, sigmaHeight, wLimit)
        } catch (e: LocalizationException) {
            return out
        }
    }
}
