import type { SpectrumSnapshot } from "../types";

const BAR_COLOR = "#4a9eff";
const CHANNEL_BAR_COLOR = "#ff7043"; // the 7 NWR channel bins, distinguished from the 41 spectrum-only bins
const BACKGROUND_COLOR = "#0e1116";
const NWR_CHANNEL_FREQUENCIES_HZ = new Set([162_400_000, 162_425_000, 162_450_000, 162_475_000, 162_500_000, 162_525_000, 162_550_000]);

function isNwrChannel(frequencyHz: number): boolean {
  // bin_frequencies_hz carries fractional Hz (LO + (k+0.5)*25kHz); round
  // before comparing against the nominal channel centers.
  return NWR_CHANNEL_FREQUENCIES_HZ.has(Math.round(frequencyHz));
}

export function renderSpectrum(canvas: HTMLCanvasElement, snapshot: SpectrumSnapshot): void {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  const { width, height } = canvas;
  ctx.fillStyle = BACKGROUND_COLOR;
  ctx.fillRect(0, 0, width, height);

  const { bin_power_db: powers, bin_frequencies_hz: frequencies } = snapshot;
  if (powers.length === 0) return;

  const minDb = Math.min(...powers);
  const maxDb = Math.max(...powers, minDb + 1); // avoid a zero-height chart on a perfectly flat input
  const barWidth = width / powers.length;

  powers.forEach((db, i) => {
    const normalized = (db - minDb) / (maxDb - minDb);
    const barHeight = normalized * (height - 20);
    ctx.fillStyle = isNwrChannel(frequencies[i]) ? CHANNEL_BAR_COLOR : BAR_COLOR;
    ctx.fillRect(i * barWidth, height - barHeight, Math.max(1, barWidth - 1), barHeight);
  });
}
