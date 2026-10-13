package mathdatum.core

import kotlin.math.abs
import kotlin.math.hypot
import kotlin.math.sqrt

data class ControlPair(val surface: SurfacePoint, val wgs84: Geodetic)

enum class LocalizationWarning {
    SINGLE_PAIR_TRANSLATION_ONLY, // 1 пара: только сдвиг, ориентация и масштаб предположены
    NO_REDUNDANCY,                // 2 пары: невязок нет, ошибку не проверить
    DUPLICATE_POINTS,             // совпадающие точки в паре/между парами
    SCALE_NOT_ONE,                // масштаб отличается от 1 больше допуска
    RMS_ABOVE_TOLERANCE,
    OUTLIER_SUSPECTED,            // см. LocalizationResult.suspectedOutlier
    HEIGHT_PLANE_FALLBACK,        // плоскость высоты запрошена, но данных/геометрии мало: применён сдвиг
    NO_HEIGHTS,                   // у пар нет высот: поправка высоты нулевая
}

data class LocalizationOptions(
    val fixScale: Boolean = false,        // масштаб = 1 (только сдвиг + поворот)
    val allowSinglePair: Boolean = false, // решение 0: явно разрешить «только сдвиг»
    val scaleTolerance: Double = 1e-4,    // 0,01 %
    val rmsToleranceM: Double = 0.05,
    val heightMode: HeightMode = HeightMode.OFFSET,
)

enum class HeightMode { OFFSET, PLANE }

class PairResidual(val index: Int, val dEast: Double, val dNorth: Double) {
    val distance get() = hypot(dEast, dNorth)
}

sealed interface LocalizationResult {
    class Ok(
        val georef: Georef,
        val similarity: Similarity2D,
        val residuals: List<PairResidual>,
        val rmsM: Double,
        val warnings: Set<LocalizationWarning>,
        val suspectedOutlier: Int?,
        val heightRmsM: Double? = null,
    ) : LocalizationResult

    /** Не NaN и не исключение, а понятная причина. */
    class Failed(val reason: String) : LocalizationResult
}

object Localization {
    fun localize(pairs: List<ControlPair>, opts: LocalizationOptions = LocalizationOptions()): LocalizationResult {
        if (pairs.isEmpty()) return LocalizationResult.Failed("Нет пар точек")
        if (pairs.size == 1 && !opts.allowSinglePair) return LocalizationResult.Failed("Нужно минимум 2 пары точек")
        val p = pairs.map { it.surface.x to it.surface.y }
        val dz = pairs.map { if (it.surface.z.isNaN()) Double.NaN else it.wgs84.h - it.surface.z }
        return fit(pairs, p, dz, opts) { plane, sim, h -> LocalizedGeoref(plane, sim, h) }
    }

    /**
     * Калибровка поверх известной СК (слой ГСКО): проекцию берёт [base], по парам подгоняется малая поправка
     * (подобие в локальной плоскости + высота). Точность не деградирует вдали от ЦМ, как у [localize].
     * Поверхность в парах задана в тех же осях и единицах, что у [base].
     */
    fun calibrate(base: CrsGeoref, pairs: List<ControlPair>, opts: LocalizationOptions = LocalizationOptions()): LocalizationResult {
        if (pairs.isEmpty()) return LocalizationResult.Failed("Нет пар точек")
        if (pairs.size == 1 && !opts.allowSinglePair) return LocalizationResult.Failed("Нужно минимум 2 пары точек")
        val mapped = pairs.map { base.toWgs84(it.surface.x, it.surface.y, it.surface.z) }
        val lat0 = mapped.map { it.lat }.average()
        val lon0 = circularMeanLon(mapped.map { it.lon })
        val plane = LocalPlane(lat0, lon0)
        val p = mapped.map { plane.toPlane(it) }
        val dz = pairs.indices.map { i -> if (pairs[i].surface.z.isNaN()) Double.NaN else pairs[i].wgs84.h - mapped[i].h }
        return fit(pairs, p, dz, opts, plane) { pl, sim, h -> CalibratedGeoref(base, pl, sim, h) }
    }

