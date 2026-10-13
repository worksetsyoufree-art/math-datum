package mathdatum.core

import kotlin.math.cos
import kotlin.math.sin

enum class RotationConvention { COORDINATE_FRAME, POSITION_VECTOR }

/**
 * Гельмерт 7 параметров, точный (ортонормированная матрица, не линеаризация).
 * Параметры заданы в направлении [forward]: сдвиги м, вращения угл. секунды, масштаб ppm.
 * Обратное — транспонирование матрицы и деление на масштаб, а не отрицание параметров.
 */
class Helmert(
    val tx: Double, val ty: Double, val tz: Double,
    val rxArcsec: Double, val ryArcsec: Double, val rzArcsec: Double,
    val ppm: Double,
    val convention: RotationConvention = RotationConvention.COORDINATE_FRAME,
) {
    private val k = 1.0 + ppm * 1e-6
    private val r = DoubleArray(9)

    init {
        val rx = rxArcsec * ARCSEC
        val ry = ryArcsec * ARCSEC
        val rz = rzArcsec * ARCSEC
        val cx = cos(rx); val sx = sin(rx)
        val cy = cos(ry); val sy = sin(ry)
        val cz = cos(rz); val sz = sin(rz)
        // coordinate_frame; для position_vector — транспонированная
        val m = doubleArrayOf(
            cy * cz, cx * sz + sx * sy * cz, sx * sz - cx * sy * cz,
            -cy * sz, cx * cz - sx * sy * sz, sx * cz + cx * sy * sz,
            sy, -sx * cy, cx * cy,
        )
        for (i in 0 until 3) for (j in 0 until 3) {
            r[i * 3 + j] = if (convention == RotationConvention.COORDINATE_FRAME) m[i * 3 + j] else m[j * 3 + i]
        }
    }

    fun forward(v: Vec3) = Vec3(
        tx + k * (r[0] * v.x + r[1] * v.y + r[2] * v.z),
        ty + k * (r[3] * v.x + r[4] * v.y + r[5] * v.z),
        tz + k * (r[6] * v.x + r[7] * v.y + r[8] * v.z),
    )

    fun inverse(v: Vec3): Vec3 {
        val dx = v.x - tx
        val dy = v.y - ty
        val dz = v.z - tz
        return Vec3(
            (r[0] * dx + r[3] * dy + r[6] * dz) / k,
            (r[1] * dx + r[4] * dy + r[7] * dz) / k,
            (r[2] * dx + r[5] * dy + r[8] * dz) / k,
        )
    }
}
