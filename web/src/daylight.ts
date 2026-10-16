/** Time-of-day look for the page, from the sun's elevation at the station.
 * Pure math (NOAA solar position), so it works offgrid; sunrise and sunset
 * are the elevation crossing -0.833 deg, which is what almanacs use. */

export type Rgb = [number, number, number];
type Rgba = [number, number, number, number];

export interface SunPosition {
  /** Degrees above the horizon, atmospheric refraction not included. */
  elevation: number;
  /** Before solar noon: warm "sunrise" colours rather than "sunset" ones. */
  morning: boolean;
}

export interface SkyLook {
  bg: string;
  bg1: string;
  glowA: string;
  glowB: string;
  /** Backdrop tint while no alert is active. */
  calmTint: Rgb;
  /** 1 in full night, 0 once the sun is near the horizon; fades the stars. */
  starlight: number;
  /** 0..1 strength of morning / evening twilight, peaking at sunrise / sunset. */
  dawn: number;
  dusk: number;
}

const RAD = Math.PI / 180;

interface SolarCore {
  /** Radians. */
  decl: number;
  /** Degrees, sun's ecliptic longitude. */
  lambda: number;
  /** Degrees; negative before solar noon. */
  hourAngle: number;
}

function solarCore(when: Date, lon: number): SolarCore {
  const jd = when.getTime() / 86_400_000 + 2440587.5;
  const T = (jd - 2451545) / 36525;
  const L0 = (280.46646 + T * (36000.76983 + T * 0.0003032)) % 360;
  const M = 357.52911 + T * (35999.05029 - 0.0001537 * T);
  const e = 0.016708634 - T * (0.000042037 + 0.0000001267 * T);
  const C =
    Math.sin(M * RAD) * (1.914602 - T * (0.004817 + 0.000014 * T)) +
    Math.sin(2 * M * RAD) * (0.019993 - 0.000101 * T) +
    Math.sin(3 * M * RAD) * 0.000289;
  const trueLon = L0 + C;
  const omega = 125.04 - 1934.136 * T;
  const lambda = trueLon - 0.00569 - 0.00478 * Math.sin(omega * RAD);
  const obliq =
    23 + (26 + (21.448 - T * (46.815 + T * (0.00059 - T * 0.001813))) / 60) / 60 +
    0.00256 * Math.cos(omega * RAD);
  const decl = Math.asin(Math.sin(obliq * RAD) * Math.sin(lambda * RAD));

  const y = Math.tan((obliq / 2) * RAD) ** 2;
  const eqTime =
    4 *
    (y * Math.sin(2 * L0 * RAD) -
      2 * e * Math.sin(M * RAD) +
      4 * e * y * Math.sin(M * RAD) * Math.cos(2 * L0 * RAD) -
      0.5 * y * y * Math.sin(4 * L0 * RAD) -
      1.25 * e * e * Math.sin(2 * M * RAD)) /
    RAD;

  const utcMinutes = when.getUTCHours() * 60 + when.getUTCMinutes() + when.getUTCSeconds() / 60;
  const solarMinutes = (((utcMinutes + eqTime + 4 * lon) % 1440) + 1440) % 1440;
  return { decl, lambda, hourAngle: solarMinutes / 4 - 180 };
}

const elevationOf = (latDeg: number, decl: number, hourAngleDeg: number): number =>
  Math.asin(
    Math.sin(latDeg * RAD) * Math.sin(decl) + Math.cos(latDeg * RAD) * Math.cos(decl) * Math.cos(hourAngleDeg * RAD),
  ) / RAD;

export function sunPosition(when: Date, lat: number, lon: number): SunPosition {
  const { decl, hourAngle } = solarCore(when, lon);
  return { elevation: elevationOf(lat, decl, hourAngle), morning: hourAngle < 0 };
}

export interface MoonPosition {
  /** 0 new, 0.5 full, back to 1 new. */
  phase: number;
  elevation: number;
  /** 0 = east horizon, 1 = west horizon, along the sky as seen from the northern hemisphere. */
  across: number;
}

const SYNODIC_DAYS = 29.530588;
// A new moon: 2000-01-06 18:14 UTC.
const NEW_MOON_MS = Date.UTC(2000, 0, 6, 18, 14);

export const moonPhase = (when: Date): number =>
  ((((when.getTime() - NEW_MOON_MS) / 86_400_000 / SYNODIC_DAYS) % 1) + 1) % 1;

/** Decorative accuracy: the moon is placed by its elongation from the sun
 * along the ecliptic, ignoring orbital inclination and parallax (a few degrees). */
