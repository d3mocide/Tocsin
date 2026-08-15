import { el, replaceChildren } from "../dom";
import type { Store } from "../store";

export interface HourlyPeriod {
  number: number;
  name: string;
  startTime: string;
  isDaytime: boolean;
  temperature: number;
  temperatureUnit: string;
  probabilityOfPrecipitation?: { unitCode: string; value: number | null } | null;
  relativeHumidity?: { unitCode: string; value: number | null } | null;
  dewpoint?: { unitCode: string; value: number | null } | null;
  windSpeed: string;
  windDirection: string;
  shortForecast: string;
}

export interface ExtendedPeriod {
  number: number;
  name: string;
  isDaytime: boolean;
  temperature: number;
  temperatureUnit: string;
  probabilityOfPrecipitation?: { unitCode: string; value: number | null } | null;
  windSpeed: string;
  windDirection: string;
  shortForecast: string;
  detailedForecast: string;
}

export interface MetarObservation {
  stationId: string;
  stationName: string;
  timestamp: string;
  temperatureC: number | null;
  temperatureF: number | null;
  dewpointF: number | null;
  relativeHumidity: number | null;
  windSpeedMph: number | null;
  windGustMph: number | null;
  windDirectionDeg: number | null;
  windDirectionCard: string | null;
  barometricPressureInHg: number | null;
  seaLevelPressureMb: number | null;
  visibilityMiles: number | null;
  textDescription: string | null;
}

export interface AfdProduct {
  issuedTime: string;
  wfo: string;
  text: string;
  sections: { title: string; body: string }[];
}

export interface WeatherDashboardData {
  city?: string;
  state?: string;
  wfo?: string;
  gridX?: number;
  gridY?: number;
  fetchedAt: number;
  stations: { id: string; name: string }[];
  selectedStationId?: string;
  currentObservation?: MetarObservation | null;
  hourly: HourlyPeriod[];
  extended: ExtendedPeriod[];
  afd?: AfdProduct | null;
}

const CACHE_KEY = "tocsin_weather_dashboard_cache";
const CACHE_TTL_MS = 15 * 60 * 1000;

export class WeatherDashboardView {
  private readonly container: HTMLElement;
  private readonly store: Store;
  private data: WeatherDashboardData | null = null;
  private isLoading = false;
  private activeAfdSection = 0;

  constructor(container: HTMLElement, store: Store) {
    this.container = container;
    this.store = store;
    this.loadFromStorage();
  }

  private loadFromStorage(): void {
    try {
      const raw = localStorage.getItem(CACHE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as WeatherDashboardData;
        if (Date.now() - parsed.fetchedAt < CACHE_TTL_MS) {
          this.data = parsed;
        }
      }
    } catch {
      // Storage load failed
    }
  }

  private saveToStorage(data: WeatherDashboardData): void {
    this.data = data;
    try {
      localStorage.setItem(CACHE_KEY, JSON.stringify(data));
    } catch {
      // Storage save failed
    }
  }

