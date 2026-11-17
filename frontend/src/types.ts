/**
 * Types partagés avec le backend. Formes figées par docs/contrat-interface.md
 * (sections 3 et 5.3). Ne pas diverger du contrat sans le modifier d'abord.
 */

/** Cible d'un programme : une pièce (`room`) ou une tête isolée (`device`). */
export interface Target {
  type: "room" | "device";
  id: string;
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
}

/** Pièce (contrat §3.4). */
export interface Room {
  id: string;
  name: string;
  home: string;
  product_id: string;
  heads: HeadState[];
  comfort: number | null;
  setback: number | null;
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
  // Fonction de localisation du frontend HA (clé -> texte). Optionnelle : repli en dur.
  localize?: (key: string, ...args: unknown[]) => string;
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
