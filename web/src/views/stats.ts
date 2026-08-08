import type { Stats } from "../types";

export function renderStats(container: HTMLElement, stats: Stats): void {
  container.innerHTML = "";

  const divergence = document.createElement("div");
  divergence.className = "stat-tile stat-tile-primary";
  divergence.innerHTML = `
    <div class="stat-value">${(stats.divergence_rate * 100).toFixed(1)}%</div>
    <div class="stat-label">RF/API divergence rate</div>
  `;
  container.appendChild(divergence);

  for (const [state, count] of Object.entries(stats.counts)) {
    const tile = document.createElement("div");
    tile.className = "stat-tile";
    tile.innerHTML = `
      <div class="stat-value">${count}</div>
      <div class="stat-label">${state}</div>
    `;
    container.appendChild(tile);
  }
}
