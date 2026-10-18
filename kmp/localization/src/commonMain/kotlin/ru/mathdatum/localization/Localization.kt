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
 *  1. рабочая проекция — поперечный Меркатор с центром (lat0, lon0) на эллипсоиде системы ГНСС-измерений
 *     (gnssDatum, по умолчанию WGS-84; координаты в другую систему не переводятся): (B, L) → (N, E);
 *     можно задать свою (k0, x0, y0 — например, спроектированная LDP, [Ldp]): масштаб подобия тогда ≈ 1;
 *  2. план — подобие относительно центроида:  [x, y] = [tx, ty] + [[a, -b], [b, a]]·([N, E] - [Nc, Ec]);
 *  3. высота (heightModel): plane — H = h + c0 + c1·(N - Nc) + c2·(E - Ec); geoid — H = h − N(B, L) + c0;
 *     geoid_plane — H = h − N(B, L) + c0 + c1·(N - Nc) + c2·(E - Ec). N — сетка геоида ([GeoidGrid]); в датуме
 *     только ссылка ([GeoidRef]: имя файла, SHA-256, интерполяция). Вне сетки / NODATA — GeoidException.
 * Подгонки — взвешенный линейный МНК в замкнутой форме; при малом числе точек модель упрощается до сдвига.
 * Вес точки p = σ0² / σi² (σi — sigmaPlan / sigmaHeight пары, null → p = 1); центроид плана взвешенный.
 *
 * Надёжность (только диагностика, точки автоматически не исключаются):
 *  избыточность r_plan = 2n − 4 (сдвиг 2n − 2), r_height = n − 3 (сдвиг n − 1);
 *  кофакторы Q = (AᵀPA)⁻¹, ковариация σ²·Q (σ — априорная σ0 или апостериорная s0 = sqrt(vᵀPv/r));
 *  q_vv = 1/p − aᵀQa (для точек вне подгонки 1/p + aᵀQa), Σ p·q_vv = r;
 *  нормированная поправка w = v / (σ0·sqrt(q_vv));
 *  ошибка с исключением (leave-one-out) — прогноз датумом без точки, v / (p·q_vv);
 *  СКО прогноза m = σ0·sqrt(aᵀQa); экстраполяция — расстояние до выпуклой оболочки опорных пунктов.
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

/**
 * Пара точек: ГНСС (B, L — градусы WGS-84, h — эллипсоидальная высота) и местные x (север), y (восток), H.
 * [sigmaPlan], [sigmaHeight] — априорные СКО точки, м (план — на координату): суммарная точность каталога
 * и ГНСС, sqrt(σ_кат² + σ_ГНСС²); null — глобальная σ из параметров [localize].
 */
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
    @SerialName("sigma_plan") val sigmaPlan: Double? = null,
    @SerialName("sigma_height") val sigmaHeight: Double? = null,
)

