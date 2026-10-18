package ru.mathdatum.localization

import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.floor
import kotlin.math.hypot
import kotlin.math.sin
import kotlin.math.sqrt

/*
 * Государственные системы координат и пересчёты между ними (ГОСТ 32453-2017).
 * Те же формулы, что у Python-эталона (mathdatum/datums.py):
 *  BLH ↔ XYZ на эллипсоиде; 7 параметров (малые углы, поворот системы координат,
 *  в PROJ +convention=coordinate_frame):  X2 = (1 + m)·R·X1 + ΔX,  R = [[1, ωz, −ωy], [−ωz, 1, ωx], [ωy, −ωx, 1]];
 *  обратный — точное обращение:  X1 = (Rᵀ + ω·ωᵀ)·(X2 − ΔX) / ((1 + |ω|²)(1 + m));
 *  цепочки — кратчайший путь по графу параметров; эпоха — только линейный перенос X(t) = X(t0) + V·(t − t0)
 *  перед шагом с эпохой параметров (ГСК-2011, ПЗ-90.02 → ПЗ-90.11, ПЗ-90.11 → ITRF-2008), как в прил. Е ГОСТ;
 *  Гаусс–Крюгер: зоны 6° (L0 = 6n − 3, y = n·10⁶ + 500 000 + E) и произвольный поперечный Меркатор.
 */

/** Геодезические координаты: широта, долгота (градусы), высота над эллипсоидом (м). */
data class GeodeticPoint(val lat: Double, val lon: Double, val h: Double)

/** Геоцентрические координаты (м) или скорость пункта (м/год). */
data class Xyz(val x: Double, val y: Double, val z: Double)

/** Плоские координаты: x — север, y — восток (м). */
data class PlanePoint(val x: Double, val y: Double)

/** Эллипсоид с названием и записью PROJ (как в Python-эталоне). */
class NamedEllipsoid(val key: String, val name: String, val a: Double, val rf: Double, val proj: String) {
    val ellipsoid: Ellipsoid = Ellipsoid(a, 1 / rf)
}

/** Система координат: код (как в JSON датума), название, эллипсоид, другие написания. */
class GeodeticSystem(
    val id: String,
    val name: String,
    val ellipsoid: NamedEllipsoid,
    val aliases: List<String> = emptyList(),
    /** Государственные плоские координаты — зоны Гаусса–Крюгера 6°. */
    val gkZones: Boolean = false,
)

/** 7 параметров from → to: ΔX, ΔY, ΔZ (м), ωx, ωy, ωz (″), m (ppm); epoch — эпоха параметров. */
data class HelmertParams(
    val from: String, val to: String,
    val dX: Double, val dY: Double, val dZ: Double,
    val wx: Double, val wy: Double, val wz: Double,
    val m: Double,
    val epoch: Double? = null,
    val source: String = "",
)

/** Шаг цепочки: параметры и направление (forward — как в ГОСТ, иначе обратный). */
data class Step(val params: HelmertParams, val forward: Boolean) {
    val from: String get() = if (forward) params.from else params.to
    val to: String get() = if (forward) params.to else params.from
}

object Datums {
    const val ARCSEC = kotlin.math.PI / (180 * 3600)

    val ELLIPSOIDS: List<NamedEllipsoid> = listOf(
        NamedEllipsoid("krass", "Красовского", 6378245.0, 298.3, "+ellps=krass"),
        NamedEllipsoid("pz90", "ПЗ-90", 6378136.0, 298.25784, "+a=6378136 +rf=298.25784"),
        NamedEllipsoid("gsk2011", "ГСК-2011", 6378136.5, 298.2564151, "+a=6378136.5 +rf=298.2564151"),
        NamedEllipsoid("wgs84", "WGS-84", 6378137.0, 298.257223563, "+ellps=WGS84"),
        NamedEllipsoid("grs80", "GRS80", 6378137.0, 298.257222101, "+ellps=GRS80"),
    )

    fun ellipsoid(key: String): NamedEllipsoid = ELLIPSOIDS.firstOrNull { it.key == key.lowercase() }
        ?: system(key).ellipsoid

