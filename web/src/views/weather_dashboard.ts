import { el, replaceChildren } from "../dom";
import { isActive } from "../format";
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

export interface DailySummary {
  dayName: string;
  isDaytime: boolean;
  highTemp: number | null;
  lowTemp: number | null;
  tempUnit: string;
  popMax: number;
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
}

const CACHE_KEY = "tocsin_weather_dashboard_cache";
const CACHE_TTL_MS = 15 * 60 * 1000;

export class WeatherDashboardView {
  private readonly container: HTMLElement;
  private readonly store: Store;
  private data: WeatherDashboardData | null = null;
  private isLoading = false;

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

      // 2. Parallel fetch hourly, extended, and stations list
      const [hourlyRes, extendedRes, stationsRes] = await Promise.allSettled([
        hourlyUrl ? fetch(hourlyUrl, { headers: { Accept: "application/geo+json" } }) : Promise.reject(),
        forecastUrl ? fetch(forecastUrl, { headers: { Accept: "application/geo+json" } }) : Promise.reject(),
        stationsUrl ? fetch(stationsUrl, { headers: { Accept: "application/geo+json" } }) : Promise.reject(),
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

    const { city, state, wfo, currentObservation, hourly, extended, stations, selectedStationId } = this.data;

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

    // 5. 7-Day Extended Outlook Matrix (Paired Daily Summary)
    const extendedSection = this.render7DayOutlook(extended);

    const mainGrid = el(
      "div",
      { class: "weather-dash-grid" },
      el("div", { class: "weather-dash-col-left" }, metarHero, fireRiskCard),
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
    const select = el("select", { class: "station-select-full", attrs: { "aria-label": "Observation station" } }) as HTMLSelectElement;

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
      { class: "metar-head-stacked" },
      el(
        "div",
        { class: "metar-head-row" },
        el("h3", { text: "Surface Observations" }),
        el("span", { class: "badge badge-status-synced", text: "METAR" }),
      ),
      el("div", { class: "station-select-container" }, select),
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
    const windDirDeg = obs.windDirectionDeg !== null ? `${Math.round(obs.windDirectionDeg)}° (${obs.windDirectionCard || ""})` : "--";

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
        renderMetricDial("Wind Bearing", windDirDeg, "Compass direction"),
        renderMetricDial("Barometer", pressure, "Altimeter reading"),
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
    const head = el(
      "div",
      { class: "panel-head" },
      el("h3", { text: "Fire Weather & Red Flag Index" }),
      el("span", { class: "badge badge-status-synced", text: "NFDRS" }),
    );

    // Check active fire weather / red flag / air quality alerts in store
    const alerts = Array.from(this.store.state.alerts.values());
    const activeFireAlerts = alerts.filter(
      (a) =>
        isActive(a) &&
        (a.event_name.toLowerCase().includes("fire") ||
          a.event_name.toLowerCase().includes("red flag") ||
          a.event_name.toLowerCase().includes("smoke") ||
          a.event_name.toLowerCase().includes("air quality")),
    );

    // Evaluate fire danger metrics: RH (40% weight), Wind (35% weight), Temp (25% weight)
    const rh = obs?.relativeHumidity ?? 50;
    const tempF = obs?.temperatureF ?? 70;
    const wind = obs?.windSpeedMph ?? 5;
    const gust = obs?.windGustMph ?? wind;

    let dangerIndex = 0; // 0 (Low) to 4 (Extreme)
    let riskLevel = "LOW";
    let riskColor = "#22c55e";
    let explanation = "High surface humidity and light winds keep ignition risk minimal.";

    if (activeFireAlerts.length > 0 || (rh <= 18 && wind >= 15 && tempF >= 82)) {
      dangerIndex = 4;
      riskLevel = "CRITICAL / RED FLAG";
      riskColor = "#e11d48";
      explanation = "Severe fire weather conditions: Very low humidity, elevated heat, and dangerous spread winds.";
    } else if (rh <= 22 && (wind >= 12 || tempF >= 88)) {
      dangerIndex = 3;
      riskLevel = "VERY HIGH";
      riskColor = "#f97316";
      explanation = "Dry vegetation and active surface breezes support rapid fire spread upon ignition.";
    } else if (rh <= 28 && (wind >= 8 || tempF >= 80)) {
      dangerIndex = 2;
      riskLevel = "HIGH";
      riskColor = "#eab308";
      explanation = "Moderately low humidity; afternoon gusts can dry fine fuels quickly.";
    } else if (rh <= 38) {
      dangerIndex = 1;
      riskLevel = "MODERATE";
      riskColor = "#38bdf8";
      explanation = "Seasonal drying with manageable wind speeds and moderate daytime recovery.";
    }

    // Active Alert Banner if applicable
    const alertBanner =
      activeFireAlerts.length > 0
        ? el(
            "div",
            { class: "fire-alert-callout" },
            el("div", { class: "fire-alert-callout-title", text: "ACTIVE NWS ADVISORY IN EFFECT" }),
            el("div", {
              class: "fire-alert-callout-body",
              text: activeFireAlerts.map((a) => a.event_name).join(" · "),
            }),
          )
        : null;

    // 5-segment NFDRS gauge bar
    const segmentLabels = ["Low", "Moderate", "High", "Very High", "Extreme"];
    const segmentColors = ["#22c55e", "#38bdf8", "#eab308", "#f97316", "#e11d48"];
    const segments = segmentLabels.map((lbl, idx) => {
      const isCurrent = idx === dangerIndex;
      return el(
        "div",
        {
          class: `nfdrs-segment${isCurrent ? " is-active" : ""}`,
          style: isCurrent
            ? `background: ${segmentColors[idx]}; box-shadow: 0 0 10px ${segmentColors[idx]}88; border-color: ${segmentColors[idx]};`
            : `background: color-mix(in srgb, ${segmentColors[idx]} 20%, var(--panel-deep)); border-color: ${segmentColors[idx]}44;`,
        },
        el("span", { class: "nfdrs-segment-label", text: lbl }),
      );
    });

    const meter = el("div", { class: "nfdrs-meter-strip" }, ...segments);

    // Threat Factor Rows with mini progress bars
    // 1. Relative Humidity Factor (0% to 100%, lower is worse)
    const rhPercentClamped = Math.min(Math.max(rh, 0), 100);
    const rhColor = rh <= 20 ? "#e11d48" : rh <= 30 ? "#f97316" : rh <= 40 ? "#eab308" : "#22c55e";
    const rhStatus = rh <= 20 ? "Critical (<20%)" : rh <= 30 ? "Dry (20-30%)" : "Safe (>30%)";

    // 2. Wind & Gust Factor (0 to 35 mph, higher is worse)
    const windPercentClamped = Math.min((gust / 35) * 100, 100);
    const windColor = gust >= 20 ? "#e11d48" : gust >= 12 ? "#f97316" : "#22c55e";
    const windStatus = gust >= 20 ? "Strong Gusts" : gust >= 12 ? "Moderate" : "Light (<10 mph)";

    // 3. Air Temp Factor (40°F to 105°F, higher is worse)
    const tempPercentClamped = Math.min(Math.max(((tempF - 40) / 65) * 100, 0), 100);
    const tempColor = tempF >= 90 ? "#e11d48" : tempF >= 80 ? "#f97316" : "#22c55e";
    const tempStatus = tempF >= 90 ? "High Evaporation" : tempF >= 80 ? "Warm" : "Moderate";

    const factorRows = el(
      "div",
      { class: "fire-factors-container" },
      renderFactorRow("Relative Humidity", `${Math.round(rh)}%`, rhStatus, rhPercentClamped, rhColor),
      renderFactorRow("Surface Winds", `${Math.round(wind)} mph (gusts ${Math.round(gust)})`, windStatus, windPercentClamped, windColor),
      renderFactorRow("Air Temperature", `${Math.round(tempF)}°F`, tempStatus, tempPercentClamped, tempColor),
    );

    const body = el(
      "div",
      { class: "fire-risk-body" },
      alertBanner,
      el(
        "div",
        { class: "fire-risk-badge-row" },
        el(
          "div",
          {
            class: "fire-risk-badge",
            style: `background: color-mix(in srgb, ${riskColor} 18%, transparent); color: ${riskColor}; border-color: ${riskColor};`,
          },
          riskLevel,
        ),
        el("div", { class: "fire-risk-desc", text: explanation }),
      ),
      meter,
      factorRows,
    );

    card.append(head, body);
    return card;
  }

  private render7DayOutlook(extended: ExtendedPeriod[]): HTMLElement {
    const card = el("section", { class: "panel weather-extended-panel" });
    const head = el("div", { class: "panel-head" }, el("h3", { text: "7-Day Extended Weather Outlook" }));

    if (extended.length === 0) {
      card.append(head, el("p", { class: "empty", text: "Extended forecast unavailable." }));
      return card;
    }

    // Group day and night periods into 7 daily summaries
    const dailyList: DailySummary[] = groupDailyForecasts(extended);

    const grid = el("div", { class: "seven-day-strip" });

    for (const d of dailyList) {
      const icon = weatherSvg(d.shortForecast, d.isDaytime, 28);
      const highStr = d.highTemp !== null ? `${d.highTemp}°` : "--";
      const lowStr = d.lowTemp !== null ? `${d.lowTemp}°` : "--";

      const pCard = el(
        "div",
        { class: "seven-day-card" },
        el("div", { class: "seven-day-name", text: d.dayName }),
        el("div", { class: "seven-day-icon" }, icon),
        el(
          "div",
          { class: "seven-day-temps" },
          el("span", { class: "seven-day-high", text: highStr }),
          el("span", { class: "seven-day-divider", text: "/" }),
          el("span", { class: "seven-day-low", text: lowStr }),
        ),
        d.popMax > 0
          ? el("div", { class: "seven-day-precip", text: `${d.popMax}% rain` })
          : el("div", { class: "seven-day-precip", text: " " }),
        el("div", { class: "seven-day-desc", text: d.shortForecast, title: d.detailedForecast }),
      );
      grid.appendChild(pCard);
    }

    card.append(head, grid);
    return card;
  }
}

function groupDailyForecasts(periods: ExtendedPeriod[]): DailySummary[] {
  const map: Map<string, DailySummary> = new Map();

  for (const p of periods) {
    // Extract base day name (e.g. "This Afternoon" -> "Today", "Saturday Night" -> "Saturday")
    let baseDay = p.name.replace(/ Night$/, "").trim();
    if (baseDay.toLowerCase().includes("afternoon") || baseDay.toLowerCase().includes("today")) {
      baseDay = "Today";
    }

    if (!map.has(baseDay)) {
      map.set(baseDay, {
        dayName: baseDay,
        isDaytime: p.isDaytime,
        highTemp: p.isDaytime ? p.temperature : null,
        lowTemp: !p.isDaytime ? p.temperature : null,
        tempUnit: p.temperatureUnit,
        popMax: p.probabilityOfPrecipitation?.value ?? 0,
        shortForecast: p.shortForecast,
        detailedForecast: p.detailedForecast,
      });
    } else {
      const entry = map.get(baseDay)!;
      if (p.isDaytime && entry.highTemp === null) {
        entry.highTemp = p.temperature;
        entry.shortForecast = p.shortForecast;
        entry.detailedForecast = p.detailedForecast;
        entry.isDaytime = true;
      } else if (!p.isDaytime && entry.lowTemp === null) {
        entry.lowTemp = p.temperature;
      }
      const pPop = p.probabilityOfPrecipitation?.value ?? 0;
      if (pPop > entry.popMax) entry.popMax = pPop;
    }
  }

  return Array.from(map.values()).slice(0, 7);
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

function renderFactorRow(
  label: string,
  value: string,
  status: string,
  percent: number,
  barColor: string,
): HTMLElement {
  return el(
    "div",
    { class: "fire-factor-row" },
    el(
      "div",
      { class: "fire-factor-info" },
      el("span", { class: "fire-factor-label", text: label }),
      el("span", { class: "fire-factor-val", text: value }),
      el("span", { class: "fire-factor-status", text: status, style: `color: ${barColor};` }),
    ),
    el(
      "div",
      { class: "fire-factor-bar-bg" },
      el("div", {
        class: "fire-factor-bar-fill",
        style: `width: ${percent}%; background-color: ${barColor};`,
      }),
    ),
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
