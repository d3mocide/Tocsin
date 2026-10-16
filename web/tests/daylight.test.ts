import { strict as assert } from "node:assert";
import { test } from "node:test";
import { guessLocation, skyLook, sunPosition } from "../src/daylight.ts";

// Portland, OR. Reference times for 2026-10-16 are from the `astral` library
// (sunrise 14:28:52Z, sunset 01:24:33Z the next UTC day).
const PDX = { lat: 45.52, lon: -122.68 };
const at = (iso: string) => sunPosition(new Date(iso), PDX.lat, PDX.lon);

/** Minutes after `from` where elevation crosses -0.833 deg, to the minute. */
function crossing(from: string, rising: boolean): string {
  const start = new Date(from).getTime();
  for (let m = 0; m < 1440; m += 1) {
    const t = new Date(start + m * 60_000);
    const a = sunPosition(t, PDX.lat, PDX.lon).elevation;
    const b = sunPosition(new Date(t.getTime() + 60_000), PDX.lat, PDX.lon).elevation;
    if (rising ? a < -0.833 && b >= -0.833 : a > -0.833 && b <= -0.833) return t.toISOString();
  }
  throw new Error("no crossing");
}

test("equinox noon at the equator is overhead", () => {
  const p = sunPosition(new Date("2026-03-20T12:00:00Z"), 0, 0);
  assert.ok(p.elevation > 88, `elevation ${p.elevation}`);
});

test("sunrise and sunset in Portland match an independent reference within 2 minutes", () => {
  const within = (iso: string, target: string) =>
    assert.ok(Math.abs(new Date(iso).getTime() - new Date(target).getTime()) <= 2 * 60_000, `${iso} vs ${target}`);
  within(crossing("2026-10-16T10:00:00Z", true), "2026-10-16T14:28:52Z");
  within(crossing("2026-10-16T22:00:00Z", false), "2026-10-17T01:24:33Z");
});

test("morning flag flips at solar noon", () => {
  assert.equal(at("2026-10-16T16:00:00Z").morning, true);
  assert.equal(at("2026-10-16T22:00:00Z").morning, false);
});

test("polar night and midnight sun do not blow up", () => {
  assert.ok(sunPosition(new Date("2026-12-21T12:00:00Z"), 80, 0).elevation < 0);
  assert.ok(sunPosition(new Date("2026-06-21T00:00:00Z"), 80, 0).elevation > 0);
});

test("night look is the original static palette, stars fully on", () => {
  const look = skyLook({ elevation: -40, morning: false });
  assert.equal(look.bg, "#04050b");
  assert.equal(look.bg1, "#0a0c1f");
  assert.equal(look.starlight, 1);
});

test("looks are continuous across the horizon", () => {
  const a = skyLook({ elevation: 0.99, morning: true });
  const b = skyLook({ elevation: 1.01, morning: true });
  assert.equal(a.bg1, b.bg1);
  assert.deepEqual(a.calmTint, b.calmTint);
});

test("dawn and dusk differ, full day agrees, stars gone by day", () => {
  assert.notEqual(skyLook({ elevation: 1, morning: true }).glowA, skyLook({ elevation: 1, morning: false }).glowA);
  assert.equal(skyLook({ elevation: 50, morning: true }).bg1, skyLook({ elevation: 50, morning: false }).bg1);
  assert.equal(skyLook({ elevation: 50, morning: true }).starlight, 0);
});

test("fallback location follows the UTC offset", () => {
  const { lon } = guessLocation(new Date());
  assert.ok(lon >= -180 && lon <= 180);
});
