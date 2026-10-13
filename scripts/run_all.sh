#!/usr/bin/env sh
# Rebuild everything from the raw data committed in data/raw.
#   --scrape  re-download the two Russian sites first
#   --world   re-export the world EPSG catalogue (~6 min, needs pyproj) and rebuild country areas
set -e
cd "$(dirname "$0")/.."
for a in "$@"; do
  [ "$a" = "--scrape" ] && { python3 -I scripts/scrape_geoprof.py; python3 -I scripts/scrape_tg.py; }
  [ "$a" = "--world" ] && { python3 -I scripts/export_epsg.py; node scripts/pack_world.mjs; python3 -I scripts/build_areas.py; python3 -I scripts/build_regions.py; }
done
python3 -I scripts/parse_msk.py
python3 -I scripts/build_dataset.py
python3 -I scripts/validate.py
python3 -I scripts/merge_fieldworker.py
python3 -I scripts/finalize.py
[ -f build/ne50_admin1.geojson ] && python3 -I scripts/build_regions.py
python3 -I scripts/make_reference.py
python3 -I scripts/build_web.py
node tests/proj4_parity.mjs
python3 -I tests/test_survey_cloud.py
python3 -I tests/test_user_points.py
node tests/survey_cloud.mjs
node tests/calib.test.mjs
