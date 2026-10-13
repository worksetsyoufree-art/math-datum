package mathdatum.core

/**
 * Формат справочника (версия 1):
 * { "format": 1, "version": "...", "source": "...",
 *   "entries": [ { "id", "name", "ellipsoid": "WGS84" | {"a","invF","name"},
 *                  "helmert": null | {"t":[m,m,m], "r":[arcsec x3], "ppm", "convention"},   // WGS84 → местная
 *                  "tm": {"lat0","lon0","k0","x0","y0"},                                    // градусы / метры; x0 = восток, y0 = север
 *                  "bounds": null | [minLat,maxLat,minLon,maxLon], "epsg", "region", "source" } ] }
 */
object CatalogJson {
    const val FORMAT = 1

    fun encodeCrs(c: CrsDef): Map<String, Any?> = linkedMapOf(
        "id" to c.id,
        "name" to c.name,
        "ellipsoid" to encodeEllipsoid(c.ellipsoid),
        "helmert" to c.helmert?.let {
            linkedMapOf(
                "t" to listOf(it.tx, it.ty, it.tz),
                "r" to listOf(it.rxArcsec, it.ryArcsec, it.rzArcsec),
                "ppm" to it.ppm,
                "convention" to if (it.convention == RotationConvention.COORDINATE_FRAME) "coordinate_frame" else "position_vector",
            )
        },
        "tm" to linkedMapOf(
            "lat0" to c.tm.lat0 / DEG, "lon0" to c.tm.lon0 / DEG, "k0" to c.tm.k0,
            "x0" to c.tm.falseEasting, "y0" to c.tm.falseNorthing,
        ),
        "bounds" to c.bounds?.let { listOf(it.minLat, it.maxLat, it.minLon, it.maxLon) },
        "epsg" to c.epsg?.toDouble(),
        "region" to c.region,
        "source" to c.source,
    )

    private fun encodeEllipsoid(e: Ellipsoid): Any = e.id ?: linkedMapOf("a" to e.a, "invF" to e.invF, "name" to e.name)

    fun decodeCrs(v: Any?): CrsDef {
        val m = v.asMap("СК")
        val id = m["id"].asString("id")
        val ell = when (val e = m["ellipsoid"]) {
            is String -> Ellipsoid.byId(e) ?: throw Json.ParseException("$id: неизвестный эллипсоид '$e'")
            else -> e.asMap("$id: ellipsoid").let { Ellipsoid(it["name"]?.asString("name") ?: "custom", it["a"].asDouble("a"), it["invF"].asDouble("invF")) }
        }
        val helmert = m["helmert"]?.let { h ->
            val hm = h.asMap("$id: helmert")
            val t = hm["t"].asList("t").map { it.asDouble("t") }
            val r = hm["r"].asList("r").map { it.asDouble("r") }
            if (t.size != 3 || r.size != 3) throw Json.ParseException("$id: t и r должны быть по 3 числа")
            val conv = when (val c = hm["convention"]?.asString("convention") ?: "coordinate_frame") {
                "coordinate_frame" -> RotationConvention.COORDINATE_FRAME
                "position_vector" -> RotationConvention.POSITION_VECTOR
                else -> throw Json.ParseException("$id: неизвестное соглашение '$c'")
            }
            Helmert(t[0], t[1], t[2], r[0], r[1], r[2], hm["ppm"].asDouble("ppm"), conv)
        }
        val tmm = m["tm"].asMap("$id: tm")
        val tm = TransverseMercator(
            ell, tmm["lat0"].asDouble("lat0") * DEG, tmm["lon0"].asDouble("lon0") * DEG,
            tmm["k0"].asDouble("k0"), tmm["x0"].asDouble("x0"), tmm["y0"].asDouble("y0"),
        )
        val bounds = m["bounds"]?.let { b ->
            b.asList("$id: bounds").map { it.asDouble("bounds") }.also { if (it.size != 4) throw Json.ParseException("$id: bounds из 4 чисел") }
                .let { GeoBounds(it[0], it[1], it[2], it[3]) }
        }
        return CrsDef(
            id, m["name"].asString("name"), ell, helmert, tm, bounds,
            epsg = m["epsg"]?.asInt("epsg"), region = m["region"]?.asString("region"), source = m["source"]?.asString("source"),
        )
    }

    fun encode(catalog: Catalog, version: String = "", source: String = ""): String = Json.write(
        linkedMapOf("format" to FORMAT.toDouble(), "version" to version, "source" to source, "entries" to catalog.entries.map { encodeCrs(it) }),
        indent = true,
    )

    /** Бросает [Json.ParseException] с указанием записи при любой ошибке формата. */
    fun decode(text: String): Catalog {
        val root = Json.parse(text).asMap("справочник")
        val fmt = root["format"].asInt("format")
        if (fmt != FORMAT) throw Json.ParseException("Версия формата $fmt не поддерживается (ожидается $FORMAT)")
        val ids = HashSet<String>()
        val entries = root["entries"].asList("entries").map { decodeCrs(it) }
        entries.forEach { if (!ids.add(it.id)) throw Json.ParseException("Дубль id '${it.id}'") }
        return Catalog(entries)
    }
}
