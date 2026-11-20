/**
 * Logique pure de la carte par zone et de la section « autres zones » du panneau
 * (contrat §8.3). Aucune dépendance au DOM : lit seulement les états et les
 * registres que le frontend HA publie dans `hass` (`states`, `entities`,
 * `devices`, `areas`), et se teste avec un `hass` synthétique.
 *
 * Tout `climate` d'une zone y est pris, quelle que soit son intégration (p. ex. une
 * tête Danfoss appairée directement à Zigbee2MQTT). Les autres entités de son
 * appareil complètent la ligne quand elles existent (batterie, vanne, fenêtre,
 * demande de chauffe, qualité de lien) : appariées par appareil, puis par
 * `device_class`, puis par clé (clé de traduction ou fin de l'`entity_id`, avec les
 * noms de Zigbee2MQTT et ceux de cette intégration).
 *
 * Seule écriture proposée pour un climate hors Ally : `climate.set_temperature`,
 * dans `min_temp` / `max_temp` / `target_temp_step`. Un climate de cette
 * intégration n'est JAMAIS écrit par ce chemin : il garde ses propres règles.
 */
import { LOW_BATTERY_PERCENT } from "./room";
import type { HassEntityEntry, HassEntityState, HassLike, Room } from "./types";

/** Domaine de cette intégration dans le registre des entités. */
export const ALLY_PLATFORM = "danfoss_ally_cloud";

/**
 * Intégrations qui pilotent les MÊMES têtes Danfoss Ally par un autre chemin (l'API
 * cloud officielle de Danfoss). Leurs climates sont montrés mais JAMAIS écrits par
 * ces cartes : ce serait écrire la consigne d'une tête Ally par un canal que cette
 * intégration n'a pas prouvé, à côté du programme de sa pièce.
 */
export const DUPLICATE_PLATFORMS: ReadonlySet<string> = new Set(["danfoss_ally"]);

/** Bit `TARGET_TEMPERATURE` de `ClimateEntityFeature` (consigne unique réglable). */
const FEATURE_TARGET_TEMPERATURE = 1;

/** Pas par défaut quand le climate ne publie pas `target_temp_step`. */
const DEFAULT_STEP = 0.5;

// Clés reconnues (Zigbee2MQTT d'abord, cette intégration ensuite), cf.
// docs/zigbee2mqtt-alignment.md.
const KEYS_TEMPERATURE = ["local_temperature", "temperature"];
const KEYS_BATTERY = ["battery"];
const KEYS_BATTERY_LOW = ["battery_low"];
const KEYS_VALVE = ["pi_heating_demand", "valve_opening"];
const KEYS_WINDOW_STATE = ["window_open_internal"];
const KEYS_WINDOW_BINARY = ["window_open_external", "window_open", "window"];
const KEYS_HEAT = ["heat_required"];
const KEYS_LINK = ["linkquality"];

/** États de `window_open_internal` (Zigbee2MQTT) qui signifient « ouverte ». */
const WINDOW_OPEN_STATES = new Set(["open", "external_open"]);

/** Ce que les autres entités de l'appareil d'un climate apportent (null = absent). */
export interface HeadExtras {
  battery: number | null;
  low_battery: boolean;
  valve_opening: number | null;
  window_open: boolean | null;
  heat_required: boolean | null;
  linkquality: number | null;
}

/** Vue d'un climate quelconque, prête à afficher. */
export interface ClimateView {
  entity_id: string;
  name: string;
  /** Le climate est de cette intégration (aucune écriture générique pour lui). */
  ally: boolean;
  /** Le climate pilote une tête Ally par une autre intégration (`DUPLICATE_PLATFORMS`). */
  duplicate: boolean;
  available: boolean;
  current: number | null;
  target: number | null;
  /** `hvac_action` brut (`heating`, `idle`, `off`…), ou `null`. */
  action: string | null;
  hvac_mode: string;
  min: number;
  max: number;
  step: number;
  supports_target: boolean;
  extras: HeadExtras;
}

/** Zone et ses climates (pour l'éditeur et le panneau). */
export interface AreaClimates {
  area_id: string;
  name: string;
  entity_ids: string[];
}

/** Santé agrégée d'une zone (lecture seule, panneau). */
export interface AreaSummary {
  count: number;
  temperature: number | null;
  setpoint_min: number | null;
  setpoint_max: number | null;
  heating: number;
  offline: number;
  low_battery: number;
  window_open: number;
}

const UNAVAILABLE = new Set(["unavailable", "unknown", ""]);

function domainOf(entityId: string): string {
  return entityId.split(".", 1)[0];
}

function objectId(entityId: string): string {
  const dot = entityId.indexOf(".");
  return dot < 0 ? entityId : entityId.slice(dot + 1);
}

