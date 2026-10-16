import { birdBob, birdGlyph, birdTarget, spawnFlock, stepBirds, type Bird } from "./birds";
import {
  nextPlaneDelay,
  nextShootingStarDelay,
  planeCells,
  planeEligible,
  shootingStarCells,
  shootingStarEligible,
  spawnPlane,
  spawnShootingStar,
  stepPlane,
  stepShootingStar,
  type Cell,
  type Plane,
  type ShootingStar,
} from "./sky_events";
import {
  balloonCells,
  cloudCells,
  fogDensity,
  fireflyCells,
  moonCells,
  nextBalloonDelay,
  spawnBalloon,
  spawnCloudBank,
  spawnClouds,
  spawnFireflies,
  stepBalloon,
  stepClouds,
  type Balloon,
  type Cloud,
  type Firefly,
} from "./scenery";
import {
  auroraCells,
  auroraSwell,
  growSnow,
  nextGeeseDelay,
  rippleCells,
  settleSnow,
  snowCells,
  spawnGeese,
  spawnRipple,
  stepRipples,
  type Ripple,
} from "./weather";
import { currentScene, daylight, onScene, type Alarm, type Sky } from "./scene";

const CELL_W = 11;
const CELL_H = 18;
const FRAME_MS = 1000 / 15;
const STORE_KEY = "tocsin_backdrop";

const TINT: Record<Exclude<Alarm, "calm">, [number, number, number]> = {
  watch: [252, 211, 77],
  warning: [251, 113, 133],
};

interface Drop {
  x: number;
  y: number;
  speed: number;
  glyph: string;
  phase: number;
}

// Cheap smooth 2-D field for fog/cloud banks; no noise library needed.
function field(x: number, y: number, t: number): number {
  return (
    0.5 +
    0.25 * Math.sin(x * 0.11 + t * 0.35) +
    0.15 * Math.sin(y * 0.19 - t * 0.21 + x * 0.05) +
    0.1 * Math.sin((x + y) * 0.07 + t * 0.13)
  );
}

export class Backdrop {
  private readonly ctx: CanvasRenderingContext2D;
  private cols = 0;
  private rows = 0;
  private drops: Drop[] = [];
  private birds: Bird[] = [];
  private shooter: ShootingStar | null = null;
  private plane: Plane | null = null;
  private clouds: Cloud[] = [];
  private overcast: Cloud[] = [];
  private ripples: Ripple[] = [];
  private pile: number[] = [];
  private geese: Bird[] = [];
  private nextGeese = 0;
  private auroraForced = false;
  private flies: Firefly[] = [];
  private balloon: Balloon | null = null;
  private nextBalloon = 0;
  private nextShooter = 0;
  private nextPlane = 0;
  private flash = 0;
  private nextBolt = 0;
  private raf = 0;
  private last = 0;
  private enabled: boolean;

  constructor(private readonly canvas: HTMLCanvasElement) {
    this.ctx = canvas.getContext("2d")!;
    this.enabled = this.readPref();
    this.canvas.hidden = !this.enabled;
    onScene(() => this.seed());
    window.addEventListener("resize", () => this.resize());
    document.addEventListener("visibilitychange", () => this.sync());
    window.matchMedia("(prefers-reduced-motion: reduce)").addEventListener("change", () => this.sync());
    this.resize();
  }

  /** Dev panel hook: trigger an event now instead of waiting for the timer. */
  fire(kind: "star" | "plane" | "balloon" | "geese" | "aurora" | "snow"): void {
    if (kind === "star") this.shooter = spawnShootingStar(this.cols, this.rows);
    else if (kind === "plane") this.plane = spawnPlane(this.cols, this.rows);
    else if (kind === "balloon") this.balloon = spawnBalloon(this.cols, this.rows);
    else if (kind === "geese") this.geese = spawnGeese(this.cols, this.rows);
    else if (kind === "aurora") this.auroraForced = !this.auroraForced;
    else this.pile = new Array(this.cols).fill(2);
  }

  get isOn(): boolean {
    return this.enabled;
  }

  toggle(): boolean {
    this.enabled = !this.enabled;
    try {
      localStorage.setItem(STORE_KEY, this.enabled ? "on" : "off");
    } catch {
      // Storage unavailable; the choice just won't persist.
    }
    this.canvas.hidden = !this.enabled;
    this.sync();
    return this.enabled;
  }

  private readPref(): boolean {
    try {
      const saved = localStorage.getItem(STORE_KEY);
      if (saved) return saved === "on";
    } catch {
      // fall through to the default
    }
    // Weak devices default to off; they can still opt in with the toggle.
    return (navigator.hardwareConcurrency ?? 4) > 2;
  }

