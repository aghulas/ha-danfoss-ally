/**
 * Page d'un élément du panneau (contrat §8.2) : logique pure, sans DOM.
 *
 * Un élément est une tête, un capteur de pièce, un relais de chaudière ou une passerelle. Son état vient de
 * ce que le panneau a déjà lu (`overview`, `rooms`) ; ses réglages sont les ENTITÉS de
 * son appareil Home Assistant, lues dans les registres du frontend (`hass.devices`,
 * `hass.entities`, `hass.states`). Le panneau ne les écrit jamais lui-même : une ligne
 * ouvre la fenêtre d'entité de Home Assistant, où chaque entité garde ses propres règles
 * (validation, indisponible plutôt que mensongère).
 */
import { ALLY_PLATFORM } from "./area";
import type {
  FleetGateway,
  FleetHome,
  FleetOverview,
  FleetRelay,
  FleetRoom,
  FleetSensor,
  HassLike,
  HeadState,
  Room,
} from "./types";

/** Élément retrouvé, avec ce qui le situe (maison, pièce) et son état connu. */
export type PanelElement =
  | { kind: "head"; id: string; name: string; online: boolean; home: FleetHome; room: FleetRoom; head: HeadState | null }
  | { kind: "sensor"; id: string; name: string; online: boolean; home: FleetHome; room: FleetRoom | null; sensor: FleetSensor }
  | { kind: "relay"; id: string; name: string; online: boolean; home: FleetHome; relay: FleetRelay }
  | { kind: "gateway"; id: string; name: string; online: boolean; home: FleetHome; gateway: FleetGateway };

/** Tête d'une pièce, telle que la page de la pièce la liste. */
export interface RoomHead {
  id: string;
  name: string;
  online: boolean;
  head: HeadState | null;
}

/**
 * Têtes d'une pièce : celles de `rooms` pour une pièce groupée, la tête unique de la vue
 * d'ensemble pour une pièce d'une seule tête. Liste vide si `rooms` ne connaît pas la pièce.
 */
export function roomHeads(room: FleetRoom, rooms: readonly Room[]): RoomHead[] {
  if (room.kind === "single_head") {
    const id = room.head_id ?? room.id;
    return [{ id, name: room.head_name ?? room.name, online: room.online !== false, head: null }];
  }
  const full = rooms.find((r) => r.id === room.id);
  return (full?.heads ?? []).map((head) => ({
    id: head.device_id,
    name: head.name,
    online: head.online,
    head,
  }));
}

/** Capteurs de pièce d'une maison qui mesurent la pièce donnée. */
export function roomSensors(home: FleetHome, roomId: string): FleetSensor[] {
  return (home.sensors ?? []).filter((s) => s.room_id === roomId);
}

/**
 * Capteurs d'une maison sans pièce connue dans cette maison (lien absent, ou pièce
 * disparue) : le bâtiment les montre lui-même, pour qu'aucun ne soit invisible.
 */
export function unplacedSensors(home: FleetHome): FleetSensor[] {
  return (home.sensors ?? []).filter(
    (s) => s.room_id === null || !home.rooms.some((r) => r.id === s.room_id),
  );
}

/** Retrouve un élément par son identifiant d'appareil, ou `null`. */
export function findElement(
  overview: FleetOverview | null,
  rooms: readonly Room[],
  deviceId: string,
): PanelElement | null {
  for (const home of overview?.homes ?? []) {
    for (const room of home.rooms) {
      const hit = roomHeads(room, rooms).find((h) => h.id === deviceId);
      if (hit) {
        return { kind: "head", id: hit.id, name: hit.name, online: hit.online, home, room, head: hit.head };
      }
    }
    const sensor = (home.sensors ?? []).find((s) => s.device_id === deviceId);
    if (sensor) {
      const room = home.rooms.find((r) => r.id === sensor.room_id) ?? null;
      return { kind: "sensor", id: deviceId, name: sensor.name, online: sensor.online, home, room, sensor };
    }
    const relay = home.relays.find((r) => r.device_id === deviceId);
    if (relay) {
      return { kind: "relay", id: deviceId, name: relay.name, online: relay.online !== false, home, relay };
    }
    const gateway = home.gateways.find((g) => g.device_id === deviceId);
    if (gateway) {
      return { kind: "gateway", id: deviceId, name: gateway.name, online: gateway.online, home, gateway };
    }
  }
  return null;
}