function num(value: unknown): number | null {
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : null;
  }
  if (typeof value === "string" && value.trim() !== "") {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

/** L'entité porte-t-elle l'une des clés (clé de traduction, `entity_id` = clé ou finit par `_clé`) ? */
export function matchesKey(entry: HassEntityEntry, keys: readonly string[]): boolean {
  const oid = objectId(entry.entity_id);
  return keys.some(
    (key) => entry.translation_key === key || oid === key || oid.endsWith(`_${key}`),
  );
}

/** Zone effective d'une entité : la sienne, sinon celle de son appareil. */
export function entityArea(hass: HassLike, entityId: string): string | null {
  const entry = hass.entities?.[entityId];
  if (!entry) {
    return null;
  }
  if (entry.area_id) {
    return entry.area_id;
  }
  return (entry.device_id && hass.devices?.[entry.device_id]?.area_id) || null;
}

/** Le climate est-il de cette intégration ? */
export function isAllyEntity(hass: HassLike, entityId: string): boolean {
  return hass.entities?.[entityId]?.platform === ALLY_PLATFORM;
}

function climateName(hass: HassLike, entityId: string): string {
  const friendly = hass.states?.[entityId]?.attributes.friendly_name;
  if (typeof friendly === "string" && friendly) {
    return friendly;
  }
  return hass.entities?.[entityId]?.name || entityId;
}

function visibleClimates(hass: HassLike): HassEntityEntry[] {
  return Object.values(hass.entities ?? {}).filter(
    (e) => domainOf(e.entity_id) === "climate" && !e.hidden,
  );
}

function byName(hass: HassLike): (a: string, b: string) => number {
  return (a, b) => climateName(hass, a).localeCompare(climateName(hass, b));
}

/** Climates (non masqués) d'une zone, toutes intégrations, triés par nom. */
export function climatesInArea(hass: HassLike, areaId: string): string[] {
  return visibleClimates(hass)
    .map((e) => e.entity_id)
    .filter((id) => entityArea(hass, id) === areaId)
    .sort(byName(hass));
}

/**
 * Zones qui contiennent au moins un climate, triées par nom. Avec `foreignOnly`, ne
 * garde que les climates d'AUTRES intégrations (section « autres zones » du panneau).
 */
export function areasWithClimates(hass: HassLike, foreignOnly = false): AreaClimates[] {
  const byArea = new Map<string, string[]>();
  for (const entry of visibleClimates(hass)) {
    if (foreignOnly && entry.platform === ALLY_PLATFORM) {
      continue;
    }
    const area = entityArea(hass, entry.entity_id);
    if (!area || !hass.areas?.[area]) {
      continue;
    }
    byArea.set(area, [...(byArea.get(area) ?? []), entry.entity_id]);
  }
  return [...byArea.entries()]
    .map(([area_id, ids]) => ({
      area_id,
      name: hass.areas?.[area_id]?.name ?? area_id,
      entity_ids: ids.sort(byName(hass)),
    }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

/** Pièces Ally dont le thermostat de pièce est dans la zone, dans l'ordre reçu. */
export function allyRoomsInArea(hass: HassLike, rooms: Room[], areaId: string): Room[] {
  return rooms.filter(
    (room) => room.climate_entity_id && entityArea(hass, room.climate_entity_id) === areaId,
  );
}

type Sibling = { entry: HassEntityEntry; state: HassEntityState };

function siblings(hass: HassLike, entityId: string): Sibling[] {
  const deviceId = hass.entities?.[entityId]?.device_id;
  if (!deviceId) {
    return [];
  }
  const out: Sibling[] = [];
  for (const entry of Object.values(hass.entities ?? {})) {
    if (entry.device_id !== deviceId || entry.entity_id === entityId) {
      continue;
    }
    const state = hass.states?.[entry.entity_id];
    if (state && !UNAVAILABLE.has(state.state)) {
      out.push({ entry, state });
    }
  }
  return out;
}

function deviceClass(s: Sibling): unknown {
  return s.state.attributes.device_class;
}

/** Première entité trouvée : par `device_class` d'abord, puis par clé. */
function pick(
  list: Sibling[],
  domain: string,
  deviceClasses: readonly string[],
  keys: readonly string[],
): Sibling | undefined {
  const inDomain = list.filter((s) => domainOf(s.entry.entity_id) === domain);
  return (
    inDomain.find((s) => deviceClasses.includes(String(deviceClass(s)))) ??
    inDomain.find((s) => matchesKey(s.entry, keys))
  );
}

/** Ce que les autres entités de l'appareil du climate disent de la tête. */
export function headExtras(hass: HassLike, entityId: string): HeadExtras {
  const list = siblings(hass, entityId);
  const battery = num(pick(list, "sensor", ["battery"], KEYS_BATTERY)?.state.state);
  const batteryLow = pick(list, "binary_sensor", ["battery"], KEYS_BATTERY_LOW);
  const valve = num(pick(list, "sensor", [], KEYS_VALVE)?.state.state);

  let window: boolean | null = null;
  const windowBinary =
    pick(list, "binary_sensor", ["window"], KEYS_WINDOW_BINARY) ??
    pick(list, "switch", [], ["window_open_external"]);
  const windowState = pick(list, "sensor", [], KEYS_WINDOW_STATE);
  if (windowState) {
    window = WINDOW_OPEN_STATES.has(windowState.state.state);
  }
  if (windowBinary) {
    window = Boolean(window) || windowBinary.state.state === "on";
  }

  const heat = pick(list, "binary_sensor", [], KEYS_HEAT);
  const link = num(pick(list, "sensor", [], KEYS_LINK)?.state.state);
  return {
    battery,
    low_battery:
      batteryLow?.state.state === "on" || (battery !== null && battery <= LOW_BATTERY_PERCENT),
    valve_opening: valve,
    window_open: window,
    heat_required: heat ? heat.state.state === "on" : null,
    linkquality: link,
  };
}

/** Température mesurée de repli (capteur de l'appareil), quand le climate n'en publie pas. */
function fallbackTemperature(hass: HassLike, entityId: string): number | null {
  const list = siblings(hass, entityId).filter((s) => !s.entry.entity_category);
  return num(pick(list, "sensor", ["temperature"], KEYS_TEMPERATURE)?.state.state);
}

/** Vue d'un climate, ou `null` s'il n'a pas d'état. */
export function climateView(hass: HassLike, entityId: string): ClimateView | null {
  const st = hass.states?.[entityId];
  if (!st) {
    return null;
  }
  const a = st.attributes;
  const available = !UNAVAILABLE.has(st.state);
  const features = num(a.supported_features) ?? 0;
  const step = num(a.target_temp_step) ?? DEFAULT_STEP;
  return {
    entity_id: entityId,
    name: climateName(hass, entityId),
    ally: isAllyEntity(hass, entityId),
    duplicate: DUPLICATE_PLATFORMS.has(hass.entities?.[entityId]?.platform ?? ""),
    available,
    current: num(a.current_temperature) ?? fallbackTemperature(hass, entityId),
    target: num(a.temperature),
    action: typeof a.hvac_action === "string" ? a.hvac_action : null,
    hvac_mode: st.state,
    min: num(a.min_temp) ?? 7,
    max: num(a.max_temp) ?? 35,
    step: step > 0 ? step : DEFAULT_STEP,
    supports_target: (features & FEATURE_TARGET_TEMPERATURE) !== 0,
    extras: headExtras(hass, entityId),
  };
}

/**
 * La carte peut-elle proposer ± sur ce climate ? Jamais pour un climate de cette
 * intégration (ses règles d'écriture sont celles de la pièce, §8.1), ni pour une tête
 * Ally vue par une autre intégration (`DUPLICATE_PLATFORMS`), ni s'il est indisponible,
 * éteint, sans consigne unique réglable ou sans consigne. La carte exige en plus que
 * l'écriture soit activée dans sa configuration (`allow_foreign_writes`).
 */
export function canAdjustClimate(view: ClimateView): boolean {
  return (
    !view.ally &&
    !view.duplicate &&
    view.available &&
    view.hvac_mode !== "off" &&
    view.supports_target &&
    view.target !== null
  );
}

/**
 * Consigne après un pas, alignée sur le pas et bornée à [min, max] ; `null` si elle
 * ne change pas (déjà en butée) ou si le climate n'est pas réglable.
 */
export function steppedClimateTarget(view: ClimateView, direction: 1 | -1): number | null {
  if (!canAdjustClimate(view) || view.target === null) {
    return null;
  }
  const raw = Math.round((view.target + direction * view.step) / view.step) * view.step;
  const next = Number(Math.min(view.max, Math.max(view.min, raw)).toFixed(2));
  return next === view.target ? null : next;
}

/** Agrège les climates d'une zone (moyenne des mesures, plage des consignes, comptes). */
export function areaSummary(hass: HassLike, entityIds: readonly string[]): AreaSummary {
  const views = entityIds
    .map((id) => climateView(hass, id))
    .filter((v): v is ClimateView => v !== null);
  const live = views.filter((v) => v.available);
  const temps = live.map((v) => v.current).filter((x): x is number => x !== null);
  const targets = live.map((v) => v.target).filter((x): x is number => x !== null);
  return {
    count: views.length,
    temperature: temps.length
      ? Math.round((temps.reduce((s, x) => s + x, 0) / temps.length) * 10) / 10
      : null,
    setpoint_min: targets.length ? Math.min(...targets) : null,
    setpoint_max: targets.length ? Math.max(...targets) : null,
    heating: live.filter((v) => v.action === "heating").length,
    offline: views.length - live.length,
    low_battery: views.filter((v) => v.extras.low_battery).length,
    window_open: views.filter((v) => v.extras.window_open).length,
  };
}

function degrees(value: number): string {
  return `${Number.isInteger(value) ? value : value.toFixed(1)} °C`;
}

/** « 19.5 °C → 20 °C » ou « 19.5 °C → 19–21 °C », `null` si rien à montrer. */
export function areaClimateLine(summary: AreaSummary): string | null {
  const { temperature, setpoint_min: lo, setpoint_max: hi } = summary;
  if (temperature === null && lo === null) {
    return null;
  }
  const left = temperature === null ? "–" : degrees(temperature);
  if (lo === null || hi === null) {
    return left;
  }
  const right =
    lo === hi
      ? degrees(lo)
      : `${Number.isInteger(lo) ? lo : lo.toFixed(1)}–${degrees(hi)}`;
  return `${left} → ${right}`;
}