  private reduced(): boolean {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  private resize(): void {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    this.canvas.width = Math.floor(window.innerWidth * dpr);
    this.canvas.height = Math.floor(window.innerHeight * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.cols = Math.ceil(window.innerWidth / CELL_W);
    this.rows = Math.ceil(window.innerHeight / CELL_H);
    this.seed();
    this.sync();
  }

  private seed(): void {
    const { sky, alarm } = currentScene();
    const area = this.cols * this.rows;
    this.clouds = spawnClouds(this.cols, this.rows);
    this.overcast = spawnCloudBank(this.cols, this.rows);
    this.flies = spawnFireflies(this.cols, this.rows);
    const density: Record<Sky, number> = {
      clear: 0,
      cloudy: 0,
      fog: 0,
      wind: 0.012,
      snow: 0.02,
      rain: 0.035,
      storm: 0.05,
    };
    const boost = alarm === "warning" ? 1.5 : 1;
    const count = Math.floor(area * density[sky] * boost);
    this.drops = Array.from({ length: count }, () => this.drop(sky, true));
  }

  private drop(sky: Sky, anywhere: boolean): Drop {
    const x = Math.random() * this.cols;
    const y = anywhere ? Math.random() * this.rows : -1;
    const phase = Math.random() * Math.PI * 2;
    if (sky === "snow") return { x, y, speed: 2 + Math.random() * 3, glyph: "*·.+"[Math.floor(Math.random() * 4)], phase };
    if (sky === "wind") {
      return { x: anywhere ? x : -4, y: Math.random() * this.rows, speed: 18 + Math.random() * 22, glyph: "~-≈"[Math.floor(Math.random() * 3)], phase };
    }
    return { x, y, speed: 14 + Math.random() * 14, glyph: "'|¦,"[Math.floor(Math.random() * 4)], phase };
  }

  private sync(): void {
    cancelAnimationFrame(this.raf);
    this.raf = 0;
    if (!this.enabled) return;
    if (this.reduced() || document.hidden) {
      // One still frame: the scene stays visible without any motion.
      if (!document.hidden || this.reduced()) this.frame(performance.now(), true);
      return;
    }
    this.last = 0;
    this.raf = requestAnimationFrame((t) => this.loop(t));
  }

  private loop(now: number): void {
    this.raf = requestAnimationFrame((t) => this.loop(t));
    if (now - this.last < FRAME_MS) return;
    const dt = this.last ? (now - this.last) / 1000 : 0;
    this.last = now;
    this.frame(now, false, dt);
  }

  private text(glyph: string, col: number, row: number, alpha: number, rgb: [number, number, number]): void {
    this.ctx.fillStyle = `rgba(${rgb[0]},${rgb[1]},${rgb[2]},${alpha.toFixed(3)})`;
    this.ctx.fillText(glyph, col * CELL_W, row * CELL_H);
  }

  private frame(now: number, still: boolean, dt = 0): void {
    const { sky, alarm } = currentScene();
    const ctx = this.ctx;
    const t = now / 1000;
    const rgb = alarm === "calm" ? daylight.calmTint : TINT[alarm];
    const pulse = alarm === "warning" ? 0.75 + 0.25 * Math.sin(t * 2.4) : 1;
    ctx.clearRect(0, 0, window.innerWidth, window.innerHeight);
    ctx.font = `${CELL_H - 4}px "JetBrains Mono", ui-monospace, monospace`;
    ctx.textBaseline = "top";

    this.ambient(t, rgb, pulse, sky);
    this.flyBirds(t, dt, still, rgb, sky, alarm);
    this.scenery(t, dt, still, rgb, sky, alarm);
    if (!still) this.skyEvents(t, dt, rgb, sky, alarm);

    for (const d of this.drops) {
      if (!still) {
        d.y += sky === "wind" ? 0 : d.speed * dt;
        const slant = sky === "storm" ? 0.4 : 0.15;
        d.x += sky === "wind" ? d.speed * dt : sky === "snow" ? Math.sin(t + d.phase) * 2 * dt : -d.speed * slant * dt;
        if (d.y > this.rows || d.x > this.cols + 2 || d.x < -4) {
          if (d.y > this.rows) this.landed(d.x, sky);
          Object.assign(d, this.drop(sky, false));
        }
      }
      this.text(d.glyph, d.x, d.y, (sky === "snow" ? 0.8 : 0.6) * pulse, rgb);
    }

    this.ground(dt, still, rgb, sky);

    if (sky === "storm" && !still) this.lightning(t, rgb);
  }

  private landed(x: number, sky: Sky): void {
    if ((sky === "rain" || sky === "storm") && this.ripples.length < 70 && Math.random() < 0.3) {
      this.ripples.push(spawnRipple(x, this.rows));
    } else if (sky === "snow" && this.pile.length) {
      growSnow(this.pile, x);
    }
  }

  // Puddle ripples under rain and storm; snow that builds up while it falls and melts after.
  private ground(dt: number, still: boolean, rgb: [number, number, number], sky: Sky): void {
    if (this.pile.length !== this.cols) this.pile = new Array(this.cols).fill(0);
    if (!still) {
      this.ripples = sky === "rain" || sky === "storm" ? stepRipples(this.ripples, dt) : [];
      settleSnow(this.pile, dt, sky === "snow");
    }
    this.drawCells(rippleCells(this.ripples), rgb);
    this.drawCells(snowCells(this.pile, this.rows), rgb);
  }

  // Low-contrast base layer: stars for clear skies, fog banks for the rest.
  private ambient(t: number, rgb: [number, number, number], pulse: number, sky: Sky): void {
    // Cloudy and fog have their own looks (scenery clouds / ground mist); only rain and storm use the shared bank.
    if (sky === "cloudy") return;
    if (sky === "fog") {
      this.groundFog(t, rgb, pulse);
      return;
    }
    const banks = sky === "storm" || sky === "rain" ? 0.5 : 0;
    for (let r = 0; r < this.rows; r += 1) {
      for (let c = 0; c < this.cols; c += 1) {
        const n = (c * 374761393 + r * 668265263) >>> 0;
        if (banks) {
          const v = field(c, r * 1.6, t);
          if (v > 1 - banks * 0.9) this.text(v > 0.9 ? "▒" : "░", c, r, Math.min(0.5, (v - (1 - banks * 0.9)) * 0.7) * pulse, rgb);
        } else if (n % 47 === 0 && daylight.starlight > 0) {
          const twinkle = 0.5 + 0.5 * Math.sin(t * 1.5 + (n % 97));
          this.text(n % 5 === 0 ? ":" : ".", c, r, (0.25 + 0.5 * twinkle) * pulse * daylight.starlight, rgb);
        }
      }
    }
  }

  private flyBirds(t: number, dt: number, still: boolean, rgb: [number, number, number], sky: Sky, alarm: Alarm): void {
    const dayness = 1 - daylight.starlight;
    const target = birdTarget(this.cols, dayness, sky, alarm);
    if (target === 0) {
      this.birds = [];
      return;
    }
    if (!still) this.birds = stepBirds(this.birds, dt, this.cols);
    // Seed a populated sky at once; afterwards new flocks wander in from the edges.
    if (this.birds.length < target && (this.birds.length === 0 || (!still && Math.random() < dt * 0.4))) {
      this.birds.push(...spawnFlock(this.cols, this.rows, this.birds.length === 0));
    }
    const alpha = 0.85 * Math.min(1, dayness * 2);
    for (const b of this.birds) this.text(birdGlyph(b, still ? 0 : t), b.x, b.y + birdBob(b, t), alpha, rgb);
  }

  // Rare night/day extras; both wait a random while after each one finishes.
  private skyEvents(t: number, dt: number, rgb: [number, number, number], sky: Sky, alarm: Alarm): void {
    if (shootingStarEligible(daylight.starlight, sky, alarm)) {
      if (!this.nextShooter) this.nextShooter = t + nextShootingStarDelay();
      if (!this.shooter && t >= this.nextShooter) this.shooter = spawnShootingStar(this.cols, this.rows);
    } else {
      this.shooter = null;
      this.nextShooter = 0;
    }
    if (this.shooter) {
      this.drawCells(shootingStarCells(this.shooter), rgb);
      if (!stepShootingStar(this.shooter, dt)) {
        this.shooter = null;
        this.nextShooter = t + nextShootingStarDelay();
      }
    }

    if (planeEligible(daylight.starlight, sky, alarm)) {
      if (!this.nextPlane) this.nextPlane = t + nextPlaneDelay();
      if (!this.plane && t >= this.nextPlane) this.plane = spawnPlane(this.cols, this.rows);
    } else {
      this.plane = null;
      this.nextPlane = 0;
    }
    if (this.plane) {
      this.drawCells(planeCells(this.plane), rgb);
      if (!stepPlane(this.plane, dt, this.cols)) {
        this.plane = null;
        this.nextPlane = t + nextPlaneDelay();
      }
    }
  }

  // Moon and clouds are weather, so they stay up during alerts; fireflies and the balloon stand down.
  private scenery(t: number, dt: number, still: boolean, rgb: [number, number, number], sky: Sky, alarm: Alarm): void {
    if (sky !== "clear" && sky !== "cloudy") {
      this.balloon = null;
      this.nextBalloon = 0;
      this.geese = [];
      return;
    }
    const dayness = 1 - daylight.starlight;
    if (daylight.moon) this.drawCells(moonCells(daylight.moon, this.cols, this.rows, daylight.starlight), rgb);

    if (sky === "cloudy") {
      if (!still) stepClouds(this.overcast, dt, this.cols);
      for (const c of this.overcast) this.drawCells(cloudCells(c, Math.max(dayness, 0.6), 0.32), rgb);
    }

    if (sky === "clear" && dayness > 0.15) {
      if (!still) stepClouds(this.clouds, dt, this.cols);
      for (const c of this.clouds) this.drawCells(cloudCells(c, dayness), rgb);
    }

    if (alarm !== "calm") {
      this.balloon = null;
      this.nextBalloon = 0;
      this.geese = [];
      return;
    }

    if (sky === "clear") {
      const night = Math.min(Math.max((daylight.starlight - 0.9) * 10, 0), 1);
      const natural = daylight.auroraNight && daylight.season === "winter" ? auroraSwell(t) * night : 0;
      this.drawCells(auroraCells(this.cols, this.rows, t, this.auroraForced ? 1 : natural), rgb);
    }

    if (!still && (daylight.season === "spring" || daylight.season === "fall") && planeEligible(daylight.starlight, sky, alarm)) {
      if (!this.nextGeese) this.nextGeese = t + nextGeeseDelay();
      if (!this.geese.length && t >= this.nextGeese) this.geese = spawnGeese(this.cols, this.rows);
    }
    if (this.geese.length) {
      if (!still) this.geese = stepBirds(this.geese, dt, this.cols, 60);
      for (const g of this.geese) this.text(birdGlyph(g, t), g.x, g.y + birdBob(g, t), 0.85, rgb);
      if (!this.geese.length) this.nextGeese = t + nextGeeseDelay();
    }

    if (daylight.season !== "winter" && daylight.dusk > 0.05) this.drawCells(fireflyCells(this.flies, t, daylight.dusk), [200, 255, 120]);

    if (still) return;
    if (daylight.dawn > 0.3) {
      if (!this.nextBalloon) this.nextBalloon = t + nextBalloonDelay();
      if (!this.balloon && t >= this.nextBalloon) this.balloon = spawnBalloon(this.cols, this.rows);
    }
    if (this.balloon) {
      this.drawCells(balloonCells(this.balloon), rgb);
      if (!stepBalloon(this.balloon, dt, this.cols)) {
        this.balloon = null;
        this.nextBalloon = t + nextBalloonDelay();
      }
    }
  }

  private drawCells(cells: Cell[], rgb: [number, number, number]): void {
    for (const c of cells) {
      if (c.x >= -1 && c.x < this.cols && c.y >= 0 && c.y < this.rows) this.text(c.glyph, c.x, c.y, c.alpha, c.rgb ?? rgb);
    }
  }

  // Long horizontal streaks (field is stretched along x), densest at the bottom.
  private groundFog(t: number, rgb: [number, number, number], pulse: number): void {
    for (let r = 0; r < this.rows; r += 1) {
      const density = fogDensity(r, this.rows);
      for (let c = 0; c < this.cols; c += 1) {
        const v = field(c * 0.3 + t * 0.4, r * 2.6, t * 0.5);
        const cut = 1 - density * 0.85;
        if (v <= cut) continue;
        this.text(density > 0.65 && v > cut + 0.12 ? "▒" : "░", c, r, Math.min(0.45, (0.06 + 0.3 * density) * (1 + (v - cut) * 2)) * pulse, rgb);
      }
    }
  }

  private lightning(t: number, rgb: [number, number, number]): void {
    if (t > this.nextBolt) {
      this.flash = 1;
      this.nextBolt = t + 4 + Math.random() * 9;
    }
    if (this.flash <= 0) return;
    const col = Math.floor(this.cols * (0.2 + 0.6 * ((this.nextBolt * 7) % 1)));
    let c = col;
    for (let r = 0; r < this.rows * 0.7; r += 1) {
      c += Math.random() < 0.5 ? -1 : 1;
      this.text(r % 2 ? "/" : "\\", c, r, this.flash * 0.7, [255, 255, 255]);
    }
    this.ctx.fillStyle = `rgba(${rgb[0]},${rgb[1]},${rgb[2]},${(this.flash * 0.05).toFixed(3)})`;
    this.ctx.fillRect(0, 0, window.innerWidth, window.innerHeight);
    this.flash -= 0.18;
  }
}
