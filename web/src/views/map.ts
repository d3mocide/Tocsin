import type { Feature, FeatureCollection, Polygon } from "geojson";
import {
  Map as MapLibreMap,
  Marker,
  Popup,
  setWorkerUrl,
  type GeoJSONSource,
  type StyleSpecification,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import { el } from "../dom";
import { apiSource, isActive, tierOf } from "../format";
import type { Store } from "../store";
import type { Alert } from "../types";
import { NWS_ZONES, type ZoneGeo } from "./zone_data";

// maplibre-gl derives its worker script URL at runtime from its own bundled
// chunk's import.meta.url + a hardcoded filename -- a pattern Vite's static
// asset scanner can't see, so `vite build` never copies maplibre-gl-worker.mjs
// into dist/assets. The result 404s in production (served by FastAPI's SPA
// fallback as a JSON 404, which the browser then refuses to run as a worker
// for MIME-type mismatch), silently disabling all vector tile rendering.
// Importing the worker file with `?url` makes Vite bundle it as a real,
// correctly-hashed asset; setWorkerUrl() points maplibre at it directly,
// bypassing the broken runtime derivation.
setWorkerUrl(maplibreWorkerUrl);

const RADAR_LOCAL_LAYER = "ridge::RTX-N0B-0";
const RADAR_WIDE_LAYER = "ridge::USCOMP-N0Q-0";
const RADAR_WIDE_MAX_ZOOM = 6;

function radarTileUrl(layer: string): string {
  return `https://mesonet.agron.iastate.edu/cache/tile.py/1.0.0/${layer}/{z}/{x}/{y}.png`;
}

// Free, keyless vector basemap. CARTO's raster tiles (the previous basemap)
// now require a registered API key -- see carto.com/basemaps/apikey -- which
// would turn a cosmetic enhancement into an account-management dependency.
const DARK_STYLE_URL = "https://tiles.openfreemap.org/styles/dark";

// A blocked/blackholed route (common on a firewalled or offgrid network) lets
// fetch() hang far longer than a plain refusal -- without a deadline the map
// sits on OFFLINE_STYLE indefinitely while the status pill still claims "Live".
const BASEMAP_FETCH_TIMEOUT_MS = 6000;

// Zero-network style so the map -- and our own zone/station overlays, which
// don't depend on the basemap at all -- render instantly even with no route
// to tiles.openfreemap.org. See CLAUDE.md's "no hard network dependency" rule.
const OFFLINE_STYLE: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: "background", type: "background", paint: { "background-color": "#090c10" } }],
};

const ZONES_SOURCE_ID = "tocsin-zones";
const ZONES_FILL_LAYER_ID = "tocsin-zones-fill";
const ZONES_LINE_LAYER_ID = "tocsin-zones-line";
const RADAR_LOCAL_ID = "tocsin-radar-local";
const RADAR_WIDE_ID = "tocsin-radar-wide";

// In-memory + persistent localStorage cache for NWS Zone GeoJSON geometry
const ZONE_GEO_CACHE: Record<string, any> = {};
const pendingZoneFetches = new Set<string>();

function loadZoneGeoFromStorage(code: string): any | null {
  if (ZONE_GEO_CACHE[code]) return ZONE_GEO_CACHE[code];
  try {
    const raw = localStorage.getItem(`tocsin_zone_geo_${code}`);
    if (raw) {
      const parsed = JSON.parse(raw);
      ZONE_GEO_CACHE[code] = parsed;
      return parsed;
    }
  } catch {
    // Storage access failed
  }
  return null;
}

function saveZoneGeoToStorage(code: string, geometry: any): void {
  ZONE_GEO_CACHE[code] = geometry;
  try {
    localStorage.setItem(`tocsin_zone_geo_${code}`, JSON.stringify(geometry));
  } catch {
    // Storage write failed
  }
}

// NWS_ZONES polygons are stored as [lat, lon] pairs (built for a
// lat/lon-first mapping library); GeoJSON -- and MapLibre -- expect [lon, lat].
function zonePolygonGeometry(geo: ZoneGeo): Polygon {
  return {
    type: "Polygon",
    coordinates: [geo.polygon.map(([lat, lon]): [number, number] => [lon, lat])],
  };
}

