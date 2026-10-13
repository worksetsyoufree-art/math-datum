package mathdatum.core

import kotlin.math.max
import kotlin.math.min

/** Вершины поверхности в её локальных координатах. [z] может быть null. */
class SurfaceVertices(val x: DoubleArray, val y: DoubleArray, val z: DoubleArray? = null) {
    init {
        require(x.size == y.size) { "x и y разной длины" }
        require(z == null || z.size == x.size) { "z другой длины" }
    }
    val size get() = x.size
}

/** Что viewer3d (или другой источник) должен уметь отдать для привязки. */
interface SurfaceSource {
    fun vertices(): SurfaceVertices
    /** Код $INSUNITS из DXF, если известен. */
    val insunits: Int? get() = null
}

class RobustBounds(val bounds: SurfaceBounds, val used: Int, val dropped: Int)

object SurfaceAnalysis {
    /**
     * Габариты без «мусорных» вершин вдали от основного облака (нулевая точка чертежа, ошибочные вставки).
     * Вершина — кандидат в мусор, если выходит за [P1 − k·R, P99 + k·R] по любой оси, где R = P99 − P1.
     * Отбрасывается только если таких кандидатов не больше [maxJunkFraction] от числа вершин: протяжённые или
     * неравномерные реальные поверхности (плотная траншея и разреженные окрестности) целиком остаются.
     * Нефинитные значения отбрасываются всегда.
     */
    fun robustBounds(v: SurfaceVertices, k: Double = 3.0, maxJunkFraction: Double = 0.01): RobustBounds? {
        val finite = (0 until v.size).filter { v.x[it].isFinite() && v.y[it].isFinite() }
        if (finite.isEmpty()) return null
        val xs = DoubleArray(finite.size) { v.x[finite[it]] }
        val ys = DoubleArray(finite.size) { v.y[finite[it]] }
        val fx = fences(xs, k)
        val fy = fences(ys, k)
        val junk = BooleanArray(xs.size) { xs[it] < fx.first || xs[it] > fx.second || ys[it] < fy.first || ys[it] > fy.second }
        val junkCount = junk.count { it }
        val dropJunk = junkCount > 0 && junkCount <= maxJunkFraction * xs.size
        var minX = Double.POSITIVE_INFINITY; var maxX = Double.NEGATIVE_INFINITY
        var minY = Double.POSITIVE_INFINITY; var maxY = Double.NEGATIVE_INFINITY
        var used = 0
        for (i in xs.indices) {
            if (dropJunk && junk[i]) continue
            used++
            minX = min(minX, xs[i]); maxX = max(maxX, xs[i]); minY = min(minY, ys[i]); maxY = max(maxY, ys[i])
        }
        return RobustBounds(SurfaceBounds(minX, maxX, minY, maxY), used, v.size - used)
    }

    private fun fences(a: DoubleArray, k: Double): Pair<Double, Double> {
        val s = a.copyOf().also { it.sort() }
        val p1 = quantile(s, 0.01)
        val p99 = quantile(s, 0.99)
        val r = p99 - p1
        return (p1 - k * r) to (p99 + k * r)
    }

    private fun quantile(sorted: DoubleArray, p: Double): Double {
        val pos = p * (sorted.size - 1)
        val lo = pos.toInt()
        val hi = min(lo + 1, sorted.size - 1)
        return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo)
    }
}

/** Единицы чертежа → метры. */
object SurfaceUnits {
    /** Коэффициенты по коду DXF $INSUNITS. 0 (без единиц) и неизвестные коды → null. */
    fun fromInsunits(code: Int?): Double? = when (code) {
        1 -> 0.0254; 2 -> 0.3048; 3 -> 1609.344; 4 -> 0.001; 5 -> 0.01; 6 -> 1.0; 7 -> 1000.0; 10 -> 0.9144; 14 -> 0.1
        else -> null
    }

    private val ALL = listOf(1.0, 0.001, 0.01, 1000.0)

    /**
     * Кандидаты единиц, лучшие первыми. Сначала $INSUNITS (если задан), затем по правдоподобию размера участка:
     * диагональ в метрах 5 м … 200 км считается разумной; среди разумных м идёт раньше мм, см, км.
     * Неразумные единицы остаются в конце — перебор 2×2 не должен терять вариант из-за неверной эвристики.
     */
    fun candidates(bounds: SurfaceBounds, insunits: Int? = null): List<Double> {
        val d = bounds.diagonal
        val declared = fromInsunits(insunits)
        val plausible = ALL.filter { d * it in 5.0..200_000.0 }
        val rest = ALL.filter { it !in plausible }
        return (listOfNotNull(declared) + plausible + rest).distinct()
    }
}
