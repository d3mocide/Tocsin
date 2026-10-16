import { strict as assert } from "node:assert";
import { test } from "node:test";
import { AIR_ALERT, FIRE_ALERT, FIRE_ESCALATING, fireDanger, hazyWeather } from "../src/weather_risk.ts";

test("an air quality alert is not a fire weather alert", () => {
  assert.ok(AIR_ALERT.test("Air Quality Alert"));
  assert.ok(AIR_ALERT.test("Dense Smoke Advisory"));
  assert.ok(AIR_ALERT.test("Blowing Dust Warning"));
  assert.ok(!FIRE_ALERT.test("Air Quality Alert"));
  assert.ok(!FIRE_ALERT.test("Dense Smoke Advisory"));
  assert.ok(FIRE_ESCALATING.test("Red Flag Warning"));
  assert.ok(FIRE_ESCALATING.test("Fire Weather Watch"));
  assert.ok(FIRE_ALERT.test("Fire Warning") && !FIRE_ESCALATING.test("Fire Warning"));
});

test("no observation and no alert gives no estimate, not a safe-looking default", () => {
  assert.equal(fireDanger(null, false), null);
  assert.equal(fireDanger({ rh: null, tempF: 70, wind: 5 }, false), null);
  assert.equal(fireDanger({ rh: 50, tempF: null, wind: 5 }, false), null);
});

test("a red flag product escalates even without an observation", () => {
  assert.equal(fireDanger(null, true)?.index, 4);
});

test("danger rises as humidity falls and wind or heat rise", () => {
  assert.equal(fireDanger({ rh: 66, tempF: 55, wind: 7 }, false)?.index, 0);
  assert.equal(fireDanger({ rh: 35, tempF: 60, wind: 3 }, false)?.index, 1);
  assert.equal(fireDanger({ rh: 25, tempF: 75, wind: 10 }, false)?.index, 2);
  assert.equal(fireDanger({ rh: 20, tempF: 75, wind: 14 }, false)?.index, 3);
  assert.equal(fireDanger({ rh: 15, tempF: 90, wind: 20 }, false)?.index, 4);
});

test("only present weather that means smoke, haze or dust counts as hazy", () => {
  assert.ok(hazyWeather("Haze"));
  assert.ok(hazyWeather("Patchy smoke"));
  assert.ok(!hazyWeather("Mostly Clear"));
  assert.ok(!hazyWeather(null));
});
