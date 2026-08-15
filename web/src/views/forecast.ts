import { byIdOptional, el, replaceChildren } from "../dom";
import type { Store } from "../store";

export interface ForecastPeriod {
  number: number;
  name: string;
  startTime: string;
  endTime: string;
  isDaytime: boolean;
  temperature: number;
  temperatureUnit: string;
  temperatureTrend?: string | null;
  probabilityOfPrecipitation?: { unitCode: string; value: number | null } | null;
  windSpeed: string;
  windDirection: string;
  icon: string;
  shortForecast: string;
  detailedForecast: string;
}

export interface ForecastData {
  city?: string;
  state?: string;
  fetchedAt: number;
  periods: ForecastPeriod[];
}

const CACHE_KEY = "tocsin_nws_forecast_cache";
const CACHE_TTL_MS = 15 * 60 * 1000; // 15 minutes

export class ForecastView {
  private readonly container: HTMLElement;
  private readonly store: Store;
  private forecastData: ForecastData | null = null;
  private isLoading = false;
  private lastFetchedCoords: string | null = null;

  constructor(container: HTMLElement, store: Store) {
    this.container = container;
    this.store = store;
    this.loadFromStorage();
  }

  private loadFromStorage(): void {
    try {
      const raw = localStorage.getItem(CACHE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as ForecastData;
        if (Date.now() - parsed.fetchedAt < CACHE_TTL_MS) {
          this.forecastData = parsed;
        }
      }
    } catch {
      // Storage unavailable or corrupted
    }
  }

  private saveToStorage(data: ForecastData): void {
    this.forecastData = data;
    try {
      localStorage.setItem(CACHE_KEY, JSON.stringify(data));
    } catch {
      // Storage write failed
    }
  }

  async fetchForecast(lat: number, lon: number): Promise<void> {
    const coordsKey = `${lat.toFixed(4)},${lon.toFixed(4)}`;
    if (
      this.forecastData &&
      this.lastFetchedCoords === coordsKey &&
      Date.now() - this.forecastData.fetchedAt < CACHE_TTL_MS
    ) {
      return;
    }

    this.isLoading = true;
    this.lastFetchedCoords = coordsKey;

    try {
      // 1. Fetch gridpoint metadata
      const pointsRes = await fetch(`https://api.weather.gov/points/${lat},${lon}`, {
        headers: { Accept: "application/geo+json" },
      });
      if (!pointsRes.ok) throw new Error(`NWS Points API HTTP ${pointsRes.status}`);
      const pointsData = await pointsRes.json();
      const forecastUrl = pointsData.properties?.forecast;
      const city = pointsData.properties?.relativeLocation?.properties?.city;
      const state = pointsData.properties?.relativeLocation?.properties?.state;

      if (!forecastUrl) throw new Error("No forecast endpoint in NWS points response");

      // 2. Fetch period forecast
      const forecastRes = await fetch(forecastUrl, {
        headers: { Accept: "application/geo+json" },
      });
      if (!forecastRes.ok) throw new Error(`NWS Forecast API HTTP ${forecastRes.status}`);
      const forecastJson = await forecastRes.json();
      const periods: ForecastPeriod[] = forecastJson.properties?.periods ?? [];

      this.saveToStorage({
        city,
        state,
        fetchedAt: Date.now(),
        periods,
      });
    } catch (err) {
      // If we don't already have cached data, leave forecastData null
      if (!this.forecastData) {
        this.forecastData = null;
      }
    } finally {
      this.isLoading = false;
      this.render();
    }
  }