  async fetchWeatherDashboard(lat: number, lon: number, force = false): Promise<void> {
    if (this.data && !force && Date.now() - this.data.fetchedAt < CACHE_TTL_MS) {
      return;
    }

    this.isLoading = true;
    try {
      // 1. Gridpoint metadata
      const pointsRes = await fetch(`https://api.weather.gov/points/${lat},${lon}`, {
        headers: { Accept: "application/geo+json" },
      });
      if (!pointsRes.ok) throw new Error(`Points API HTTP ${pointsRes.status}`);
      const pointsJson = await pointsRes.json();
      const props = pointsJson.properties ?? {};
      const wfo = props.cwa;
      const gridX = props.gridX;
      const gridY = props.gridY;
      const city = props.relativeLocation?.properties?.city;
      const state = props.relativeLocation?.properties?.state;
      const stationsUrl = props.observationStations;
      const hourlyUrl = props.forecastHourly;
      const forecastUrl = props.forecast;

      // 2. Parallel fetch hourly, extended, stations list, and AFD
      const [hourlyRes, extendedRes, stationsRes, afdRes] = await Promise.allSettled([
        hourlyUrl ? fetch(hourlyUrl, { headers: { Accept: "application/geo+json" } }) : Promise.reject(),
        forecastUrl ? fetch(forecastUrl, { headers: { Accept: "application/geo+json" } }) : Promise.reject(),
        stationsUrl ? fetch(stationsUrl, { headers: { Accept: "application/geo+json" } }) : Promise.reject(),
        wfo ? fetch(`https://api.weather.gov/products/types/AFD/locations/${wfo}`, { headers: { Accept: "application/json" } }) : Promise.reject(),
      ]);

      const hourly: HourlyPeriod[] =
        hourlyRes.status === "fulfilled" && hourlyRes.value.ok
          ? (await hourlyRes.value.json()).properties?.periods ?? []
          : [];

      const extended: ExtendedPeriod[] =
        extendedRes.status === "fulfilled" && extendedRes.value.ok
          ? (await extendedRes.value.json()).properties?.periods ?? []
          : [];

      const stationsList: { id: string; name: string }[] = [];
      if (stationsRes.status === "fulfilled" && stationsRes.value.ok) {
        const stationsJson = await stationsRes.value.json();
        const features = stationsJson.features ?? [];
        for (const f of features.slice(0, 8)) {
          const sProps = f.properties ?? {};
          if (sProps.stationIdentifier) {
            stationsList.push({
              id: sProps.stationIdentifier,
              name: sProps.name || sProps.stationIdentifier,
            });
          }
        }
      }

      // 3. Fetch latest METAR observation for primary station
      const primaryStation = stationsList[0]?.id;
      let observation: MetarObservation | null = null;
      if (primaryStation) {
        try {
          const obsRes = await fetch(`https://api.weather.gov/stations/${primaryStation}/observations/latest`, {
            headers: { Accept: "application/geo+json" },
          });
          if (obsRes.ok) {
            const obsJson = await obsRes.json();
            observation = parseObservation(primaryStation, stationsList[0].name, obsJson.properties ?? {});
          }
        } catch {
          // Observation fetch failed
        }
      }

      // 4. Parse Area Forecast Discussion (AFD)
      let afdProduct: AfdProduct | null = null;
      if (afdRes.status === "fulfilled" && afdRes.value.ok) {
        const afdListJson = await afdRes.value.json();
        const latestAfd = afdListJson["@graph"]?.[0];
        if (latestAfd?.id) {
          try {
            const fullAfdRes = await fetch(latestAfd.id, { headers: { Accept: "application/json" } });
            if (fullAfdRes.ok) {
              const fullAfdJson = await fullAfdRes.json();
              afdProduct = parseAfd(wfo, fullAfdJson.issuanceTime, fullAfdJson.productText ?? "");
            }
          } catch {
            // Full AFD fetch failed
          }
        }
      }

      this.saveToStorage({
        city,
        state,
        wfo,
        gridX,
        gridY,
        fetchedAt: Date.now(),
        stations: stationsList,
        selectedStationId: primaryStation,
        currentObservation: observation,
        hourly: hourly.slice(0, 36),
        extended: extended.slice(0, 14),
        afd: afdProduct,
      });
    } catch {
      // Fetch error handled gracefully
    } finally {
      this.isLoading = false;
      this.render();
    }
  }

  async selectStation(stationId: string): Promise<void> {
    if (!this.data) return;
    this.data.selectedStationId = stationId;
    const stationObj = this.data.stations.find((s) => s.id === stationId);
    const stationName = stationObj?.name || stationId;

    try {
      const res = await fetch(`https://api.weather.gov/stations/${stationId}/observations/latest`, {
        headers: { Accept: "application/geo+json" },
      });
      if (res.ok) {
        const obsJson = await res.json();
        this.data.currentObservation = parseObservation(stationId, stationName, obsJson.properties ?? {});
        this.saveToStorage(this.data);
        this.render();
      }
    } catch {
      // Station switch error
    }
  }

