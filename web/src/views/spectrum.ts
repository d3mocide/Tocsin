import type { SpectrumSnapshot } from "../types";

/**
 * Scrolling waterfall over the 48-bin snapshot `api`'s `/spectrum/{site}`
 * returns (design doc §3: the 41 unused bins are free occupancy data).
 *
 * Replaces a per-frame bar chart that rescaled to each snapshot's own
 * min/max. That made the display breathe with the noise floor and made no
 * two frames comparable -- a carrier appearing and the noise floor
 * dropping looked identical. The dB scale here is shared by every row on
 * screen and eased between redraws, so a bin getting brighter means the
 * signal actually got stronger.
 *
 * History is accumulated client-side: `sdr_rx` publishes a latest-value
 * snapshot key roughly once a second and deliberately keeps no history
 * (see its `redis_sink`), so the waterfall's depth is however long this
 * tab has been open.
 */

// Channel numbering follows design doc §3's table (k=-4 -> 162.400 ->
// WX1, ascending), which is what `sdr_rx/channels.py` publishes and what
// every other panel, Icecast mount, and decoded alert on this page is
// labelled with. It is deliberately not the NOAA/scanner numbering
// (WX1=162.550): this axis exists to line the waterfall up with *this*
// system's channels, and two numberings on one screen is how the axis
// came to read WX2 WX4 WX5 WX3 WX6 WX7 WX1 from left to right.
const NWR_CHANNEL_NAMES = new Map([
  [162_400_000, "WX1"],
  [162_425_000, "WX2"],
  [162_450_000, "WX3"],
  [162_475_000, "WX4"],
  [162_500_000, "WX5"],
  [162_525_000, "WX6"],
  [162_550_000, "WX7"],
]);

const AXIS_HEIGHT = 26;
const MAX_ROWS = 180;
// The snapshot's dB values are 20*log10 of channelizer output magnitude --
// uncalibrated, with no fixed relationship to dBm or dBFS. A hardcoded
// window (this was -110..-20 dB) therefore either clips or, as here,
// leaves every bin bunched into the top of the ramp as one flat wash.
// Ranging over the whole retained history instead keeps the scale steady
// across frames -- the property that matters, and the reason a per-frame
// min/max was wrong -- while still landing on the data actually present.
const FLOOR_PERCENTILE = 0.05;
const CEILING_PERCENTILE = 0.995;
const MIN_SPAN_DB = 12;
// Slew per redraw, so the scale drifts with the noise floor instead of
// stepping every time a transmitter keys up and re-ranges the display.
const SCALE_SMOOTHING = 0.15;

function isNwrChannel(frequencyHz: number): boolean {
  // bin_frequencies_hz carries fractional Hz (LO + (k+0.5)*25kHz); round
  // before comparing against the nominal channel centers.
  return NWR_CHANNEL_NAMES.has(Math.round(frequencyHz));
}

function percentile(sorted: number[], fraction: number): number {
  const index = Math.min(sorted.length - 1, Math.max(0, Math.round(fraction * (sorted.length - 1))));
  return sorted[index];
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
  private scale: { min: number; max: number } | null = null;

  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas;
  }

  clear(): void {
    this.rows = [];
    this.lastTimestampNs = -1;
    this.scale = null;
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

  /** The canvas is laid out at `width: 100%` but its backing store was
   * fixed at the element's 640x260 attributes, so the browser stretched a
   * 640px-wide image across whatever the column actually was -- every bin
   * edge smeared, and the channel labels along with them. Size the backing
   * store to the real box (times the device pixel ratio) and draw in CSS
   * pixels. */
  private resize(): { width: number; height: number } {
    const ratio = window.devicePixelRatio || 1;
    const rect = this.canvas.getBoundingClientRect();
    const width = Math.max(1, Math.round(rect.width));
    const height = Math.max(1, Math.round(rect.height));
    const backingWidth = Math.round(width * ratio);
    const backingHeight = Math.round(height * ratio);
    if (this.canvas.width !== backingWidth || this.canvas.height !== backingHeight) {
      this.canvas.width = backingWidth;
      this.canvas.height = backingHeight;
    }
    return { width, height };
  }

  /** dB window covering the retained history, eased toward rather than
   * snapped to, so the ramp uses its whole range without the display
   * re-scaling visibly on every keyup. */
  private displayRange(): { min: number; max: number } {
    const values: number[] = [];
    for (const row of this.rows) {
      for (const db of row.bin_power_db) if (Number.isFinite(db)) values.push(db);
    }
    if (values.length === 0) return this.scale ?? { min: -100, max: 0 };
    values.sort((a, b) => a - b);

    const floor = percentile(values, FLOOR_PERCENTILE);
    let ceiling = percentile(values, CEILING_PERCENTILE);
    if (ceiling - floor < MIN_SPAN_DB) ceiling = floor + MIN_SPAN_DB;

    if (!this.scale) {
      this.scale = { min: floor, max: ceiling };
    } else {
      this.scale = {
        min: this.scale.min + (floor - this.scale.min) * SCALE_SMOOTHING,
        max: this.scale.max + (ceiling - this.scale.max) * SCALE_SMOOTHING,
      };
    }
    return this.scale;
  }

  private draw(): void {
    const ctx = this.canvas.getContext("2d");
    if (!ctx) return;

    const { width, height } = this.resize();
    const ratio = window.devicePixelRatio || 1;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
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
    const { min, max } = this.displayRange();
    const span = Math.max(1e-6, max - min);

    // Newest at the top, scrolling downward -- the convention every SDR
    // waterfall uses, so the eye lands on "now" first. `rows` is in
    // arrival order, so the last element is the one drawn at y=0.
    this.rows.forEach((snapshot, rowIndex) => {
      const y = (this.rows.length - 1 - rowIndex) * rowHeight;
      snapshot.bin_power_db.forEach((db, binIndex) => {
        const normalized = (db - min) / span;
        ctx.fillStyle = color(normalized, isNwrChannel(snapshot.bin_frequencies_hz[binIndex]));
        ctx.fillRect(binIndex * binWidth, y, Math.ceil(binWidth), Math.ceil(rowHeight));
      });
    });

    this.drawChannelAxis(ctx, this.rows[this.rows.length - 1], width, plotHeight, binWidth, styles, min, max);
  }

  private drawChannelAxis(
    ctx: CanvasRenderingContext2D,
    snapshot: SpectrumSnapshot,
    width: number,
    plotHeight: number,
    binWidth: number,
    styles: CSSStyleDeclaration,
    minDb: number,
    maxDb: number,
  ): void {
    ctx.font = "9px system-ui, sans-serif";
    ctx.textAlign = "center";
    const labelColor = styles.getPropertyValue("--text-dim").trim() || "#8b949e";

    // The seven channels sit in seven adjacent 25 kHz bins in the middle
    // of a 1.2 MHz span, so their labels are ~binWidth apart -- too close
    // to read on one line at any realistic panel width. Alternate rows.
    let channelIndex = 0;
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
      ctx.fillText(name, x, plotHeight + (channelIndex % 2 === 0 ? 10 : 20));
      channelIndex += 1;
    });

    // The dB numbers are the current auto-range, not a constant, so they
    // have to be drawn from the values actually used for the ramp.
    ctx.textAlign = "left";
    ctx.fillStyle = labelColor;
    ctx.fillText(`${minDb.toFixed(0)} dB`, 2, plotHeight + 10);
    ctx.textAlign = "right";
    ctx.fillText(`${maxDb.toFixed(0)} dB`, width - 2, plotHeight + 10);
  }
}
