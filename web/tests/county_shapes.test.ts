import { strict as assert } from "node:assert";
import { test } from "node:test";
import { alertCounties, parseCountyShapes, sameToGeoids } from "../src/county_shapes.ts";

const square = { type: "Polygon", coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] } as const;
const shapes = parseCountyShapes({
  type: "FeatureCollection",
  features: ["41005", "41051", "41067", "53011"].map((GEOID) => ({
    type: "Feature" as const,
    properties: { GEOID },
    geometry: square,
  })),
});

test("a SAME code resolves to its county, ignoring the part-of-county digit", () => {
  assert.deepEqual(sameToGeoids("041051", shapes), ["41051"]);
  assert.deepEqual(sameToGeoids("341051", shapes), ["41051"]);
});

test("a state-wide code (county 000) covers every county of that state", () => {
  assert.deepEqual(sameToGeoids("041000", shapes).sort(), ["41005", "41051", "41067"]);
});

test("unknown, malformed and nationwide codes resolve to nothing", () => {
  assert.deepEqual(sameToGeoids("041999", shapes), []);
  assert.deepEqual(sameToGeoids("41051", shapes), []);
  assert.deepEqual(sameToGeoids("abcdef", shapes), []);
  assert.deepEqual(sameToGeoids("000000", shapes), []);
});

test("an alert's counties are de-duplicated across its codes", () => {
  assert.deepEqual(alertCounties(["041051", "041005", "341051"], shapes).sort(), ["41005", "41051"]);
  assert.deepEqual(alertCounties([], shapes), []);
});

test("features without a GEOID are skipped", () => {
  const partial = parseCountyShapes({
    type: "FeatureCollection",
    features: [{ type: "Feature", properties: {}, geometry: square }],
  });
  assert.equal(partial.size, 0);
});
