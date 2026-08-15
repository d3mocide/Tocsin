import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { el } from "../dom";
import { apiSource, isActive, tierOf } from "../format";
import type { Store } from "../store";
import type { Alert } from "../types";
import { NWS_ZONES } from "./zone_data";

const RADAR_LOCAL_LAYER = "ridge::RTX-N0B-0";
const RADAR_WIDE_LAYER = "ridge::USCOMP-N0Q-0";
const RADAR_WIDE_MAX_ZOOM = 6;

function radarTileUrl(layer: string): string {
  return `https://mesonet.agron.iastate.edu/cache/tile.py/1.0.0/${layer}/{z}/{x}/{y}.png`;
}

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
  private map: L.Map | null = null;
  private zoneGroup: L.LayerGroup | null = null;
  private stationGroup: L.LayerGroup | null = null;
  private operatorGroup: L.LayerGroup | null = null;
  private radarLocalLayer: L.TileLayer | null = null;
  private radarWideLayer: L.TileLayer | null = null;
  private radarZoomListenerAttached = false;
  private showRadar = false;
  private tileStatus = "Live";

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
      setTimeout(() => this.map?.invalidateSize(), 100);
    }
  }

  private initMap(): void {
    this.container.innerHTML = "";

    const checkbox = el("input", {
      class: "map-checkbox",
      attrs: { type: "checkbox", id: "map-radar-toggle" },
    }) as HTMLInputElement;

    checkbox.addEventListener("change", () => {
      this.showRadar = checkbox.checked;
      this.toggleRadar();
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
      el("div", { class: "map-status-pill", text: `Tiles: ${this.tileStatus}` }),
    );

    const mapDiv = el("div", { class: "map-canvas", attrs: { id: "leaflet-map-canvas" } });
    this.container.appendChild(controls);
    this.container.appendChild(mapDiv);

    // Initial center on Pacific Northwest (Portland / Seattle regional view)
    this.map = L.map(mapDiv, {
      center: [45.52, -122.67],
      zoom: 7,
      zoomControl: true,
      attributionControl: false,
    });

    // Dark Carto tiles
    const tileUrl = "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png";
    const tiles = L.tileLayer(tileUrl, {
      maxZoom: 18,
      subdomains: "abcd",
    });

    tiles.on("tileerror", () => {
      this.tileStatus = "Offline (Vector Mode)";
      const statusEl = this.container.querySelector(".map-status-pill");
      if (statusEl) statusEl.textContent = `Tiles: ${this.tileStatus}`;
    });

    tiles.addTo(this.map);

    this.zoneGroup = L.layerGroup().addTo(this.map);
    this.operatorGroup = L.layerGroup().addTo(this.map);
    this.stationGroup = L.layerGroup().addTo(this.map);
  }

  private toggleRadar(): void {
    if (!this.map) return;

    if (this.showRadar) {
      if (!this.radarLocalLayer) {
        this.radarLocalLayer = L.tileLayer(radarTileUrl(RADAR_LOCAL_LAYER), {
          opacity: 0.55,
          maxZoom: 18,
          maxNativeZoom: 11,
        });
      }
      if (!this.radarWideLayer) {
        this.radarWideLayer = L.tileLayer(radarTileUrl(RADAR_WIDE_LAYER), {
          opacity: 0.50,
          maxZoom: 18,
          maxNativeZoom: 11,
        });
      }

      if (!this.radarZoomListenerAttached) {
        this.map.on("zoomend", this.updateRadarForZoom, this);
        this.radarZoomListenerAttached = true;
      }
      this.updateRadarForZoom();
    } else {
      if (this.radarZoomListenerAttached) {
        this.map.off("zoomend", this.updateRadarForZoom, this);
        this.radarZoomListenerAttached = false;
      }
      if (this.radarLocalLayer) this.map.removeLayer(this.radarLocalLayer);
      if (this.radarWideLayer) this.map.removeLayer(this.radarWideLayer);
    }
  }

  private updateRadarForZoom(): void {
    if (!this.map || !this.showRadar || !this.radarLocalLayer || !this.radarWideLayer) return;

    const useWide = this.map.getZoom() <= RADAR_WIDE_MAX_ZOOM;
    if (useWide) {
      if (this.map.hasLayer(this.radarLocalLayer)) this.map.removeLayer(this.radarLocalLayer);
      if (!this.map.hasLayer(this.radarWideLayer)) this.radarWideLayer.addTo(this.map);
    } else {
      if (this.map.hasLayer(this.radarWideLayer)) this.map.removeLayer(this.radarWideLayer);
      if (!this.map.hasLayer(this.radarLocalLayer)) this.radarLocalLayer.addTo(this.map);
    }
  }

  private async fetchMissingZoneGeo(code: string): Promise<void> {
    if (ZONE_GEO_CACHE[code] || pendingZoneFetches.has(code)) return;
    pendingZoneFetches.add(code);

    try {
      const isCounty = code.length === 6 && (code.includes("C") || /^[0-9]+$/.test(code));
      const url = isCounty
        ? `https://api.weather.gov/zones/county/${code}`
        : `https://api.weather.gov/zones/forecast/${code}`;

      const res = await fetch(url, { headers: { Accept: "application/geo+json" } });
      if (res.ok) {
        const json = await res.json();
        if (json.geometry) {
          saveZoneGeoToStorage(code, json.geometry);
          this.updateLayers();
        }
      }
    } catch {
      // Offline or network error
    } finally {
      pendingZoneFetches.delete(code);
    }
  }

  private updateLayers(): void {
    if (!this.map || !this.zoneGroup || !this.stationGroup || !this.operatorGroup) return;

    this.zoneGroup.clearLayers();
    this.operatorGroup.clearLayers();
    this.stationGroup.clearLayers();

    const alertsMap = this.store.state.alerts;
    const alerts: Alert[] = alertsMap ? Array.from(alertsMap.values()) : [];
    const reference = this.store.state.reference;
    const stations = reference?.stations ?? {};
    const system = this.store.state.system;

    let activeAdvisoryCount = 0;

    // 1. Draw Real NWS Alert Polygons with Authentic Color Palette
    for (const alert of alerts) {
      if (!isActive(alert)) continue;
      activeAdvisoryCount++;

      const tier = tierOf(alert, reference) ?? "C";
      const cap = apiSource(alert);
      const style = alertHazardStyle(alert.event_name, tier);

      const popupHtml = `
        <div class="map-popup">
          <div class="map-popup-title">⚠️ ${alert.event_name}</div>
          <div class="map-popup-sub">
            <b>Area:</b> ${cap?.area_desc ?? "Monitored Region"}<br/>
            <b>Severity:</b> <span class="badge badge-tier-${tier.toLowerCase()}">Tier ${tier}</span>
            ${cap?.expires ? `<br/><b>Expires:</b> ${new Date(cap.expires).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}` : ""}
          </div>
        </div>
      `;

      // Case A: Alert contains exact GeoJSON geometry from NWS
      if (cap?.geometry && cap.geometry.coordinates) {
        const geoLayer = L.geoJSON(cap.geometry, {
          style: {
            color: style.color,
            fillColor: style.fillColor,
            fillOpacity: style.fillOpacity,
            weight: style.weight,
          },
        });
        geoLayer.bindPopup(popupHtml);
        geoLayer.bindTooltip(`⚠️ ${alert.event_name}`, { sticky: true });
        this.zoneGroup.addLayer(geoLayer);
        continue;
      }

      // Case B: Render UGC / SAME zones
      const ugcCodes = cap?.ugc_codes ?? [];
      for (const ugc of ugcCodes) {
        const cachedGeo = loadZoneGeoFromStorage(ugc);
        if (cachedGeo) {
          const geoLayer = L.geoJSON(cachedGeo, {
            style: {
              color: style.color,
              fillColor: style.fillColor,
              fillOpacity: style.fillOpacity,
              weight: style.weight,
            },
          });
          geoLayer.bindPopup(popupHtml);
          geoLayer.bindTooltip(`⚠️ ${alert.event_name} (${ugc})`, { sticky: true });
          this.zoneGroup.addLayer(geoLayer);
        } else if (NWS_ZONES[ugc]) {
          const geo = NWS_ZONES[ugc];
          const polygon = L.polygon(geo.polygon as [number, number][], {
            color: style.color,
            fillColor: style.fillColor,
            fillOpacity: style.fillOpacity,
            weight: style.weight,
          });
          polygon.bindPopup(popupHtml);
          polygon.bindTooltip(`⚠️ ${alert.event_name} (${geo.name})`, { sticky: true });
          this.zoneGroup.addLayer(polygon);
        } else {
          // Fetch real NWS polygon geometry asynchronously for this zone
          void this.fetchMissingZoneGeo(ugc);
        }
      }
    }

    // 2. Draw Operator Position & Coverage Range Ring (Matches Screenshot 1)
    const lat = system?.latitude;
    const lon = system?.longitude;

    if (lat !== undefined && lon !== undefined && lat !== null && lon !== null) {
      // 40-mile (64.3 km) Reception Range Ring
      const rangeRing = L.circle([lat, lon], {
        radius: 64374,
        color: "#38bdf8",
        fillColor: "#0284c7",
        fillOpacity: 0.08,
        weight: 1.5,
        dashArray: "4, 4",
      });
      rangeRing.bindTooltip("Receiver RF Coverage Radius (~40 mi)", { sticky: true });
      this.operatorGroup.addLayer(rangeRing);

      // Operator Location Crosshair Marker
      const operatorIcon = L.divIcon({
        className: "custom-operator-marker-container",
        html: `
          <div class="operator-marker">
            <div class="operator-pulse"></div>
            <div class="operator-crosshair"></div>
          </div>
        `,
        iconSize: [20, 20],
        iconAnchor: [10, 10],
      });

      const operatorMarker = L.marker([lat, lon], { icon: operatorIcon });
      operatorMarker.bindPopup(`
        <div class="map-popup">
          <div class="map-popup-title">🎯 Receiver Base Station</div>
          <div class="map-popup-sub">
            <b>Location:</b> ${lat.toFixed(4)}°, ${lon.toFixed(4)}°<br/>
            <b>RF Receiver:</b> Active SDR Monitoring
          </div>
        </div>
      `);
      operatorMarker.bindTooltip("🎯 Receiver Location", { direction: "top" });
      this.operatorGroup.addLayer(operatorMarker);
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

      const towerIcon = L.divIcon({
        className: "custom-tower-marker-container",
        html: `
          <div class="tower-marker ${statusClass}">
            ${isMonitored ? '<div class="tower-pulse"></div>' : ""}
            <div class="tower-dot"></div>
          </div>
        `,
        iconSize: [16, 16],
        iconAnchor: [8, 8],
      });

      const marker = L.marker([station.lat, station.lon], { icon: towerIcon });
      const distStr = station.distance_km !== null ? `${station.distance_km.toFixed(1)} km away` : "";

      const popupHtml = `
        <div class="map-popup">
          <div class="map-popup-title">📻 ${station.name} (${callsign}) ${isMonitored ? '<span class="badge badge-tier-a" style="font-size:0.65rem;margin-left:0.3rem;">📡 MONITORED</span>' : ""}</div>
          <div class="map-popup-sub">
            <b>${station.frequency_mhz.toFixed(3)} MHz</b> · WFO ${station.wfo}<br/>
            Power: ${station.power_watts ?? 0}W · Status: <span style="color:${markerColor}">${station.status}</span><br/>
            ${distStr ? `<b>${distStr}</b>` : ""}
          </div>
        </div>
      `;

      marker.bindPopup(popupHtml);
      marker.bindTooltip(`📻 NWR ${callsign} (${station.name})${isMonitored ? " [Monitored]" : ""}`, { direction: "top" });
      this.stationGroup.addLayer(marker);
    }

    // Update map status pill
    const statusEl = this.container.querySelector(".map-status-pill");
    if (statusEl) {
      statusEl.textContent = `Active Advisories: ${activeAdvisoryCount} | Tiles: ${this.tileStatus}`;
    }
  }
}
