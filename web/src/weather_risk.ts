/** Which active alerts bear on fire weather and air quality, and a fire-danger
 * estimate from a surface observation. Only real inputs go in: no observation
 * (or no alert) means no estimate, never a made-up "safe" number. */

export const FIRE_ALERT = /red flag|fire weather|extreme fire danger|fire warning/i;
/** The NWS products that actually declare critical fire weather. */
export const FIRE_ESCALATING = /red flag|fire weather|extreme fire danger/i;
export const AIR_ALERT = /air quality|smoke|dust|ashfall|air stagnation/i;

export interface FireInputs {
  rh: number | null;
  tempF: number | null;
  wind: number | null;
}

export interface FireDanger {
  /** 0 Low .. 4 Extreme. */
  index: 0 | 1 | 2 | 3 | 4;
  label: string;
  color: string;
  explanation: string;
}

/** `null` when there is nothing real to base an estimate on. */
export function fireDanger(obs: FireInputs | null, redFlag: boolean): FireDanger | null {
  const known = obs !== null && obs.rh !== null && obs.tempF !== null;
  if (!known && !redFlag) return null;
  const rh = obs?.rh ?? 100;
  const tempF = obs?.tempF ?? 0;
  const wind = obs?.wind ?? 0;

  if (redFlag || (rh <= 18 && wind >= 15 && tempF >= 82)) {
    return {
      index: 4,
      label: "CRITICAL / RED FLAG",
      color: "#e11d48",
      explanation: redFlag
        ? "The NWS has an active fire weather product for this area."
        : "Very low humidity, strong winds and heat: conditions for rapid fire spread.",
    };
  }
  if (rh <= 22 && (wind >= 12 || tempF >= 88)) {
    return { index: 3, label: "VERY HIGH", color: "#f97316", explanation: "Dry fuels and active breezes support rapid fire spread." };
  }
  if (rh <= 28 && (wind >= 8 || tempF >= 80)) {
    return { index: 2, label: "HIGH", color: "#eab308", explanation: "Low humidity; afternoon gusts can dry fine fuels quickly." };
  }
  if (rh <= 38) {
    return { index: 1, label: "MODERATE", color: "#38bdf8", explanation: "Seasonal drying with manageable wind." };
  }
  return { index: 0, label: "LOW", color: "#22c55e", explanation: "High humidity and light winds keep ignition risk minimal." };
}

/** Observed present weather that points to smoke, haze or dust. */
export const hazyWeather = (description: string | null | undefined): boolean =>
  /smoke|haze|dust|ash/i.test(description ?? "");
