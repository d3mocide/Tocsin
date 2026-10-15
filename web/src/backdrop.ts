import { currentScene, onScene, type Alarm, type Sky } from "./scene";

const CELL_W = 11;
const CELL_H = 18;
const FRAME_MS = 1000 / 15;
const STORE_KEY = "tocsin_backdrop";

const TINT: Record<Alarm, [number, number, number]> = {
  calm: [103, 232, 249],
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
    const rgb = TINT[alarm];
    const pulse = alarm === "warning" ? 0.75 + 0.25 * Math.sin(t * 2.4) : 1;
    ctx.clearRect(0, 0, window.innerWidth, window.innerHeight);
    ctx.font = `${CELL_H - 4}px "JetBrains Mono", ui-monospace, monospace`;
    ctx.textBaseline = "top";

    this.ambient(t, rgb, pulse, sky);

    for (const d of this.drops) {
      if (!still) {
        d.y += sky === "wind" ? 0 : d.speed * dt;
        d.x += sky === "wind" ? d.speed * dt : sky === "snow" ? Math.sin(t + d.phase) * 2 * dt : -d.speed * 0.15 * dt;
        if (d.y > this.rows || d.x > this.cols + 2 || d.x < -4) Object.assign(d, this.drop(sky, false));
      }
      this.text(d.glyph, d.x, d.y, (sky === "snow" ? 0.8 : 0.6) * pulse, rgb);
    }

    if (sky === "storm" && !still) this.lightning(t, rgb);
  }

  // Low-contrast base layer: stars for clear skies, fog banks for the rest.
  private ambient(t: number, rgb: [number, number, number], pulse: number, sky: Sky): void {
    const banks = sky === "fog" ? 0.34 : sky === "cloudy" || sky === "storm" || sky === "rain" ? 0.5 : 0;
    for (let r = 0; r < this.rows; r += 1) {
      for (let c = 0; c < this.cols; c += 1) {
        const n = (c * 374761393 + r * 668265263) >>> 0;
        if (banks) {
          const v = field(c, r * 1.6, t);
          if (v > 1 - banks * 0.9) this.text(v > 0.9 ? "▒" : "░", c, r, Math.min(0.5, (v - (1 - banks * 0.9)) * 0.7) * pulse, rgb);
        } else if (n % 47 === 0) {
          const twinkle = 0.5 + 0.5 * Math.sin(t * 1.5 + (n % 97));
          this.text(n % 5 === 0 ? ":" : ".", c, r, (0.25 + 0.5 * twinkle) * pulse, rgb);
        }
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
