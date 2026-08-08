import type { SpectrumSnapshot } from "../types";

/**
 * Scrolling waterfall over the 48-bin snapshot `api`'s `/spectrum/{site}`
 * returns (design doc §3: the 41 unused bins are free occupancy data).
 *
 * Replaces a per-frame bar chart that rescaled to each snapshot's own
 * min/max. That made the display breathe with the noise floor and made no
 * two frames comparable -- a carrier appearing and the noise floor
 * dropping looked identical. The dB scale here is fixed, so a bin getting
 * brighter means the signal actually got stronger.
 *
 * History is accumulated client-side: `sdr_rx` publishes a latest-value
 * snapshot key roughly once a second and deliberately keeps no history
 * (see its `redis_sink`), so the waterfall's depth is however long this
 * tab has been open.
 */

const NWR_CHANNEL_FREQUENCIES_HZ = new Set([
  162_400_000, 162_425_000, 162_450_000, 162_475_000, 162_500_000, 162_525_000, 162_550_000,
]);
const NWR_CHANNEL_NAMES = new Map([
  [162_400_000, "WX2"],
  [162_425_000, "WX4"],
  [162_450_000, "WX5"],
  [162_475_000, "WX3"],
  [162_500_000, "WX6"],
  [162_525_000, "WX7"],
  [162_550_000, "WX1"],
]);

// Fixed rather than auto-ranged; see the module docstring. Wide enough to
// cover a quiet receiver and a strong local transmitter without clipping
// either end in practice.
const MIN_DB = -110;
const MAX_DB = -20;
const AXIS_HEIGHT = 16;
const MAX_ROWS = 180;

function isNwrChannel(frequencyHz: number): boolean {
  // bin_frequencies_hz carries fractional Hz (LO + (k+0.5)*25kHz); round
  // before comparing against the nominal channel centers.
  return NWR_CHANNEL_FREQUENCIES_HZ.has(Math.round(frequencyHz));
}

/** Blue -> cyan -> yellow -> red, the conventional SDR waterfall ramp.
 * NWR channel bins get a warmer floor so the seven channels stay findable
 * against the 41 spectrum-only bins even when everything is quiet. */
function color(normalized: number, channelBin: boolean): string {
  const value = Math.max(0, Math.min(1, normalized));
  const hue = channelBin ? 20 + (1 - value) * 20 : 240 - value * 240;
  const lightness = 8 + value * 52;
  const saturation = channelBin ? 85 : 70;
  return `hsl(${hue}, ${saturation}%, ${lightness}%)`;
}

export class WaterfallView {
  private readonly canvas: HTMLCanvasElement;
  private rows: SpectrumSnapshot[] = [];
  private lastTimestampNs = -1;

  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas;
  }

  clear(): void {
    this.rows = [];
    this.lastTimestampNs = -1;
    this.draw();
  }

  push(snapshot: SpectrumSnapshot | null): void {
    if (snapshot && snapshot.bin_power_db.length > 0) {
      // `/spectrum/{site}` is polled, but sdr_rx only republishes ~1/sec,
      // so the same snapshot is routinely fetched twice. Appending it
      // again would make the waterfall scroll at the poll rate rather
      // than the data rate and stretch every feature vertically.
      if (snapshot.timestamp_ns !== this.lastTimestampNs) {
        this.lastTimestampNs = snapshot.timestamp_ns;
        this.rows.push(snapshot);
        if (this.rows.length > MAX_ROWS) this.rows.shift();
      }
    }
    this.draw();
  }

  private draw(): void {
    const ctx = this.canvas.getContext("2d");
    if (!ctx) return;

    const { width, height } = this.canvas;
    const styles = getComputedStyle(this.canvas);
    ctx.fillStyle = styles.getPropertyValue("--panel-deep").trim() || "#0e1116";
    ctx.fillRect(0, 0, width, height);

    if (this.rows.length === 0) {
      ctx.fillStyle = styles.getPropertyValue("--text-dim").trim() || "#8b949e";
      ctx.font = "13px system-ui, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("Waiting for spectrum data…", width / 2, height / 2);
      return;
    }

    const plotHeight = height - AXIS_HEIGHT;
    const binCount = this.rows[this.rows.length - 1].bin_power_db.length;
    const binWidth = width / binCount;
    const rowHeight = Math.max(1, plotHeight / MAX_ROWS);

    // Newest at the top, scrolling downward -- the convention every SDR
    // waterfall uses, so the eye lands on "now" first. `rows` is in
    // arrival order, so the last element is the one drawn at y=0.
    this.rows.forEach((snapshot, rowIndex) => {
      const y = (this.rows.length - 1 - rowIndex) * rowHeight;
      snapshot.bin_power_db.forEach((db, binIndex) => {
        const normalized = (db - MIN_DB) / (MAX_DB - MIN_DB);
        ctx.fillStyle = color(normalized, isNwrChannel(snapshot.bin_frequencies_hz[binIndex]));
        ctx.fillRect(binIndex * binWidth, y, Math.ceil(binWidth), Math.ceil(rowHeight));
      });
    });

    this.drawChannelAxis(ctx, this.rows[this.rows.length - 1], width, plotHeight, binWidth, styles);
  }

  private drawChannelAxis(
    ctx: CanvasRenderingContext2D,
    snapshot: SpectrumSnapshot,
    width: number,
    plotHeight: number,
    binWidth: number,
    styles: CSSStyleDeclaration,
  ): void {
    ctx.font = "9px system-ui, sans-serif";
    ctx.textAlign = "center";
    const labelColor = styles.getPropertyValue("--text-dim").trim() || "#8b949e";

    snapshot.bin_frequencies_hz.forEach((frequency, index) => {
      const name = NWR_CHANNEL_NAMES.get(Math.round(frequency));
      if (!name) return;
      const x = index * binWidth + binWidth / 2;
      ctx.strokeStyle = "rgba(255, 112, 67, 0.35)";
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, plotHeight);
      ctx.stroke();
      ctx.fillStyle = labelColor;
      ctx.fillText(name, x, plotHeight + 11);
    });

    ctx.textAlign = "left";
    ctx.fillStyle = labelColor;
    ctx.fillText(`${MIN_DB} dB`, 2, plotHeight + 11);
    ctx.textAlign = "right";
    ctx.fillText(`${MAX_DB} dB`, width - 2, plotHeight + 11);
  }
}
