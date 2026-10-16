import { strict as assert } from "node:assert";
import { test } from "node:test";
import {
  balloonCells,
  cloudCells,
  fireflyCells,
  moonCells,
  spawnBalloon,
  spawnClouds,
  spawnFireflies,
  stepBalloon,
  stepClouds,
} from "../src/scenery.ts";

const moon = (phase: number, elevation = 40, across = 0.5) => ({ phase, elevation, across });
const litCols = (phase: number) => moonCells(moon(phase), 120, 40, 1).filter((c) => c.glyph === "@").map((c) => c.x);

test("moon is hidden below the horizon and brighter at night than by day", () => {
  assert.equal(moonCells(moon(0.5, -5), 120, 40, 1).length, 0);
  const night = Math.max(...moonCells(moon(0.5), 120, 40, 1).map((c) => c.alpha));
  const day = Math.max(...moonCells(moon(0.5), 120, 40, 0).map((c) => c.alpha));
  assert.ok(day < night);
});

test("moon phases: new is dark, full is a full disc, waxing lights the right side", () => {
  assert.equal(litCols(0).length, 0);
  assert.ok(litCols(0.5).length > litCols(0.25).length);
  const full = litCols(0.5);
  const mid = (Math.min(...full) + Math.max(...full)) / 2;
  const waxing = litCols(0.25);
  const waning = litCols(0.75);
  assert.ok(waxing.every((x) => x >= mid - 1));
  assert.ok(waning.every((x) => x <= mid + 1));
});

test("clouds drift right and wrap around", () => {
  const clouds = spawnClouds(120, 40);
  assert.ok(clouds.length >= 2);
  const before = clouds.map((c) => c.x);
  stepClouds(clouds, 1, 120);
  assert.ok(clouds.every((c, i) => c.x > before[i]));
  stepClouds(clouds, 10_000, 120);
  assert.ok(clouds.every((c) => c.x < 120 + 30));
  assert.ok(cloudCells(clouds[0], 1).length > 10);
});

test("fireflies only appear with dusk and blink", () => {
  const flies = spawnFireflies(120, 40);
  assert.equal(fireflyCells(flies, 3, 0).length, 0);
  const counts = new Set<number>();
  for (let t = 0; t < 20; t += 0.5) counts.add(fireflyCells(flies, t, 1).length);
  assert.ok(counts.size > 1);
});

test("a balloon drifts upward across the sky and leaves", () => {
  const b = spawnBalloon(120, 40);
  const y0 = b.y;
  stepBalloon(b, 5, 120);
  assert.ok(b.y < y0);
  let steps = 0;
  while (stepBalloon(b, 0.5, 120) && steps < 10_000) steps += 1;
  assert.ok(steps < 10_000);
  assert.ok(balloonCells(spawnBalloon(120, 40)).length > 8);
});

import { fogDensity, spawnCloudBank } from "../src/scenery.ts";

test("fog is thin overhead and thick at the ground", () => {
  assert.ok(fogDensity(0, 40) < 0.35);
  assert.ok(fogDensity(39, 40) > 0.9);
  assert.ok(fogDensity(20, 40) > fogDensity(10, 40));
});

test("overcast has more and bigger clouds than a few fair-weather ones", () => {
  const fair = spawnClouds(120, 40);
  const bank = spawnCloudBank(120, 40);
  assert.ok(bank.length > fair.length);
  const mean = (cs: { w: number }[]) => cs.reduce((a, c) => a + c.w, 0) / cs.length;
  assert.ok(mean(bank) > mean(fair));
});
