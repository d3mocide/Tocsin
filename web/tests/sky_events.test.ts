import { strict as assert } from "node:assert";
import { test } from "node:test";
import {
  planeCells,
  planeEligible,
  shootingStarCells,
  shootingStarEligible,
  spawnPlane,
  spawnShootingStar,
  stepPlane,
  stepShootingStar,
} from "../src/sky_events.ts";

test("shooting stars only on clear calm nights", () => {
  assert.ok(shootingStarEligible(1, "clear", "calm"));
  assert.ok(!shootingStarEligible(0.3, "clear", "calm"));
  assert.ok(!shootingStarEligible(1, "cloudy", "calm"));
  assert.ok(!shootingStarEligible(1, "clear", "warning"));
});

test("planes fly in fair calm weather, not in the dead of night or during alerts", () => {
  assert.ok(planeEligible(0, "clear", "calm"));
  assert.ok(planeEligible(0.5, "cloudy", "calm"));
  assert.ok(!planeEligible(1, "clear", "calm"));
  assert.ok(!planeEligible(0, "rain", "calm"));
  assert.ok(!planeEligible(0, "clear", "watch"));
});

test("a shooting star streaks, trails behind its motion, then burns out", () => {
  const s = spawnShootingStar(100, 40);
  const cells = shootingStarCells(s);
  assert.equal(cells[0].glyph, "*");
  assert.ok(cells.slice(1).every((c) => (s.vx > 0 ? c.x < s.x : c.x > s.x)));
  assert.ok(cells.slice(1).every((c) => c.alpha < cells[0].alpha));
  let alive = true;
  let steps = 0;
  while (alive && steps < 200) {
    alive = stepShootingStar(s, 1 / 15);
    steps += 1;
  }
  assert.ok(!alive && steps < 30);
});

test("a plane crosses the sky leaving a contrail that fades after it has gone", () => {
  const p = spawnPlane(100, 40);
  let steps = 0;
  let maxTrail = 0;
  while (stepPlane(p, 1 / 15, 100) && steps < 15 * 120) {
    maxTrail = Math.max(maxTrail, p.trail.length);
    steps += 1;
  }
  assert.ok(steps < 15 * 120, "plane never finished");
  assert.ok(maxTrail > 10);
  assert.equal(p.trail.length, 0);
});

test("contrail is older and fainter further behind the plane", () => {
  const p = spawnPlane(100, 40);
  for (let i = 0; i < 100; i += 1) stepPlane(p, 1 / 15, 100);
  const cells = planeCells(p);
  const head = cells[cells.length - 1];
  assert.equal(head.glyph, "+");
  assert.ok(cells[0].alpha < cells[cells.length - 2].alpha);
});
