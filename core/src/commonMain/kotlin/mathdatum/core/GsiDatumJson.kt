package mathdatum.core

import kotlin.math.abs

/**
 * Импорт СК из формата справочника приложения (`datum.json`):
 * `{"azimuth","orientation","csCode","ellipsoidOriginal","ellipsoid","projection":{"type":…ProjectionTM,"longitudeCenter","eastShift","northShift"},
 *   "parameters7":{"d_x","d_y","d_z","r_x","r_y","r_z","k"}}`.
 * Параметры7 — `coordinate_frame`, вращения в угловых секундах, k в ppm. Широта начала 0, масштаб 1, если не заданы
 * ("latitudeOrigin"/"scale"). Ось X — на север при orientation "NE", на восток при "EN".
 *
 * Направление параметров7 источником не задокументировано: по умолчанию [HelmertDirection.WGS84_TO_LOCAL] (так прочитаны
 * 340 записей справочника при сверке с EPSG), но запись помечается как неподтверждённая —
 * см. [CrsDef.helmertAmbiguityMeters].
 */
object GsiDatumJson {
    fun decode(
        text: String,
        direction: HelmertDirection = HelmertDirection.WGS84_TO_LOCAL,
        confirmed: Boolean = false,
    ): CrsDef {
        val m = Json.parse(text).asMap("datum")
        val code = m["csCode"].asString("csCode")
        val az = m["azimuth"]?.asString("azimuth") ?: "North"
        if (az != "North") throw Json.ParseException("$code: azimuth '$az' не поддерживается (ожидается North)")
        val orientation = m["orientation"]?.asString("orientation") ?: "NE"
        if (orientation != "NE" && orientation != "EN") throw Json.ParseException("$code: orientation '$orientation' не поддерживается")

        m["ellipsoidOriginal"]?.asMap("ellipsoidOriginal")?.let {
            val a = it["paramA"].asDouble("ellipsoidOriginal.paramA")
            val f = it["param1f"].asDouble("ellipsoidOriginal.param1f")
            if (abs(a - Ellipsoid.WGS84.a) > 1e-3 || abs(f - Ellipsoid.WGS84.invF) > 1e-6) {
                throw Json.ParseException("$code: исходный эллипсоид не WGS84 (a=$a, 1/f=$f)")
            }
        }
        val e = m["ellipsoid"].asMap("$code: ellipsoid")
        val ell = Ellipsoid(e["type"]?.asString("type") ?: "custom", e["paramA"].asDouble("paramA"), e["param1f"].asDouble("param1f"))

        val pr = m["projection"].asMap("$code: projection")
        val type = pr["type"].asString("projection.type")
        if (!type.endsWith("ProjectionTM")) throw Json.ParseException("$code: проекция '$type' не поддерживается (только TM)")
        val tm = TransverseMercator(
            ell,
            (pr["latitudeOrigin"]?.asDouble("latitudeOrigin") ?: 0.0) * DEG,
            pr["longitudeCenter"].asDouble("longitudeCenter") * DEG,
            pr["scale"]?.asDouble("scale") ?: 1.0,
            pr["eastShift"].asDouble("eastShift"),
            pr["northShift"].asDouble("northShift"),
        )
        val helmert = m["parameters7"]?.let {
            val p = it.asMap("$code: parameters7")
            Helmert(
                p["d_x"].asDouble("d_x"), p["d_y"].asDouble("d_y"), p["d_z"].asDouble("d_z"),
                p["r_x"].asDouble("r_x"), p["r_y"].asDouble("r_y"), p["r_z"].asDouble("r_z"), p["k"].asDouble("k"),
                RotationConvention.COORDINATE_FRAME,
            )
        }
        return CrsDef(
            id = "user:$code", name = code.replace('_', ' '), ellipsoid = ell, helmert = helmert, projection = tm,
            region = m["country"]?.asString("country"), source = "user datum.json",
            helmertDirection = direction, firstAxisIsEast = orientation == "EN", helmertDirectionConfirmed = confirmed || helmert == null,
        )
    }
}
