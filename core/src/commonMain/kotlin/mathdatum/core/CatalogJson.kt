package mathdatum.core

/**
 * Формат справочника (версия 2; версия 1 читается):
 * { "format": 2, "version", "source",
 *   "ellipsoids": { "<ключ>": {"a","invF","name"} },          // необязательно: общие таблицы
 *   "helmerts":   { "<ключ>": {"t":[м×3],"r":[угл.сек×3],"ppm","convention","direction","confirmed"} },
 *   "entries": [ { "id","name",
 *       "ellipsoid": "<id встроенного>" | "<ключ таблицы>" | {"a","invF","name"},
 *       "helmert": null | "<ключ таблицы>" | {…},
 *       "projection": {"method": 9807|9808|9801|9802, …параметры, градусы и метры…},
 *       "axes": "NE"|"EN", "unit": метров в единице СК,
 *       "bounds": null | [minLat,maxLat,minLon,maxLon], "epsg","region","source" } ] }
 * Параметры проекции: TM/TMS — lat0, lon0, k0, x0 (восток), y0 (север); LCC 1SP — то же;
 * LCC 2SP — latF, lonF, lat1, lat2, eF, nF. Направление Гельмерта: "wgs84_to_local" (по умолчанию) или "local_to_wgs84".
 * В v1 вместо "projection" был ключ "tm" (lat0, lon0, k0, x0, y0).
 */
object CatalogJson {
    const val FORMAT = 2

    fun encodeCrs(c: CrsDef): Map<String, Any?> = linkedMapOf(
        "id" to c.id,
        "name" to c.name,
        "ellipsoid" to encodeEllipsoid(c.ellipsoid),
        "helmert" to c.helmert?.let { encodeHelmert(it, c.helmertDirection, c.helmertDirectionConfirmed) },
        "projection" to encodeProjection(c.projection, c.ellipsoid),
        "axes" to if (c.firstAxisIsEast) "EN" else "NE",
        "unit" to c.unitToMeters,
        "bounds" to c.bounds?.let { listOf(it.minLat, it.maxLat, it.minLon, it.maxLon) },
        "epsg" to c.epsg?.toDouble(),
        "region" to c.region,
        "source" to c.source,
    )

    private fun encodeEllipsoid(e: Ellipsoid): Any = e.id ?: linkedMapOf("a" to e.a, "invF" to e.invF, "name" to e.name)

    private fun encodeHelmert(h: Helmert, dir: HelmertDirection, confirmed: Boolean): Map<String, Any?> = linkedMapOf(
        "t" to listOf(h.tx, h.ty, h.tz),
        "r" to listOf(h.rxArcsec, h.ryArcsec, h.rzArcsec),
        "ppm" to h.ppm,
        "convention" to if (h.convention == RotationConvention.COORDINATE_FRAME) "coordinate_frame" else "position_vector",
        "direction" to if (dir == HelmertDirection.WGS84_TO_LOCAL) "wgs84_to_local" else "local_to_wgs84",
        "confirmed" to confirmed,
    )

    private fun encodeProjection(p: MapProjection, ell: Ellipsoid): Map<String, Any?> = when (p) {
        is TransverseMercator -> tmMap(p, MapProjection.TM)
        is TransverseMercatorSouthOriented -> tmMap(p.base, MapProjection.TM_SOUTH_ORIENTED)
        is LambertConformalConic -> p.toParams()
        else -> throw IllegalArgumentException("Проекция ${p::class} не сериализуется")
    }

    private fun tmMap(t: TransverseMercator, method: Int): Map<String, Any?> = linkedMapOf(
        "method" to method.toDouble(), "lat0" to t.lat0 / DEG, "lon0" to t.lon0 / DEG, "k0" to t.k0,
        "x0" to t.falseEasting, "y0" to t.falseNorthing,
    )

    class Tables(val ellipsoids: Map<String, Ellipsoid>, val helmerts: Map<String, Map<String, Any?>>)

    private fun decodeEllipsoid(id: String, v: Any?, t: Tables): Ellipsoid = when (v) {
        is String -> Ellipsoid.byId(v) ?: t.ellipsoids[v] ?: throw Json.ParseException("$id: неизвестный эллипсоид '$v'")
        else -> v.asMap("$id: ellipsoid").let { Ellipsoid(it["name"]?.asString("name") ?: "custom", it["a"].asDouble("a"), it["invF"].asDouble("invF")) }
    }

