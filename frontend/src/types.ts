/**
 * Types partagés avec le backend. Formes figées par docs/interface-contract.md
 * (sections 3 et 5.3). Ne pas diverger du contrat sans le modifier d'abord.
 */

/** Cible d'un programme : une pièce (`room`) ou une tête isolée (`device`). */
export interface Target {
  type: "room" | "device";
  id: string;
}

/** Défaut décodé d'une tête (contrat §3.3, table DP 45/184). */
export interface Fault {
  code: string;
  bit?: number;
  label?: string;
  action?: string;
}

/** État d'une tête (contrat §3.3). */
export interface HeadState {
  device_id: string;
  name: string;
  room_id: string | null;
  online: boolean;
  mode_displayed: string;
  schedule_active: boolean | null;
  preheat: boolean | null;
  mounting: boolean;
  inconsistent: boolean;
  // Champs d'état (lecture seule, ajoutés en 0.6.0 / axe D) ; `null` si le DP est absent.
  battery: number | null;
  valve_opening: number | null;
  heat_request: boolean | null;
  window_open: boolean | null;
  window_detection: boolean | null;
  child_lock: boolean | null;
  faults: Fault[];
}

/** Pièce (contrat §3.4). */
export interface Room {
  id: string;
  name: string;
  home?: string;
  product_id: string;
  heads: HeadState[];
  comfort: number | null;
  setback: number | null;
  // Climat vivant + droits d'écriture (lecture seule, axe D) ; optionnels pour rester
  // compatibles avec un backend 0.5.x qui ne les renvoie pas encore.
  temperature?: number | null;
  setpoint?: number | null;
  mode?: string | null;
  heating?: boolean | null;
  online?: boolean;
  writable?: boolean;
  climate_entity_id?: string | null;
}

/** Jours de la semaine, lundi d'abord (contrat §3). */
export type DayKey = "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun";

/** Plage de confort d'un jour : heures `HH:MM` sur 24 h (contrat §3.2). */
export interface TimeRange {
  start: string;
  end: string;
}

/** Programme hebdomadaire d'une cible (contrat §3.2). */
export interface Schedule {
  target: Target;
  name: string;
  comfort: number | null;
  setback: number | null;
  /** Toujours les sept jours ; liste vide = jour entièrement en réduit. */
  days: Record<DayKey, TimeRange[]>;
  max_transitions_per_day: number;
  source: string;
  /** Horodatage ISO de la dernière lecture (contrat §3.2). */
  read_at: string | null;
}

/** Réponse de `danfoss_ally_cloud/info` (contrat §5.3). */
export interface Info {
  version: string;
  local_enabled: boolean;
  is_admin: boolean;
}

/** État d'une tête dans le suivi d'un lot d'écriture (contrat §3.5). */
export interface JobHead {
  device_id: string;
  status: "pending" | "applied" | "mismatch" | "unreachable" | "unverified";
  detail: string | null;
}

/** Suivi d'une écriture de programme (contrat §3.5). */
export interface WriteJob {
  job_id: string;
  kind: string;
  target: Target;
  status: "sent" | "applied" | "partial" | "unverified" | "failed";
  created_at: string;
  heads: JobHead[];
}

/** Réponse de `danfoss_ally_cloud/schedule/validate` (contrat §5.3 / §5.4). */
export interface ValidateResponse {
  valid: boolean;
  errors: { code: string; message: string; day: string | null }[];
  transitions: Record<string, number>;
}

/**
 * Sous-ensemble de l'objet `hass` de Home Assistant dont la carte a besoin.
 * Volontairement minimal pour rester testable et utilisable par la page de démo.
 */
export interface HassLike {
  callWS<T = unknown>(msg: Record<string, unknown>): Promise<T>;
  /**
   * Appel de service HA (p. ex. `climate.set_temperature`). Optionnel : absent de
   * la démo et des tests. La carte pièce ne l'utilise que pour réutiliser un
   * service DÉJÀ validé (jamais un nouveau chemin d'écriture, contrat §8.1).
   */
  callService?: (
    domain: string,
    service: string,
    data?: Record<string, unknown>,
  ) => Promise<unknown>;
  // Fonction de localisation du frontend HA (clé -> texte). Optionnelle : repli en dur.
  localize?: (key: string, ...args: unknown[]) => string;
  /**
   * États et registres du frontend HA (optionnels : absents de la démo et des vieux
   * tests). Lus pour la carte par zone et la section « autres zones » du panneau.
   */
  states?: Record<string, HassEntityState>;
  entities?: Record<string, HassEntityEntry>;
  devices?: Record<string, HassDeviceEntry>;
  areas?: Record<string, HassAreaEntry>;
  /** Utilisateur courant ; `is_admin` garde l'écriture d'un climate hors Ally. */
  user?: { is_admin?: boolean };
  language?: string;
  /**
   * Connexion WebSocket de Home Assistant, pour les commandes à abonnement
   * (`jobs/subscribe`). Optionnelle : absente dans la démo et les tests, auquel
   * cas l'abonnement se dégrade en « rien » (unsubscribe sans effet).
   */
  connection?: {
    subscribeMessage<T = unknown>(
      callback: (message: T) => void,
      subscription: Record<string, unknown>,
    ): Promise<() => void>;
  };
}