/** Identifiant de registre de l'appareil HA d'une pièce groupée (thermostat de pièce). */
export function roomDeviceIdent(groupId: string): string {
  return `group_${groupId}`;
}

/**
 * Appareil Home Assistant de cette intégration qui porte l'identifiant donné
 * (`identifiers` contient `[danfoss_ally_cloud, ident]`), ou `null`.
 */
export function haDeviceId(hass: HassLike | undefined, ident: string): string | null {
  for (const device of Object.values(hass?.devices ?? {})) {
    if ((device.identifiers ?? []).some(([domain, id]) => domain === ALLY_PLATFORM && id === ident)) {
      return device.id;
    }
  }
  return null;
}

/** Groupe d'affichage d'une entité, d'après sa catégorie. */
export type EntityGroup = "controls" | "config" | "diagnostic";

export const ENTITY_GROUPS: readonly EntityGroup[] = ["controls", "config", "diagnostic"];

/** Ligne d'entité prête à afficher. */
export interface EntityRow {
  entity_id: string;
  name: string;
  /** État brut (`on`, `21.5`, `unavailable`…). */
  state: string;
  unit: string | null;
  available: boolean;
}

const UNAVAILABLE = new Set(["unavailable", "unknown", ""]);

/** Nom d'une entité sans le nom de son appareil en préfixe (« Salle 1 Batterie » → « Batterie »). */
function shortName(friendly: string, deviceName: string | null): string {
  if (deviceName && friendly.toLowerCase().startsWith(`${deviceName.toLowerCase()} `)) {
    const rest = friendly.slice(deviceName.length + 1).trim();
    if (rest) {
      return rest.charAt(0).toUpperCase() + rest.slice(1);
    }
  }
  return friendly;
}

/**
 * Entités d'un appareil HA, par groupe (commandes et mesures, réglages, diagnostic),
 * triées par nom. Sont écartées : les entités masquées et celles sans état (désactivées).
 * Une entité indisponible RESTE listée, marquée indisponible : elle n'est jamais cachée
 * ni remplacée par une valeur supposée.
 */
export function deviceEntities(
  hass: HassLike | undefined,
  deviceId: string,
): Record<EntityGroup, EntityRow[]> {
  const out: Record<EntityGroup, EntityRow[]> = { controls: [], config: [], diagnostic: [] };
  const device = hass?.devices?.[deviceId];
  const deviceName = device?.name_by_user || device?.name || null;
  for (const entry of Object.values(hass?.entities ?? {})) {
    if (entry.device_id !== deviceId || entry.hidden) {
      continue;
    }
    const st = hass?.states?.[entry.entity_id];
    if (!st) {
      continue;
    }
    const friendly = st.attributes.friendly_name;
    const unit = st.attributes.unit_of_measurement;
    const group: EntityGroup =
      entry.entity_category === "config"
        ? "config"
        : entry.entity_category === "diagnostic"
          ? "diagnostic"
          : "controls";
    out[group].push({
      entity_id: entry.entity_id,
      name: shortName(
        typeof friendly === "string" && friendly ? friendly : entry.name || entry.entity_id,
        deviceName,
      ),
      state: st.state,
      unit: typeof unit === "string" && unit ? unit : null,
      available: !UNAVAILABLE.has(st.state),
    });
  }
  for (const group of ENTITY_GROUPS) {
    out[group].sort((a, b) => a.name.localeCompare(b.name) || a.entity_id.localeCompare(b.entity_id));
  }
  return out;
}

/** Nombre total d'entités listées. */
export function entityCount(groups: Record<EntityGroup, EntityRow[]>): number {
  return ENTITY_GROUPS.reduce((n, g) => n + groups[g].length, 0);
}
