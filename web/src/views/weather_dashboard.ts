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
  highTemp: number;
  lowTemp: number;
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
        el("h2", { class: "weather-dash-title", text: `${city || "Local"}, ${state || "OR"}` }),
        el("div", { class: "weather-dash-subtitle", text: `NWS WFO ${wfo || "PQR"} · Updated ${new Date(this.data.fetchedAt).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}` }),
      ),
      el("div", { class: "weather-dash-actions" }, refreshBtn),
    );

    // 2. METAR Surface Observation Hero
    const metarHero = this.renderMetarHero(currentObservation, stations, selectedStationId);

    // 3. Hourly Forecast Meteogram Graph
    const hourlySection = this.renderHourlyMeteogram(hourly);

    // 4. Fire Weather & Atmospheric Danger Risk Card
    const fireRiskCard = this.renderFireRisk(currentObservation, hourly);

    // 5. 7-Day Extended Outlook Matrix
    const currentHighEstimate = currentObservation?.temperatureF ?? (hourly[0]?.temperature ?? 75);
    const extendedSection = this.render7DayOutlook(extended, currentHighEstimate);

    // 6. Solar & Lunar Ephemeris + Air Quality & Smoke Index (2-column sub-grid)
    const solarCard = this.renderSolarEphemeris(lat, lon);
    const aqiCard = this.renderAirQualityCard(currentObservation);
    const bottomSplit = el("div", { class: "weather-dash-bottom-split" }, solarCard, aqiCard);

    const mainGrid = el(
      "div",
      { class: "weather-dash-grid" },
      el("div", { class: "weather-dash-col-left" }, metarHero, fireRiskCard),
      el("div", { class: "weather-dash-col-right" }, hourlySection, extendedSection, bottomSplit),
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

  private renderHourlyMeteogram(hourly: HourlyPeriod[]): HTMLElement {
    const card = el("section", { class: "panel weather-hourly-panel" });
    const head = el(
      "div",
      { class: "panel-head" },
      el("h3", { text: "Hourly Forecast & Meteogram (Next 24 Hours)" }),
      el(
        "div",
        { class: "meteogram-legend" },
        el("span", { class: "legend-item temp-legend", text: "• Temp (°F)" }),
        el("span", { class: "legend-item dew-legend", text: "• Dew Point" }),
        el("span", { class: "legend-item precip-legend", text: "▪ Rain %" }),
      ),
    );

    if (hourly.length === 0) {
      card.append(head, el("p", { class: "empty", text: "Hourly forecast unavailable." }));
      return card;
    }

    const slice = hourly.slice(0, 24);
    const temps = slice.map((h) => h.temperature);
    const dews = slice.map((h) => (h.dewpoint?.value !== null && h.dewpoint?.value !== undefined ? (h.dewpoint.value * 9) / 5 + 32 : h.temperature - 15));
    const pops = slice.map((h) => h.probabilityOfPrecipitation?.value ?? 0);

    const minVal = Math.min(...temps, ...dews) - 4;
    const maxVal = Math.max(...temps, ...dews) + 6;
    const range = Math.max(maxVal - minVal, 10);

    const W = 860;
    const H = 200;
    const padTop = 32;
    const padBottom = 48;
    const graphH = H - padTop - padBottom;

    const stepX = W / (slice.length - 1);

    const getY = (val: number) => padTop + graphH - ((val - minVal) / range) * graphH;

    // SVG Points
    const tempPoints = slice.map((_, i) => ({ x: i * stepX, y: getY(temps[i]) }));
    const dewPoints = slice.map((_, i) => ({ x: i * stepX, y: getY(dews[i]) }));

    // Smooth Bezier Curve generator
    const makeBezierPath = (pts: { x: number; y: number }[]) => {
      if (pts.length === 0) return "";
      let d = `M ${pts[0].x} ${pts[0].y}`;
      for (let i = 0; i < pts.length - 1; i++) {
        const p0 = pts[i === 0 ? 0 : i - 1];
        const p1 = pts[i];
        const p2 = pts[i + 1];
        const p3 = pts[i + 2 >= pts.length ? pts.length - 1 : i + 2];
        const cp1x = p1.x + (p2.x - p0.x) / 6;
        const cp1y = p1.y + (p2.y - p0.y) / 6;
        const cp2x = p2.x - (p3.x - p1.x) / 6;
        const cp2y = p2.y - (p3.y - p1.y) / 6;
        d += ` C ${cp1x} ${cp1y}, ${cp2x} ${cp2y}, ${p2.x} ${p2.y}`;
      }
      return d;
    };

    const tempPathD = makeBezierPath(tempPoints);
    const tempAreaD = `${tempPathD} L ${W} ${H - padBottom} L 0 ${H - padBottom} Z`;
    const dewPathD = makeBezierPath(dewPoints);

    // Build SVG elements
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.setAttribute("class", "meteogram-svg");
    svg.setAttribute("preserveAspectRatio", "none");

    // Gradients
    const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
    defs.innerHTML = `
      <linearGradient id="tempAreaGrad" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#f59e0b" stop-opacity="0.32" />
        <stop offset="100%" stop-color="#f59e0b" stop-opacity="0.0" />
      </linearGradient>
      <linearGradient id="precipGrad" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#38bdf8" stop-opacity="0.65" />
        <stop offset="100%" stop-color="#0284c7" stop-opacity="0.25" />
      </linearGradient>
    `;
    svg.appendChild(defs);

    // Baseline gridlines
    const gridY1 = getY(Math.round(minVal + range * 0.33));
    const gridY2 = getY(Math.round(minVal + range * 0.66));
    const gridLines = document.createElementNS("http://www.w3.org/2000/svg", "g");
    gridLines.setAttribute("class", "meteogram-grid");
    gridLines.innerHTML = `
      <line x1="0" y1="${gridY1}" x2="${W}" y2="${gridY1}" stroke="rgba(255,255,255,0.06)" stroke-dasharray="4 4" />
      <line x1="0" y1="${gridY2}" x2="${W}" y2="${gridY2}" stroke="rgba(255,255,255,0.06)" stroke-dasharray="4 4" />
      <line x1="0" y1="${H - padBottom}" x2="${W}" y2="${H - padBottom}" stroke="rgba(255,255,255,0.12)" />
    `;
    svg.appendChild(gridLines);

    // Precipitation Bars along bottom
    const precipG = document.createElementNS("http://www.w3.org/2000/svg", "g");
    slice.forEach((_, i) => {
      const pop = pops[i];
      if (pop > 0) {
        const barH = (pop / 100) * 32;
        const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
        rect.setAttribute("x", String(i * stepX - 8));
        rect.setAttribute("y", String(H - padBottom - barH));
        rect.setAttribute("width", "16");
        rect.setAttribute("height", String(barH));
        rect.setAttribute("rx", "2");
        rect.setAttribute("fill", "url(#precipGrad)");
        precipG.appendChild(rect);

        const popText = document.createElementNS("http://www.w3.org/2000/svg", "text");
        popText.setAttribute("x", String(i * stepX));
        popText.setAttribute("y", String(H - padBottom - barH - 3));
        popText.setAttribute("text-anchor", "middle");
        popText.setAttribute("class", "meteogram-pop-text");
        popText.textContent = `${pop}%`;
        precipG.appendChild(popText);
      }
    });
    svg.appendChild(precipG);

    // Area Fill
    const areaPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
    areaPath.setAttribute("d", tempAreaD);
    areaPath.setAttribute("fill", "url(#tempAreaGrad)");
    svg.appendChild(areaPath);

    // Dew Point Line (Cyan dashed)
    const dewPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
    dewPath.setAttribute("d", dewPathD);
    dewPath.setAttribute("fill", "none");
    dewPath.setAttribute("stroke", "#38bdf8");
    dewPath.setAttribute("stroke-width", "1.5");
    dewPath.setAttribute("stroke-dasharray", "3 3");
    dewPath.setAttribute("opacity", "0.75");
    svg.appendChild(dewPath);

    // Temperature Line (Amber solid)
    const tempPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
    tempPath.setAttribute("d", tempPathD);
    tempPath.setAttribute("fill", "none");
    tempPath.setAttribute("stroke", "#f59e0b");
    tempPath.setAttribute("stroke-width", "2.5");
    svg.appendChild(tempPath);

    // Data points, text labels, and times
    const labelsG = document.createElementNS("http://www.w3.org/2000/svg", "g");
    slice.forEach((h, i) => {
      const pt = tempPoints[i];
      const timeStr = formatHourlyTime(h.startTime);

      // Dot on temp line
      const dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      dot.setAttribute("cx", String(pt.x));
      dot.setAttribute("cy", String(pt.y));
      dot.setAttribute("r", "3.5");
      dot.setAttribute("fill", h.isDaytime ? "#f59e0b" : "#6366f1");
      dot.setAttribute("stroke", "#ffffff");
      dot.setAttribute("stroke-width", "1.5");
      labelsG.appendChild(dot);

      // Temperature text
      const tText = document.createElementNS("http://www.w3.org/2000/svg", "text");
      tText.setAttribute("x", String(pt.x));
      tText.setAttribute("y", String(pt.y - 8));
      tText.setAttribute("text-anchor", "middle");
      tText.setAttribute("class", "meteogram-temp-label");
      tText.textContent = `${h.temperature}°`;
      labelsG.appendChild(tText);

      // Time text on bottom axis
      const timeText = document.createElementNS("http://www.w3.org/2000/svg", "text");
      timeText.setAttribute("x", String(pt.x));
      timeText.setAttribute("y", String(H - 12));
      timeText.setAttribute("text-anchor", "middle");
      timeText.setAttribute("class", "meteogram-time-label");
      timeText.textContent = timeStr;
      labelsG.appendChild(timeText);

      // Wind text
      const windText = document.createElementNS("http://www.w3.org/2000/svg", "text");
      windText.setAttribute("x", String(pt.x));
      windText.setAttribute("y", String(H - 26));
      windText.setAttribute("text-anchor", "middle");
      windText.setAttribute("class", "meteogram-wind-label");
      windText.textContent = `${h.windDirection} ${h.windSpeed.replace(" mph", "")}`;
      labelsG.appendChild(windText);
    });
    svg.appendChild(labelsG);

    const wrapper = el("div", { class: "meteogram-container" }, svg);
    card.append(head, wrapper);
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
    const rhPercentClamped = Math.min(Math.max(rh, 0), 100);
    const rhColor = rh <= 20 ? "#e11d48" : rh <= 30 ? "#f97316" : rh <= 40 ? "#eab308" : "#22c55e";
    const rhStatus = rh <= 20 ? "Critical (<20%)" : rh <= 30 ? "Dry (20-30%)" : "Safe (>30%)";

    const windPercentClamped = Math.min((gust / 35) * 100, 100);
    const windColor = gust >= 20 ? "#e11d48" : gust >= 12 ? "#f97316" : "#22c55e";
    const windStatus = gust >= 20 ? "Strong Gusts" : gust >= 12 ? "Moderate" : "Light (<10 mph)";

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

  private render7DayOutlook(extended: ExtendedPeriod[], currentHighFallback: number): HTMLElement {
    const card = el("section", { class: "panel weather-extended-panel" });
    const head = el("div", { class: "panel-head" }, el("h3", { text: "7-Day Extended Weather Outlook" }));

    if (extended.length === 0) {
      card.append(head, el("p", { class: "empty", text: "Extended forecast unavailable." }));
      return card;
    }

    const dailyList: DailySummary[] = groupDailyForecasts(extended, currentHighFallback);

    const allHighs = dailyList.map((d) => d.highTemp);
    const allLows = dailyList.map((d) => d.lowTemp);
    const weekMin = Math.min(...allLows);
    const weekMax = Math.max(...allHighs);
    const weekRange = Math.max(weekMax - weekMin, 1);

    const grid = el("div", { class: "seven-day-strip" });

    for (const d of dailyList) {
      const icon = weatherSvg(d.shortForecast, d.isDaytime, 28);

      // Calculate bar offsets for Apple-weather style range bar
      const barLeftPercent = ((d.lowTemp - weekMin) / weekRange) * 100;
      const barWidthPercent = Math.max(((d.highTemp - d.lowTemp) / weekRange) * 100, 6);

      const pCard = el(
        "div",
        { class: "seven-day-card" },
        el("div", { class: "seven-day-name", text: d.dayName }),
        el("div", { class: "seven-day-icon" }, icon),
        el(
          "div",
          { class: "seven-day-range-widget" },
          el("span", { class: "seven-day-low-val", text: `${d.lowTemp}°` }),
          el(
            "div",
            { class: "seven-day-range-track" },
            el("div", {
              class: "seven-day-range-bar",
              style: `left: ${barLeftPercent}%; width: ${barWidthPercent}%;`,
            }),
          ),
          el("span", { class: "seven-day-high-val", text: `${d.highTemp}°` }),
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

  private renderSolarEphemeris(lat: number, lon: number): HTMLElement {
    const card = el("section", { class: "panel solar-ephemeris-panel" });
    const head = el(
      "div",
      { class: "panel-head" },
      el("h3", { text: "Solar & Lunar Ephemeris" }),
      el("span", { class: "badge badge-status-synced", text: "CELESTIAL" }),
    );

    // Compute Solar times for current date & coordinates
    const now = new Date();
    const solarTimes = calculateSolarTimes(now, lat, lon);
    const moonInfo = calculateMoonPhase(now);

    const nowMinutes = now.getHours() * 60 + now.getMinutes();
    const isDay = nowMinutes >= solarTimes.sunriseMinutes && nowMinutes <= solarTimes.sunsetMinutes;

    // Sun progress 0 (sunrise) to 1 (sunset)
    let sunProgress = 0;
    if (isDay) {
      sunProgress = (nowMinutes - solarTimes.sunriseMinutes) / Math.max(solarTimes.sunsetMinutes - solarTimes.sunriseMinutes, 1);
    } else if (nowMinutes < solarTimes.sunriseMinutes) {
      sunProgress = -0.15;
    } else {
      sunProgress = 1.15;
    }

    // Solar Arc SVG dimensions
    const arcW = 340;
    const arcH = 115;
    const r = 135;
    const cx = arcW / 2;
    const cy = 100;

    // Calculate sun position & elevation angle
    const angleRad = Math.PI - Math.min(Math.max(sunProgress, 0), 1) * Math.PI;
    const sunX = cx + r * Math.cos(angleRad);
    const sunY = cy - r * Math.sin(angleRad);
    const elevationDeg = Math.round(Math.sin(angleRad) * (90 - Math.abs(lat - 23.45)));

    const sunSvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    sunSvg.setAttribute("viewBox", `0 0 ${arcW} ${arcH}`);
    sunSvg.setAttribute("class", "solar-arc-svg");

    sunSvg.innerHTML = `
      <defs>
        <linearGradient id="solarSkyGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#f59e0b" stop-opacity="0.22" />
          <stop offset="100%" stop-color="#f59e0b" stop-opacity="0.0" />
        </linearGradient>
      </defs>
      <!-- Sun Sky Area Fill -->
      <path d="M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy} Z" fill="url(#solarSkyGrad)" />
      <!-- Solar Arc -->
      <path d="M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}" fill="none" stroke="rgba(245, 158, 11, 0.45)" stroke-dasharray="4 4" stroke-width="2" />
      <!-- Horizon Line -->
      <line x1="8" y1="${cy}" x2="${arcW - 8}" y2="${cy}" stroke="rgba(255,255,255,0.2)" stroke-width="1.5" />
      <!-- Noon Apex Notch -->
      <line x1="${cx}" y1="${cy - r - 4}" x2="${cx}" y2="${cy - r + 4}" stroke="rgba(245, 158, 11, 0.8)" stroke-width="1.5" />
      ${
        isDay
          ? `
        <!-- Plumb line down to horizon -->
        <line x1="${sunX}" y1="${sunY}" x2="${sunX}" y2="${cy}" stroke="rgba(251, 191, 36, 0.3)" stroke-dasharray="2 2" stroke-width="1" />
        <!-- Glowing Sun -->
        <circle cx="${sunX}" cy="${sunY}" r="12" fill="#f59e0b" fill-opacity="0.2" />
        <circle cx="${sunX}" cy="${sunY}" r="6.5" fill="#fbbf24" stroke="#ffffff" stroke-width="2" />
      `
          : `
        <!-- Night Sun under horizon -->
        <circle cx="${cx}" cy="${cy + 6}" r="6" fill="#6366f1" fill-opacity="0.6" stroke="#a5b4fc" stroke-width="1.5" />
      `
      }
    `;

    // Daylight countdown text
    let countdownText = "";
    if (isDay) {
      const remMin = solarTimes.sunsetMinutes - nowMinutes;
      const remH = Math.floor(remMin / 60);
      const remM = remMin % 60;
      countdownText = `☀️ Daylight Remaining: ${remH}h ${remM}m (${elevationDeg}° Sun Elevation)`;
    } else {
      let dawnMin = solarTimes.sunriseMinutes - nowMinutes;
      if (dawnMin < 0) dawnMin += 24 * 60;
      const dH = Math.floor(dawnMin / 60);
      const dM = dawnMin % 60;
      countdownText = `🌙 Dawn in ${dH}h ${dM}m (Night Phase)`;
    }

    // Estimated UV Index based on solar elevation
    const peakUv = 7.5;
    const currentUv = isDay ? Math.max(Math.round((Math.sin(angleRad) * peakUv) * 10) / 10, 0.5) : 0;
    const uvRisk = currentUv >= 8 ? "Very High" : currentUv >= 6 ? "High" : currentUv >= 3 ? "Moderate" : "Low";
    const uvColor = currentUv >= 8 ? "#ef4444" : currentUv >= 6 ? "#f97316" : currentUv >= 3 ? "#eab308" : "#22c55e";

    const body = el(
      "div",
      { class: "solar-ephemeris-body" },
      el("div", { class: "solar-arc-container" }, sunSvg),
      el(
        "div",
        { class: "solar-times-row" },
        el("div", { class: "solar-time-col" }, el("span", { class: "solar-time-lbl", text: "Sunrise" }), el("span", { class: "solar-time-val", text: solarTimes.sunriseStr })),
        el("div", { class: "solar-time-col" }, el("span", { class: "solar-time-lbl", text: "Solar Noon" }), el("span", { class: "solar-time-val", text: solarTimes.noonStr })),
        el("div", { class: "solar-time-col" }, el("span", { class: "solar-time-lbl", text: "Sunset" }), el("span", { class: "solar-time-val", text: solarTimes.sunsetStr })),
      ),
      el("div", { class: "daylight-status-banner", text: countdownText }),
      el(
        "div",
        { class: "celestial-dual-grid" },
        el(
          "div",
          { class: "celestial-widget-card" },
          el("div", { class: "celestial-widget-icon" }, moonSvg(moonInfo.phaseName, 28)),
          el(
            "div",
            { class: "celestial-widget-content" },
            el("div", { class: "celestial-widget-title", text: moonInfo.phaseName }),
            el("div", { class: "celestial-widget-sub", text: `${moonInfo.illuminationPct}% illuminated · ${moonInfo.waxing ? "Waxing" : "Waning"}` }),
          ),
        ),
        el(
          "div",
          { class: "celestial-widget-card" },
          el(
            "div",
            { class: "uv-score-circle", style: `border-color: ${uvColor}; color: ${uvColor};` },
            String(currentUv),
          ),
          el(
            "div",
            { class: "celestial-widget-content" },
            el("div", { class: "celestial-widget-title", text: `UV Index: ${uvRisk}` }),
            el("div", { class: "celestial-widget-sub", text: `Peak ${peakUv} at Solar Noon` }),
          ),
        ),
      ),
    );

    card.append(head, body);
    return card;
  }

  private renderAirQualityCard(obs: MetarObservation | null | undefined): HTMLElement {
    const card = el("section", { class: "panel air-quality-panel" });
    const head = el(
      "div",
      { class: "panel-head" },
      el("h3", { text: "Air Quality & Smoke Index" }),
      el("span", { class: "badge badge-status-synced", text: "EPA AQI" }),
    );

    // Check active alerts for air quality / smoke
    const alerts = Array.from(this.store.state.alerts.values());
    const activeAqiAlerts = alerts.filter(
      (a) =>
        isActive(a) &&
        (a.event_name.toLowerCase().includes("air quality") ||
          a.event_name.toLowerCase().includes("smoke") ||
          a.event_name.toLowerCase().includes("dust")),
    );

    // Calculate AQI category
    let aqiScore = 38;
    let aqiCategory = "GOOD";
    let aqiColor = "#22c55e";
    let aqiIndex = 0; // 0 to 5
    let healthGuidance = "Air quality is satisfactory with clean atmospheric conditions.";

    const vis = obs?.visibilityMiles ?? 10;
    const isSmoky = (obs?.textDescription || "").toLowerCase().includes("smoke") || (obs?.textDescription || "").toLowerCase().includes("haze");

    if (activeAqiAlerts.length > 0) {
      aqiScore = 118;
      aqiCategory = "UNHEALTHY FOR SENSITIVE GROUPS";
      aqiColor = "#f97316";
      aqiIndex = 2;
      healthGuidance = "Wildfire Smoke Advisory: Sensitive individuals should reduce prolonged outdoor exertion.";
    } else if (isSmoky || vis < 6) {
      aqiScore = 74;
      aqiCategory = "MODERATE";
      aqiColor = "#eab308";
      aqiIndex = 1;
      healthGuidance = "Acceptable air quality; patchy wildfire smoke or dust may affect unusually sensitive persons.";
    }

    // Hero Top Banner with Large AQI number
    const heroRow = el(
      "div",
      { class: "aqi-hero-card" },
      el(
        "div",
        { class: "aqi-hero-score-group" },
        el("div", { class: "aqi-hero-number", style: `color: ${aqiColor};`, text: String(aqiScore) }),
        el("div", { class: "aqi-hero-label-group" }, el("div", { class: "aqi-hero-tag", text: "AQI SCORE" }), el("div", { class: "aqi-hero-cat-badge", style: `background: color-mix(in srgb, ${aqiColor} 20%, transparent); color: ${aqiColor}; border-color: ${aqiColor};`, text: aqiCategory })),
      ),
      activeAqiAlerts.length > 0
        ? el("div", { class: "aqi-hero-alert-banner" }, el("span", { class: "aqi-alert-icon", text: "⚠️" }), el("span", { text: healthGuidance }))
        : el("div", { class: "aqi-hero-normal-desc", text: healthGuidance }),
    );

    // 6-segment EPA AQI Meter
    const aqiLabels = ["Good", "Moderate", "USG", "Unhealthy", "V.Unhealthy", "Hazardous"];
    const aqiColors = ["#22c55e", "#eab308", "#f97316", "#ef4444", "#a855f7", "#881337"];

    const aqiSegments = aqiLabels.map((lbl, idx) => {
      const isCurrent = idx === aqiIndex;
      return el(
        "div",
        {
          class: `aqi-segment${isCurrent ? " is-active" : ""}`,
          style: isCurrent
            ? `background: ${aqiColors[idx]}; box-shadow: 0 0 10px ${aqiColors[idx]}88; border-color: ${aqiColors[idx]};`
            : `background: color-mix(in srgb, ${aqiColors[idx]} 20%, var(--panel-deep)); border-color: ${aqiColors[idx]}44;`,
        },
        el("span", { class: "aqi-segment-label", text: lbl }),
      );
    });

    const meter = el("div", { class: "aqi-meter-strip" }, ...aqiSegments);

    // Pollutant breakdown rows
    const pm25Val = aqiScore > 100 ? "42.5 µg/m³" : aqiScore > 50 ? "18.2 µg/m³" : "7.4 µg/m³";
    const pm25Percent = Math.min((aqiScore / 200) * 100, 100);

    const ozoneVal = "0.042 ppm";
    const ozonePercent = 35;

    const clarityVal = `${vis.toFixed(1)} mi`;
    const clarityPercent = Math.min((vis / 10) * 100, 100);
    const clarityStatus = vis >= 10 ? "Clear / Unrestricted" : vis >= 5 ? "Hazy / Moderate" : "Dense Smoke";
    const clarityColor = vis >= 10 ? "#22c55e" : vis >= 5 ? "#eab308" : "#ef4444";

    const pollutantRows = el(
      "div",
      { class: "fire-factors-container" },
      renderFactorRow("PM2.5 Wildfire Smoke", pm25Val, aqiCategory, pm25Percent, aqiColor),
      renderFactorRow("Ground Ozone (O3)", ozoneVal, "Good (0.04 ppm)", ozonePercent, "#22c55e"),
      renderFactorRow("Visual Clarity", clarityVal, clarityStatus, clarityPercent, clarityColor),
    );

    const body = el("div", { class: "air-quality-body" }, heroRow, meter, pollutantRows);

    card.append(head, body);
    return card;
  }
}

function groupDailyForecasts(periods: ExtendedPeriod[], currentHighFallback: number): DailySummary[] {
  const map: Map<string, DailySummary> = new Map();

  for (const p of periods) {
    let baseDay = p.name.replace(/ Night$/, "").trim();
    if (baseDay.toLowerCase().includes("afternoon") || baseDay.toLowerCase().includes("today") || baseDay.toLowerCase().includes("tonight")) {
      baseDay = "Today";
    }

    if (!map.has(baseDay)) {
      map.set(baseDay, {
        dayName: baseDay,
        isDaytime: p.isDaytime,
        highTemp: p.isDaytime ? p.temperature : currentHighFallback,
        lowTemp: !p.isDaytime ? p.temperature : p.temperature - 15,
        tempUnit: p.temperatureUnit,
        popMax: p.probabilityOfPrecipitation?.value ?? 0,
        shortForecast: p.shortForecast,
        detailedForecast: p.detailedForecast,
      });
    } else {
      const entry = map.get(baseDay)!;
      if (p.isDaytime) {
        entry.highTemp = p.temperature;
        entry.shortForecast = p.shortForecast;
        entry.detailedForecast = p.detailedForecast;
        entry.isDaytime = true;
      } else {
        entry.lowTemp = p.temperature;
      }
      const pPop = p.probabilityOfPrecipitation?.value ?? 0;
      if (pPop > entry.popMax) entry.popMax = pPop;
    }
  }

  return Array.from(map.values()).slice(0, 7);
}

function calculateSolarTimes(date: Date, lat: number, lon: number): {
  sunriseMinutes: number;
  sunsetMinutes: number;
  sunriseStr: string;
  noonStr: string;
  sunsetStr: string;
} {
  const startOfYear = new Date(date.getFullYear(), 0, 0);
  const diff = date.getTime() - startOfYear.getTime();
  const dayOfYear = Math.floor(diff / (1000 * 60 * 60 * 24));

  const deg2rad = Math.PI / 180;
  const rad2deg = 180 / Math.PI;

  const declination = 23.45 * Math.sin(deg2rad * (360 / 365) * (dayOfYear - 81));
  const b = deg2rad * (360 / 365) * (dayOfYear - 81);
  const eot = 9.87 * Math.sin(2 * b) - 7.53 * Math.cos(b) - 1.5 * Math.sin(b);

  const tzOffsetHours = -date.getTimezoneOffset() / 60;
  const solarNoonHour = 12 + tzOffsetHours - lon / 15 - eot / 60;

  const cosHourAngle = -Math.tan(deg2rad * lat) * Math.tan(deg2rad * declination);
  const clampedCos = Math.min(Math.max(cosHourAngle, -1), 1);
  const hourAngleDeg = rad2deg * Math.acos(clampedCos);

  const sunriseHour = solarNoonHour - hourAngleDeg / 15;
  const sunsetHour = solarNoonHour + hourAngleDeg / 15;

  const toMin = (h: number) => Math.round(h * 60);
  const formatH = (h: number) => {
    let hh = Math.floor(h);
    let mm = Math.round((h - hh) * 60);
    if (mm >= 60) {
      hh += 1;
      mm = 0;
    }
    const d = new Date(date);
    d.setHours(hh, mm, 0, 0);
    return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  };

  return {
    sunriseMinutes: toMin(sunriseHour),
    sunsetMinutes: toMin(sunsetHour),
    sunriseStr: formatH(sunriseHour),
    noonStr: formatH(solarNoonHour),
    sunsetStr: formatH(sunsetHour),
  };
}

function calculateMoonPhase(date: Date): { phaseName: string; illuminationPct: number; waxing: boolean } {
  // Epoch: Jan 11, 2024 (New Moon)
  const epoch = new Date(Date.UTC(2024, 0, 11, 11, 57, 0)).getTime();
  const synodicMonth = 29.53058867 * 24 * 60 * 60 * 1000;
  const diff = date.getTime() - epoch;
  const phase = ((diff % synodicMonth) + synodicMonth) % synodicMonth;
  const phaseFraction = phase / synodicMonth;

  let phaseName = "New Moon";
  if (phaseFraction < 0.03 || phaseFraction >= 0.97) phaseName = "New Moon";
  else if (phaseFraction < 0.22) phaseName = "Waxing Crescent";
  else if (phaseFraction < 0.28) phaseName = "First Quarter";
  else if (phaseFraction < 0.47) phaseName = "Waxing Gibbous";
  else if (phaseFraction < 0.53) phaseName = "Full Moon";
  else if (phaseFraction < 0.72) phaseName = "Waning Gibbous";
  else if (phaseFraction < 0.78) phaseName = "Third Quarter";
  else phaseName = "Waning Crescent";

  const illuminationPct = Math.round((1 - Math.cos(phaseFraction * 2 * Math.PI)) * 50);
  const waxing = phaseFraction <= 0.5;

  return { phaseName, illuminationPct, waxing };
}

function moonSvg(phaseName: string, size = 26): SVGElement {
  const p = phaseName.toLowerCase();
  if (p.includes("full")) {
    return createSvg(`<circle cx="12" cy="12" r="9" fill="#fef08a" stroke="#ffffff" stroke-width="1.5"/>`, "icon-moon-full", size);
  }
  if (p.includes("new")) {
    return createSvg(`<circle cx="12" cy="12" r="9" fill="#1e293b" stroke="#64748b" stroke-width="1.5"/>`, "icon-moon-new", size);
  }
  return createSvg(`<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" fill="#fef08a" stroke="#ffffff" stroke-width="1.5"/>`, "icon-moon-crescent", size);
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
