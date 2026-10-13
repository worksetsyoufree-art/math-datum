# math-datum

Инструментарий локальных систем координат для поверхностей (DXF, позже LandXML).
Kotlin Multiplatform: android, desktop, web. План и статус — [docs/PLAN.md](docs/PLAN.md).

## Сейчас в репозитории

`:core` — чистый Kotlin без зависимостей:

- `Ellipsoid`, `Geodesy` — эллипсоиды, geodetic ↔ geocentric;
- `Helmert` — 7 параметров, точный, оба соглашения вращений;
- `TransverseMercator` — ряды Крюгера, 6-й порядок;
- `CrsDef`, `Catalog` — СК, оси, единицы, статус перехода в WGS84; демо-набор в коде, полный справочник EPSG (5021 СК) — `app/src/commonMain/composeResources/files/epsg.json`;
- `TransverseMercator`, `LambertConformalConic`, `MapProjection` — проекции;
- `SurfaceV1`, `GsiDatumJson` — чертёж SURFACE_V1 и описание СК (`datum.json`);
- `Georef` — единый результат: `toWgs84` / `fromWgs84`;
- `Localization` — привязка по парам точек (подобие 2D, невязки, выбросы);
- `DatumFinder` — поиск СК по габаритам и anchor;
- `CatalogJson`, `GeorefJson` — справочник и файл привязки (JSON v1, без зависимостей);
- `SurfaceAnalysis`, `SurfaceUnits` — габариты без мусорных вершин, кандидаты единиц.

```kotlin
val r = Localization.localize(pairs)               // пары: точка чертежа ↔ WGS84
if (r is LocalizationResult.Ok) r.georef.fromWgs84(Geodetic.ofDegrees(55.75, 37.62))

val found = DatumFinder.find(bounds, Anchor(gps), Catalog.demo())
found.first().toGeoref()
```

## Тесты

```
gradle :core:desktopTest :core:jsNodeTest :core:testDebugUnitTest   # Gradle, нужен Android SDK (см. docs/PLAN.md)
KOTLINC_HOME=/path/to/kotlinc tools/run_jvm_tests.sh   # без Gradle, JVM
```

Эталоны из PROJ: `tools/gen_golden.py` (нужен `pip install pyproj`).
