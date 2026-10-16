#!/bin/sh
# Rebuilds public/geo/*.json from US Census cartographic boundaries (public domain).
# us-county-shapes.json is county polygons keyed by GEOID (state+county FIPS) for filling alert areas.
# Needs docker; run from web/. Output is committed, so this is only for refreshing.
set -eu
YEAR=2023
WORK=$(mktemp -d)
for L in county state; do
  curl -fsSL -o "$WORK/$L.zip" "https://www2.census.gov/geo/tiger/GENZ$YEAR/shp/cb_${YEAR}_us_${L}_5m.zip"
  mkdir "$WORK/$L" && python3 -m zipfile -e "$WORK/$L.zip" "$WORK/$L"
done
docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$WORK:/work" -w /work node:22-slim sh -c "
  npx --yes mapshaper@0.6.100 county/*.shp -simplify 10% keep-shapes -innerlines -o us-counties.json format=geojson precision=0.0005
  npx --yes mapshaper@0.6.100 state/*.shp -simplify 10% keep-shapes -lines -o us-states.json format=geojson precision=0.0005
  npx --yes mapshaper@0.6.100 county/*.shp -simplify 10% keep-shapes -filter-fields GEOID -o us-county-shapes.json format=geojson precision=0.0005"
mv "$WORK"/us-counties.json "$WORK"/us-states.json "$WORK"/us-county-shapes.json public/geo/
rm -rf "$WORK"
