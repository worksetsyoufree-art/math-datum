package mathdatum.app

import mathdatum.app.res.Res
import mathdatum.core.Catalog
import mathdatum.core.CatalogJson

/** Справочник EPSG, встроенный в приложение как ресурс (tools/gen_epsg_catalog.py). */
suspend fun loadEpsgCatalog(): Catalog = CatalogJson.decode(Res.readBytes("files/epsg.json").decodeToString())
