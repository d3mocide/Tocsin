import type { Bird } from "./birds";
import type { Cell } from "./sky_events";

type Rand = () => number;

export type Season = "winter" | "spring" | "summer" | "fall";

/** Meteorological seasons; flipped south of the equator. */
export function seasonOf(when: Date, lat: number): Season {
  const month = when.getMonth();
  const north: Season = month === 11 || month < 2 ? "winter" : month < 5 ? "spring" : month < 8 ? "summer" : "fall";
  if (lat >= 0) return north;
  return ({ winter: "summer", summer: "winter", spring: "fall", fall: "spring" } as const)[north];
}

export interface Ripple {
  x: number;
  y: number;
  age: number;
}

const RIPPLE_LIFE = 0.9;

export function spawnRipple(x: number, rows: number, rand: Rand = Math.random): Ripple {
  return { x, y: rows - 1 - Math.floor(rand() * 3), age: 0 };
}

export function stepRipples(ripples: Ripple[], dt: number): Ripple[] {
  for (const r of ripples) r.age += dt;
  return ripples.filter((r) => r.age < RIPPLE_LIFE);
}

export function rippleCells(ripples: Ripple[]): Cell[] {
  const cells: Cell[] = [];
  for (const r of ripples) {
    const f = r.age / RIPPLE_LIFE;
    const alpha = 0.55 * (1 - f);
    if (f < 0.35) cells.push({ x: r.x, y: r.y, glyph: ".", alpha });
    else if (f < 0.7) cells.push({ x: r.x, y: r.y, glyph: "o", alpha });
    else {
      cells.push({ x: r.x - 1.5, y: r.y, glyph: "(", alpha });
      cells.push({ x: r.x + 1.5, y: r.y, glyph: ")", alpha });
    }
  }
  return cells;
}

const SNOW_MAX = 3;

export function growSnow(pile: number[], col: number, amount = 0.12): void {
  const i = Math.min(Math.max(Math.round(col), 0), pile.length - 1);
  pile[i] = Math.min(SNOW_MAX, pile[i] + amount);
}

/** Smooths lumps and, once the snow stops, melts the pile away. */
export function settleSnow(pile: number[], dt: number, snowing: boolean): void {
  const prev = pile.slice();
  const k = Math.min(1, dt * 1.5);
  for (let i = 0; i < pile.length; i += 1) {
    const neighbours = ((prev[i - 1] ?? prev[i]) + (prev[i + 1] ?? prev[i])) / 2;
    pile[i] = Math.max(0, prev[i] + (neighbours - prev[i]) * k - (snowing ? 0 : 0.04 * dt));
  }
}

export const SNOW_RGB: [number, number, number] = [226, 238, 255];

export function snowCells(pile: number[], rows: number): Cell[] {
  const cells: Cell[] = [];
  pile.forEach((h, col) => {
    const full = Math.floor(h);
    for (let r = 0; r < full; r += 1) cells.push({ x: col, y: rows - 1 - r, glyph: "▒", alpha: 0.55, rgb: SNOW_RGB });
    if (h - full > 0.35) cells.push({ x: col, y: rows - 1 - full, glyph: "░", alpha: 0.45, rgb: SNOW_RGB });
  });
  return cells;
}

/** Roughly one winter night in four is an aurora night, stable for the whole evening. */
export function auroraNight(when: Date): boolean {
  // Evening hours belong to the date that is ending, so shift before taking the day.
  const day = new Date(when.getTime() - 12 * 3_600_000);
  const key = day.getFullYear() * 400 + day.getMonth() * 32 + day.getDate();
  return (Math.imul(key, 2654435761) >>> 0) % 4 === 0;
}

/** Slow swell so the display comes and goes instead of sitting on screen. */
export const auroraSwell = (t: number): number => 0.35 + 0.65 * (0.5 + 0.5 * Math.sin(t * 0.04));

const GREEN: [number, number, number] = [90, 255, 170];
const VIOLET: [number, number, number] = [190, 130, 255];

export function auroraCells(cols: number, rows: number, t: number, intensity: number): Cell[] {
  if (intensity <= 0) return [];
  const cells: Cell[] = [];
  for (let c = 0; c < cols; c += 1) {
    const top = rows * (0.1 + 0.07 * Math.sin(c * 0.07 + t * 0.2));
    const len = rows * (0.16 + 0.1 * Math.sin(c * 0.11 - t * 0.3));
    const shimmer = 0.6 + 0.4 * Math.sin(c * 0.55 + t * 1.3);
    for (let i = 0; i < len; i += 1) {
      const f = i / len;
      cells.push({
        x: c,
        y: top + i,
        glyph: f < 0.5 ? "|" : f < 0.8 ? ":" : ".",
        alpha: intensity * shimmer * (1 - f) * 0.55,
        rgb: f > 0.7 ? VIOLET : GREEN,
      });
    }
  }
  return cells;
}

/** A V of geese: leader out front, the wings trailing back on alternating sides. */
export function spawnGeese(cols: number, rows: number, rand: Rand = Math.random): Bird[] {
  const dir = rand() < 0.5 ? 1 : -1;
  const count = 5 + Math.floor(rand() * 5);
  const lead = dir === 1 ? -6 : cols + 6;
  const y = 2 + rand() * rows * 0.35;
  const speed = 6 + rand() * 2;
  return Array.from({ length: count }, (_, k) => ({
    x: lead - dir * k * 4,
    y: y + (k % 2 ? -1 : 1) * Math.ceil(k / 2) * 0.9,
    speed,
    dir,
    phase: k * 0.35,
    near: true,
  }));
}

export const nextGeeseDelay = (rand: Rand = Math.random) => 60 + rand() * 90;