/** Невязка (каталог − вычисленное) и диагностика точки; null — не определено (см. Python-эталон). */
@Serializable
data class Residual(
    val name: String,
    val use: Use,
    val dx: Double,
    val dy: Double,
    val dH: Double,
    /** Использованная априорная СКО точки (σi или σ0), м, и вес p = σ0² / σi². */
    @SerialName("sigma_plan") val sigmaPlan: Double? = null,
    @SerialName("sigma_height") val sigmaHeight: Double? = null,
    @SerialName("p_plan") val pPlan: Double? = null,
    @SerialName("p_height") val pHeight: Double? = null,
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
    /** Масштаб и ложные смещения (север, восток) рабочей проекции; в старых JSON нет → 1, 0, 0. */
    val k0: Double = 1.0,
    val x0: Double = 0.0,
    val y0: Double = 0.0,
    /** Система ГНСС-координат (код [Datums.SYSTEMS]); null — старый JSON. */
    @SerialName("gnss_datum") val gnssDatum: String? = null,
    @SerialName("plan_model") val planModel: String = "similarity",
    /** Итоговая модель высоты: plane | shift | geoid_plane | geoid | none. */
    @SerialName("height_model") val heightModel: String = "plane",
    /** Ссылка на сетку геоида (модели geoid, geoid_plane); null — без геоида. */
    val geoid: GeoidRef? = null,
    val residuals: List<Residual> = emptyList(),
    @SerialName("rms_plan") val rmsPlan: Double? = null,
    @SerialName("rms_height") val rmsHeight: Double? = null,
    @SerialName("redundancy_plan") val redundancyPlan: Int? = null,
    @SerialName("redundancy_height") val redundancyHeight: Int? = null,
    /** СКО единицы веса (p = 1): координата в плане и высота, м. */
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
    /** Загруженная сетка геоида (в JSON не попадает). */
    @Transient val geoidGrid: GeoidGrid? = null,
) {
    @Transient
    private val tm = WorkProjection(Ellipsoid.fromProj(ellipsoid), lat0, lon0, k0, x0, y0)

    internal fun forwardNE(lat: Double, lon: Double) = tm.forward(lat, lon)

    val scale: Double get() = hypot(a, b)
    val scalePpm: Double get() = (scale - 1) * 1e6
    val rotationArcsec: Double get() = atan2(b, a) * 180 * 3600 / PI
    /** Есть точки со своей σ (вес ≠ 1). */
    val weighted: Boolean get() = residuals.any { r -> listOf(r.pPlan, r.pHeight).any { it != null && it != 1.0 } }
    val projection: String get() {
        val old = k0 == 1.0 && x0 == 0.0 && y0 == 0.0
        return "+proj=tmerc +lat_0=$lat0 +lon_0=$lon0 +k=${if (old) "1" else g(k0)} +x_0=${if (old) "0" else g(y0)} " +
            "+y_0=${if (old) "0" else g(x0)} $ellipsoid +units=m"
    }

    /** Подключает сетку геоида; SHA-256 должна совпасть со ссылкой датума. */
    fun withGeoid(grid: GeoidGrid): LocalizationDatum {
        val ref = geoid ?: throw GeoidException("Датум без модели геоида (height_model без geoid): сетка не нужна.")
        if (grid.sha256 != ref.sha256) throw GeoidException(
            "Сетка геоида ${grid.name}: SHA-256 ${grid.sha256} не совпадает с датумом (${ref.file}, ${ref.sha256}) — это другая сетка.",
        )
        return copy(geoidGrid = grid)
    }

    /** N(B, L) из сетки датума, м (0 — модель без геоида). */
    fun geoidHeight(lat: Double, lon: Double): Double {
        val ref = geoid ?: return 0.0
        val grid = geoidGrid ?: throw GeoidException(
            "Датум использует сетку геоида ${ref.file} (sha256 ${ref.sha256}), она не загружена: укажите файл сетки.",
        )
        return grid.value(lat, lon, ref.interpolation)
    }

    /** Система ГНСС-координат датума; у старого JSON — WGS-84, если рабочая проекция на WGS-84. */
    val gnssSystem: String? get() = gnssDatum ?: if (ellipsoid == "+ellps=WGS84") "WGS-84" else null

    private fun sameSystem(datum: String?): Boolean {
        if (datum == null) return true
        val own = gnssSystem ?: throw IllegalArgumentException(
            "В датуме не указана система ГНСС (gnss_datum) — пересчёт из другой системы невозможен.",
        )
        return Datums.system(datum).id == own
    }

    /** Точку ГНСС из системы [datum] — в систему датума (7 параметров ГОСТ 32453). */
    fun fromSystem(p: WgsPoint, datum: String?): WgsPoint {
        if (sameSystem(datum)) return p
        val g = Datums.transformBlh(GeodeticPoint(p.lat, p.lon, p.h), datum!!, gnssSystem!!)
        return WgsPoint(g.lat, g.lon, g.h)
    }

    /**
     * ГНСС → местная система. [datum] — система точки, если не совпадает с [gnssDatum]
     * (тогда она сначала пересчитывается по 7 параметрам ГОСТ 32453).
     */
    fun toLocal(p: WgsPoint, datum: String? = null): LocalPoint {
        val q = fromSystem(p, datum)
        val (n, e) = tm.forward(q.lat, q.lon)
        val dN = n - nc
        val dE = e - ec
        return LocalPoint(
            x = tx + a * dN - b * dE,
            y = ty + b * dN + a * dE,
            height = q.h - geoidHeight(q.lat, q.lon) + c0 + c1 * dN + c2 * dE,
        )
    }

    /** Местная система → ГНСС в системе датума или в [datum]. */
    fun toWgs(p: LocalPoint, datum: String? = null): WgsPoint {
        val k2 = a * a + b * b
        val u = p.x - tx
        val v = p.y - ty
        val dN = (a * u + b * v) / k2
        val dE = (-b * u + a * v) / k2
        val (lat, lon) = tm.inverse(dN + nc, dE + ec)
        val w = WgsPoint(lat, lon, p.height + geoidHeight(lat, lon) - (c0 + c1 * dN + c2 * dE))
        if (sameSystem(datum)) return w
        val g = Datums.transformBlh(GeodeticPoint(w.lat, w.lon, w.h), gnssSystem!!, datum!!)
        return WgsPoint(g.lat, g.lon, g.h)
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

    /** Строка PROJ: вход (широта, долгота, h) → выход (x, y, H); с геоидом — шаг vgridshift (PROJ читает GTX, не GGF/ISG). */
    fun toProjPipeline(): String {
        val xoff = tx - a * nc + b * ec
        val yoff = ty - b * nc - a * ec
        val zoff = c0 - c1 * nc - c2 * ec
        return "+proj=pipeline +step +proj=axisswap +order=2,1 " +
            "+step +proj=unitconvert +xy_in=deg +xy_out=rad " +
            (geoid?.let { "+step +proj=vgridshift +grids=${it.file} +multiplier=-1 " } ?: "") +
            "+step $projection " +
            "+step +proj=affine +xoff=$xoff +s11=${-b} +s12=$a +s13=0 " +
            "+yoff=$yoff +s21=$a +s22=$b +s23=0 " +
            "+zoff=$zoff +s31=$c2 +s32=$c1 +s33=1"
    }

    fun toJson(): String = JSON.encodeToString(serializer(), this)

    companion object {
        internal val JSON = Json { prettyPrint = true; ignoreUnknownKeys = true; encodeDefaults = true }

        /**
         * Читает датум из JSON (в том числе сохранённый Python-эталоном; поле summary игнорируется).
         * Датум со ссылкой на сетку геоида требует [geoid] с той же SHA-256 (иначе GeoidException);
         * [requireGeoid] = false — читать без сетки (пересчёт высот тогда — ошибка).
         */
        fun fromJson(text: String, geoid: GeoidGrid? = null, requireGeoid: Boolean = true): LocalizationDatum {
            val d = JSON.decodeFromString(serializer(), text)
            val ref = d.geoid
            if (ref == null) {
                if (geoid != null) throw GeoidException("Датум без модели геоида: сетка не нужна.")
                return d
            }
            if (geoid == null) {
                if (!requireGeoid) return d
                throw GeoidException("Датум использует сетку геоида ${ref.file} (sha256 ${ref.sha256}): загрузите этот файл.")
            }
            return d.withGeoid(geoid)
        }
    }
}

class LocalizationException(message: String) : IllegalArgumentException(message)

/** Рабочая проекция датума: поперечный Меркатор (lat0, lon0) с масштабом k0 и смещениями x0 (север), y0 (восток). */
internal class WorkProjection(e: Ellipsoid, lat0: Double, lon0: Double, private val k0: Double, private val x0: Double, private val y0: Double) {
    private val tm = TransverseMercator(e, lat0, lon0)

    /** (B, L) → (N, E) рабочей проекции. */
    fun forward(lat: Double, lon: Double): Pair<Double, Double> {
        val (n, e) = tm.forward(lat, lon)
        return (x0 + k0 * n) to (y0 + k0 * e)
    }

    fun inverse(n: Double, e: Double): Pair<Double, Double> = tm.inverse((n - x0) / k0, (e - y0) / k0)
}

/** Локализация в заданной рабочей проекции (спроектированная LDP типа tmerc): масштаб подобия остаётся ≈ 1. */
fun localizeIn(projection: LdpProjection, pairs: List<LocalizationPair>, gnssDatum: String = "WGS-84",
               heightModel: String = "plane", geoid: GeoidGrid? = null, geoidInterpolation: String = "bilinear"): LocalizationDatum =
    localize(
        pairs, projection.lat0, projection.lon0, projection.system.ellipsoid.proj, gnssDatum = gnssDatum, heightModel = heightModel,
        geoid = geoid, geoidInterpolation = geoidInterpolation, k0 = projection.k0, x0 = projection.x0, y0 = projection.y0,
    )

/**
 * Вычисляет датум локализации по парам точек.
 * [lat0], [lon0] — центр рабочей проекции; по умолчанию — среднее по используемым точкам.
 * [gnssDatum] — система ГНСС-координат пар (код или название из [Datums.SYSTEMS]), по умолчанию WGS-84;
 * [ellipsoid] — эллипсоид рабочей проекции (PROJ), по умолчанию — эллипсоид [gnssDatum].
 * [sigmaPlan], [sigmaHeight] — априорные СКО (м) координаты плана и высоты (СКО единицы веса σ0); точки со своей
 * σi получают вес p = σ0² / σi²; [wLimit] — порог |w| теста Баарда;
 * [maxScalePpm], [maxRotationDeg] — пределы правдоподобия масштаба и разворота.
 * [heightModel] — plane (по умолчанию, без геоида), geoid или geoid_plane; для двух последних [geoid] — сетка
 * на эллипсоиде системы [gnssDatum], [geoidInterpolation] — bilinear или bicubic.
 * [k0], [x0] (север), [y0] (восток) — масштаб и смещения рабочей проекции (своя, например LDP: [localizeIn]).
 */
fun localize(
    pairs: List<LocalizationPair>,
    lat0: Double? = null,
    lon0: Double? = null,
    ellipsoid: String? = null,
    sigmaPlan: Double = 0.02,
    sigmaHeight: Double = 0.03,
    wLimit: Double = 3.29,
    maxScalePpm: Double = 200.0,
    maxRotationDeg: Double = 3.0,
    gnssDatum: String = "WGS-84",
    heightModel: String = "plane",
    geoid: GeoidGrid? = null,
    geoidInterpolation: String = "bilinear",
    k0: Double = 1.0,
    x0: Double = 0.0,
    y0: Double = 0.0,
): LocalizationDatum {
    val system = Datums.system(gnssDatum)
    checkHeightModel(heightModel, geoid, geoidInterpolation)
    val d = fit(
        pairs, lat0, lon0, ellipsoid ?: system.ellipsoid.proj, sigmaPlan, sigmaHeight, heightModel, geoid, geoidInterpolation,
        k0, x0, y0,
    ).copy(gnssDatum = system.id)
    return diagnose(d, pairs, sigmaPlan, sigmaHeight, wLimit, maxScalePpm, maxRotationDeg)
}

/** Модели высоты, которые можно запросить, и модели с плоскостью (3 параметра). */
val HEIGHT_MODELS = listOf("plane", "geoid", "geoid_plane")
private val PLANE_MODELS = setOf("plane", "geoid_plane")

private fun checkHeightModel(model: String, geoid: GeoidGrid?, interpolation: String) {
    if (model !in HEIGHT_MODELS) throw LocalizationException("Модель высоты «$model»: ожидается ${HEIGHT_MODELS.joinToString(", ")}.")
    if (model == "plane") {
        if (geoid != null) throw LocalizationException("Сетка геоида задана, а модель высоты plane: укажите geoid или geoid_plane.")
        return
    }
    if (geoid == null) throw LocalizationException("Модель высоты $model: нужна сетка геоида.")
    if (interpolation !in GeoidGrid.INTERPOLATIONS) {
        throw LocalizationException("Интерполяция «$interpolation»: ожидается ${GeoidGrid.INTERPOLATIONS.joinToString(", ")}.")
    }
}

/** Запрошенная модель высоты по итоговой (для пересчёта без точки). */
private fun heightRequest(d: LocalizationDatum) = when {
    d.geoid == null -> "plane"
    d.heightModel == "geoid_plane" -> "geoid_plane"
    else -> "geoid"
}

/** Вес p = σ0² / σi² (σi — sigmaPlan или sigmaHeight пары; null → p = 1). */
private fun weight(p: LocalizationPair, sigma0: Double, plan: Boolean): Double {
    val s = (if (plan) p.sigmaPlan else p.sigmaHeight) ?: return 1.0
    if (!(s.isFinite() && s > 0)) {
        throw LocalizationException("${p.name}: sigma_${if (plan) "plan" else "height"} = $s — ожидается СКО > 0.")
    }
    val k = sigma0 / s
    return k * k
}

/** Подгонка параметров (взвешенный МНК) и невязки, без диагностики. */
private fun fit(
    pairs: List<LocalizationPair>, lat0: Double?, lon0: Double?, ellipsoid: String, sigmaPlan: Double, sigmaHeight: Double,
    heightModel: String = "plane", grid: GeoidGrid? = null, interpolation: String = "bilinear",
    k0: Double = 1.0, x0: Double = 0.0, y0: Double = 0.0,
): LocalizationDatum {
    if (!(k0 > 0)) throw LocalizationException("Масштаб рабочей проекции k0 = $k0: ожидается > 0.")
    val plan = pairs.filter { it.use.inPlan }
    val height = pairs.filter { it.use.inHeight }
    if (plan.isEmpty()) throw LocalizationException("Нет ни одной точки для плана (use = both/plan).")
    val used = pairs.filter { it.use != Use.NONE }
    val cLat = lat0 ?: used.map { it.lat }.average()
    val cLon = lon0 ?: used.map { it.lon }.average()
    val tm = WorkProjection(Ellipsoid.fromProj(ellipsoid), cLat, cLon, k0, x0, y0)
    val ref = grid?.let { GeoidRef(it.name, it.sha256, interpolation) }
    fun geoidN(p: LocalizationPair) = grid?.value(p.lat, p.lon, interpolation) ?: 0.0

    // План: подобие в комплексной форме w = t + k·(z - zc), z = N + iE, w = x + iy;
    // zc, wc — взвешенные центроиды, k = Σ p·conj(z - zc)·(w - wc) / Σ p·|z - zc|².
    val zp = plan.map { tm.forward(it.lat, it.lon) }
    val pw = plan.map { weight(it, sigmaPlan, true) }
    val sp = pw.sum()
    val nc = plan.indices.sumOf { pw[it] * zp[it].first } / sp
    val ec = plan.indices.sumOf { pw[it] * zp[it].second } / sp
    val xc = plan.indices.sumOf { pw[it] * plan[it].x } / sp
    val yc = plan.indices.sumOf { pw[it] * plan[it].y } / sp
    var a = 1.0
    var b = 0.0
    val planModel: String
    if (plan.size >= 2) {
        var sRe = 0.0
        var sIm = 0.0
        var denom = 0.0
        var spread = 0.0
        plan.forEachIndexed { i, p ->
            val zn = zp[i].first - nc
            val ze = zp[i].second - ec
            val wx = p.x - xc
            val wy = p.y - yc
            // p·conj(z)·w = p·(zn - i·ze)(wx + i·wy)
            sRe += pw[i] * (zn * wx + ze * wy)
            sIm += pw[i] * (zn * wy - ze * wx)
            denom += pw[i] * (zn * zn + ze * ze)
            spread += zn * zn + ze * ze
        }
        if (spread < 1e-6) throw LocalizationException("Точки для плана совпадают: нельзя определить разворот и масштаб.")
        a = sRe / denom
        b = sIm / denom
        planModel = "similarity"
    } else {
        planModel = "shift"
    }

    // Высота: взвешенная плоскость относительно центроида плана; решаем по данным, центрированным
    // на взвешенное среднее (устойчиво).
    var c0 = 0.0
    var c1 = 0.0
    var c2 = 0.0
    val fitted: String
    if (height.isEmpty()) {
        fitted = "none"
    } else {
        val zh = height.map { tm.forward(it.lat, it.lon) }
        val dn = zh.map { it.first - nc }
        val de = zh.map { it.second - ec }
        // После геоида подгоняются разности H − (h − N).
        val dh = height.map { it.height - it.h + geoidN(it) }
        val ph = height.map { weight(it, sigmaHeight, false) }
        val sh = ph.sum()
        val mn = height.indices.sumOf { ph[it] * dn[it] } / sh
        val me = height.indices.sumOf { ph[it] * de[it] } / sh
        val mh = height.indices.sumOf { ph[it] * dh[it] } / sh
        var snn = 0.0; var see = 0.0; var sne = 0.0; var snh = 0.0; var seh = 0.0
        for (i in height.indices) {
            val u = dn[i] - mn
            val v = de[i] - me
            val w = dh[i] - mh
            val q = ph[i]
            snn += q * u * u; see += q * v * v; sne += q * u * v; snh += q * u * w; seh += q * v * w
        }
        val det = snn * see - sne * sne
        val trace = snn + see
        if (heightModel in PLANE_MODELS && height.size >= 3 && trace > 0 && det > 1e-12 * trace * trace) {
            c1 = (snh * see - seh * sne) / det
            c2 = (seh * snn - snh * sne) / det
            c0 = mh - c1 * mn - c2 * me
            fitted = if (grid != null) "geoid_plane" else "plane"
        } else {
            c0 = mh
            fitted = if (grid != null) "geoid" else "shift"
        }
    }

    val datum = LocalizationDatum(
        lat0 = cLat, lon0 = cLon, nc = nc, ec = ec, a = a, b = b, tx = xc, ty = yc,
        c0 = c0, c1 = c1, c2 = c2, ellipsoid = ellipsoid, k0 = k0, x0 = x0, y0 = y0, planModel = planModel, heightModel = fitted,
        geoid = ref, geoidGrid = grid,
    )
    // Невязки (каталог − вычисленное) по всем точкам; точки use = none — контроль, в СКО не входят. СКО невзвешенные.
    val residuals = pairs.map { p ->
        val r = datum.toLocal(WgsPoint(p.lat, p.lon, p.h))
        Residual(p.name, p.use, p.x - r.x, p.y - r.y, p.height - r.height)
    }
    val vp = residuals.filter { it.use.inPlan }.map { it.dx * it.dx + it.dy * it.dy }
    val vh = residuals.filter { it.use.inHeight }.map { it.dH * it.dH }
    return datum.copy(
        residuals = residuals,
        rmsPlan = if (vp.isEmpty()) null else sqrt(vp.average()),
        rmsHeight = if (vh.isEmpty()) null else sqrt(vh.average()),
        sigma0Plan = sigmaPlan, sigma0Height = sigmaHeight,
    )
}

/** p·q_vv меньше — у точки нет контроля (без неё модель вырождается). */
private const val Q_EPS = 1e-8

/** aᵀ·Q·a. */
internal fun qform(q: List<List<Double>>, vararg a: Double): Double {
    var s = 0.0
    for (i in a.indices) for (j in a.indices) s += q[i][j] * a[i] * a[j]
    return s
}

/**
 * Кофакторы Q = (AᵀPA)⁻¹ в замкнутой форме (как в Python-эталоне).
 * План (относительно взвешенного центроида): AᵀPA = diag(P, P, S, S), P = Σp, S = Σp·(dN² + dE²);
 * сдвиг — Q = diag(1/P, 1/P, 0, 0).
 * Высота: m — взвешенные средние (dN, dE), K = Σp·(u, v)ᵀ(u, v) по отклонениям от m:
 *   Q[c1,c2] = K⁻¹, Q[c0,c·] = −K⁻¹m, Q[c0,c0] = 1/P + mᵀK⁻¹m; сдвиг — Q[c0,c0] = 1/P.
 */
private fun cofactors(d: LocalizationDatum, pairs: List<LocalizationPair>): Pair<List<List<Double>>, List<List<Double>>?> {
    val plan = pairs.filter { it.use.inPlan }
    val sigmaPlan = d.sigma0Plan!!
    val n = plan.sumOf { weight(it, sigmaPlan, true) }
    val qp = if (d.planModel == "similarity") {
        var s = 0.0
        for (p in plan) {
            val (pn, pe) = d.forwardNE(p.lat, p.lon)
            s += weight(p, sigmaPlan, true) * ((pn - d.nc) * (pn - d.nc) + (pe - d.ec) * (pe - d.ec))
        }
        listOf(listOf(1 / n, 0.0, 0.0, 0.0), listOf(0.0, 1 / n, 0.0, 0.0), listOf(0.0, 0.0, 1 / s, 0.0), listOf(0.0, 0.0, 0.0, 1 / s))
    } else {
        listOf(listOf(1 / n, 0.0, 0.0, 0.0), listOf(0.0, 1 / n, 0.0, 0.0), listOf(0.0, 0.0, 0.0, 0.0), listOf(0.0, 0.0, 0.0, 0.0))
    }
    val height = pairs.filter { it.use.inHeight }
    if (height.isEmpty()) return qp to null
    val ph = height.map { weight(it, d.sigma0Height!!, false) }
    val nh = ph.sum()
    if (d.heightModel !in PLANE_MODELS) {
        return qp to listOf(listOf(1 / nh, 0.0, 0.0), listOf(0.0, 0.0, 0.0), listOf(0.0, 0.0, 0.0))
    }
    val ne = height.map { d.forwardNE(it.lat, it.lon) }
    val dn = ne.map { it.first - d.nc }
    val de = ne.map { it.second - d.ec }
    val mn = dn.indices.sumOf { ph[it] * dn[it] } / nh
    val me = de.indices.sumOf { ph[it] * de[it] } / nh
    var snn = 0.0; var see = 0.0; var sne = 0.0
    for (i in dn.indices) {
        val u = dn[i] - mn
        val v = de[i] - me
        snn += ph[i] * u * u; see += ph[i] * v * v; sne += ph[i] * u * v
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
        fit(
            without(pairs, i, part), d.lat0, d.lon0, d.ellipsoid, d.sigma0Plan!!, d.sigma0Height!!,
            heightRequest(d), d.geoidGrid, d.geoid?.interpolation ?: "bilinear", d.k0, d.x0, d.y0,
        )
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
    val rh = if (nh == 0) null else nh - if (d.heightModel in PLANE_MODELS) 3 else 1
    val (qp, qh) = cofactors(d, pairs)
    val pp = pairs.map { weight(it, sigmaPlan, true) }
    val ph = pairs.map { weight(it, sigmaHeight, false) }
    val hull = convexHull(plan.map { d.forwardNE(it.lat, it.lon) })

    var vp = 0.0
    var vh = 0.0
    pairs.forEachIndexed { i, p ->
        val r = d.residuals[i]
        if (p.use.inPlan) vp += pp[i] * (r.dx * r.dx + r.dy * r.dy)
        if (p.use.inHeight) vh += ph[i] * r.dH * r.dH
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
        r = r.copy(
            sigmaPlan = p.sigmaPlan ?: sigmaPlan, sigmaHeight = p.sigmaHeight ?: sigmaHeight,
            pPlan = pp[i], pHeight = ph[i],
        )
        // План: кофактор поправки по x и по y одинаков, q_vv = 1/p ∓ aᵀQa.
        val hp = qform(qp, 1.0, 0.0, dN, -dE)
        val qvvP = if (p.use.inPlan) 1 / pp[i] - hp else 1 / pp[i] + hp
        val okP = pp[i] * qvvP > Q_EPS
        r = r.copy(qvvPlan = qvvP)
        if (okP) {
            val s = sigmaPlan * sqrt(qvvP)
            r = r.copy(wx = r.dx / s, wy = r.dy / s)
        }
        r = if (p.use.inPlan) {
            val l = if (okP) looFit(d, pairs, i, "plan") else null
            r.copy(looDx = l?.dx, looDy = l?.dy)
        } else {
            r.copy(looDx = r.dx, looDy = r.dy)
        }
        if (qh != null) {
            val hh = qform(qh, 1.0, dN, dE)
            val qvvH = if (p.use.inHeight) 1 / ph[i] - hh else 1 / ph[i] + hh
            val okH = ph[i] * qvvH > Q_EPS
            r = r.copy(qvvHeight = qvvH)
            if (okH) r = r.copy(wH = r.dH / (sigmaHeight * sqrt(qvvH)))
            r = if (p.use.inHeight) {
                r.copy(looDH = if (okH) looFit(d, pairs, i, "height")?.dH else null)
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
    ellipsoid: String? = null,
    gnssDatum: String = "WGS-84",
    heightModel: String = "plane",
    geoid: GeoidGrid? = null,
    geoidInterpolation: String = "bilinear",
    lat0: Double? = null,
    lon0: Double? = null,
    k0: Double = 1.0,
    x0: Double = 0.0,
    y0: Double = 0.0,
): List<Exclusion> {
    var d = localize(
        pairs, lat0, lon0, ellipsoid = ellipsoid, sigmaPlan = sigmaPlan, sigmaHeight = sigmaHeight, wLimit = wLimit,
        gnssDatum = gnssDatum, heightModel = heightModel, geoid = geoid, geoidInterpolation = geoidInterpolation,
        k0 = k0, x0 = x0, y0 = y0,
    )
    val cLat = d.lat0
    val cLon = d.lon0
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
            localize(
                cur, cLat, cLon, ellipsoid, sigmaPlan, sigmaHeight, wLimit, gnssDatum = gnssDatum,
                heightModel = heightModel, geoid = geoid, geoidInterpolation = geoidInterpolation, k0 = k0, x0 = x0, y0 = y0,
            )
        } catch (e: LocalizationException) {
            return out
        }
    }
}