  render(): void {
    const { system } = this.store.state;
    const isOffgrid = system?.mode === "offgrid";
    const lat = system?.latitude;
    const lon = system?.longitude;

    if (isOffgrid) {
      replaceChildren(
        this.container,
        el(
          "div",
          { class: "weather-dash-offgrid panel" },
          el("h3", { text: "Offgrid Mode — Internet Weather Feed Unavailable" }),
          el("p", {
            class: "empty",
            text: "Tocsin is operating in autonomous offgrid mode with zero external network connectivity. Routine NWR voice broadcasts, SAME emergency decoding, and local SDR spectrum feeds remain 100% active.",
          }),
        ),
      );
      return;
    }

    if (lat === undefined || lon === undefined || lat === null || lon === null) {
      replaceChildren(
        this.container,
        el(
          "div",
          { class: "weather-dash-offgrid panel" },
          el("h3", { text: "Coordinates Required" }),
          el("p", {
            class: "empty",
            text: "Set TOCSIN_LATITUDE and TOCSIN_LONGITUDE in .env to activate high-resolution local weather forecasting.",
          }),
        ),
      );
      return;
    }

    if (!this.data && !this.isLoading) {
      void this.fetchWeatherDashboard(lat, lon);
      replaceChildren(this.container, el("p", { class: "empty", text: "Loading meteorological telemetry…" }));
      return;
    }

    if (!this.data) {
      replaceChildren(this.container, el("p", { class: "empty", text: "Loading meteorological telemetry…" }));
      return;
    }

    const { city, state, wfo, currentObservation, hourly, extended, afd, stations, selectedStationId } = this.data;

    // 1. Header Toolbar
    const refreshBtn = el("button", { class: "btn-secondary", text: "Refresh Data", attrs: { type: "button" } });
    refreshBtn.addEventListener("click", () => {
      void this.fetchWeatherDashboard(lat, lon, true);
    });

    const header = el(
      "div",
      { class: "weather-dash-header" },
      el(
        "div",
        { class: "weather-dash-title-group" },
        el("h2", { class: "weather-dash-title", text: `${city || "Local"}, ${state || "OR"} Weather Center` }),
        el("div", { class: "weather-dash-subtitle", text: `NWS WFO ${wfo || "PQR"} · Updated ${new Date(this.data.fetchedAt).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}` }),
      ),
      el("div", { class: "weather-dash-actions" }, refreshBtn),
    );

    // 2. METAR Surface Observation Hero
    const metarHero = this.renderMetarHero(currentObservation, stations, selectedStationId);

    // 3. Hourly Forecast Horizontal Timeline
    const hourlySection = this.renderHourlyTimeline(hourly);

    // 4. Fire Weather & Atmospheric Danger Risk Card
    const fireRiskCard = this.renderFireRisk(currentObservation, hourly);

    // 5. 7-Day Extended Outlook Matrix
    const extendedSection = this.renderExtendedMatrix(extended);

    // 6. Area Forecast Discussion (AFD)
    const afdSection = this.renderAfdSection(afd);

    const mainGrid = el(
      "div",
      { class: "weather-dash-grid" },
      el("div", { class: "weather-dash-col-left" }, metarHero, fireRiskCard, afdSection),
      el("div", { class: "weather-dash-col-right" }, hourlySection, extendedSection),
    );

    replaceChildren(this.container, header, mainGrid);
  }

