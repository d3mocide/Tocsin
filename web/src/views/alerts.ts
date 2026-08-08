import type { Alert } from "../types";

const MAX_RENDERED_ALERTS = 100;

function formatTimestamp(iso: string): string {
  return new Date(iso).toLocaleString();
}

function stateClass(state: Alert["state"]): string {
  return `badge badge-${state.toLowerCase()}`;
}

function alertToListItem(alert: Alert): HTMLLIElement {
  const item = document.createElement("li");
  item.className = "alert-item";
  item.dataset.alertId = alert.id;

  const badge = document.createElement("span");
  badge.className = stateClass(alert.state);
  badge.textContent = alert.state;

  const title = document.createElement("span");
  title.className = "alert-title";
  title.textContent = alert.event_name;

  const meta = document.createElement("span");
  meta.className = "alert-meta";
  meta.textContent = `${alert.fips_codes.join(", ")} · ${formatTimestamp(alert.last_updated)} · confidence ${alert.confidence.toFixed(2)}`;

  item.append(badge, title, meta);
  return item;
}

export class AlertFeedView {
  private readonly container: HTMLUListElement;
  private renderedIds = new Set<string>();

  constructor(container: HTMLUListElement) {
    this.container = container;
  }

  setInitial(alerts: Alert[]): void {
    this.container.innerHTML = "";
    this.renderedIds.clear();
    if (alerts.length === 0) {
      this.container.innerHTML = '<li class="empty">No alerts yet.</li>';
      return;
    }
    for (const alert of alerts) {
      this.container.appendChild(alertToListItem(alert));
      this.renderedIds.add(alert.id);
    }
  }

  /** Handles both a brand-new alert and a re-published state transition
   * (e.g. RF_ONLY -> CONFIRMED) for an id already on screen -- fusion
   * republishes the same alert id on every transition, not just once. */
  upsert(alert: Alert): void {
    const existing = this.container.querySelector<HTMLLIElement>(`[data-alert-id="${CSS.escape(alert.id)}"]`);
    const rendered = alertToListItem(alert);

    if (existing) {
      existing.replaceWith(rendered);
      return;
    }

    this.container.querySelector(".empty")?.remove();
    this.container.prepend(rendered);
    this.renderedIds.add(alert.id);

    while (this.container.children.length > MAX_RENDERED_ALERTS) {
      this.container.lastElementChild?.remove();
    }
  }
}
