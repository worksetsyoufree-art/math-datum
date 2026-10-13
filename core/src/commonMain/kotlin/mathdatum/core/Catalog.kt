package mathdatum.core

class Catalog(val entries: List<CrsDef>) {
    companion object {
        /**
         * ДЕМО-справочник для прототипа и тестов. Параметры СК-42 здесь ориентировочные;
         * реальный справочник — отдельный модуль (блок 2 плана), после выяснения лицензии.
         */
        fun demo(): Catalog = Catalog(listOf(utm(37), utm(36), utm(38), sk42Gk(7), sk42Gk(6), sk42Gk(8)))

        fun utm(zone: Int): CrsDef {
            val lon0 = (6.0 * zone - 183.0) * DEG
            return CrsDef(
                id = "demo:utm$zone", name = "WGS 84 / UTM $zone N", ellipsoid = Ellipsoid.WGS84, helmert = null,
                projection = TransverseMercator(Ellipsoid.WGS84, 0.0, lon0, 0.9996, 500000.0, 0.0),
                epsg = 32600 + zone,
            )
        }

        /** Гаусс–Крюгер СК-42, 6° зона, префикс зоны в восточном смещении. */
        fun sk42Gk(zone: Int): CrsDef {
            val lon0 = (6.0 * zone - 3.0) * DEG
            return CrsDef(
                id = "demo:sk42gk$zone", name = "SK-42 / GK zone $zone (demo)", ellipsoid = Ellipsoid.KRASSOVSKY,
                helmert = Helmert(23.92, -141.27, -80.9, 0.0, -0.35, -0.82, -0.12),
                projection = TransverseMercator(Ellipsoid.KRASSOVSKY, 0.0, lon0, 1.0, zone * 1_000_000.0 + 500000.0, 0.0),
            )
        }
    }
}