/** Configuration de la carte `danfoss-ally-schedule-card`. */
export interface ScheduleCardConfig {
  type?: string;
  /** `group_id` de la pièce (en chaîne), cf. contrat §1. */
  room_id?: string;
}

/** Configuration de la carte `danfoss-ally-room-card` (axe D). */
export interface RoomCardConfig {
  type?: string;
  /** `group_id` de la pièce (en chaîne). */
  room_id?: string;
  /**
   * Zone Home Assistant (`area_id`) : la carte montre tous les `climate` de la zone,
   * quelle que soit leur intégration, et la pièce Danfoss Ally qui s'y trouve (§8.1).
   */
  area_id?: string;
  /**
   * Avec `area_id` : propose ± (`climate.set_temperature`) sur les climates d'AUTRES
   * intégrations, pour un administrateur. Désactivé par défaut : la carte est alors en
   * lecture seule pour eux. Jamais pour une tête Ally vue par une autre intégration.
   */
  allow_foreign_writes?: boolean;
}

// --- Registres du frontend HA (sous-ensemble lu par la carte et le panneau, §8.3). ---

/** État d'une entité (`hass.states[entity_id]`). */
export interface HassEntityState {
  entity_id: string;
  state: string;
  attributes: Record<string, unknown>;
}

/** Entrée du registre des entités telle que le frontend la publie (`hass.entities`). */
export interface HassEntityEntry {
  entity_id: string;
  device_id?: string | null;
  area_id?: string | null;
  platform?: string;
  translation_key?: string | null;
  entity_category?: string | null;
  hidden?: boolean;
  name?: string | null;
}

/** Entrée du registre des appareils (`hass.devices`). */
export interface HassDeviceEntry {
  id: string;
  area_id?: string | null;
  name?: string | null;
  name_by_user?: string | null;
}

/** Entrée du registre des zones (`hass.areas`). */
export interface HassAreaEntry {
  area_id: string;
  name: string;
}

// --- Vue d'ensemble de la flotte (contrat §3.6, axe D) : lecture seule. ---

/** Passerelle dans la vue d'ensemble. */
export interface FleetGateway {
  device_id: string;
  name: string;
  online: boolean;
}

/**
 * Santé agrégée d'une pièce dans la vue d'ensemble. `kind` distingue une pièce
 * groupée (groupe-programme, ≥ 2 têtes) d'une pièce d'une seule tête, sans groupe
 * (contrat §3.6). Les champs ajoutés après 1.2.0 sont optionnels : un backend plus
 * ancien ne les envoie pas.
 */
export interface FleetRoom {
  id: string;
  name: string;
  kind?: "group" | "single_head";
  /** Pièce d'une tête : nom tiré de la pièce de l'app (`room`) ou, à défaut, de la tête (`head`). */
  name_source?: "room" | "head";
  room_id?: string | null;
  head_id?: string;
  head_name?: string;
  head_count: number;
  online?: boolean;
  offline: number;
  low_battery: number;
  heating: boolean;
  window_open: boolean;
  inconsistent: number;
  faults: number;
  temperature?: number | null;
  setpoint?: number | null;
}

/** Relais de chaudière dans la vue d'ensemble. */
export interface FleetRelay {
  device_id: string;
  name: string;
  on: boolean | null;
  online: boolean;
  linked_rooms: number;
}

/** Une maison (account "home") dans la vue d'ensemble. */
export interface FleetHome {
  gid: string;
  name: string;
  holiday_active: boolean;
  gateways: FleetGateway[];
  rooms: FleetRoom[];
  relays: FleetRelay[];
}

/** Totaux à l'échelle du bâtiment. */
export interface FleetTotals {
  homes: number;
  gateways: number;
  rooms: number;
  heads: number;
  offline: number;
  low_battery: number;
  heating: number;
  faults: number;
  relays_on: number;
}

/** Réponse de `danfoss_ally_cloud/overview` (contrat §3.6). */
export interface FleetOverview {
  homes: FleetHome[];
  totals: FleetTotals;
}