    private fun decodeHelmert(id: String, v: Any?, t: Tables): Triple<Helmert, HelmertDirection, Boolean> {
        val hm = (if (v is String) t.helmerts[v] ?: throw Json.ParseException("$id: неизвестный набор параметров '$v'") else v).asMap("$id: helmert")
        val tr = hm["t"].asList("t").map { it.asDouble("t") }
        val r = hm["r"].asList("r").map { it.asDouble("r") }
        if (tr.size != 3 || r.size != 3) throw Json.ParseException("$id: t и r должны быть по 3 числа")
        val conv = when (val c = hm["convention"]?.asString("convention") ?: "coordinate_frame") {
            "coordinate_frame" -> RotationConvention.COORDINATE_FRAME
            "position_vector" -> RotationConvention.POSITION_VECTOR
            else -> throw Json.ParseException("$id: неизвестное соглашение '$c'")
        }
        val dir = when (val d = hm["direction"]?.asString("direction") ?: "wgs84_to_local") {
            "wgs84_to_local" -> HelmertDirection.WGS84_TO_LOCAL
            "local_to_wgs84" -> HelmertDirection.LOCAL_TO_WGS84
            else -> throw Json.ParseException("$id: неизвестное направление '$d'")
        }
        val confirmed = hm["confirmed"] as? Boolean ?: true
        return Triple(Helmert(tr[0], tr[1], tr[2], r[0], r[1], r[2], hm["ppm"].asDouble("ppm"), conv), dir, confirmed)
    }

    private fun decodeProjection(id: String, m: Map<String, Any?>, ell: Ellipsoid): MapProjection {
        fun d(k: String) = m[k].asDouble("$id: $k")
        return when (val method = m["method"].asInt("$id: method")) {
            MapProjection.TM -> TransverseMercator(ell, d("lat0") * DEG, d("lon0") * DEG, d("k0"), d("x0"), d("y0"))
            MapProjection.TM_SOUTH_ORIENTED ->
                TransverseMercatorSouthOriented(TransverseMercator(ell, d("lat0") * DEG, d("lon0") * DEG, d("k0"), d("x0"), d("y0")))
            MapProjection.LCC_1SP -> LambertConformalConic.oneParallel(ell, d("lat0") * DEG, d("lon0") * DEG, d("k0"), d("x0"), d("y0"))
            MapProjection.LCC_2SP -> LambertConformalConic.twoParallel(
                ell, d("latF") * DEG, d("lonF") * DEG, d("lat1") * DEG, d("lat2") * DEG, d("eF"), d("nF"),
            )
            else -> throw Json.ParseException("$id: метод проекции $method не поддерживается")
        }
    }

    fun decodeCrs(v: Any?, tables: Tables = Tables(emptyMap(), emptyMap())): CrsDef {
        val m = v.asMap("СК")
        val id = m["id"].asString("id")
        val ell = decodeEllipsoid(id, m["ellipsoid"], tables)
        val hel = m["helmert"]?.let { decodeHelmert(id, it, tables) }
        val projMap = (m["projection"] ?: m["tm"]?.let { old -> LinkedHashMap(old.asMap("$id: tm")).also { it["method"] = MapProjection.TM.toDouble() } })
            .asMap("$id: projection")
        val projection = decodeProjection(id, projMap, ell)
        val bounds = m["bounds"]?.let { b ->
            b.asList("$id: bounds").map { it.asDouble("bounds") }.also { if (it.size != 4) throw Json.ParseException("$id: bounds из 4 чисел") }
                .let { GeoBounds(it[0], it[1], it[2], it[3]) }
        }
        val axes = m["axes"]?.asString("axes") ?: "NE"
        if (axes != "NE" && axes != "EN") throw Json.ParseException("$id: axes должно быть NE или EN")
        val unit = m["unit"]?.asDouble("unit") ?: 1.0
        if (!(unit > 0.0)) throw Json.ParseException("$id: unit должен быть > 0")
        return CrsDef(
            id, m["name"].asString("name"), ell, hel?.first, projection, bounds,
            epsg = m["epsg"]?.asInt("epsg"), region = m["region"]?.asString("region"), source = m["source"]?.asString("source"),
            helmertDirection = hel?.second ?: HelmertDirection.WGS84_TO_LOCAL,
            firstAxisIsEast = axes == "EN", unitToMeters = unit, helmertDirectionConfirmed = hel?.third ?: true,
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
        if (fmt != 1 && fmt != FORMAT) throw Json.ParseException("Версия формата $fmt не поддерживается (ожидается 1 или $FORMAT)")
        val ells = (root["ellipsoids"]?.asMap("ellipsoids") ?: emptyMap()).mapValues { (k, v) ->
            v.asMap("ellipsoid $k").let { Ellipsoid(it["name"]?.asString("name") ?: k, it["a"].asDouble("a"), it["invF"].asDouble("invF")) }
        }
        val tables = Tables(ells, (root["helmerts"]?.asMap("helmerts") ?: emptyMap()).mapValues { it.value.asMap("helmert") })
        val ids = HashSet<String>()
        val entries = root["entries"].asList("entries").map { decodeCrs(it, tables) }
        entries.forEach { if (!ids.add(it.id)) throw Json.ParseException("Дубль id '${it.id}'") }
        return Catalog(entries)
    }
}