  private renderMetarHero(
    obs: MetarObservation | null | undefined,
    stations: { id: string; name: string }[],
    selectedId?: string,
  ): HTMLElement {
    const card = el("section", { class: "panel weather-metar-card" });
    const select = el("select", { class: "filter-select", attrs: { "aria-label": "Observation station" } }) as HTMLSelectElement;

    for (const s of stations) {
      const opt = el("option", { text: `${s.id} — ${s.name}`, attrs: { value: s.id } }) as HTMLOptionElement;
      if (s.id === selectedId) opt.selected = true;
      select.appendChild(opt);
    }

    select.addEventListener("change", () => {
      void this.selectStation(select.value);
    });

    const head = el(
      "div",
      { class: "panel-head" },
      el("h3", { text: "Live Surface Observations (METAR)" }),
      select,
    );

    if (!obs) {
      card.append(head, el("p", { class: "empty", text: "Surface observations loading…" }));
      return card;
    }

    const tempF = obs.temperatureF !== null ? `${Math.round(obs.temperatureF)}°F` : "--";
    const dewF = obs.dewpointF !== null ? `${Math.round(obs.dewpointF)}°F` : "--";
    const rh = obs.relativeHumidity !== null ? `${Math.round(obs.relativeHumidity)}%` : "--";
    const wind = obs.windSpeedMph !== null ? `${obs.windDirectionCard || ""} ${Math.round(obs.windSpeedMph)} mph` : "--";
    const gust = obs.windGustMph ? ` (gusts ${Math.round(obs.windGustMph)} mph)` : "";
    const pressure = obs.barometricPressureInHg !== null ? `${obs.barometricPressureInHg.toFixed(2)} inHg` : "--";
    const vis = obs.visibilityMiles !== null ? `${obs.visibilityMiles.toFixed(1)} mi` : "--";

    const body = el(
      "div",
      { class: "metar-body" },
      el(
        "div",
        { class: "metar-primary" },
        el("div", { class: "metar-temp-display" }, tempF),
        el("div", { class: "metar-desc" }, obs.textDescription || "Current Surface Reading"),
      ),
      el(
        "div",
        { class: "metar-metrics-grid" },
        renderMetricDial("Dew Point", dewF, "Comfort / Fog"),
        renderMetricDial("Relative Humidity", rh, "Fire danger indicator"),
        renderMetricDial("Wind Speed", `${wind}${gust}`, "Surface flow"),
        renderMetricDial("Barometer", pressure, "Altimeter trend"),
        renderMetricDial("Visibility", vis, "Atmospheric clarity"),
      ),
    );

    card.append(head, body);
    return card;
  }

  private renderHourlyTimeline(hourly: HourlyPeriod[]): HTMLElement {
    const card = el("section", { class: "panel weather-hourly-panel" });
    const head = el(
      "div",
      { class: "panel-head" },
      el("h3", { text: "Hourly Forecast Timeline (Next 36 Hours)" }),
    );

    if (hourly.length === 0) {
      card.append(head, el("p", { class: "empty", text: "Hourly forecast unavailable." }));
      return card;
    }

    const timeline = el("div", { class: "hourly-timeline-track" });

    for (const h of hourly) {
      const timeStr = formatHourlyTime(h.startTime);
      const icon = weatherSvg(h.shortForecast, h.isDaytime, 22);
      const precip = h.probabilityOfPrecipitation?.value;
      const precipStr = precip !== null && precip !== undefined && precip > 0 ? `${precip}%` : "";

      const col = el(
        "div",
        { class: `hourly-cell${h.isDaytime ? " is-day" : " is-night"}` },
        el("div", { class: "hourly-time", text: timeStr }),
        el("div", { class: "hourly-icon" }, icon),
        el("div", { class: "hourly-temp", text: `${h.temperature}°` }),
        el(
          "div",
          { class: "hourly-precip", text: precipStr || " " },
        ),
        el("div", { class: "hourly-wind", text: `${h.windDirection} ${h.windSpeed.replace(" mph", "")}` }),
      );
      timeline.appendChild(col);
    }

    card.append(head, timeline);
    return card;
  }

