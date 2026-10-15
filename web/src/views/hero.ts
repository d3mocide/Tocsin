import { el, replaceChildren } from "../dom";
import { expiresAt, isActive, tierOf } from "../format";
import { getWeatherNow } from "../scene";
import type { Store } from "../store";

function chip(label: string, value: string, tone = ""): HTMLElement {
  return el("div", { class: `hero-chip ${tone}`.trim() }, el("span", { class: "hero-chip-label", text: label }), el("span", { class: "hero-chip-value", text: value }));
}

export function renderHero(container: HTMLElement, store: Store): void {
  const { alerts, reference, health, stats } = store.state;

  const active = Array.from(alerts.values()).filter((alert) => isActive(alert));
  const rank = (tier: string | null) => (tier === "A" ? 0 : tier === "B" ? 1 : 2);
  active.sort((a, b) => rank(tierOf(a, reference)) - rank(tierOf(b, reference)));
  const top = active[0];
  const topTier = top ? tierOf(top, reference) : null;
  const level = !top ? "calm" : topTier === "A" ? "warning" : topTier === "B" ? "watch" : "notice";
  container.className = `hero hero-${level}`;

  const wx = getWeatherNow();
  const weather = wx
    ? el("div", { class: "hero-wx" }, el("div", { class: "hero-temp", text: `${wx.temp}\u00b0${wx.unit}` }), el("div", { class: "hero-wx-text" }, el("span", { text: wx.short }), el("span", { class: "hero-dim", text: [wx.place, wx.wind].filter(Boolean).join(" \u00b7 ") })))
    : el("div", { class: "hero-wx" }, el("div", { class: "hero-wx-text" }, el("span", { text: "Weather" }), el("span", { class: "hero-dim", text: "forecast unavailable" })));

  let status: HTMLElement;
  if (!top) {
    status = el("div", { class: "hero-status" }, el("div", { class: "hero-eyebrow", text: "Status" }), el("div", { class: "hero-headline", text: "ALL CLEAR" }), el("div", { class: "hero-dim", text: "No active alerts in your area" }));
  } else {
    const ends = expiresAt(top);
    const more = active.length > 1 ? ` \u00b7 +${active.length - 1} more active` : "";
    status = el("div", { class: "hero-status" }, el("div", { class: "hero-eyebrow", text: `${topTier ? `Tier ${topTier}` : "Active"} alert` }), el("div", { class: "hero-headline", text: top.event_name.toUpperCase() }), el("div", { class: "hero-dim", text: `${ends ? `until ${ends.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}` : "in effect"}${more}` }));
  }

  const channels = Array.from(health.values());
  const alive = channels.filter((sample) => !sample.dead).length;
  const chips = el(
    "div",
    { class: "hero-chips" },
    chip("RF channels", channels.length ? `${alive}/${channels.length}` : "\u2014", channels.length && alive < channels.length ? "warn" : ""),
    chip("Active alerts", String(active.length)),
    chip("Dispatched", stats ? String(stats.dispatch.sent) : "\u2014"),
  );

  replaceChildren(container, weather, status, chips);
}
