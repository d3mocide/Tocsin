import type { HealthSample } from "../types";

export function renderHealthTable(tbody: HTMLTableSectionElement, samples: HealthSample[]): void {
  if (samples.length === 0) {
    tbody.innerHTML = '<tr><td colspan="4" class="empty">No health samples yet.</td></tr>';
    return;
  }

  const sorted = [...samples].sort((a, b) => a.site.localeCompare(b.site) || a.channel.localeCompare(b.channel));

  tbody.innerHTML = "";
  for (const sample of sorted) {
    const row = document.createElement("tr");
    row.className = sample.dead ? "row-dead" : "row-alive";

    const site = document.createElement("td");
    site.textContent = sample.site;

    const channel = document.createElement("td");
    channel.textContent = sample.channel;

    const rms = document.createElement("td");
    rms.textContent = sample.rms.toExponential(2);

    const status = document.createElement("td");
    status.className = sample.dead ? "badge badge-dead" : "badge badge-alive";
    // Flat carrier > 30s means the RF path is dead (design doc §3) --
    // this is the primary liveness signal for the whole SDR path, so it
    // gets the loudest treatment on the page, not a quiet number.
    status.textContent = sample.dead ? "DEAD" : "alive";

    row.append(site, channel, rms, status);
    tbody.appendChild(row);
  }
}