  render(): void {
    const { system } = this.store.state;
    const isOffgrid = system?.mode === "offgrid";
    const lat = system?.latitude;
    const lon = system?.longitude;

    const headerSummary = byIdOptional("forecast-header-summary");

    if (isOffgrid) {
      if (headerSummary) replaceChildren(headerSummary);
      replaceChildren(
        this.container,
        el("p", { class: "empty", text: "Offgrid mode — internet weather forecast unavailable." }),
      );
      return;
    }

    if (lat === undefined || lon === undefined || lat === null || lon === null) {
      if (headerSummary) replaceChildren(headerSummary);
      replaceChildren(
        this.container,
        el("p", {
          class: "empty",
          text: "Set TOCSIN_LATITUDE / TOCSIN_LONGITUDE in .env to display your local NWS forecast.",
        }),
      );
      return;
    }

    // Trigger fetch if not loaded or stale
    if (!this.forecastData && !this.isLoading) {
      void this.fetchForecast(lat, lon);
      replaceChildren(this.container, el("p", { class: "empty", text: "Loading local NWS forecast…" }));
      return;
    }

    if (!this.forecastData || this.forecastData.periods.length === 0) {
      if (this.isLoading) {
        replaceChildren(this.container, el("p", { class: "empty", text: "Loading local NWS forecast…" }));
      } else {
        replaceChildren(this.container, el("p", { class: "empty", text: "Local forecast temporarily unavailable." }));
      }
      return;
    }

    const { city, state, periods } = this.forecastData;
    const current = periods[0];

    // Header Summary
    if (headerSummary) {
      const locationLabel = city && state ? `${city}, ${state}` : `${lat.toFixed(2)}°, ${lon.toFixed(2)}°`;
      replaceChildren(
        headerSummary,
        el("span", {
          class: "badge badge-status-synced",
          text: `${locationLabel} · ${current.temperature}°${current.temperatureUnit}`,
        }),
      );
    }

    const emoji = weatherEmoji(current.shortForecast, current.isDaytime);
    const precipVal = current.probabilityOfPrecipitation?.value;

    // Headline Hero Banner
    const heroBanner = el(
      "div",
      { class: `forecast-hero${current.isDaytime ? " is-day" : " is-night"}` },
      el(
        "div",
        { class: "forecast-hero-left" },
        el("span", { class: "forecast-hero-emoji", text: emoji, attrs: { "aria-hidden": "true" } }),
        el(
          "div",
          { class: "forecast-hero-temps" },
          el("div", { class: "forecast-hero-val", text: `${current.temperature}°${current.temperatureUnit}` }),
          el("div", { class: "forecast-hero-desc", text: current.shortForecast }),
        ),
      ),
      el(
        "div",
        { class: "forecast-hero-right" },
        el("div", { class: "forecast-hero-stat", text: `💨 ${current.windDirection} ${current.windSpeed}` }),
        precipVal !== null && precipVal !== undefined && precipVal > 0
          ? el("div", { class: "forecast-hero-stat", text: `💧 ${precipVal}% precip` })
          : null,
      ),
    );

    // Multi-Period Strip (next 4 upcoming periods)
    const upcomingPeriods = periods.slice(1, 5);
    const periodCards = upcomingPeriods.map((p) => {
      const pEmoji = weatherEmoji(p.shortForecast, p.isDaytime);
      return el(
        "div",
        { class: `forecast-period-card${p.isDaytime ? " day-card" : " night-card"}` },
        el("div", { class: "forecast-period-name", text: p.name }),
        el("div", { class: "forecast-period-emoji", text: pEmoji }),
        el("div", { class: "forecast-period-temp", text: `${p.temperature}°${p.temperatureUnit}` }),
        el("div", { class: "forecast-period-desc", text: p.shortForecast, title: p.detailedForecast }),
      );
    });

    const strip = el("div", { class: "forecast-period-strip" }, ...periodCards);

    // Detailed Synopsis Drawer
    const synopsis = el(
      "div",
      { class: "forecast-synopsis" },
      el("span", { class: "forecast-synopsis-label", text: `${current.name.toUpperCase()}: ` }),
      el("span", { class: "forecast-synopsis-text", text: current.detailedForecast }),
    );

    replaceChildren(
      this.container,
      el("div", { class: "forecast-container" }, heroBanner, strip, synopsis),
    );
  }
}

function weatherEmoji(shortForecast: string, isDaytime: boolean): string {
  const s = shortForecast.toLowerCase();
  if (s.includes("thunder") || s.includes("storm") || s.includes("severe")) return "⛈️";
  if (s.includes("snow") || s.includes("blizzard") || s.includes("flurr") || s.includes("sleet") || s.includes("ice"))
    return "❄️";
  if (s.includes("heavy rain") || s.includes("downpour")) return "🌧️";
  if (s.includes("rain") || s.includes("shower") || s.includes("drizzle")) return "🌦️";
  if (s.includes("fog") || s.includes("haze") || s.includes("smoke") || s.includes("dust")) return "🌫️";
  if (s.includes("wind") || s.includes("breez") || s.includes("gust")) return "💨";
  if (s.includes("cloud") || s.includes("overcast")) {
    if (s.includes("partly") || s.includes("mostly")) return isDaytime ? "🌤️" : "☁️";
    return "☁️";
  }
  if (s.includes("sun") || s.includes("clear") || s.includes("fair")) return isDaytime ? "☀️" : "🌙";
  return isDaytime ? "🌤️" : "🌙";
}
