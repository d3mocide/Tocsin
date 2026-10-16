import type { MoonPosition } from "./daylight";
import type { Cell } from "./sky_events";

type Rand = () => number;

const MOON_RY = 3;
const MOON_RX = 5.2;

/** A lit disc whose terminator follows the phase; waxing is lit on the right. */
export function moonCells(moon: MoonPosition, cols: number, rows: number, starlight: number): Cell[] {
  const alpha = Math.min(1, moon.elevation / 6) * (0.3 + 0.7 * starlight);
  if (alpha <= 0) return [];
  const cx = moon.across * (cols - 12) + 6;
  const cy = Math.max(2, (1 - Math.min(moon.elevation, 70) / 70) * rows * 0.45 + 2);
  const waxing = moon.phase < 0.5;
  const c = Math.cos(moon.phase * 2 * Math.PI);
  const cells: Cell[] = [];
  for (let dy = -MOON_RY; dy <= MOON_RY; dy += 1) {
    const v = dy / (MOON_RY + 0.5);
    const half = Math.sqrt(Math.max(0, 1 - v * v));
    for (let dx = -Math.ceil(MOON_RX); dx <= Math.ceil(MOON_RX); dx += 1) {
      const u = dx / (MOON_RX + 0.4);
      if (u * u + v * v > 1) continue;
      const edge = c * half;
      const lit = waxing ? u > edge : u < -edge;
      cells.push({ x: cx + dx, y: cy + dy, glyph: lit ? "@" : ".", alpha: (lit ? 0.8 : 0.12) * alpha });
    }
  }
  return cells;
}

export interface Cloud {
  x: number;
  y: number;
  w: number;
  h: number;
  speed: number;
  seed: number;
}

export function spawnClouds(cols: number, rows: number, rand: Rand = Math.random): Cloud[] {
  const count = Math.max(2, Math.round(cols / 30));
  return Array.from({ length: count }, (_, i) => ({
    x: ((i + rand() * 0.8) / count) * cols,
    y: 2 + rand() * rows * 0.45,
    w: 7 + rand() * 9,
    h: 1.5 + rand() * 1.5,
    speed: 0.5 + rand() * 1.1,
    seed: rand() * 100,
  }));
}

/** Overcast: bigger, denser, layered clouds that fill most of the sky. */
export function spawnCloudBank(cols: number, rows: number, rand: Rand = Math.random): Cloud[] {
  const count = Math.max(4, Math.round(cols / 11));
  return Array.from({ length: count }, (_, i) => ({
    x: ((i + rand() * 0.6) / count) * cols,
    y: 1 + rand() * rows * 0.6,
    w: 12 + rand() * 14,
    h: 2 + rand() * 2.2,
    speed: 0.8 + rand() * 1.8,
    seed: rand() * 100,
  }));
}

/** Fog is a thin veil overhead that thickens toward the ground. */
export function fogDensity(row: number, rows: number): number {
  const depth = Math.min(Math.max(row / rows, 0), 1);
  return 0.3 + 0.7 * depth ** 1.2;
}

export function stepClouds(clouds: Cloud[], dt: number, cols: number): void {
  for (const c of clouds) {
    c.x += c.speed * dt;
    if (c.x - c.w > cols) c.x = -c.w;
  }
}

export function cloudCells(c: Cloud, dayness: number, strength = 0.2): Cell[] {
  const cells: Cell[] = [];
  for (let dy = -Math.ceil(c.h); dy <= Math.ceil(c.h); dy += 1) {
    for (let dx = -Math.ceil(c.w); dx <= Math.ceil(c.w); dx += 1) {
      // Lumpy top edge: flat underside, billowed top.
      const bump = 1 + 0.25 * Math.sin(dx * 0.7 + c.seed) + (dy < 0 ? 0.2 * Math.sin(dx * 1.9 + c.seed * 2) : 0);
      const d = (dx / c.w) ** 2 + (dy / (c.h * (dy > 0 ? 0.6 : 1))) ** 2;
      if (d > bump) continue;
      cells.push({ x: c.x + dx, y: c.y + dy, glyph: d < bump * 0.45 ? "▒" : "░", alpha: strength * Math.min(1, dayness * 1.5) });
    }
  }
  return cells;
}

export interface Firefly {
  x: number;
  y: number;
  phase: number;
  drift: number;
}

export function spawnFireflies(cols: number, rows: number, rand: Rand = Math.random): Firefly[] {
  return Array.from({ length: Math.round(cols / 3) }, () => ({
    x: rand() * cols,
    y: rows * (0.55 + rand() * 0.42),
    phase: rand() * Math.PI * 2,
    drift: 0.4 + rand() * 0.8,
  }));
}

export function fireflyCells(flies: Firefly[], t: number, dusk: number): Cell[] {
  const shown = Math.round(flies.length * dusk);
  const cells: Cell[] = [];
  for (let i = 0; i < shown; i += 1) {
    const f = flies[i];
    const blink = Math.max(0, Math.sin(t * 0.9 * f.drift + f.phase)) ** 2;
    if (blink < 0.05) continue;
    cells.push({
      x: f.x + Math.sin(t * 0.3 * f.drift + f.phase) * 2.5,
      y: f.y + Math.cos(t * 0.23 * f.drift + f.phase * 2) * 1.2,
      glyph: blink > 0.5 ? "*" : "+",
      alpha: 0.9 * blink,
    });
  }
  return cells;
}

export interface Balloon {
  x: number;
  y: number;
  vx: number;
  vy: number;
}

const BALLOON_ART = [" .-. ", "(   )", " `-' ", "  u  "];

export function spawnBalloon(cols: number, rows: number, rand: Rand = Math.random): Balloon {
  const dir = rand() < 0.5 ? 1 : -1;
  return { x: dir === 1 ? -6 : cols + 6, y: rows * (0.45 + rand() * 0.2), vx: dir * (2 + rand() * 1.5), vy: -(0.15 + rand() * 0.2) };
}

/** Returns false once the balloon has drifted off the far side or off the top. */
export function stepBalloon(b: Balloon, dt: number, cols: number): boolean {
  b.x += b.vx * dt;
  b.y += b.vy * dt;
  return b.y > -5 && (b.vx > 0 ? b.x < cols + 6 : b.x > -6);
}

export function balloonCells(b: Balloon): Cell[] {
  const cells: Cell[] = [];
  BALLOON_ART.forEach((line, row) => {
    [...line].forEach((ch, col) => {
      if (ch !== " ") cells.push({ x: b.x + col - 2, y: b.y + row, glyph: ch, alpha: row === 3 ? 0.7 : 0.85 });
    });
  });
  return cells;
}

export const nextBalloonDelay = (rand: Rand = Math.random) => 40 + rand() * 80;