    private fun circularMeanLon(lons: List<Double>) =
        Geodesy.normLon(kotlin.math.atan2(lons.sumOf { kotlin.math.sin(it) }, lons.sumOf { kotlin.math.cos(it) }))

    /** Общая часть: плоскость по WGS84-сторонам, подобие p → q, невязки, предупреждения, высота. */
    private fun fit(
        pairs: List<ControlPair>, p: List<Pair<Double, Double>>, dz: List<Double>, opts: LocalizationOptions,
        fixedPlane: LocalPlane? = null, build: (LocalPlane, Similarity2D, HeightModel) -> Georef,
    ): LocalizationResult {
        val warnings = mutableSetOf<LocalizationWarning>()
        if (hasDuplicates(p) || hasDuplicates(pairs.map { it.wgs84.lat to it.wgs84.lon })) {
            warnings += LocalizationWarning.DUPLICATE_POINTS
        }
        if (pairs.size >= 2 && spread(p) < 1e-9) return LocalizationResult.Failed("Все точки чертежа совпадают")

        val plane = fixedPlane ?: LocalPlane(
            pairs.map { it.wgs84.lat }.average(), circularMeanLon(pairs.map { it.wgs84.lon }),
        )
        val q = pairs.map { plane.toPlane(it.wgs84) }

        val sim = solve(p, q, opts, pairs.size) ?: return LocalizationResult.Failed("Вырожденная конфигурация точек")
        when (pairs.size) {
            1 -> warnings += LocalizationWarning.SINGLE_PAIR_TRANSLATION_ONLY
            2 -> warnings += LocalizationWarning.NO_REDUNDANCY
        }
        if (!opts.fixScale && pairs.size >= 2 && abs(sim.scale - 1.0) > opts.scaleTolerance) {
            warnings += LocalizationWarning.SCALE_NOT_ONE
        }

        val residuals = pairs.indices.map { i ->
            val (e, n) = sim.apply(p[i].first, p[i].second)
            PairResidual(i, e - q[i].first, n - q[i].second)
        }
        val rms = rms(residuals)
        if (pairs.size > 2 && rms > opts.rmsToleranceM) warnings += LocalizationWarning.RMS_ABOVE_TOLERANCE

        val outlier = if (pairs.size >= 4) suspectOutlier(p, q, opts, rms) else null
        if (outlier != null) warnings += LocalizationWarning.OUTLIER_SUSPECTED

        val idx = pairs.indices.filter { !dz[it].isNaN() }
        val height = fitHeight(
            idx.map { pairs[it].surface.x }, idx.map { pairs[it].surface.y }, idx.map { dz[it] }, opts.heightMode, warnings,
        )
        val heightRms = if (idx.isEmpty()) null
        else sqrt(idx.sumOf { val d = dz[it] - height.correction(pairs[it].surface.x, pairs[it].surface.y); d * d } / idx.size)

        return LocalizationResult.Ok(build(plane, sim, height), sim, residuals, rms, warnings, outlier, heightRms)
    }

