import { strict as assert } from "node:assert";
import { test } from "node:test";
import { stepBirds } from "../src/birds.ts";
import {
  auroraCells,
  auroraNight,
  growSnow,
  rippleCells,
  seasonOf,
  settleSnow,
  snowCells,
  spawnGeese,
  spawnRipple,
  stepRipples,
} from "../src/weather.ts";

test("seasons follow the month and flip in the southern hemisphere", () => {
  assert.equal(seasonOf(new Date(2026, 0, 15), 45), "winter");
  assert.equal(seasonOf(new Date(2026, 3, 15), 45), "spring");
  assert.equal(seasonOf(new Date(2026, 6, 15), 45), "summer");
  assert.equal(seasonOf(new Date(2026, 9, 15), 45), "fall");
  assert.equal(seasonOf(new Date(2026, 9, 15), -33), "spring");
  assert.equal(seasonOf(new Date(2026, 11, 25), -33), "summer");
});

test("ripples land near the ground, spread, then vanish", () => {
  let ripples = [spawnRipple(10, 40)];
  assert.ok(ripples[0].y >= 37 && ripples[0].y <= 39);
  const first = rippleCells(ripples)[0].glyph;
  ripples = stepRipples(ripples, 0.45);
  const second = rippleCells(ripples)[0].glyph;
  ripples = stepRipples(ripples, 0.3);
  assert.equal(rippleCells(ripples).length, 2);
  assert.notEqual(first, second);
  assert.equal(stepRipples(ripples, 1).length, 0);
});

test("snow piles up, evens out, and melts when it stops", () => {
  const pile = new Array(20).fill(0);
  for (let i = 0; i < 40; i += 1) growSnow(pile, 10);
  assert.ok(pile[10] <= 3);
  for (let i = 0; i < 100; i += 1) settleSnow(pile, 0.1, true);
  assert.ok(pile[8] > 0.2 && pile[8] < pile[10], "snow should spread to neighbours");
  const field = new Array(20).fill(0);
  for (let c = 0; c < 20; c += 1) for (let i = 0; i < 10; i += 1) growSnow(field, c);
  for (let i = 0; i < 40; i += 1) growSnow(field, 10);
  settleSnow(field, 0.1, true);
  assert.ok(snowCells(field, 40).length > 20);
  assert.ok(snowCells(field, 40).every((c) => c.y >= 40 - 4 && c.y < 40));
  for (let i = 0; i < 2000; i += 1) settleSnow(pile, 0.1, false);
  assert.equal(snowCells(pile, 40).length, 0);
});

test("aurora nights are about one in four and stable through an evening", () => {
  let nights = 0;
  for (let d = 1; d <= 120; d += 1) if (auroraNight(new Date(2026, 0, d, 22))) nights += 1;
  assert.ok(nights > 15 && nights < 45, `${nights} of 120`);
  assert.equal(auroraNight(new Date(2026, 0, 10, 20)), auroraNight(new Date(2026, 0, 11, 2)));
});

test("aurora draws only with intensity, in green and violet", () => {
  assert.equal(auroraCells(100, 40, 5, 0).length, 0);
  const cells = auroraCells(100, 40, 5, 1);
  assert.ok(cells.length > 300);
  assert.ok(cells.every((c) => c.rgb && c.alpha >= 0));
  assert.ok(new Set(cells.map((c) => c.rgb!.join())).size === 2);
});

test("geese form a V trailing behind the leader", () => {
  const geese = spawnGeese(120, 40);
  assert.ok(geese.length >= 5);
  const [lead, ...rest] = geese;
  assert.ok(rest.every((g) => (lead.dir === 1 ? g.x < lead.x : g.x > lead.x)));
  assert.ok(geese.some((g) => g.y < lead.y) && geese.some((g) => g.y > lead.y));
  assert.ok(geese.every((g) => g.speed === lead.speed));
});

test("a whole formation survives entering the screen", () => {
  const geese = spawnGeese(120, 40);
  const flying = stepBirds(geese, 1 / 15, 120, 60);
  assert.equal(flying.length, geese.length);
  let moved = flying;
  for (let i = 0; i < 15 * 12; i += 1) moved = stepBirds(moved, 1 / 15, 120, 60);
  assert.equal(moved.length, geese.length, "all geese should still be flying after 12s");
});
