package mathdatum.core

import kotlin.math.abs

class SurfaceParseException(message: String) : Exception(message)

/** Служебные точки заголовка SURFACE_V1, распознанные по содержимому (порядок в файле может отличаться). */
class SurfaceHints(val mid: Vec3, val min: Vec3, val max: Vec3, val near: Vec3)

/** TIN-поверхность: вершины в координатах чертежа и треугольники (индексы 0-based по [vertices]). */
class SurfaceMesh(
    val title: String,
    val points: SurfaceVertices,
    val triangles: IntArray,
    val service: List<Vec3>,
    val hints: SurfaceHints?,
) : SurfaceSource {
    override fun vertices(): SurfaceVertices = points
    val triangleCount get() = triangles.size / 3
}

/**
 * Формат SURFACE_V1 (текст):
 * ```
 * SURFACE_V1
 * loaded file name: <имя> surfaceId: <n> dxf
 * <N вершин>
 * <T треугольников>
 * x y z        ← 4 служебные точки: центр (среднее), min, max и «near» — вершина, ближайшая к центру
 * x y z × N    ← вершины поверхности
 * i j k × T    ← треугольники, индексы 0-based по N вершинам (служебные точки не считаются)
 * ```
 * Оси точек — как в чертеже; для файла из Москвы X — север, Y — восток (с ложными смещениями СК).
 */
object SurfaceV1 {
    fun parse(text: String): SurfaceMesh {
        val lines = text.split('\n').map { it.trim() }
        var pos = 0
        fun next(what: String): String {
            while (pos < lines.size && lines[pos].isEmpty()) pos++
            if (pos >= lines.size) throw SurfaceParseException("Неожиданный конец файла: ожидалось $what")
            return lines[pos++]
        }
        fun lineNo() = pos // номер последней прочитанной строки (1-based)

        val magic = next("SURFACE_V1")
        if (magic != "SURFACE_V1") throw SurfaceParseException("Неверный заголовок '$magic', ожидалось SURFACE_V1")
        val titleLine = next("имя файла")
        val title = titleLine.removePrefix("loaded file name:").trim().let { t ->
            val i = t.indexOf(" surfaceId:")
            if (i >= 0) t.substring(0, i).trim() else t
        }
        val n = next("число вершин").toIntOrNull()?.takeIf { it >= 0 } ?: throw SurfaceParseException("Строка ${lineNo()}: неверное число вершин")
        val t = next("число треугольников").toIntOrNull()?.takeIf { it >= 0 } ?: throw SurfaceParseException("Строка ${lineNo()}: неверное число треугольников")

        fun point(): Vec3 {
            val s = next("координаты точки")
            val p = s.split(' ', '\t').filter { it.isNotEmpty() }
            if (p.size != 3) throw SurfaceParseException("Строка ${lineNo()}: ожидалось 3 числа, получено '${s.take(40)}'")
            val v = p.map { it.toDoubleOrNull() ?: throw SurfaceParseException("Строка ${lineNo()}: не число '${it.take(20)}'") }
            if (v.any { !it.isFinite() }) throw SurfaceParseException("Строка ${lineNo()}: нечисловое значение")
            return Vec3(v[0], v[1], v[2])
        }

        val service = List(4) { point() }
        val xs = DoubleArray(n); val ys = DoubleArray(n); val zs = DoubleArray(n)
        for (i in 0 until n) { val p = point(); xs[i] = p.x; ys[i] = p.y; zs[i] = p.z }
        val tri = IntArray(t * 3)
        for (i in 0 until t) {
            val s = next("треугольник")
            val p = s.split(' ', '\t').filter { it.isNotEmpty() }
            if (p.size != 3) throw SurfaceParseException("Строка ${lineNo()}: ожидалось 3 индекса, получено '${s.take(40)}'")
            for (k in 0 until 3) {
                val idx = p[k].toIntOrNull() ?: throw SurfaceParseException("Строка ${lineNo()}: не индекс '${p[k].take(20)}'")
                if (idx !in 0 until n) throw SurfaceParseException("Строка ${lineNo()}: индекс $idx вне диапазона 0..${n - 1}")
                tri[i * 3 + k] = idx
            }
        }
        val v = SurfaceVertices(xs, ys, zs)
        return SurfaceMesh(title, v, tri, service, classify(service, v))
    }

    /** Служебные точки: центр = среднее, min/max — покоординатные экстремумы, near — совпадает с вершиной. null, если не сходится. */
    internal fun classify(service: List<Vec3>, v: SurfaceVertices): SurfaceHints? {
        if (v.size == 0) return null
        val z = v.z ?: return null
        val mean = Vec3(v.x.average(), v.y.average(), z.average())
        val lo = Vec3(v.x.min(), v.y.min(), z.min())
        val hi = Vec3(v.x.max(), v.y.max(), z.max())
        val eps = 1e-6 * maxOf(1.0, abs(hi.x - lo.x), abs(hi.y - lo.y))
        fun same(a: Vec3, b: Vec3) = abs(a.x - b.x) <= eps && abs(a.y - b.y) <= eps && abs(a.z - b.z) <= eps
        val rest = service.toMutableList()
        fun take(t: Vec3): Vec3? = rest.firstOrNull { same(it, t) }?.also { rest.remove(it) }
        val mid = take(mean) ?: return null
        val mn = take(lo) ?: return null
        val mx = take(hi) ?: return null
        val near = rest.singleOrNull() ?: return null
        if ((0 until v.size).none { same(near, Vec3(v.x[it], v.y[it], z[it])) }) return null
        return SurfaceHints(mid, mn, mx, near)
    }
}
