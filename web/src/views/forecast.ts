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

    const heroSvg = weatherSvgIcon(current.shortForecast, current.isDaytime, 36);
    const precipVal = current.probabilityOfPrecipitation?.value;

    // Headline Hero Banner
    const heroBanner = el(
      "div",
      { class: `forecast-hero${current.isDaytime ? " is-day" : " is-night"}` },
      el(
        "div",
        { class: "forecast-hero-left" },
        el("div", { class: "forecast-hero-icon" }, heroSvg),
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
        el(
          "div",
          { class: "forecast-hero-stat" },
          windStatSvg(),
          el("span", { text: `${current.windDirection} ${current.windSpeed}` }),
        ),
        precipVal !== null && precipVal !== undefined && precipVal > 0
          ? el(
              "div",
              { class: "forecast-hero-stat" },
              dropletStatSvg(),
              el("span", { text: `${precipVal}% precip` }),
            )
          : null,
      ),
    );

    // Multi-Period Strip (next 4 upcoming periods) with equal fixed width columns
    const upcomingPeriods = periods.slice(1, 5);
    const periodCards = upcomingPeriods.map((p) => {
      const pSvg = weatherSvgIcon(p.shortForecast, p.isDaytime, 20);
      return el(
        "div",
        { class: `forecast-period-card${p.isDaytime ? " day-card" : " night-card"}` },
        el("div", { class: "forecast-period-name", text: p.name, title: p.name }),
        el("div", { class: "forecast-period-icon" }, pSvg),
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

function createSvg(innerSvg: string, className: string, size = 24): SVGElement {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", String(size));
  svg.setAttribute("height", String(size));
  svg.setAttribute("class", `forecast-svg ${className}`);
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "2");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  svg.innerHTML = innerSvg;
  return svg;
}

function windStatSvg(): SVGElement {
  return createSvg(
    `<path d="M17.7 7.7A2.5 2.5 0 1 1 20 10H2"/><path d="M19.7 13.7A2.5 2.5 0 1 0 18 18H2"/><path d="M15.7 19.7A2.5 2.5 0 1 0 14 22H2"/>`,
    "forecast-stat-icon",
    14,
  );
}

function dropletStatSvg(): SVGElement {
  return createSvg(
    `<path d="M12 2.69l5.66 5.66a8 8 0 1 1-11.31 0z" stroke="#38bdf8" fill="#38bdf8" fill-opacity="0.35"/>`,
    "forecast-stat-icon",
    14,
  );
}

function weatherSvgIcon(shortForecast: string, isDaytime: boolean, size = 24): SVGElement {
  const s = shortForecast.toLowerCase();

  // Thunderstorm / Severe
  if (s.includes("thunder") || s.includes("storm") || s.includes("severe")) {
    return createSvg(
      `<path d="M6 16.326A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 .5 8.973"/><path d="m13 12-3 5h4l-3 5" stroke="#f59e0b" fill="#f59e0b" fill-opacity="0.25"/>`,
      "icon-thunderstorm",
      size,
    );
  }
  // Snow / Ice
  if (s.includes("snow") || s.includes("blizzard") || s.includes("flurr") || s.includes("sleet") || s.includes("ice")) {
    return createSvg(
      `<line x1="2" x2="22" y1="12" y2="12"/><line x1="12" x2="12" y1="2" y2="22"/><path d="m20 16-4-4 4-4"/><path d="m4 8 4 4-4 4"/><path d="m16 4-4 4-4-4"/><path d="m8 20 4-4 4 4"/>`,
      "icon-snow",
      size,
    );
  }
  // Rain / Showers
  if (s.includes("heavy rain") || s.includes("downpour") || s.includes("rain") || s.includes("shower") || s.includes("drizzle")) {
    return createSvg(
      `<path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242"/><path d="M16 14v6" stroke="#38bdf8"/><path d="M8 14v6" stroke="#38bdf8"/><path d="M12 16v6" stroke="#38bdf8"/>`,
      "icon-rain",
      size,
    );
  }
  // Smoke / Fog / Haze / Dust
  if (s.includes("smoke") || s.includes("fog") || s.includes("haze") || s.includes("dust")) {
    return createSvg(
      `<path d="M4 10h16" stroke="#94a3b8"/><path d="M2 14h20" stroke="#94a3b8"/><path d="M6 18h12" stroke="#94a3b8"/><circle cx="12" cy="5" r="2.5" stroke="#f59e0b" stroke-dasharray="2 2"/>`,
      "icon-smoke",
      size,
    );
  }
  // Wind / Breeze
  if (s.includes("wind") || s.includes("breez") || s.includes("gust")) {
    return createSvg(
      `<path d="M17.7 7.7A2.5 2.5 0 1 1 20 10H2"/><path d="M19.7 13.7A2.5 2.5 0 1 0 18 18H2"/><path d="M15.7 19.7A2.5 2.5 0 1 0 14 22H2"/>`,
      "icon-wind",
      size,
    );
  }
  // Partly Cloudy / Mostly Sunny / Mostly Cloudy
  if (s.includes("partly") || s.includes("mostly")) {
    if (isDaytime) {
      return createSvg(
        `<path d="M12 2v2" stroke="#e3b341"/><path d="m4.93 4.93 1.41 1.41" stroke="#e3b341"/><path d="M20 12h2" stroke="#e3b341"/><path d="m19.07 4.93-1.41 1.41" stroke="#e3b341"/><path d="M15.5 8.5a4 4 0 0 0-4-3.5 4 4 0 0 0-3.5 2.1" stroke="#e3b341"/><path d="M17.5 19H9a5 5 0 0 1-1-9.9 6 6 0 0 1 11.5 2.9A4.5 4.5 0 0 1 17.5 19Z"/>`,
        "icon-partly-cloudy-day",
        size,
      );
    }
    return createSvg(
      `<path d="M10.1 2.18a7 7 0 0 0 9.72 9.72" stroke="#a5b4fc"/><path d="M17.5 19H9a5 5 0 0 1-1-9.9 6 6 0 0 1 11.5 2.9A4.5 4.5 0 0 1 17.5 19Z"/>`,
      "icon-partly-cloudy-night",
      size,
    );
  }
  // Cloudy / Overcast
  if (s.includes("cloud") || s.includes("overcast")) {
    return createSvg(
      `<path d="M17.5 19H9a5 5 0 0 1-1-9.9 6 6 0 0 1 11.5 2.9A4.5 4.5 0 0 1 17.5 19Z"/>`,
      "icon-cloudy",
      size,
    );
  }
  // Clear / Sunny
  if (isDaytime) {
    return createSvg(
      `<circle cx="12" cy="12" r="4" stroke="#e3b341" fill="#e3b341" fill-opacity="0.25"/><path d="M12 2v2" stroke="#e3b341"/><path d="M12 20v2" stroke="#e3b341"/><path d="m4.93 4.93 1.41 1.41" stroke="#e3b341"/><path d="m17.66 17.66 1.41 1.41" stroke="#e3b341"/><path d="M2 12h2" stroke="#e3b341"/><path d="M20 12h2" stroke="#e3b341"/><path d="m6.34 17.66-1.41 1.41" stroke="#e3b341"/><path d="m19.07 4.93-1.41 1.41" stroke="#e3b341"/>`,
      "icon-sun",
      size,
    );
  }
  return createSvg(
    `<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" stroke="#a5b4fc" fill="#a5b4fc" fill-opacity="0.2"/>`,
    "icon-moon",
    size,
  );
}