  private renderFireRisk(obs: MetarObservation | null | undefined, _hourly: HourlyPeriod[]): HTMLElement {
    const card = el("section", { class: "panel fire-risk-panel" });
    const head = el("div", { class: "panel-head" }, el("h3", { text: "Fire Weather & Red Flag Risk Index" }));

    // Evaluate fire danger: RH < 25% + Temp > 80°F + Wind > 12 mph
    const rh = obs?.relativeHumidity ?? 50;
    const tempF = obs?.temperatureF ?? 70;
    const wind = obs?.windSpeedMph ?? 5;

    let riskLevel = "LOW";
    let riskColor = "#22c55e";
    let explanation = "Normal atmospheric humidity and moderate surface winds.";

    if (rh <= 20 && wind >= 15 && tempF >= 80) {
      riskLevel = "CRITICAL / RED FLAG";
      riskColor = "#ef4444";
      explanation = "Extreme fire weather danger: Very low RH combined with strong gusts and high heat.";
    } else if (rh <= 25 && (wind >= 10 || tempF >= 85)) {
      riskLevel = "ELEVATED";
      riskColor = "#f97316";
      explanation = "Heightened fire spread risk: Low afternoon relative humidity with active surface breezes.";
    } else if (rh <= 30) {
      riskLevel = "MODERATE";
      riskColor = "#eab308";
      explanation = "Seasonally dry ground conditions; monitoring for afternoon wind surges.";
    }

    const gauge = el(
      "div",
      { class: "fire-risk-gauge" },
      el(
        "div",
        { class: "fire-risk-badge", style: `background: color-mix(in srgb, ${riskColor} 18%, transparent); color: ${riskColor}; border-color: ${riskColor};` },
        riskLevel,
      ),
      el("div", { class: "fire-risk-desc", text: explanation }),
      el(
        "div",
        { class: "fire-risk-stats" },
        el("div", { text: `Surface RH: ${Math.round(rh)}%` }),
        el("div", { text: `Sustained Wind: ${Math.round(wind)} mph` }),
        el("div", { text: `Air Temp: ${Math.round(tempF)}°F` }),
      ),
    );

    card.append(head, gauge);
    return card;
  }

  private renderExtendedMatrix(extended: ExtendedPeriod[]): HTMLElement {
    const card = el("section", { class: "panel weather-extended-panel" });
    const head = el("div", { class: "panel-head" }, el("h3", { text: "7-Day Extended Weather Outlook" }));

    if (extended.length === 0) {
      card.append(head, el("p", { class: "empty", text: "Extended forecast unavailable." }));
      return card;
    }

    const grid = el("div", { class: "extended-grid" });

    for (const p of extended) {
      const icon = weatherSvg(p.shortForecast, p.isDaytime, 24);
      const precipVal = p.probabilityOfPrecipitation?.value;

      const pCard = el(
        "div",
        { class: `extended-card${p.isDaytime ? " is-day" : " is-night"}` },
        el("div", { class: "extended-card-head" }, p.name),
        el("div", { class: "extended-card-icon" }, icon),
        el("div", { class: "extended-card-temp", text: `${p.temperature}°${p.temperatureUnit}` }),
        precipVal !== null && precipVal !== undefined && precipVal > 0
          ? el("div", { class: "extended-card-precip", text: `${precipVal}% rain` })
          : el("div", { class: "extended-card-precip", text: " " }),
        el("div", { class: "extended-card-desc", text: p.shortForecast, title: p.detailedForecast }),
      );
      grid.appendChild(pCard);
    }

    card.append(head, grid);
    return card;
  }

  private renderAfdSection(afd: AfdProduct | null | undefined): HTMLElement {
    const card = el("section", { class: "panel afd-panel" });
    const head = el(
      "div",
      { class: "panel-head" },
      el("h3", { text: "Area Forecast Discussion (AFD) — Meteorologist Brief" }),
      afd ? el("span", { class: "panel-head-summary", text: `WFO ${afd.wfo}` }) : null,
    );

    if (!afd || afd.sections.length === 0) {
      card.append(head, el("p", { class: "empty", text: "NWS Forecaster discussion loading…" }));
      return card;
    }

    const nav = el("div", { class: "afd-nav-tabs" });
    const body = el("div", { class: "afd-content-box" });

    afd.sections.forEach((sec, idx) => {
      const btn = el("button", {
        class: `afd-nav-btn${idx === this.activeAfdSection ? " active" : ""}`,
        text: sec.title,
        attrs: { type: "button" },
      });
      btn.addEventListener("click", () => {
        this.activeAfdSection = idx;
        this.render();
      });
      nav.appendChild(btn);
    });

    const activeSec = afd.sections[this.activeAfdSection] || afd.sections[0];
    body.textContent = activeSec.body;

    card.append(head, nav, body);
    return card;
  }
}

