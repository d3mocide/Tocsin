import type { FeatureCollection, Geometry } from "geojson";

/** County outlines keyed by GEOID (2-digit state + 3-digit county FIPS). */
export type CountyShapes = Map<string, Geometry>;

export function parseCountyShapes(collection: FeatureCollection): CountyShapes {
  const shapes: CountyShapes = new Map();
  for (const feature of collection.features) {
    const geoid = feature.properties?.GEOID;
    if (typeof geoid === "string" && feature.geometry) shapes.set(geoid, feature.geometry);
  }
  return shapes;
}

/** A SAME location code is PSSCCC: P marks part of a county (0 = all of it), SS the state,
 * CCC the county, and 000 means the whole state. The part-of-county marker is ignored, so
 * a partial county fills the whole county. */
export function sameToGeoids(code: string, shapes: CountyShapes): string[] {
  if (!/^\d{6}$/.test(code)) return [];
  const state = code.slice(1, 3);
  const county = code.slice(3);
  if (state === "00") return [];
  if (county === "000") return [...shapes.keys()].filter((geoid) => geoid.startsWith(state));
  return shapes.has(state + county) ? [state + county] : [];
}

export function alertCounties(fipsCodes: readonly string[], shapes: CountyShapes): string[] {
  return [...new Set(fipsCodes.flatMap((code) => sameToGeoids(code, shapes)))];
}