    val SYSTEMS: List<GeodeticSystem> = listOf(
        GeodeticSystem("SK-42", "СК-42", ellipsoid("krass"), listOf("Pulkovo 1942"), true),
        GeodeticSystem("SK-95", "СК-95", ellipsoid("krass"), listOf("Pulkovo 1995"), true),
        GeodeticSystem("GSK-2011", "ГСК-2011", ellipsoid("gsk2011"), emptyList(), true),
        GeodeticSystem("PZ-90", "ПЗ-90", ellipsoid("pz90")),
        GeodeticSystem("PZ-90.02", "ПЗ-90.02", ellipsoid("pz90")),
        GeodeticSystem("PZ-90.11", "ПЗ-90.11", ellipsoid("pz90")),
        GeodeticSystem("WGS-84", "WGS-84 (G1150)", ellipsoid("wgs84"), listOf("WGS-84 (G1150)", "WGS 84")),
        GeodeticSystem("ITRF-2008", "ITRF-2008", ellipsoid("grs80"), listOf("ITRF2008")),
    )

    /** ГОСТ 32453-2017, приложения А–Д (те же значения, что в Python-эталоне). */
    val TRANSFORMATIONS: List<HelmertParams> = listOf(
        HelmertParams("SK-42", "PZ-90.11", 23.557, -140.844, -79.778, -0.00230, -0.34646, -0.79421, -0.228, null, "А.1"),
        HelmertParams("SK-95", "PZ-90.11", 24.457, -130.784, -81.538, -0.00230, 0.00354, -0.13421, -0.228, null, "А.3"),
        HelmertParams("GSK-2011", "PZ-90.11", 0.000, 0.014, -0.008, -0.000562, -0.000019, 0.000053, -0.0006, 2011.0, "А.5"),
        HelmertParams("PZ-90.02", "PZ-90.11", -0.373, 0.186, 0.202, -0.00230, 0.00354, -0.00421, -0.008, 2010.0, "Б.1"),
        HelmertParams("PZ-90", "PZ-90.11", -1.443, 0.156, 0.222, -0.00230, 0.00354, -0.134210, -0.228, null, "В.1"),
        HelmertParams("WGS-84", "PZ-90.11", -0.013, 0.106, 0.022, -0.00230, 0.00354, -0.00421, -0.008, null, "Г.1"),
        HelmertParams("PZ-90.11", "ITRF-2008", -0.003, -0.001, 0.000, 0.000019, -0.000042, 0.000002, 0.000, 2010.0, "Д.1"),
    )

    private val CYR = mapOf('С' to 'S', 'К' to 'K', 'Г' to 'G', 'П' to 'P', 'З' to 'Z')

    private fun key(s: String) = s.uppercase().filterNot { it.isWhitespace() || it in "-_()" }.map { CYR[it] ?: it }.joinToString("")

    private val LOOKUP: Map<String, GeodeticSystem> =
        SYSTEMS.flatMap { s -> (listOf(s.id, s.name) + s.aliases).map { key(it) to s } }.toMap()

    /** Система по коду или названию: "SK-42", "СК-42", "ск42", "WGS-84 (G1150)", "ITRF2008"… */
    fun system(name: String): GeodeticSystem = LOOKUP[key(name)]
        ?: throw IllegalArgumentException("Неизвестная система координат «$name». Есть: ${SYSTEMS.joinToString(", ") { it.id }}")

    // --- BLH ↔ XYZ ---

    fun blhToXyz(p: GeodeticPoint, e: Ellipsoid): Xyz {
        val e2 = e.f * (2 - e.f)
        val b = p.lat.toRadians()
        val l = p.lon.toRadians()
        val sb = sin(b)
        val n = e.a / sqrt(1 - e2 * sb * sb)
        return Xyz((n + p.h) * cos(b) * cos(l), (n + p.h) * cos(b) * sin(l), (n * (1 - e2) + p.h) * sb)
    }

