package mathdatum.core

import kotlin.math.abs
import kotlin.math.hypot
import kotlin.math.sqrt

/** Подобие 3D: q = s·R·p + t. R — ортонормированная матрица 3×3 по строкам. */
class Similarity3D(val scale: Double, val r: DoubleArray, val t: Vec3) {
    fun apply(p: Vec3) = Vec3(
        scale * (r[0] * p.x + r[1] * p.y + r[2] * p.z) + t.x,
        scale * (r[3] * p.x + r[4] * p.y + r[5] * p.z) + t.y,
        scale * (r[6] * p.x + r[7] * p.y + r[8] * p.z) + t.z,
    )

    fun applyInverse(q: Vec3): Vec3 {
        val dx = (q.x - t.x) / scale; val dy = (q.y - t.y) / scale; val dz = (q.z - t.z) / scale
        return Vec3(r[0] * dx + r[3] * dy + r[6] * dz, r[1] * dx + r[4] * dy + r[7] * dz, r[2] * dx + r[5] * dy + r[8] * dz)
    }
}

/** Абсолютная ориентация по Хорну (1987): кватернион — собственный вектор максимального собственного числа матрицы 4×4. */
object Horn {
    /** null — если пар меньше трёх или точки лежат на одной прямой (поворот вокруг неё не определён). */
    fun solve(p: List<Vec3>, q: List<Vec3>, fixScale: Boolean = false): Similarity3D? {
        require(p.size == q.size) { "p и q разной длины" }
        val n = p.size
        if (n < 3) return null
        val pc = Vec3(p.sumOf { it.x } / n, p.sumOf { it.y } / n, p.sumOf { it.z } / n)
        val qc = Vec3(q.sumOf { it.x } / n, q.sumOf { it.y } / n, q.sumOf { it.z } / n)
        val a = p.map { Vec3(it.x - pc.x, it.y - pc.y, it.z - pc.z) }
        val b = q.map { Vec3(it.x - qc.x, it.y - qc.y, it.z - qc.z) }
        if (collinear(a) || collinear(b)) return null

        var sxx = 0.0; var sxy = 0.0; var sxz = 0.0
        var syx = 0.0; var syy = 0.0; var syz = 0.0
        var szx = 0.0; var szy = 0.0; var szz = 0.0
        for (i in 0 until n) {
            sxx += a[i].x * b[i].x; sxy += a[i].x * b[i].y; sxz += a[i].x * b[i].z
            syx += a[i].y * b[i].x; syy += a[i].y * b[i].y; syz += a[i].y * b[i].z
            szx += a[i].z * b[i].x; szy += a[i].z * b[i].y; szz += a[i].z * b[i].z
        }
        val m = arrayOf(
            doubleArrayOf(sxx + syy + szz, syz - szy, szx - sxz, sxy - syx),
            doubleArrayOf(syz - szy, sxx - syy - szz, sxy + syx, szx + sxz),
            doubleArrayOf(szx - sxz, sxy + syx, -sxx + syy - szz, syz + szy),
            doubleArrayOf(sxy - syx, szx + sxz, syz + szy, -sxx - syy + szz),
        )
        val (vals, vecs) = jacobi(m)
        var best = 0
        for (i in 1 until 4) if (vals[i] > vals[best]) best = i
        val w = vecs[0][best]; val x = vecs[1][best]; val y = vecs[2][best]; val z = vecs[3][best]
        val norm = sqrt(w * w + x * x + y * y + z * z)
        val qw = w / norm; val qx = x / norm; val qy = y / norm; val qz = z / norm
        val r = doubleArrayOf(
            1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qw * qz), 2 * (qx * qz + qw * qy),
            2 * (qx * qy + qw * qz), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qw * qx),
            2 * (qx * qz - qw * qy), 2 * (qy * qz + qw * qx), 1 - 2 * (qx * qx + qy * qy),
        )
        var num = 0.0; var den = 0.0
        for (i in 0 until n) {
            val rx = r[0] * a[i].x + r[1] * a[i].y + r[2] * a[i].z
            val ry = r[3] * a[i].x + r[4] * a[i].y + r[5] * a[i].z
            val rz = r[6] * a[i].x + r[7] * a[i].y + r[8] * a[i].z
            num += b[i].x * rx + b[i].y * ry + b[i].z * rz
            den += a[i].x * a[i].x + a[i].y * a[i].y + a[i].z * a[i].z
        }
        val s = if (fixScale || den <= 0.0) 1.0 else num / den
        if (!(s > 0.0)) return null
        val t = Vec3(
            qc.x - s * (r[0] * pc.x + r[1] * pc.y + r[2] * pc.z),
            qc.y - s * (r[3] * pc.x + r[4] * pc.y + r[5] * pc.z),
            qc.z - s * (r[6] * pc.x + r[7] * pc.y + r[8] * pc.z),
        )
        return Similarity3D(s, r, t)
    }

    private fun norm(v: Vec3) = sqrt(v.x * v.x + v.y * v.y + v.z * v.z)

    /** Центрированные точки на одной прямой: все векторное произведение с самым дальним ≈ 0. */
    private fun collinear(a: List<Vec3>): Boolean {
        val far = a.maxByOrNull { norm(it) } ?: return true
        val len = norm(far)
        if (len < 1e-12) return true
        var maxCross = 0.0
        for (v in a) {
            val cx = far.y * v.z - far.z * v.y
            val cy = far.z * v.x - far.x * v.z
            val cz = far.x * v.y - far.y * v.x
            maxCross = maxOf(maxCross, sqrt(cx * cx + cy * cy + cz * cz))
        }
        return maxCross / (len * len) < 1e-9
    }

    /** Циклический метод Якоби для симметричной 4×4. Возвращает собственные числа и матрицу собственных векторов (по столбцам). */
    internal fun jacobi(src: Array<DoubleArray>): Pair<DoubleArray, Array<DoubleArray>> {
        val n = 4
        val a = Array(n) { src[it].copyOf() }
        val v = Array(n) { i -> DoubleArray(n) { j -> if (i == j) 1.0 else 0.0 } }
        for (sweep in 0 until 60) {
            var off = 0.0
            for (i in 0 until n) for (j in i + 1 until n) off += a[i][j] * a[i][j]
            if (off < 1e-30) break
            for (p in 0 until n - 1) for (q in p + 1 until n) {
                if (abs(a[p][q]) < 1e-300) continue
                val theta = (a[q][q] - a[p][p]) / (2 * a[p][q])
                val t = (if (theta >= 0) 1.0 else -1.0) / (abs(theta) + hypot(theta, 1.0))
                val c = 1 / hypot(t, 1.0)
                val s = t * c
                for (k in 0 until n) {
                    val akp = a[k][p]; val akq = a[k][q]
                    a[k][p] = c * akp - s * akq; a[k][q] = s * akp + c * akq
                }
                for (k in 0 until n) {
                    val apk = a[p][k]; val aqk = a[q][k]
                    a[p][k] = c * apk - s * aqk; a[q][k] = s * apk + c * aqk
                }
                for (k in 0 until n) {
                    val vkp = v[k][p]; val vkq = v[k][q]
                    v[k][p] = c * vkp - s * vkq; v[k][q] = s * vkp + c * vkq
                }
            }
        }
        return DoubleArray(n) { a[it][it] } to v
    }
}
