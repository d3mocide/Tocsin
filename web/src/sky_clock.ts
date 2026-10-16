import { guessLocation, moonPosition, skyLook, sunPosition } from "./daylight";
import { daylight } from "./scene";

let override: Date | null = null;
let moonPhaseOverride: number | undefined;

/** Dev panel hook: pin the clock to a fixed instant, or `null` to follow real time. */
export function setTimeOverride(when: Date | null): void {
  override = when;
}

/** Dev panel hook: force the moon phase (0 new .. 0.5 full), or `undefined` for the real one. */
export function setMoonPhaseOverride(phase: number | undefined): void {
  moonPhaseOverride = phase;
}

type Place = { latitude?: number | null; longitude?: number | null } | null;
let lastPlace: Place = null;

export function refreshSky(): void {
  applySky(lastPlace);
}

export function applySky(system: Place): void {
  lastPlace = system;
  const now = override ?? new Date();
  const guess = guessLocation(now);
  const lat = system?.latitude ?? guess.lat;
  const lon = system?.longitude ?? guess.lon;
  const look = skyLook(sunPosition(now, lat, lon));
  const style = document.documentElement.style;
  style.setProperty("--bg", look.bg);
  style.setProperty("--bg-1", look.bg1);
  style.setProperty("--glow-a", look.glowA);
  style.setProperty("--glow-b", look.glowB);
  daylight.calmTint = look.calmTint;
  daylight.starlight = look.starlight;
  daylight.dawn = look.dawn;
  daylight.dusk = look.dusk;
  daylight.moon = moonPosition(now, lat, lon, moonPhaseOverride);
}
