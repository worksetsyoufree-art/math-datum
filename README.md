# math-datum

Инструментарий локальных систем координат для поверхностей (DXF, позже LandXML).
Kotlin Multiplatform: android, desktop, web. План и статус — [docs/PLAN.md](docs/PLAN.md).

## Сейчас в репозитории

`:core` — чистый Kotlin без зависимостей:

- `Ellipsoid`, `Geodesy` — эллипсоиды, geodetic ↔ geocentric;
- `Helmert` — 7 параметров, точный, оба соглашения вращений;
- `TransverseMercator` — ряды Крюгера, 6-й порядок;
- `CrsDef`, `Catalog` — СК и демо-справочник (не настоящий);
- `Georef` — единый результат: `toWgs84` / `fromWgs84`;
- `Localization` — привязка по парам точек (подобие 2D, невязки, выбросы);
- `DatumFinder` — поиск СК по габаритам и anchor.

```kotlin
val r = Localization.localize(pairs)               // пары: точка чертежа ↔ WGS84
if (r is LocalizationResult.Ok) r.georef.fromWgs84(Geodetic.ofDegrees(55.75, 37.62))

val found = DatumFinder.find(bounds, Anchor(gps), Catalog.demo())
found.first().toGeoref()
```

## Тесты

```
./gradlew :core:allTests
```

Эталоны из PROJ: `tools/gen_golden.py` (нужен `pip install pyproj`).