    /** XYZ → BLH: приближение Боуринга и 3 итерации tg B = (Z + e²·N·sin B) / p; h = p·cos B + Z·sin B − a²/N. */
    fun xyzToBlh(p: Xyz, e: Ellipsoid): GeodeticPoint {
        val a = e.a
        val e2 = e.f * (2 - e.f)
        val b = a * (1 - e.f)
        val ep2 = e2 / (1 - e2)
        val r = hypot(p.x, p.y)
        val u = atan2(p.z * a, r * b)
        val su = sin(u)
        val cu = cos(u)
        var lat = atan2(p.z + ep2 * b * su * su * su, r - e2 * a * cu * cu * cu)
        repeat(3) {
            val n = a / sqrt(1 - e2 * sin(lat) * sin(lat))
            lat = atan2(p.z + e2 * n * sin(lat), r)
        }
        val sl = sin(lat)
        val n = a / sqrt(1 - e2 * sl * sl)
        return GeodeticPoint(lat.toDegrees(), atan2(p.y, p.x).toDegrees(), r * cos(lat) + p.z * sl - a * a / n)
    }

    // --- 7 параметров ---

    /** Формула ГОСТ 32453: X2 = (1 + m)·R·X1 + ΔX. */
    fun helmertForward(p: Xyz, t: HelmertParams): Xyz {
        val wx = t.wx * ARCSEC
        val wy = t.wy * ARCSEC
        val wz = t.wz * ARCSEC
        val s = 1 + t.m * 1e-6
        return Xyz(
            s * (p.x + wz * p.y - wy * p.z) + t.dX,
            s * (-wz * p.x + p.y + wx * p.z) + t.dY,
            s * (wy * p.x - wx * p.y + p.z) + t.dZ,
        )
    }

    /** Точное обращение [helmertForward]: X1 = (Rᵀ + ω·ωᵀ)·(X2 − ΔX) / ((1 + |ω|²)(1 + m)). */
    fun helmertInverse(p: Xyz, t: HelmertParams): Xyz {
        val wx = t.wx * ARCSEC
        val wy = t.wy * ARCSEC
        val wz = t.wz * ARCSEC
        val k = 1 / ((1 + wx * wx + wy * wy + wz * wz) * (1 + t.m * 1e-6))
        val x = p.x - t.dX
        val y = p.y - t.dY
        val z = p.z - t.dZ
        val dot = wx * x + wy * y + wz * z
        // Rᵀ·v = (x − ωz·y + ωy·z, ωz·x + y − ωx·z, −ωy·x + ωx·y + z).
        return Xyz(
            k * (x - wz * y + wy * z + wx * dot),
            k * (wz * x + y - wx * z + wy * dot),
            k * (-wy * x + wx * y + z + wz * dot),
        )
    }

    /** Кратчайшая цепочка from → to по графу параметров (каждый набор — ребро в обе стороны). */
    fun findPath(from: String, to: String, transformations: List<HelmertParams> = TRANSFORMATIONS): List<Step> {
        val a = system(from).id
        val b = system(to).id
        val prev = mutableMapOf<String, Pair<String, Step>?>(a to null)
        val queue = ArrayDeque(listOf(a))
        while (queue.isNotEmpty()) {
            val cur = queue.removeFirst()
            if (cur == b) break
            for (t in transformations) {
                for ((fwd, s, d) in listOf(Triple(true, t.from, t.to), Triple(false, t.to, t.from))) {
                    if (s == cur && d !in prev) {
                        prev[d] = cur to Step(t, fwd)
                        queue.addLast(d)
                    }
                }
            }
        }
        if (b !in prev) throw IllegalArgumentException("Нет цепочки параметров $a → $b.")
        val path = mutableListOf<Step>()
        var cur = b
        while (true) {
            val (p, step) = prev[cur] ?: break
            path += step
            cur = p
        }
        return path.reversed()
    }

    /** «СК-42 → ПЗ-90.11 → WGS-84 (G1150) (прил. А.1; Г.1, обратный)». */
    fun describePath(path: List<Step>): String {
        if (path.isEmpty()) return "без пересчёта"
        val names = listOf(system(path.first().from).name) + path.map { system(it.to).name }
        return names.joinToString(" → ") + " (прил. " +
            path.joinToString("; ") { it.params.source + if (it.forward) "" else ", обратный" } + ")"
    }

    /** X(tTo) = X(tFrom) + V·(tTo − tFrom); V — м/год. */
    fun propagateEpoch(p: Xyz, v: Xyz, tFrom: Double, tTo: Double): Xyz {
        val dt = tTo - tFrom
        return Xyz(p.x + v.x * dt, p.y + v.y * dt, p.z + v.z * dt)
    }

