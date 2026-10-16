import { strict as assert } from "node:assert";
import { test } from "node:test";
import { birdGlyph, birdTarget, spawnFlock, stepBirds } from "../src/birds.ts";

test("no birds at night, in bad weather, or during an alert", () => {
  assert.equal(birdTarget(120, 0, "clear", "calm"), 0);
  assert.equal(birdTarget(120, 1, "rain", "calm"), 0);
  assert.equal(birdTarget(120, 1, "storm", "calm"), 0);
  assert.equal(birdTarget(120, 1, "clear", "watch"), 0);
  assert.equal(birdTarget(120, 1, "clear", "warning"), 0);
});

test("fair-weather daytime gets birds, thinning toward dusk", () => {
  const day = birdTarget(120, 1, "clear", "calm");
  assert.ok(day > 0);
  assert.ok(birdTarget(120, 0.4, "cloudy", "calm") < day);
});

test("flocks enter from the edge they fly away from", () => {
  const seq = [0.1, 0.9, 0.5, 0.5];
  let i = 0;
  const rand = () => seq[i++ % seq.length];
  const flock = spawnFlock(100, 40, false, rand);
  assert.ok(flock.every((b) => b.dir === 1 && b.x <= -4));
  assert.ok(flock.every((b) => b.y >= 0 && b.y <= 40 * 0.6));
});

test("birds that leave the screen are dropped", () => {
  const flock = spawnFlock(100, 40, true);
  const moved = stepBirds(flock, 1000, 100);
  assert.equal(moved.length, 0);
});

test("wings flap between two glyphs", () => {
  const [b] = spawnFlock(100, 40, true);
  const seen = new Set<string>();
  for (let t = 0; t < 2; t += 0.05) seen.add(birdGlyph(b, t));
  assert.equal(seen.size, 2);
});