    /** Сдвиг по высоте или плоскость (МНК, центрирование). [dz] = h_wgs84 − h_поверхности. Вырождение — откат к сдвигу. */
    private fun fitHeight(
        xs: List<Double>, ys: List<Double>, dz: List<Double>, mode: HeightMode, warnings: MutableSet<LocalizationWarning>,
    ): HeightModel {
        if (dz.isEmpty()) { warnings += LocalizationWarning.NO_HEIGHTS; return HeightModel.ZERO }
        val mean = dz.average()
        if (mode == HeightMode.OFFSET) return HeightModel(0.0, 0.0, mean)
        val x0 = xs.average()
        val y0 = ys.average()
        if (dz.size < 3) { warnings += LocalizationWarning.HEIGHT_PLANE_FALLBACK; return HeightModel(0.0, 0.0, mean) }
        var sxx = 0.0; var sxy = 0.0; var syy = 0.0; var sxz = 0.0; var syz = 0.0
        for (i in dz.indices) {
            val x = xs[i] - x0; val y = ys[i] - y0; val z = dz[i] - mean
            sxx += x * x; sxy += x * y; syy += y * y; sxz += x * z; syz += y * z
        }
        val det = sxx * syy - sxy * sxy
        // det/(sxx·syy) → 0 при коллинеарных точках
        if (sxx <= 0.0 || syy <= 0.0 || det <= 1e-9 * sxx * syy) {
            warnings += LocalizationWarning.HEIGHT_PLANE_FALLBACK
            return HeightModel(0.0, 0.0, mean)
        }
        return HeightModel((sxz * syy - syz * sxy) / det, (syz * sxx - sxz * sxy) / det, mean, x0, y0)
    }

    /** Замкнутое решение (Умеяма в комплексной форме). Для n = 1 — сдвиг, scale = 1, θ = 0. */
    internal fun solve(
        p: List<Pair<Double, Double>>, q: List<Pair<Double, Double>>, opts: LocalizationOptions, n: Int,
    ): Similarity2D? {
        val pmx = p.map { it.first }.average(); val pmy = p.map { it.second }.average()
        val qmx = q.map { it.first }.average(); val qmy = q.map { it.second }.average()
        if (n == 1) return Similarity2D(1.0, 0.0, qmx - pmx, qmy - pmy)
        var dot = 0.0; var cross = 0.0; var norm = 0.0
        for (i in p.indices) {
            val px = p[i].first - pmx; val py = p[i].second - pmy
            val qx = q[i].first - qmx; val qy = q[i].second - qmy
            dot += px * qx + py * qy
            cross += px * qy - py * qx
            norm += px * px + py * py
        }
        if (norm < 1e-18) return null
        var aRe = dot / norm
        var aIm = cross / norm
        val len = hypot(aRe, aIm)
        if (len < 1e-18) return null
        if (opts.fixScale) { aRe /= len; aIm /= len }
        val tx = qmx - (aRe * pmx - aIm * pmy)
        val ty = qmy - (aIm * pmx + aRe * pmy)
        return Similarity2D(aRe, aIm, tx, ty)
    }

    private fun rms(r: List<PairResidual>) = if (r.isEmpty()) 0.0 else sqrt(r.sumOf { it.distance * it.distance } / r.size)

    private fun hasDuplicates(pts: List<Pair<Double, Double>>, eps: Double = 1e-9): Boolean {
        for (i in pts.indices) for (j in i + 1 until pts.size) {
            if (hypot(pts[i].first - pts[j].first, pts[i].second - pts[j].second) < eps) return true
        }
        return false
    }

    private fun spread(pts: List<Pair<Double, Double>>): Double {
        val cx = pts.map { it.first }.average(); val cy = pts.map { it.second }.average()
        return pts.maxOf { hypot(it.first - cx, it.second - cy) }
    }

    /** Leave-one-out: пара подозрительна, если без неё RMS падает более чем втрое и общий RMS заметен. */
    private fun suspectOutlier(
        p: List<Pair<Double, Double>>, q: List<Pair<Double, Double>>, opts: LocalizationOptions, totalRms: Double,
    ): Int? {
        if (totalRms < 1e-3) return null
        var best = -1
        var bestRms = Double.MAX_VALUE
        for (i in p.indices) {
            val pi = p.filterIndexed { k, _ -> k != i }
            val qi = q.filterIndexed { k, _ -> k != i }
            val s = solve(pi, qi, opts, pi.size) ?: continue
            val res = pi.indices.map { k ->
                val (e, n) = s.apply(pi[k].first, pi[k].second)
                PairResidual(k, e - qi[k].first, n - qi[k].second)
            }
            val r = rms(res)
            if (r < bestRms) { bestRms = r; best = i }
        }
        return if (best >= 0 && totalRms > 3 * bestRms) best else null
    }
}
