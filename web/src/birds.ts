import type { Alarm, Sky } from "./scene";

export interface Bird {
  x: number;
  y: number;
  speed: number;
  dir: 1 | -1;
  phase: number;
  near: boolean;
}

/** Birds only fly in fair weather, in daylight, and stay out of the way of an alert. */
export function birdTarget(cols: number, dayness: number, sky: Sky, alarm: Alarm): number {
  if (alarm !== "calm" || (sky !== "clear" && sky !== "cloudy") || dayness < 0.1) return 0;
  return Math.round((cols / 14) * dayness);
}

export function spawnFlock(cols: number, rows: number, anywhere: boolean, rand: () => number = Math.random): Bird[] {
  const dir = rand() < 0.5 ? 1 : -1;
  const near = rand() < 0.3;
  const size = 1 + Math.floor(rand() * 4);
  const speed = near ? 5 + rand() * 3 : 2.5 + rand() * 2;
  const lead = anywhere ? rand() * cols : dir === 1 ? -4 : cols + 4;
  const y = 1 + rand() * rows * 0.55;
  return Array.from({ length: size }, (_, i) => ({
    x: lead - dir * i * (near ? 5 : 3),
    y: y + (i % 2 ? 1 : 0) * 0.6 + (rand() - 0.5) * 0.8,
    speed,
    dir,
    phase: rand() * Math.PI * 2,
    near,
  }));
}

export function stepBirds(birds: Bird[], dt: number, cols: number): Bird[] {
  for (const b of birds) b.x += b.dir * b.speed * dt;
  return birds.filter((b) => b.x > -12 && b.x < cols + 12);
}

export function birdGlyph(b: Bird, t: number): string {
  const up = Math.sin(t * (b.near ? 5 : 7) + b.phase) > 0;
  if (b.near) return up ? "\\v/" : "-v-";
  return up ? "v" : "-";
}

/** Gentle vertical bob in rows. */
export function birdBob(b: Bird, t: number): number {
  return Math.sin(t * 1.3 + b.phase) * 0.35;
}
