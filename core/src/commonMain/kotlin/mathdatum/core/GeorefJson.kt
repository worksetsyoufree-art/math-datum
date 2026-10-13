package mathdatum.core

/**
 * Файл привязки (sidecar `.georef.json`), версия формата 1. Самодостаточный: СК встроена целиком,
 * поэтому привязка не ломается при обновлении справочника.
 *
 * { "format": 1, "type": "crs",   "crs": {...как в справочнике...}, "swapXY": false, "unitToMeters": 1 }
 * { "format": 1, "type": "local", "lat0": deg, "lon0": deg,
 *   "similarity": {"aRe","aIm","tx","ty"}, "height": {"a","b","c","x0","y0"} }
 */
object GeorefJson {
    const val FORMAT = 1

    fun encode(g: Georef): String = Json.write(toMap(g), indent = true)

    fun toMap(g: Georef): Map<String, Any?> = when (g) {
        is CrsGeoref -> linkedMapOf(
            "format" to FORMAT.toDouble(), "type" to "crs",
            "crs" to CatalogJson.encodeCrs(g.crs), "swapXY" to g.swapXY, "unitToMeters" to g.unitToMeters,
        )
        is LocalizedGeoref -> linkedMapOf(
            "format" to FORMAT.toDouble(), "type" to "local",
            "lat0" to g.plane.lat0 / DEG, "lon0" to g.plane.lon0 / DEG,
            "similarity" to linkedMapOf("aRe" to g.similarity.aRe, "aIm" to g.similarity.aIm, "tx" to g.similarity.tx, "ty" to g.similarity.ty),
            "height" to linkedMapOf("a" to g.height.a, "b" to g.height.b, "c" to g.height.c, "x0" to g.height.x0, "y0" to g.height.y0),
        )
        else -> throw IllegalArgumentException("Неизвестная реализация Georef: ${g::class}")
    }

    /** Бросает [Json.ParseException] при неверном формате или неподдерживаемой версии. */
    fun decode(text: String): Georef {
        val m = Json.parse(text).asMap("привязка")
        val fmt = m["format"].asInt("format")
        if (fmt != FORMAT) throw Json.ParseException("Версия формата привязки $fmt не поддерживается (ожидается $FORMAT)")
        return when (val t = m["type"].asString("type")) {
            "crs" -> CrsGeoref(
                CatalogJson.decodeCrs(m["crs"]),
                swapXY = m["swapXY"] as? Boolean ?: throw Json.ParseException("swapXY: ожидалось true/false"),
                unitToMeters = m["unitToMeters"].asDouble("unitToMeters").also {
                    if (!(it > 0.0)) throw Json.ParseException("unitToMeters должен быть > 0")
                },
            )
            "local" -> {
                val s = m["similarity"].asMap("similarity")
                val h = m["height"].asMap("height")
                LocalizedGeoref(
                    LocalPlane(m["lat0"].asDouble("lat0") * DEG, m["lon0"].asDouble("lon0") * DEG),
                    Similarity2D(s["aRe"].asDouble("aRe"), s["aIm"].asDouble("aIm"), s["tx"].asDouble("tx"), s["ty"].asDouble("ty")),
                    HeightModel(h["a"].asDouble("a"), h["b"].asDouble("b"), h["c"].asDouble("c"), h["x0"].asDouble("x0"), h["y0"].asDouble("y0")),
                )
            }
            else -> throw Json.ParseException("Неизвестный тип привязки '$t'")
        }
    }
}