export function alertHazardStyle(
  eventName: string,
  tier: string,
): { color: string; fillColor: string; fillOpacity: number; weight: number } {
  const name = eventName.toLowerCase();

  // Fire Weather / Red Flag Warning (Vibrant Magenta / Pink)
  if (name.includes("red flag") || name.includes("fire weather") || name.includes("burn")) {
    return { color: "#f43f5e", fillColor: "#be185d", fillOpacity: 0.50, weight: 2.0 };
  }
  // Severe Storm / Tornado / Hurricane (Crimson Red)
  if (name.includes("tornado") || name.includes("severe") || name.includes("extreme wind")) {
    return { color: "#ef4444", fillColor: "#dc2626", fillOpacity: 0.55, weight: 2.5 };
  }
  // Flood / Flash Flood / Marine (Forest Green)
  if (name.includes("flood") || name.includes("marine") || name.includes("coastal") || name.includes("tsunami")) {
    return { color: "#22c55e", fillColor: "#15803d", fillOpacity: 0.48, weight: 2.0 };
  }
  // Winter Storm / Blizzard / Ice / Freeze (Ice Blue / Cyan)
  if (
    name.includes("winter") ||
    name.includes("blizzard") ||
    name.includes("snow") ||
    name.includes("ice") ||
    name.includes("freeze") ||
    name.includes("frost")
  ) {
    return { color: "#38bdf8", fillColor: "#0284c7", fillOpacity: 0.48, weight: 2.0 };
  }
  // Excessive Heat / Heat Advisory (Amber Orange)
  if (name.includes("heat")) {
    return { color: "#f97316", fillColor: "#ea580c", fillOpacity: 0.48, weight: 2.0 };
  }
  // Air Quality / Smoke / Fog / Statements (Charcoal Slate / Gray)
  if (
    name.includes("air quality") ||
    name.includes("smoke") ||
    name.includes("fog") ||
    name.includes("statement") ||
    name.includes("advisory")
  ) {
    return { color: "#94a3b8", fillColor: "#475569", fillOpacity: 0.45, weight: 1.5 };
  }

  // Fallback by Tier
  if (tier === "A") return { color: "#ef4444", fillColor: "#dc2626", fillOpacity: 0.50, weight: 2.0 };
  if (tier === "B") return { color: "#f97316", fillColor: "#ea580c", fillOpacity: 0.45, weight: 1.8 };
  return { color: "#94a3b8", fillColor: "#475569", fillOpacity: 0.38, weight: 1.5 };
}

export class MapView {
  private readonly container: HTMLElement;
  private readonly store: Store;
  private map: MapLibreMap | null = null;
  private stationMarkers: Marker[] = [];
  private operatorMarker: Marker | null = null;
  private hoverPopup: Popup | null = null;
  private showRadar = false;
  private tileStatus = "Loading…";
  private activeAdvisoryCount = 0;

  constructor(container: HTMLElement, store: Store) {
    this.container = container;
    this.store = store;
  }

  render(): void {
    if (!this.map) {
      this.initMap();
    }
    this.updateLayers();
  }

  invalidateSize(): void {
    if (this.map) {
      setTimeout(() => this.map?.resize(), 100);
    }
  }

  private statusPillText(): string {
    return `Active Advisories: ${this.activeAdvisoryCount} | Tiles: ${this.tileStatus}`;
  }

  private setTileStatus(status: string): void {
    if (this.tileStatus === status) return;
    this.tileStatus = status;
    const statusEl = this.container.querySelector(".map-status-pill");
    if (statusEl) statusEl.textContent = this.statusPillText();
  }