export function moonPosition(when: Date, lat: number, lon: number, phaseOverride?: number): MoonPosition {
  const phase = phaseOverride ?? moonPhase(when);
  const elongation = phase * 360;
  const sun = solarCore(when, lon);
  const decl = Math.asin(Math.sin(23.44 * RAD) * Math.sin((sun.lambda + elongation) * RAD));
  const hourAngle = sun.hourAngle - elongation;
  const wrapped = ((((hourAngle + 180) % 360) + 360) % 360) - 180;
  return {
    phase,
    elevation: elevationOf(lat, decl, wrapped),
    across: Math.min(Math.max(0.5 + wrapped / 180, 0), 1),
  };
}

// Stops are [elevation, bg, bg1, glowA, glowB, calm tint]. Night matches the
// original static page; "day" stays dark enough for the panel text contrast.
type Stop = [number, Rgba, Rgba, Rgba, Rgba, Rgb];

const NIGHT: Stop = [-18, [4, 5, 11, 1], [10, 12, 31, 1], [56, 189, 248, 0.11], [139, 92, 246, 0.14], [103, 232, 249]];
const DAY: Stop = [20, [8, 17, 32, 1], [17, 38, 66, 1], [125, 211, 252, 0.16], [96, 165, 250, 0.12], [147, 220, 252]];
const DAWN: Stop[] = [
  NIGHT,
  [-5, [10, 8, 22, 1], [34, 24, 58, 1], [244, 114, 182, 0.14], [129, 140, 248, 0.14], [196, 181, 253]],
  [1, [20, 12, 26, 1], [66, 40, 62, 1], [251, 146, 60, 0.22], [244, 114, 182, 0.16], [253, 186, 116]],
  [9, [14, 20, 36, 1], [38, 52, 84, 1], [253, 186, 116, 0.18], [147, 197, 253, 0.14], [186, 230, 253]],
  DAY,
];
const DUSK: Stop[] = [
  NIGHT,
  [-5, [10, 6, 20, 1], [38, 20, 56, 1], [192, 38, 211, 0.16], [99, 102, 241, 0.14], [216, 180, 254]],
  [1, [22, 10, 22, 1], [74, 30, 60, 1], [249, 115, 22, 0.24], [217, 70, 239, 0.18], [251, 146, 100]],
  [9, [14, 18, 34, 1], [40, 46, 80, 1], [251, 146, 60, 0.16], [129, 140, 248, 0.14], [186, 214, 253]],
  DAY,
];

const mix = (a: number[], b: number[], k: number): number[] => a.map((v, i) => v + (b[i] - v) * k);
const css = ([r, g, b, a]: number[]): string =>
  `rgb(${Math.round(r)} ${Math.round(g)} ${Math.round(b)} / ${(a * 100).toFixed(1)}%)`;
const hex = ([r, g, b]: number[]): string =>
  `#${[r, g, b].map((v) => Math.round(v).toString(16).padStart(2, "0")).join("")}`;

export function skyLook(sun: Pick<SunPosition, "elevation" | "morning">): SkyLook {
  const stops = sun.morning ? DAWN : DUSK;
  const elev = Math.min(Math.max(sun.elevation, stops[0][0]), stops[stops.length - 1][0]);
  let hi = stops.findIndex((s) => s[0] >= elev);
  if (hi < 1) hi = 1;
  const lo = stops[hi - 1];
  const up = stops[hi];
  const k = (elev - lo[0]) / (up[0] - lo[0]);
  const twilight = Math.min(Math.max(1 - Math.abs(sun.elevation + 1) / 9, 0), 1);
  return {
    bg: hex(mix(lo[1], up[1], k)),
    bg1: hex(mix(lo[2], up[2], k)),
    glowA: css(mix(lo[3], up[3], k)),
    glowB: css(mix(lo[4], up[4], k)),
    calmTint: mix(lo[5], up[5], k).map(Math.round) as Rgb,
    starlight: Math.min(Math.max((2 - sun.elevation) / 8, 0), 1),
    dawn: sun.morning ? twilight : 0,
    dusk: sun.morning ? 0 : twilight,
  };
}

/** Used only when the operator hasn't set TOCSIN_LATITUDE/LONGITUDE: the
 * browser's UTC offset pins longitude to within a few hundred km, and
 * latitude only shifts the season, so a mid-latitude guess still looks right. */
export function guessLocation(when: Date): { lat: number; lon: number } {
  return { lat: 40, lon: -when.getTimezoneOffset() / 4 };
}