    /**
     * XYZ из [from] в [to]. [epoch], [velocity] — эпоха координат и скорость пункта: перед шагом с эпохой
     * параметров координаты переносятся на неё, в конце — на [targetEpoch]. Без скорости эпохи не учитываются.
     */
    fun transformXyz(
        p: Xyz, from: String, to: String,
        epoch: Double? = null, velocity: Xyz? = null, targetEpoch: Double? = null, path: List<Step>? = null,
    ): Xyz {
        if (velocity != null && epoch == null) throw IllegalArgumentException("Для учёта скорости нужна эпоха координат (epoch).")
        var x = p
        var t = epoch
        for (st in path ?: findPath(from, to)) {
            val te = st.params.epoch
            if (velocity != null && te != null) {
                x = propagateEpoch(x, velocity, t!!, te)
                t = te
            }
            x = if (st.forward) helmertForward(x, st.params) else helmertInverse(x, st.params)
        }
        if (velocity != null && targetEpoch != null) x = propagateEpoch(x, velocity, t!!, targetEpoch)
        return x
    }

    /** B, L, h в [from] → в [to] (через XYZ на эллипсоидах систем). */
    fun transformBlh(
        p: GeodeticPoint, from: String, to: String,
        epoch: Double? = null, velocity: Xyz? = null, targetEpoch: Double? = null,
    ): GeodeticPoint {
        val s = system(from)
        val d = system(to)
        if (s.id == d.id && velocity == null) return p
        val xyz = transformXyz(blhToXyz(p, s.ellipsoid.ellipsoid), s.id, d.id, epoch, velocity, targetEpoch)
        return xyzToBlh(xyz, d.ellipsoid.ellipsoid)
    }
}

/**
 * Поперечный Меркатор с осевым меридианом [lon0], широтой начала [lat0], масштабом [k0] и ложными смещениями
 * [x0] (на север) и [y0] (на восток) — «МСК-подобные» системы. Ряды Крюгера 6-го порядка ([TransverseMercator]).
 */
class TmProjection(
    val ellipsoid: Ellipsoid, val lon0: Double, val lat0: Double = 0.0, val k0: Double = 1.0,
    val x0: Double = 0.0, val y0: Double = 0.0,
) {
    private val tm = TransverseMercator(ellipsoid, lat0, lon0)

    fun forward(lat: Double, lon: Double): PlanePoint {
        val (n, e) = tm.forward(lat, lon)
        return PlanePoint(x0 + k0 * n, y0 + k0 * e)
    }

    /** (x, y) → (широта, долгота), градусы. */
    fun inverse(x: Double, y: Double): Pair<Double, Double> = tm.inverse((x - x0) / k0, (y - y0) / k0)
}

/** Зоны Гаусса–Крюгера 6° (СК-42, СК-95, ГСК-2011): L0 = 6n − 3, k0 = 1, y = n·10⁶ + 500 000 + E. */
object GaussKruger {
    /** Номер зоны по долготе: n = ⌊L/6⌋ + 1, L приводится к [0, 360). */
    fun zone(lon: Double): Int = floor((((lon % 360.0) + 360.0) % 360.0) / 6).toInt() + 1

    fun projection(zone: Int, ellipsoid: Ellipsoid): TmProjection {
        if (zone !in 1..60) throw IllegalArgumentException("Номер зоны Гаусса–Крюгера $zone: ожидается 1…60.")
        return TmProjection(ellipsoid, 6.0 * zone - 3, 0.0, 1.0, 0.0, zone * 1e6 + 500_000.0)
    }

    /** B, L → x, y (y с номером зоны); [zone] — принудительная зона, иначе по долготе. */
    fun forward(lat: Double, lon: Double, ellipsoid: Ellipsoid, zone: Int? = null): PlanePoint =
        projection(zone ?: zone(lon), ellipsoid).forward(lat, lon)

    /** x, y → (B, L); зона — по первым цифрам y; если задана [zone], y должен содержать тот же номер. */
    fun inverse(x: Double, y: Double, ellipsoid: Ellipsoid, zone: Int? = null): Pair<Double, Double> {
        val z = floor(y / 1e6).toInt()
        if (zone != null && z != zone) {
            throw IllegalArgumentException("Координата y не из зоны $zone (ожидается y = $zone·10⁶ + 500 000 + E).")
        }
        return projection(z, ellipsoid).inverse(x, y)
    }
}