  private initMap(): void {
    this.container.innerHTML = "";

    const checkbox = el("input", {
      class: "map-checkbox",
      attrs: { type: "checkbox", id: "map-radar-toggle" },
    }) as HTMLInputElement;

    checkbox.addEventListener("change", () => {
      this.showRadar = checkbox.checked;
      this.applyRadarVisibility();
    });

    const controls = el(
      "div",
      { class: "map-controls-bar" },
      el(
        "label",
        { class: "map-toggle-label", attrs: { for: "map-radar-toggle" } },
        checkbox,
        el("span", { text: " NEXRAD Radar Overlay" }),
      ),
      el("div", { class: "map-status-pill", text: this.statusPillText() }),
    );

    const mapDiv = el("div", { class: "map-canvas", attrs: { id: "map-canvas" } });
    this.container.appendChild(controls);
    this.container.appendChild(mapDiv);

    // Initial center on Pacific Northwest (Portland / Seattle regional view)
    this.map = new MapLibreMap({
      container: mapDiv,
      style: OFFLINE_STYLE,
      center: [-122.67, 45.52],
      zoom: 7,
      // Collapse to just the info icon by default; the full text is one click away.
      attributionControl: { compact: true },
    });

    // Fires after the initial (offline) style loads and again after every
    // setStyle() below -- both wipe any sources/layers we added, so this is
    // the one place overlays get (re)built.
    this.map.on("style.load", () => {
      this.ensureOverlayLayers();
      this.applyRadarVisibility();
      this.updateLayers();
    });

    this.map.on("error", () => this.setTileStatus("Offline (Vector Mode)"));
    this.map.on("zoomend", () => this.applyRadarVisibility());

    // OpenFreeMap's "dark" style references city/town dot icons as
    // "circle-11", but its sprite sheet only defines them as "circle_11" --
    // an upstream naming mismatch (verified against the live sprite JSON),
    // not anything in our own style config. Alias it rather than let every
    // affected label silently drop its dot and spam styleimagemissing.
    this.map.setMissingStyleImageResolver((id) => {
      const fallback = id === "circle-11" ? "circle_11" : null;
      if (!fallback || !this.map || this.map.hasImage(id) || !this.map.hasImage(fallback)) return;
      const source = this.map.getImage(fallback);
      this.map.addImage(id, source.data, { pixelRatio: source.pixelRatio, sdf: source.sdf });
    });

    this.map.on("click", ZONES_FILL_LAYER_ID, (e) => {
      const feature = e.features?.[0];
      if (!feature || !this.map) return;
      new Popup().setLngLat(e.lngLat).setHTML(String(feature.properties?.popupHtml ?? "")).addTo(this.map);
    });
    this.map.on("mouseenter", ZONES_FILL_LAYER_ID, () => {
      if (this.map) this.map.getCanvas().style.cursor = "pointer";
    });
    this.map.on("mouseleave", ZONES_FILL_LAYER_ID, () => {
      if (this.map) this.map.getCanvas().style.cursor = "";
      this.hoverPopup?.remove();
    });
    this.map.on("mousemove", ZONES_FILL_LAYER_ID, (e) => {
      const feature = e.features?.[0];
      if (!feature || !this.map) return;
      this.hoverPopup ??= new Popup({ closeButton: false, closeOnClick: false, className: "map-hover-tooltip" });
      this.hoverPopup.setLngLat(e.lngLat).setText(String(feature.properties?.tooltipText ?? "")).addTo(this.map);
    });

    void this.loadRemoteBasemap();
  }

  private async loadRemoteBasemap(): Promise<void> {
    try {
      const res = await fetch(DARK_STYLE_URL, { signal: AbortSignal.timeout(BASEMAP_FETCH_TIMEOUT_MS) });
      if (!res.ok) throw new Error(`basemap fetch failed: ${res.status}`);
      const style = (await res.json()) as StyleSpecification;
      // The trivial OFFLINE_STYLE it's replacing can still be mid-load internally
      // even though it looks instant, racing setStyle()'s default diff attempt and
      // triggering a harmless but noisy "Style is not done loading" warning -- skip
      // diffing outright since we're always doing a full swap, never a partial update.
      this.map?.setStyle(style, { diff: false });
      this.setTileStatus("Live");
    } catch {
      // Offline, blocked, or timed-out -- stay on the local OFFLINE_STYLE.
      this.setTileStatus("Offline (Vector Mode)");
    }
  }