function parseObservation(stationId: string, stationName: string, props: any): MetarObservation {
  const tempC = props.temperature?.value ?? null;
  const tempF = tempC !== null ? (tempC * 9) / 5 + 32 : null;
  const dewC = props.dewpoint?.value ?? null;
  const dewF = dewC !== null ? (dewC * 9) / 5 + 32 : null;
  const rh = props.relativeHumidity?.value ?? null;
  const windKmh = props.windSpeed?.value ?? null;
  const windMph = windKmh !== null ? windKmh * 0.621371 : null;
  const gustKmh = props.windGust?.value ?? null;
  const gustMph = gustKmh !== null ? gustKmh * 0.621371 : null;
  const windDir = props.windDirection?.value ?? null;
  const baroPa = props.barometricPressure?.value ?? null;
  const baroInHg = baroPa !== null ? baroPa * 0.0002953 : null;
  const seaMb = props.seaLevelPressure?.value ?? null;
  const visM = props.visibility?.value ?? null;
  const visMi = visM !== null ? visM * 0.000621371 : null;

  return {
    stationId,
    stationName,
    timestamp: props.timestamp || "",
    temperatureC: tempC,
    temperatureF: tempF,
    dewpointF: dewF,
    relativeHumidity: rh,
    windSpeedMph: windMph,
    windGustMph: gustMph,
    windDirectionDeg: windDir,
    windDirectionCard: degToCard(windDir),
    barometricPressureInHg: baroInHg,
    seaLevelPressureMb: seaMb !== null ? seaMb / 100 : null,
    visibilityMiles: visMi,
    textDescription: props.textDescription || null,
  };
}

function parseAfd(wfo: string, issuanceTime: string, rawText: string): AfdProduct {
  const sections: { title: string; body: string }[] = [];
  const lines = rawText.split("\n");
  let currentTitle = "Overview";
  let currentLines: string[] = [];

  for (const line of lines) {
    if (line.startsWith(".") && line.includes("...")) {
      if (currentLines.length > 0) {
        sections.push({ title: cleanAfdTitle(currentTitle), body: currentLines.join("\n").trim() });
        currentLines = [];
      }
      currentTitle = line.replace(/^\./, "").replace(/\.\.\..*$/, "").trim();
    } else {
      currentLines.push(line);
    }
  }

  if (currentLines.length > 0) {
    sections.push({ title: cleanAfdTitle(currentTitle), body: currentLines.join("\n").trim() });
  }

  return {
    issuedTime: issuanceTime,
    wfo,
    text: rawText,
    sections: sections.filter((s) => s.body.length > 20).slice(0, 6),
  };
}

function cleanAfdTitle(title: string): string {
  const t = title.toUpperCase();
  if (t.includes("SYNOPSIS")) return "Synopsis";
  if (t.includes("SHORT TERM")) return "Short Term";
  if (t.includes("LONG TERM")) return "Long Term";
  if (t.includes("FIRE WEATHER")) return "Fire Weather";
  if (t.includes("AVIATION")) return "Aviation";
  if (t.includes("MARINE")) return "Marine";
  return title.slice(0, 16);
}

function degToCard(deg: number | null): string {
  if (deg === null) return "";
  const directions = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
  const idx = Math.round(deg / 22.5) % 16;
  return directions[idx];
}

function formatHourlyTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: "numeric" });
  } catch {
    return "";
  }
}

function renderMetricDial(label: string, value: string, sub: string): HTMLElement {
  return el(
    "div",
    { class: "metar-metric-dial" },
    el("div", { class: "dial-label", text: label }),
    el("div", { class: "dial-value", text: value }),
    el("div", { class: "dial-sub", text: sub }),
  );
}

function weatherSvg(shortForecast: string, isDaytime: boolean, size = 24): SVGElement {
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
