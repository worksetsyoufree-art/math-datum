#!/usr/bin/env sh
# Rebuild everything from the raw scrapes committed in data/raw (add --scrape to re-download first).
set -e
cd "$(dirname "$0")/.."
if [ "$1" = "--scrape" ]; then python3 -I scripts/scrape_geoprof.py; python3 -I scripts/scrape_tg.py; fi
python3 -I scripts/parse_msk.py
python3 -I scripts/build_dataset.py
python3 -I scripts/validate.py
python3 -I scripts/merge_fieldworker.py
python3 -I scripts/finalize.py
python3 -I scripts/make_reference.py
python3 -I scripts/build_web.py
node tests/proj4_parity.mjs
