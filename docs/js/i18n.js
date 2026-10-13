/* Localisation. To add a language: copy one block, translate the values, add it to LANGS. */
(function (root) {
  "use strict";
  var LANGS = { ru: "Русский", en: "English" };
  var D = {};

  D.ru = {
    title: "Подбор датума и системы координат",
    subtitle: "Какой датум и какую проекцию использовать для места и задачи — с пересчётом координат и проверками",
    tabFinder: "Подбор", tabIdentify: "Определить СК", tabConvert: "Конвертер", tabCatalog: "Каталог", tabAbout: "О проекте",
    language: "Язык",

    whereTitle: "1. Где находится объект?",
    lat: "Широта", lon: "Долгота", latPh: "55.7558 или 55°45′21″", lonPh: "37.6173 или 37°37′02″",
    myLoc: "Моё местоположение", example: "Пример", examplePh: "— выбрать город —",
    placeSearch: "Найти страну / регион", placeSearchPh: "например: Germany, Россия, Japan",
    placeHint: "Названия областей применения в EPSG английские; для русских названий стран работают подсказки.",
    geoDenied: "Не удалось определить местоположение.",
    purposeTitle: "2. Для чего нужны координаты?",
    p_gnss: "Навигация / ГНСС", p_gnss_d: "Данные с приёмников GPS/ГЛОНАСС/Galileo, совместимость с WGS 84",
    p_survey: "Геодезия, кадастр, стройка", p_survey_d: "Официальная местная система — максимально «локальная» и точная для региона",
    p_legacy: "Старые карты и данные", p_legacy_d: "Материалы в устаревших датумах (СК-42, NAD27, ED50 …)",
    showUnverified: "учитывать неподтверждённые российские МСК",
    resultsTitle: "Рекомендуемые датумы", noResults: "Для этой точки в реестре EPSG нет подходящих датумов.",
    rank: "место", score: "оценка",
    selectDatum: "Выбран", projTitle: "Подходящие проекции для выбранного датума",
    projNone: "Не нашлось проекций, покрывающих эту точку.", projLoading: "Загрузка каталога проекций…",
    areaOfUse: "Область применения", ellipsoid: "Эллипсоид", toWgs: "Преобразование в WGS 84", accuracy: "точность",
    helmert: "Гельмерт (7 параметров, ГОСТ/EPSG), точность ≈ {v} м", identity: "совпадает с WGS 84 (в пределах ≈ {v} м)",
    ballpark: "официального преобразования нет — принято равенство WGS 84", noTransform: "преобразование в EPSG отсутствует",
    shift: "Если читать эти координаты как WGS 84, точка сместится на ≈ {v} м",
    coordsAt: "Координаты точки", east: "Восток (E / Y)", north: "Север (N / X)", offsetCm: "от осевого меридиана", km: "км",
    copyEpsg: "Копировать код", copyProj: "Копировать PROJ", copied: "Скопировано",
    approxNote: "строка PROJ приближает цепочку EPSG: расхождение ≈ {v} м",
    mskNote: "Российская МСК: область применения оценена кругом вокруг столицы региона (границ нет), параметры — из открытых источников",
    verified: "подтверждена", unverified: "неподтверждена",

    w_modern: "современная реализация (эпоха ГНСС)", w_old: "устаревший датум", w_gnssNative: "родной датум спутниковых систем",
    w_global: "глобальный датум", w_regional: "региональный (несколько стран), специфичность {v}%", w_local: "локальный, специфичность {v}%", w_modernNotLegacy: "современный — для старых данных не нужен",
    w_inBorders: "точка внутри границ стран области применения", w_noTransform: "нет преобразования в WGS 84", w_ballpark: "преобразование только приблизительное",
    w_identity: "в EPSG совпадает с WGS 84 (≈ {v} м)", w_helmert: "преобразование Гельмерта (≈ {v} м)",
    w_gridBetter: "точнее ({v} м) только с файлами сеток", w_ensemble: "ансамбль датумов",
    w_sameDatum: "основан на выбранном датуме", w_offset: "{v} км от осевого меридиана", w_mskVerified: "МСК: подтверждена",
    w_mskUnverified: "МСК: один источник", w_mskArea: "область оценена по столице региона",

    idTitle: "В какой системе координат эти числа?",
    idDesc: "Введите координаты в метрах и, если можете, примерное место. Перебираются все проекции каталога: подходят те, чей результат попадает в область их применения и рядом с подсказкой.",
    idHint: "Примерное место (необязательно)", idRadius: "Радиус, км", idFind: "Искать", idNone: "Ничего не подошло — расширьте радиус или уберите подсказку.",
    idDist: "до подсказки", idLoading: "Загрузка каталога…", idExample: "Пример: МСК-50, зона 1 (Красногорск)", idShown: "Показано {n} из {m}",
    idTable: "Система", idLat: "Широта", idLon: "Долгота",

    convTitle: "Пересчёт между системами", from: "Из системы", to: "В систему", pickCrs: "поиск по названию или коду EPSG",
    inLon: "Долгота (x)", inLat: "Широта (y)", inE: "Восток E / Y, м", inN: "Север N / X, м", result: "Результат",
    swap: "Поменять местами", geoOrder: "Для географических систем порядок: долгота, широта (градусы).",
    convError: "Не удалось пересчитать", pickFirst: "Выберите системы.",

    catTitle: "Каталог", catSearch: "Поиск", catSearchPh: "название, страна, код EPSG…", catType: "Тип",
    t_all: "всё", t_geo: "датумы (географические СК)", t_proj: "проекции EPSG", t_msk: "МСК России",
    catShown: "Показано {n} из {m}", catDetails: "Подробности", catParams: "Параметры", catSources: "Источники",
    catChecks: "Проверки", catFlags: "Примечания", catUse: "Открыть в конвертере", ruOnlyVerified: "только подтверждённые МСК",

    aboutTitle: "О проекте",
  };

  D.en = {
    title: "Datum & CRS Finder",
    subtitle: "Which datum and projection to use for a place and a task — with coordinate conversion and quality checks",
    tabFinder: "Finder", tabIdentify: "Identify CRS", tabConvert: "Converter", tabCatalog: "Catalog", tabAbout: "About",
    language: "Language",

    whereTitle: "1. Where is the site?",
    lat: "Latitude", lon: "Longitude", latPh: "55.7558 or 55°45′21″", lonPh: "37.6173 or 37°37′02″",
    myLoc: "My location", example: "Example", examplePh: "— pick a city —",
    placeSearch: "Find a country / region", placeSearchPh: "e.g. Germany, Japan, Россия",
    placeHint: "EPSG area names are in English; common Russian country names are mapped.",
    geoDenied: "Could not get your location.",
    purposeTitle: "2. What are the coordinates for?",
    p_gnss: "Navigation / GNSS", p_gnss_d: "Data from GPS/GLONASS/Galileo receivers, WGS 84 compatible",
    p_survey: "Surveying, cadastre, construction", p_survey_d: "Official local system — the most local and accurate for the area",
    p_legacy: "Old maps and data", p_legacy_d: "Material in outdated datums (SK-42, NAD27, ED50 …)",
    showUnverified: "include unverified Russian MSK",
    resultsTitle: "Recommended datums", noResults: "The EPSG registry has no datum for this point.",
    rank: "rank", score: "score",
    selectDatum: "Selected", projTitle: "Suitable projections for the selected datum",
    projNone: "No projection covers this point.", projLoading: "Loading the projection catalogue…",
    areaOfUse: "Area of use", ellipsoid: "Ellipsoid", toWgs: "Transformation to WGS 84", accuracy: "accuracy",
    helmert: "Helmert (7 parameters, EPSG), accuracy ≈ {v} m", identity: "equal to WGS 84 (within ≈ {v} m)",
    ballpark: "no official transformation — treated as equal to WGS 84", noTransform: "no transformation in EPSG",
    shift: "Reading these coordinates as WGS 84 would move the point by ≈ {v} m",
    coordsAt: "Coordinates of the point", east: "Easting (E / Y)", north: "Northing (N / X)", offsetCm: "from central meridian", km: "km",
    copyEpsg: "Copy code", copyProj: "Copy PROJ", copied: "Copied",
    approxNote: "the PROJ string approximates the EPSG chain: difference ≈ {v} m",
    mskNote: "Russian MSK: area of use is estimated as a circle around the regional capital (no boundaries); parameters come from open sources",
    verified: "verified", unverified: "unverified",

    w_modern: "modern (GNSS-era) realisation", w_old: "outdated datum", w_gnssNative: "native datum of satellite systems",
    w_global: "global datum", w_regional: "regional (several countries), specificity {v}%", w_local: "local, specificity {v}%", w_modernNotLegacy: "modern — not needed for old data",
    w_inBorders: "point is inside the countries of the area of use", w_noTransform: "no transformation to WGS 84", w_ballpark: "only an approximate transformation",
    w_identity: "equal to WGS 84 in EPSG (≈ {v} m)", w_helmert: "Helmert transformation (≈ {v} m)",
    w_gridBetter: "better ({v} m) only with grid files", w_ensemble: "datum ensemble",
    w_sameDatum: "based on the selected datum", w_offset: "{v} km from the central meridian", w_mskVerified: "MSK: verified",
    w_mskUnverified: "MSK: single source", w_mskArea: "area estimated from the regional capital",

    idTitle: "Which coordinate system are these numbers in?",
    idDesc: "Enter the coordinates in metres and, if you can, the approximate place. Every projection in the catalogue is tried: it fits if the result falls inside its area of use and near your hint.",
    idHint: "Approximate place (optional)", idRadius: "Radius, km", idFind: "Search", idNone: "Nothing fits — widen the radius or drop the hint.",
    idDist: "from the hint", idLoading: "Loading the catalogue…", idExample: "Example: MSK-50 zone 1 (Krasnogorsk)", idShown: "Showing {n} of {m}",
    idTable: "System", idLat: "Latitude", idLon: "Longitude",

    convTitle: "Convert between systems", from: "From system", to: "To system", pickCrs: "search by name or EPSG code",
    inLon: "Longitude (x)", inLat: "Latitude (y)", inE: "Easting E / Y, m", inN: "Northing N / X, m", result: "Result",
    swap: "Swap", geoOrder: "For geographic systems the order is longitude, latitude (degrees).",
    convError: "Conversion failed", pickFirst: "Pick the systems.",

    catTitle: "Catalog", catSearch: "Search", catSearchPh: "name, country, EPSG code…", catType: "Type",
    t_all: "all", t_geo: "datums (geographic CRS)", t_proj: "EPSG projections", t_msk: "Russian MSK",
    catShown: "Showing {n} of {m}", catDetails: "Details", catParams: "Parameters", catSources: "Sources",
    catChecks: "Checks", catFlags: "Notes", catUse: "Open in converter", ruOnlyVerified: "verified MSK only",

    aboutTitle: "About",
  };

  /* long texts: HTML, one block per language; {tokens} are filled from data at runtime */
  D.ru.about = [
    "<h2>Как работает подбор</h2><p>Для точки и задачи перебираются все географические СК реестра EPSG, область применения которых содержит точку. Оценка складывается из трёх частей: <b>специфичность</b> (чем меньше область применения, тем «местнее» датум), <b>точность преобразования в WGS 84</b> и <b>современность</b> (эпоха ГНСС). Веса зависят от цели: для ГНСС выигрывают современные и глобальные датумы (WGS 84), для геодезии — локальные официальные, для старых данных — устаревшие. Для выбранного датума подбираются проекции: основанные на нём, с малым смещением от осевого меридиана, местные.</p><p>Это эвристика: области применения в EPSG — прямоугольники, а не границы стран, а признак «современный» определяется по названию. Результат — подсказка, а не замена нормативных документов.</p>",
    "<h2>Данные и проверки</h2><p>Датумов: <b>{geo}</b>, проекций EPSG: <b>{proj}</b> (реестр EPSG {epsg} от {epsg_date}, PROJ {proj_ver}). Параметры преобразований приведены к конвенции PROJ <code>+towgs84</code> (position vector, локальная → WGS 84): операции в обратном направлении инвертируются, повороты «coordinate frame» меняют знак. Из реестра исключено {dropped} проекций, на которых proj4js расходится с PROJ больше чем на {tol} м (оси W/S, нестандартные единицы и т. п.). У {approx1} проекций строка PROJ приближает цепочку EPSG с расхождением более 1 м (преобразования по сеткам заменены лучшим набором Гельмерта) — это показывается в карточке.</p><p>Каждая проекция проверена: пересчёт в браузерном движке proj4js совпадает с PROJ (pyproj). Российские МСК собраны с открытых сайтов и экспорта Fieldworker; подтверждены {ru_ver} из {ru_total} систем (минимум два источника + геометрические проверки), остальные помечены.</p>",
    "<h2>Проверка на реальной съёмке</h2><p>Облако точек поверхности в МСК-78(5) (Санкт-Петербург) и набор параметров с тремя поворотами показали, что в первом экспорте потерян поворот вокруг оси Y (ωy = 5,93454″). Точка начала ENU (59,79377° с.ш., 30,46896° в.д.) через исправленную систему попадает в облако в 4,5 м от его центра; без ωy промах 181 м. Тест входит в репозиторий.</p>",
    "<h2>Ограничения</h2><ul><li>Области применения — прямоугольники EPSG; для МСК — круг вокруг столицы региона (границ в открытых данных нет).</li><li>Нет данных по МСК: {missing}.</li><li>Проверки подтверждают осевой меридиан, ложные координаты и согласованность, но не заменяют сверку по опорным пунктам.</li><li>Преобразования по сеткам (NTv2 и др.) здесь заменены 7-параметрической моделью — для точных работ используйте сетки.</li></ul>",
  ].join("");
  D.en.about = [
    "<h2>How the selection works</h2><p>For a point and a task, every geographic CRS of the EPSG registry whose area of use contains the point is scored on <b>specificity</b> (the smaller the area of use, the more local the datum), <b>accuracy of the transformation to WGS 84</b>, and <b>modernity</b> (GNSS-era realisation). Weights depend on the task: for GNSS, modern and global datums (WGS 84) win; for surveying, local official ones; for old data, outdated ones. For the chosen datum, projections are ranked: those based on it, with small offset from the central meridian, and local ones.</p><p>This is a heuristic: EPSG areas of use are rectangles, not country borders, and “modern” is detected from names. The result is a hint, not a replacement for regulations.</p>",
    "<h2>Data and checks</h2><p>Datums: <b>{geo}</b>, EPSG projections: <b>{proj}</b> (EPSG registry {epsg} of {epsg_date}, PROJ {proj_ver}). Transformation parameters are converted to the PROJ <code>+towgs84</code> convention (position vector, local → WGS 84): operations defined the other way are inverted and “coordinate frame” rotations change sign. {dropped} projections were excluded because proj4js differs from PROJ by more than {tol} m (W/S axes, unusual units, etc.). For {approx1} projections the PROJ string approximates the EPSG chain by more than 1 m (grid-based transformations are replaced by the best Helmert set) — this is shown on the card.</p><p>Every projection is checked: the in-browser engine (proj4js) matches PROJ (pyproj). Russian MSK systems are collected from open sites and a Fieldworker export; {ru_ver} of {ru_total} are verified (at least two sources + geometric checks), the rest are flagged.</p>",
    "<h2>Check on a real survey</h2><p>A surface point cloud in MSK-78(5) (Saint Petersburg) and a parameter set with three rotations showed that the first export lost the Y-axis rotation (ωy = 5.93454″). The ENU origin (59.79377°N, 30.46896°E) lands inside the cloud, 4.5 m from its centre, through the corrected system; without ωy it misses by 181 m. The test is in the repository.</p>",
    "<h2>Limitations</h2><ul><li>Areas of use are EPSG rectangles; for MSK, a circle around the regional capital (no boundaries in open data).</li><li>No MSK data for: {missing}.</li><li>Checks confirm central meridian, false origin and consistency, but do not replace a check against control points.</li><li>Grid-based transformations (NTv2 etc.) are replaced here by a 7-parameter model — use the grids for precise work.</li></ul>",
  ].join("");

  root.I18N = { LANGS: LANGS, D: D };
})(typeof self !== "undefined" ? self : this);
