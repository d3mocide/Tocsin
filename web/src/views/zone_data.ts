export interface ZoneGeo {
  code: string;
  name: string;
  center: [number, number];
  polygon: [number, number][];
}

/**
 * NWS Public Forecast Zones (PQR WFO 2024 realignment)
 * Polygon bounds covering NW Oregon & SW Washington forecast zones around PDX.
 */
export const NWS_ZONES: Record<string, ZoneGeo> = {
  ORZ108: {
    code: "ORZ108",
    name: "Lower Columbia River",
    center: [45.87, -122.85],
    polygon: [
      [45.72, -122.95],
      [46.10, -123.18],
      [46.15, -122.90],
      [45.88, -122.78],
      [45.72, -122.95],
    ],
  },
  ORZ109: {
    code: "ORZ109",
    name: "Tualatin Valley",
    center: [45.52, -122.98],
    polygon: [
      [45.38, -123.12],
      [45.65, -123.10],
      [45.62, -122.80],
      [45.36, -122.75],
      [45.38, -123.12],
    ],
  },
  ORZ110: {
    code: "ORZ110",
    name: "West Hills & Chehalem Mts",
    center: [45.46, -122.84],
    polygon: [
      [45.28, -122.98],
      [45.58, -122.85],
      [45.56, -122.72],
      [45.28, -122.88],
      [45.28, -122.98],
    ],
  },
  ORZ111: {
    code: "ORZ111",
    name: "Inner Portland Metro",
    center: [45.52, -122.65],
    polygon: [
      [45.43, -122.75],
      [45.62, -122.78],
      [45.60, -122.56],
      [45.42, -122.58],
      [45.43, -122.75],
    ],
  },
  ORZ112: {
    code: "ORZ112",
    name: "East Portland Metro",
    center: [45.52, -122.45],
    polygon: [
      [45.44, -122.56],
      [45.60, -122.56],
      [45.56, -122.32],
      [45.42, -122.36],
      [45.44, -122.56],
    ],
  },
  ORZ113: {
    code: "ORZ113",
    name: "Outer SE Portland Metro",
    center: [45.38, -122.52],
    polygon: [
      [45.26, -122.64],
      [45.44, -122.58],
      [45.42, -122.38],
      [45.26, -122.46],
      [45.26, -122.64],
    ],
  },
  ORZ114: {
    code: "ORZ114",
    name: "West Central Willamette Valley",
    center: [45.10, -123.20],
    polygon: [
      [44.85, -123.35],
      [45.35, -123.30],
      [45.30, -123.05],
      [44.85, -123.10],
      [44.85, -123.35],
    ],
  },
  ORZ115: {
    code: "ORZ115",
    name: "East Central Willamette Valley",
    center: [44.95, -122.95],
    polygon: [
      [44.75, -123.08],
      [45.25, -123.00],
      [45.20, -122.70],
      [44.75, -122.75],
      [44.75, -123.08],
    ],
  },
  ORZ119: {
    code: "ORZ119",
    name: "West Columbia Gorge OR (Upper)",
    center: [45.58, -122.18],
    polygon: [
      [45.48, -122.30],
      [45.60, -122.30],
      [45.68, -121.90],
      [45.50, -121.90],
      [45.48, -122.30],
    ],
  },
  ORZ120: {
    code: "ORZ120",
    name: "West Columbia Gorge OR (I-84)",
    center: [45.60, -122.10],
    polygon: [
      [45.53, -122.32],
      [45.58, -122.32],
      [45.71, -121.85],
      [45.65, -121.85],
      [45.53, -122.32],
    ],
  },
  ORZ123: {
    code: "ORZ123",
    name: "Clackamas Cascade Foothills",
    center: [45.30, -122.25],
    polygon: [
      [45.10, -122.45],
      [45.42, -122.38],
      [45.40, -122.00],
      [45.10, -122.05],
      [45.10, -122.45],
    ],
  },
  WAZ204: {
    code: "WAZ204",
    name: "Cowlitz County Lowlands",
    center: [46.18, -122.90],
    polygon: [
      [45.92, -122.88],
      [46.35, -123.00],
      [46.38, -122.70],
      [45.95, -122.65],
      [45.92, -122.88],
    ],
  },
  WAZ205: {
    code: "WAZ205",
    name: "North Clark County Lowlands",
    center: [45.82, -122.58],
    polygon: [
      [45.70, -122.75],
      [45.95, -122.72],
      [45.92, -122.40],
      [45.68, -122.42],
      [45.70, -122.75],
    ],
  },
  WAZ206: {
    code: "WAZ206",
    name: "Inner Vancouver Metro",
    center: [45.65, -122.62],
    polygon: [
      [45.60, -122.75],
      [45.72, -122.75],
      [45.70, -122.52],
      [45.58, -122.52],
      [45.60, -122.75],
    ],
  },
  WAZ207: {
    code: "WAZ207",
    name: "East Clark County Lowlands",
    center: [45.62, -122.40],
    polygon: [
      [45.56, -122.52],
      [45.70, -122.52],
      [45.68, -122.25],
      [45.54, -122.28],
      [45.56, -122.52],
    ],
  },
  WAZ208: {
    code: "WAZ208",
    name: "South WA Cascade Foothills",
    center: [45.90, -122.25],
    polygon: [
      [45.70, -122.40],
      [46.20, -122.40],
      [46.18, -122.00],
      [45.68, -122.05],
      [45.70, -122.40],
    ],
  },
  WAZ209: {
    code: "WAZ209",
    name: "West Columbia Gorge WA (SR 14)",
    center: [45.65, -121.98],
    polygon: [
      [45.58, -122.25],
      [45.68, -122.25],
      [45.75, -121.80],
      [45.65, -121.80],
      [45.58, -122.25],
    ],
  },
};