  private ensureOverlayLayers(): void {
    if (!this.map) return;

    if (!this.map.getSource(RADAR_WIDE_ID)) {
      this.map.addSource(RADAR_WIDE_ID, { type: "raster", tiles: [radarTileUrl(RADAR_WIDE_LAYER)], tileSize: 256, maxzoom: 11 });
      this.map.addLayer({
        id: RADAR_WIDE_ID,
        type: "raster",
        source: RADAR_WIDE_ID,
        paint: { "raster-opacity": 0.50 },
        layout: { visibility: "none" },
      });
    }

    if (!this.map.getSource(RADAR_LOCAL_ID)) {
      this.map.addSource(RADAR_LOCAL_ID, { type: "raster", tiles: [radarTileUrl(RADAR_LOCAL_LAYER)], tileSize: 256, maxzoom: 11 });
      this.map.addLayer({
        id: RADAR_LOCAL_ID,
        type: "raster",
        source: RADAR_LOCAL_ID,
        paint: { "raster-opacity": 0.55 },
        layout: { visibility: "none" },
      });
    }

    if (!this.map.getSource(ZONES_SOURCE_ID)) {
      this.map.addSource(ZONES_SOURCE_ID, { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      this.map.addLayer({
        id: ZONES_FILL_LAYER_ID,
        type: "fill",
        source: ZONES_SOURCE_ID,
        paint: { "fill-color": ["get", "fillColor"], "fill-opacity": ["get", "fillOpacity"] },
      });
      this.map.addLayer({
        id: ZONES_LINE_LAYER_ID,
        type: "line",
        source: ZONES_SOURCE_ID,
        paint: { "line-color": ["get", "color"], "line-width": ["get", "weight"] },
      });
    }
  }

  private applyRadarVisibility(): void {
    if (!this.map || !this.map.getLayer(RADAR_LOCAL_ID) || !this.map.getLayer(RADAR_WIDE_ID)) return;

    if (!this.showRadar) {
      this.map.setLayoutProperty(RADAR_LOCAL_ID, "visibility", "none");
      this.map.setLayoutProperty(RADAR_WIDE_ID, "visibility", "none");
      return;
    }

    const useWide = this.map.getZoom() <= RADAR_WIDE_MAX_ZOOM;
    this.map.setLayoutProperty(RADAR_LOCAL_ID, "visibility", useWide ? "none" : "visible");
    this.map.setLayoutProperty(RADAR_WIDE_ID, "visibility", useWide ? "visible" : "none");
  }

  private async fetchMissingZoneGeo(code: string): Promise<void> {
    if (ZONE_GEO_CACHE[code] || pendingZoneFetches.has(code)) return;
    pendingZoneFetches.add(code);

    try {
      // Query universal NWS zone endpoint which resolves fire, county, forecast, and public zones
      const url = `https://api.weather.gov/zones?include_geometry=true&id=${encodeURIComponent(code)}`;
      const res = await fetch(url, { headers: { Accept: "application/geo+json" } });
      if (res.ok) {
        const json = await res.json();
        const feat = json.features?.[0] || (json.geometry ? json : null);
        if (feat?.geometry) {
          saveZoneGeoToStorage(code, feat.geometry);
          this.updateLayers();
        }
      }
    } catch {
      // Offline or network error handled gracefully
    } finally {
      pendingZoneFetches.delete(code);
    }
  }

  private updateLayers(): void {
    if (!this.map) return;
    const zoneSource = this.map.getSource(ZONES_SOURCE_ID) as GeoJSONSource | undefined;
    if (!zoneSource) return;

    this.stationMarkers.forEach((marker) => marker.remove());
    this.stationMarkers = [];
    this.operatorMarker?.remove();
    this.operatorMarker = null;

    const alertsMap = this.store.state.alerts;
    const alerts: Alert[] = alertsMap ? Array.from(alertsMap.values()) : [];
    const reference = this.store.state.reference;
    const stations = reference?.stations ?? {};
    const system = this.store.state.system;

    const zoneFeatures: Feature[] = [];
    this.activeAdvisoryCount = 0;

    // 1. Draw Real NWS Alert Polygons with Authentic Color Palette
    for (const alert of alerts) {
      if (!isActive(alert)) continue;
      this.activeAdvisoryCount++;

      const tier = tierOf(alert, reference) ?? "C";
      const cap = apiSource(alert);
      const style = alertHazardStyle(alert.event_name, tier);

      const popupHtml = `
        <div class="map-popup">
          <div class="map-popup-title">${alert.event_name}</div>
          <div class="map-popup-sub">
            <b>Area:</b> ${cap?.area_desc ?? "Monitored Region"}<br/>
            <b>Severity:</b> <span class="badge badge-tier-${tier.toLowerCase()}">Tier ${tier}</span>
            ${cap?.expires ? `<br/><b>Expires:</b> ${new Date(cap.expires).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}` : ""}
          </div>
        </div>
      `;

      const properties = {
        color: style.color,
        fillColor: style.fillColor,
        fillOpacity: style.fillOpacity,
        weight: style.weight,
        popupHtml,
      };

      // Case A: Alert contains exact GeoJSON geometry from NWS
      if (cap?.geometry && cap.geometry.coordinates) {
        zoneFeatures.push({
          type: "Feature",
          geometry: cap.geometry,
          properties: { ...properties, tooltipText: alert.event_name },
        });
        continue;
      }

      // Case B: Render UGC / SAME zones
      const ugcCodes = cap?.ugc_codes ?? [];
      for (const ugc of ugcCodes) {
        const cachedGeo = loadZoneGeoFromStorage(ugc);
        if (cachedGeo) {
          zoneFeatures.push({
            type: "Feature",
            geometry: cachedGeo,
            properties: { ...properties, tooltipText: `${alert.event_name} (${ugc})` },
          });
        } else if (NWS_ZONES[ugc]) {
          const geo = NWS_ZONES[ugc];
          zoneFeatures.push({
            type: "Feature",
            geometry: zonePolygonGeometry(geo),
            properties: { ...properties, tooltipText: `${alert.event_name} (${geo.name})` },
          });
        } else {
          // Fetch real NWS polygon geometry asynchronously for this zone
          void this.fetchMissingZoneGeo(ugc);
        }
      }
    }

    const zoneCollection: FeatureCollection = { type: "FeatureCollection", features: zoneFeatures };
    zoneSource.setData(zoneCollection);

    // 2. Draw Operator Receiver Location
    const lat = system?.latitude;
    const lon = system?.longitude;

    if (lat !== undefined && lon !== undefined && lat !== null && lon !== null) {
      const operatorEl = document.createElement("div");
      operatorEl.className = "custom-operator-marker-container";
      operatorEl.innerHTML = `
        <div class="operator-marker">
          <div class="operator-pulse"></div>
          <div class="operator-crosshair"></div>
        </div>
      `;
      this.bindHoverLabel(operatorEl, [lon, lat], "Receiver Location");

      const popup = new Popup().setHTML(`
        <div class="map-popup">
          <div class="map-popup-title">Receiver Base Station</div>
          <div class="map-popup-sub">
            <b>Location:</b> ${lat.toFixed(4)}°, ${lon.toFixed(4)}°<br/>
            <b>RF Receiver:</b> Active SDR Monitoring
          </div>
        </div>
      `);

      this.operatorMarker = new Marker({ element: operatorEl })
        .setLngLat([lon, lat])
        .setPopup(popup)
        .addTo(this.map);
    }

    // 3. Draw NWR Radio Transmitters
    let nearestCallsign: string | null = null;
    let minStationDist = Number.POSITIVE_INFINITY;
    for (const [callsign, station] of Object.entries(stations)) {
      if (station.lat === null || station.lon === null) continue;
      const d = station.distance_miles ?? (station.distance_km !== null ? station.distance_km * 0.621371 : null);
      if (d !== null && d < minStationDist) {
        minStationDist = d;
        nearestCallsign = callsign;
      }
    }

    for (const [callsign, station] of Object.entries(stations)) {
      if (station.lat === null || station.lon === null) continue;

      const distMiles = station.distance_miles ?? (station.distance_km !== null ? station.distance_km * 0.621371 : null);
      if (distMiles !== null && distMiles > 150) continue;

      const isNormal = station.status.toUpperCase() === "NORMAL";
      const isMonitored = isNormal && (callsign === nearestCallsign || (distMiles !== null && distMiles <= 35));

      const statusClass = isNormal
        ? isMonitored
          ? "tower-icon-active"
          : "tower-icon-normal"
        : "tower-icon-abnormal";
      const markerColor = isNormal ? (isMonitored ? "#22c55e" : "#16a34a") : "#ef4444";

      const towerEl = document.createElement("div");
      towerEl.className = "custom-tower-marker-container";
      towerEl.innerHTML = `
        <div class="tower-marker ${statusClass}">
          ${isMonitored ? '<div class="tower-pulse"></div>' : ""}
          <div class="tower-dot"></div>
        </div>
      `;
      this.bindHoverLabel(towerEl, [station.lon, station.lat], `NWR ${callsign} (${station.name})${isMonitored ? " [Monitored]" : ""}`);

      const distStr = station.distance_km !== null ? `${station.distance_km.toFixed(1)} km away` : "";
      const popupHtml = `
        <div class="map-popup">
          <div class="map-popup-title">${station.name} (${callsign}) ${isMonitored ? '<span class="badge badge-tier-a" style="font-size:0.65rem;margin-left:0.3rem;">MONITORED</span>' : ""}</div>
          <div class="map-popup-sub">
            <b>${station.frequency_mhz.toFixed(3)} MHz</b> · WFO ${station.wfo}<br/>
            Power: ${station.power_watts ?? 0}W · Status: <span style="color:${markerColor}">${station.status}</span><br/>
            ${distStr ? `<b>${distStr}</b>` : ""}
          </div>
        </div>
      `;

      const marker = new Marker({ element: towerEl })
        .setLngLat([station.lon, station.lat])
        .setPopup(new Popup().setHTML(popupHtml))
        .addTo(this.map);
      this.stationMarkers.push(marker);
    }

    // Update map status pill
    const statusEl = this.container.querySelector(".map-status-pill");
    if (statusEl) statusEl.textContent = this.statusPillText();
  }

  private bindHoverLabel(element: HTMLElement, lngLat: [number, number], text: string): void {
    element.addEventListener("mouseenter", () => {
      if (!this.map) return;
      this.hoverPopup ??= new Popup({ closeButton: false, closeOnClick: false, className: "map-hover-tooltip" });
      this.hoverPopup.setLngLat(lngLat).setText(text).addTo(this.map);
    });
    element.addEventListener("mouseleave", () => this.hoverPopup?.remove());
  }
}
