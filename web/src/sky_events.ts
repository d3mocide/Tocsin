import type { Alarm, Sky } from "./scene";

export interface Cell {
  x: number;
  y: number;
  glyph: string;
  alpha: number;
  /** Overrides the scene tint (aurora, snow). */
  rgb?: [number, number, number];
}

const calmFair = (sky: Sky, alarm: Alarm) => alarm === "calm" && (sky === "clear" || sky === "cloudy");

/** Same weather/alert gating as the birds, so alerts never compete with an easter egg. */
export const shootingStarEligible = (starlight: number, sky: Sky, alarm: Alarm) =>
  starlight > 0.8 && sky === "clear" && alarm === "calm";
export const planeEligible = (starlight: number, sky: Sky, alarm: Alarm) => starlight < 0.9 && calmFair(sky, alarm);

type Rand = () => number;

export const nextShootingStarDelay = (rand: Rand = Math.random) => 12 + rand() * 25;
export const nextPlaneDelay = (rand: Rand = Math.random) => 25 + rand() * 50;

export interface ShootingStar {
  x: number;
  y: number;
  vx: number;
  vy: number;
  age: number;
}

const STAR_LIFE = 0.9;
const STAR_TRAIL = 7;

export function spawnShootingStar(cols: number, rows: number, rand: Rand = Math.random): ShootingStar {
  const dir = rand() < 0.5 ? 1 : -1;
  const vx = dir * (35 + rand() * 20);
  // Cells are taller than wide, so this slope reads as roughly 25 degrees on screen.
  return { x: cols * (0.2 + rand() * 0.7), y: rand() * rows * 0.3, vx, vy: Math.abs(vx) * 0.285, age: 0 };
}

/** Returns false once the streak has burned out. */
export function stepShootingStar(s: ShootingStar, dt: number): boolean {
  s.age += dt;
  s.x += s.vx * dt;
  s.y += s.vy * dt;
  return s.age < STAR_LIFE;
}

export function shootingStarCells(s: ShootingStar): Cell[] {
  const fade = Math.min(1, (STAR_LIFE - s.age) / 0.3);
  const sign = Math.sign(s.vx);
  const cells: Cell[] = [{ x: s.x, y: s.y, glyph: "*", alpha: fade }];
  for (let i = 1; i <= STAR_TRAIL; i += 1) {
    cells.push({
      x: s.x - sign * i,
      y: s.y - (s.vy / Math.abs(s.vx)) * i,
      glyph: i <= 3 ? "-" : i % 2 ? "." : "'",
      alpha: (1 - i / (STAR_TRAIL + 1)) * fade * 0.8,
    });
  }
  return cells;
}

interface TrailPoint {
  x: number;
  y: number;
  age: number;
}

export interface Plane {
  x: number;
  y: number;
  vx: number;
  vy: number;
  trail: TrailPoint[];
}

const TRAIL_LIFE = 12;

export function spawnPlane(cols: number, rows: number, rand: Rand = Math.random): Plane {
  const dir = rand() < 0.5 ? 1 : -1;
  return {
    x: dir === 1 ? -4 : cols + 4,
    y: 2 + rand() * rows * 0.45,
    vx: dir * (4 + rand() * 3),
    vy: (rand() - 0.5) * 0.6,
    trail: [],
  };
}

/** Returns false once the plane has left and its contrail has faded. */
export function stepPlane(p: Plane, dt: number, cols: number): boolean {
  p.x += p.vx * dt;
  p.y += p.vy * dt;
  for (const t of p.trail) t.age += dt;
  p.trail = p.trail.filter((t) => t.age < TRAIL_LIFE);
  const last = p.trail[p.trail.length - 1];
  const gone = p.vx > 0 ? p.x > cols + 4 : p.x < -4;
  if (!gone && (!last || Math.abs(p.x - last.x) >= 1)) p.trail.push({ x: p.x, y: p.y, age: 0 });
  return !gone || p.trail.length > 0;
}

export function planeCells(p: Plane): Cell[] {
  const cells: Cell[] = p.trail.map((t) => ({
    x: t.x,
    y: t.y,
    glyph: t.age < 6 ? "-" : ".",
    alpha: 0.45 * (1 - t.age / TRAIL_LIFE),
  }));
  cells.push({ x: p.x, y: p.y, glyph: "+", alpha: 0.9 });
  return cells;
}
