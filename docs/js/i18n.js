/* Localisation. To add a language: copy one block, translate the values, add it to LANGS. */
(function (root) {
  "use strict";
  var LANGS = { ru: "Русский", en: "English" };
  var D = {};

  D.ru = {
    title: "Подбор датума", subtitle: "Локальные координаты или широта-долгота → подходящие датумы; локализация по парам точек",
    language: "Язык", tabFinder: "Подбор датума", tabCalib: "Локализация", aboutTitle: "О проекте и методике",

    modeLocal: "Локальные координаты", modeLL: "Широта, долгота",
    ptsLabel: "Точка или поверхность в локальных координатах: «X Y [Z]» или «E N [Z]» по строке; принимается разметка <P …>X Y Z</P> и файл SURFACE_V1",
    chooseFile: "Выбрать файл…", exPoints: "Пример: 6 точек", exSurface: "Пример: поверхность",
    lat: "Широта", lon: "Долгота", latPh: "55.7558 или 55°45′21″", lonPh: "37.6173 или 37°37′02″", example: "Пример", examplePh: "— выбрать город —",
    purpose: "Для чего", p_gnss: "Навигация / ГНСС", p_survey: "Геодезия, кадастр", p_legacy: "Старые карты и данные",
    myLoc: "Моё местоположение", geoDenied: "Не удалось определить местоположение.",
    refine: "Уточнить (необязательно): порядок осей, страна, рамка",
    order: "Порядок чисел", orderAuto: "определить автоматически", orderXY: "X Y — север, восток (российская запись)", orderEN: "E N — восток, север",
    area: "Страна / регион", areaPh: "например: Россия, Germany", areaSet: "Область:", areaClear: "сбросить",
    box: "Рамка, в которую точка должна попасть: широта, долгота двух углов", boxPh: "55.619783, 38.310216, 55.623095, 38.304913", boxBad: "В рамке нужны 4 числа.",
    refineNote: "Без подсказки места одни и те же числа подходят многим системам (например, «зона 2» есть у МСК десятков областей). Названия областей применения в EPSG английские; для русских названий стран работают подсказки.",
    go: "Подобрать", loading: "Загрузка каталога…", noPoints: "Нет чисел в точках.",
    sumPts: "{n} точ.: X {x}; Y {y}; Z {z}", sumPtsNoZ: "{n} точ.: X {x}; Y {y}",

    resultsTitle: "Подходящие датумы", noResults: "Ни один датум не подошёл — расширьте подсказку или проверьте порядок осей.",
    shown: "Показано {n} датумов из {m}", systems: "систем", sysShown: "ещё {n}…",
    center: "центр", inArea: "в области применения", fromCenter: "{u}% по E, {v}% по N от края", rectLabel: "область в этой системе: E {e}, N {n}",
    hyp_xy: "X — север, Y — восток", hyp_en: "E — восток, N — север", details: "Подробнее", hide: "Свернуть",
    allPoints: "Все точки", csv: "Скачать CSV", copy: "Копировать", copied: "Скопировано", copyProj: "Копировать PROJ", copyEpsg: "Копировать код",
    east: "Восток (E / Y)", north: "Север (N / X)", fits: "в области: {p}% точек",
    areaOfUse: "Область применения", ellipsoid: "Эллипсоид", toWgs: "Преобразование в WGS 84", accuracy: "точность",
    helmert: "Гельмерт, ≈ {v} м", identity: "совпадает с WGS 84 (≈ {v} м)", ballpark: "официального преобразования нет", noTransform: "преобразования в EPSG нет",
    shift: "Читать как WGS 84 — сдвиг ≈ {v} м",
    mskNote: "Российская МСК: область — круг вокруг столицы региона; параметры из открытых источников",
    verified: "подтверждена", unverified: "не подтверждена", datumMsk: "Местные системы МСК: {r}", datumNone: "без датума",
    w_modern: "современная реализация", w_old: "устаревший датум", w_gnssNative: "родной датум ГНСС", w_global: "глобальный", w_regional: "региональный, спец. {v}%",
    w_local: "локальный, спец. {v}%", w_modernNotLegacy: "современный — для старых данных не нужен", w_noTransform: "нет преобразования в WGS 84",
    w_ballpark: "преобразование приблизительное", w_identity: "= WGS 84 (≈ {v} м)", w_helmert: "Гельмерт ≈ {v} м", w_gridBetter: "точнее ({v} м) только по сеткам",
    w_ensemble: "ансамбль", w_inBorders: "внутри границ стран", w_sameDatum: "на этом датуме", w_offset: "{v} км от осевого меридиана",
    w_shift: "читать как WGS 84 → сдвиг ≈ {v} м", w_mskVerified: "МСК подтверждена", w_mskUnverified: "МСК: один источник", w_mskArea: "область по столице",

    calTitle: "Локализация: датум по парам точек",
    calDesc: "Задайте точки в локальных координатах и их координаты в WGS 84 — приложение подберёт параметры перехода (сдвиг или 7 параметров Гельмерта + вертикальная плоскость) и даст преобразования в обе стороны. Результат — датум в формате Fieldworker/ГОСТ и строка PROJ.",
    calPairs: "Пары: «X Y [Z] широта долгота [h]» по строке (X — север, Y — восток; h — эллипсоидальная высота WGS 84)", calExample: "Пример (МСК-78(5), 12 точек)",
    calProj: "Проекция локальной системы (поперечный Меркатор)", calEll: "Эллипсоид", calLon0: "Осевой меридиан, °", calK: "Масштаб на осевом", calFE: "Ложный восток, м", calFN: "Ложный север, м", calLat0: "Широта начала, °",
    calModel: "Модель", calModelAuto: "автоматически", calModelT3: "сдвиг (3 параметра)", calModelH7: "Гельмерт (7 параметров)",
    calSuggest: "Подобрать проекцию по точкам", calFit: "Рассчитать датум", calImport: "Загрузить датум (JSON)…", calApply: "Преобразование точек", calRun: "Преобразовать",
    calDir: "Направление", calW2L: "WGS 84 → локальные", calL2W: "локальные → WGS 84",
    calInW: "Широта долгота [h] по строке", calInL: "X Y [Z] по строке (порядок как выше)",
    calNeedPairs: "Нужно минимум 2 пары.", calNone: "Ничего не подошло.", calSugFound: "Подходящие проекции (нажмите, чтобы подставить):",
    calParams: "Параметры датума", calResid: "Невязки по точкам", calRms: "СКО по плану {v} мм, по высоте {h} мм", calRmsNoH: "СКО по плану {v} мм",
    calModelUsed: "Модель: {m}", calResultProj: "PROJ (локальная → WGS 84)", calResultJson: "Датум (JSON Fieldworker)", calDownload: "Скачать JSON",
    calHeightPlane: "Вертикальная плоскость a0 = {v} м (H = h + a0)",
    w_singular: "Точки вырождены или лежат на одной линии — оставлен только сдвиг.", w_few: "Для 7 параметров лучше ≥ 4 точек.",
    w_small: "Участок меньше 2 км: повороты и сдвиги плохо разделимы — надёжнее сдвиг (3 параметра).", w_noHeights: "Высоты не заданы: вертикаль не оценивается, датум годится для плана.",
    calResidHead: "точка", calOut: "Результат", calImported: "Датум загружен.", calBadJson: "Не удалось прочитать JSON.",
    aboutHtml: "",
  };

  D.en = {
    title: "Datum Finder", subtitle: "Local coordinates or lat/lon → matching datums; localisation from point pairs",
    language: "Language", tabFinder: "Find datum", tabCalib: "Localisation", aboutTitle: "About and method",

    modeLocal: "Local coordinates", modeLL: "Latitude, longitude",
    ptsLabel: "A point or a surface in local coordinates: “X Y [Z]” or “E N [Z]” per line; <P …>X Y Z</P> markup and SURFACE_V1 files are accepted",
    chooseFile: "Choose file…", exPoints: "Example: 6 points", exSurface: "Example: surface",
    lat: "Latitude", lon: "Longitude", latPh: "55.7558 or 55°45′21″", lonPh: "37.6173 or 37°37′02″", example: "Example", examplePh: "— pick a city —",
    purpose: "Purpose", p_gnss: "Navigation / GNSS", p_survey: "Surveying, cadastre", p_legacy: "Old maps and data",
    myLoc: "My location", geoDenied: "Could not get your location.",
    refine: "Refine (optional): axis order, country, box",
    order: "Order of numbers", orderAuto: "detect automatically", orderXY: "X Y — north, east (Russian notation)", orderEN: "E N — east, north",
    area: "Country / region", areaPh: "e.g. Russia, Germany", areaSet: "Area:", areaClear: "clear",
    box: "Box the point must fall into: latitude, longitude of two corners", boxPh: "55.619783, 38.310216, 55.623095, 38.304913", boxBad: "The box needs 4 numbers.",
    refineNote: "Without a hint about the place the same numbers fit many systems (for example, dozens of regional MSK have a “zone 2”). EPSG area names are in English; common Russian country names are mapped.",
    go: "Find", loading: "Loading the catalogue…", noPoints: "No numbers found in the points.",
    sumPts: "{n} pts: X {x}; Y {y}; Z {z}", sumPtsNoZ: "{n} pts: X {x}; Y {y}",

    resultsTitle: "Matching datums", noResults: "No datum fits — widen the hint or check the axis order.",
    shown: "Showing {n} datums of {m}", systems: "systems", sysShown: "{n} more…",
    center: "centre", inArea: "inside the area of use", fromCenter: "{u}% in E, {v}% in N from the edge", rectLabel: "area in this system: E {e}, N {n}",
    hyp_xy: "X = north, Y = east", hyp_en: "E = east, N = north", details: "Details", hide: "Collapse",
    allPoints: "All points", csv: "Download CSV", copy: "Copy", copied: "Copied", copyProj: "Copy PROJ", copyEpsg: "Copy code",
    east: "Easting (E / Y)", north: "Northing (N / X)", fits: "inside: {p}% of points",
    areaOfUse: "Area of use", ellipsoid: "Ellipsoid", toWgs: "Transformation to WGS 84", accuracy: "accuracy",
    helmert: "Helmert, ≈ {v} m", identity: "equal to WGS 84 (≈ {v} m)", ballpark: "no official transformation", noTransform: "no transformation in EPSG",
    shift: "Read as WGS 84 — shift ≈ {v} m",
    mskNote: "Russian MSK: area is a circle around the regional capital; parameters from open sources",
    verified: "verified", unverified: "unverified", datumMsk: "Local MSK systems: {r}", datumNone: "no datum",
    w_modern: "modern realisation", w_old: "outdated datum", w_gnssNative: "native GNSS datum", w_global: "global", w_regional: "regional, spec. {v}%",
    w_local: "local, spec. {v}%", w_modernNotLegacy: "modern — not needed for old data", w_noTransform: "no transformation to WGS 84",
    w_ballpark: "approximate transformation", w_identity: "= WGS 84 (≈ {v} m)", w_helmert: "Helmert ≈ {v} m", w_gridBetter: "better ({v} m) only with grids",
    w_ensemble: "ensemble", w_inBorders: "inside country borders", w_sameDatum: "on this datum", w_offset: "{v} km from the central meridian",
    w_shift: "read as WGS 84 → shift ≈ {v} m", w_mskVerified: "MSK verified", w_mskUnverified: "MSK: single source", w_mskArea: "area from the capital",

    calTitle: "Localisation: a datum from point pairs",
    calDesc: "Enter points in local coordinates together with their WGS 84 coordinates — the app fits the transformation (translation or 7-parameter Helmert + a vertical plane) and transforms both ways. The result is a datum in Fieldworker/GOST format and a PROJ string.",
    calPairs: "Pairs: “X Y [Z] lat lon [h]” per line (X north, Y east; h = WGS 84 ellipsoidal height)", calExample: "Example (MSK-78(5), 12 points)",
    calProj: "Projection of the local system (Transverse Mercator)", calEll: "Ellipsoid", calLon0: "Central meridian, °", calK: "Scale on the meridian", calFE: "False easting, m", calFN: "False northing, m", calLat0: "Latitude of origin, °",
    calModel: "Model", calModelAuto: "automatic", calModelT3: "translation (3 parameters)", calModelH7: "Helmert (7 parameters)",
    calSuggest: "Suggest projection from the points", calFit: "Compute datum", calImport: "Load datum (JSON)…", calApply: "Transform points", calRun: "Transform",
    calDir: "Direction", calW2L: "WGS 84 → local", calL2W: "local → WGS 84",
    calInW: "lat lon [h] per line", calInL: "X Y [Z] per line (axis order as above)",
    calNeedPairs: "At least 2 pairs are needed.", calNone: "Nothing fits.", calSugFound: "Matching projections (click to fill in):",
    calParams: "Datum parameters", calResid: "Residuals", calRms: "RMS horizontal {v} mm, vertical {h} mm", calRmsNoH: "RMS horizontal {v} mm",
    calModelUsed: "Model: {m}", calResultProj: "PROJ (local → WGS 84)", calResultJson: "Datum (Fieldworker JSON)", calDownload: "Download JSON",
    calHeightPlane: "Vertical plane a0 = {v} m (H = h + a0)",
    w_singular: "Points are degenerate or collinear — translation only.", w_few: "Seven parameters need ≥ 4 points.",
    w_small: "Site is under 2 km: rotations and translations are poorly separable — translation (3 parameters) is safer.", w_noHeights: "No heights: the vertical is not estimated; the datum is good for the plan only.",
    calResidHead: "point", calOut: "Result", calImported: "Datum loaded.", calBadJson: "Could not read the JSON.",
    aboutHtml: "",
  };

  /* long texts: HTML, {tokens} are filled from data at runtime */
  D.ru.about = [
    "<h2>Как работает подбор</h2><p>У каждой системы координат есть область применения (в EPSG — прямоугольник в градусах плюс список стран). Приложение переводит эту область в <b>прямоугольник в собственных (локальных) координатах системы</b> и смотрит, куда попадают ваши числа: доля точек внутри прямоугольника, близость к центру и к осевому меридиану, специфичность области. Затем проверяется центр точек по реальным границам стран и подсказкам (страна, рамка). Для широты-долготы то же делается в обратную сторону: все датумы, чья область содержит точку, оцениваются по специфичности, точности перехода к WGS 84 и современности.</p><p>Это эвристика: области применения — прямоугольники и списки стран, а признак «современный» определяется по названию. Результат — подсказка, а не нормативная рекомендация.</p>",
    "<h2>Данные</h2><p>Датумов: <b>{geo}</b>, проекций EPSG: <b>{proj}</b> (реестр EPSG {epsg} от {epsg_date}, PROJ {proj_ver}); российские МСК: {ru_total} систем, из них подтверждены {ru_ver} (минимум два источника + геометрические проверки). Параметры переходов приведены к форме PROJ <code>+towgs84</code>. Проекции, на которых proj4js расходится с PROJ больше чем на {tol} м, исключены ({dropped}). У {approx1} проекций цепочка EPSG на сетках заменена лучшим набором Гельмерта.</p>",
    "<h2>Локализация</h2><p>Датум задаётся так же, как в геодезическом ПО: проекция (поперечный Меркатор на локальном эллипсоиде) + 3D-преобразование Гельмерта от ECEF WGS 84 к локальному ECEF + вертикальная плоскость. Параметры подбираются по методу наименьших квадратов; экспорт — JSON в формате Fieldworker (повороты «coordinate frame», секунды; масштаб в ppm) и строка PROJ. Проверка на реальной съёмке МСК-78(5): точка начала ENU попадает в облако точек в 4,5 м от его центра, а синтетическая локализация восстанавливает исходный датум до долей миллиметра.</p>",
    "<h2>Ограничения</h2><ul><li>Области применения МСК — круг вокруг столицы региона (границ в открытых данных нет); нет данных: {missing}.</li><li>Преобразования по сеткам (NTv2 и др.) заменены 7-параметрической моделью.</li><li>Для малых участков (&lt; 2 км) 7 параметров определяются плохо — используйте сдвиг.</li></ul>",
  ].join("");
  D.en.about = [
    "<h2>How the selection works</h2><p>Every coordinate system has an area of use (in EPSG a rectangle in degrees plus a list of countries). The app converts that area into a <b>rectangle in the system's own (local) coordinates</b> and sees where your numbers fall: the share of points inside the rectangle, closeness to its centre and to the central meridian, specificity of the area. Then the centre of the points is checked against real country borders and your hints (country, box). For latitude/longitude the same is done the other way round: every datum whose area of use contains the point is scored on specificity, accuracy of the transformation to WGS 84, and modernity.</p><p>This is a heuristic: areas of use are rectangles and country lists, and “modern” is detected from names. The result is a hint, not a regulation.</p>",
    "<h2>Data</h2><p>Datums: <b>{geo}</b>, EPSG projections: <b>{proj}</b> (EPSG registry {epsg} of {epsg_date}, PROJ {proj_ver}); Russian MSK: {ru_total} systems, {ru_ver} of them verified (at least two sources + geometric checks). Transformation parameters are converted to the PROJ <code>+towgs84</code> form. Projections where proj4js differs from PROJ by more than {tol} m are excluded ({dropped}). For {approx1} projections the EPSG chain on grids is replaced by the best Helmert set.</p>",
    "<h2>Localisation</h2><p>A datum is defined as in survey software: a projection (Transverse Mercator on a local ellipsoid) + a 3D Helmert from WGS 84 ECEF to local ECEF + a vertical plane. Parameters are fitted by least squares; export is Fieldworker JSON (coordinate-frame rotations in arcsec, scale in ppm) and a PROJ string. Checked on a real survey in MSK-78(5): the ENU origin lands 4.5 m from the centre of the point cloud, and a synthetic localisation recovers the original datum to fractions of a millimetre.</p>",
    "<h2>Limitations</h2><ul><li>MSK areas are circles around the regional capital (no boundaries in open data); no data for: {missing}.</li><li>Grid-based transformations (NTv2 etc.) are replaced by a 7-parameter model.</li><li>On small sites (&lt; 2 km) seven parameters are poorly determined — use translation.</li></ul>",
  ].join("");

  root.I18N = { LANGS: LANGS, D: D };
})(typeof self !== "undefined" ? self : this);
