/**
 * Logique pure de la carte pièce (axe D). Aucune dépendance au DOM ni à Home
 * Assistant : testable par Vitest. La carte n'écrit QUE via des services déjà
 * validés (contrat §8.1) ; ce module décide seulement QUAND proposer une action.
 */
import type { HeadState, Room } from "./types";

/** Modes où le thermostat de pièce accepte une écriture de consigne (R3, climate). */
export const ADJUSTABLE_MODES: ReadonlySet<string> = new Set(["at_home", "leaving_home"]);

/** Pas de consigne (°C), aligné sur le thermostat (contrat §3). */
export const SETPOINT_STEP = 0.5;

/** Seuil de batterie faible (%), partagé avec les climates hors Ally (carte par zone). */
export const LOW_BATTERY_PERCENT = 10;

/** Une tête est en batterie faible si un défaut E14/E15 est posé, ou batterie ≤ 10 %. */
export function isLowBattery(head: Pick<HeadState, "battery" | "faults">): boolean {
  if ((head.faults ?? []).some((f) => f.code === "E14" || f.code === "E15")) {
    return true;
  }
  return head.battery != null && head.battery <= LOW_BATTERY_PERCENT;
}

/**
 * La consigne de la pièce est-elle réglable depuis la carte ? Vrai seulement si le
 * produit est vérifié, l'entité climate connue, le mode confort/réduit et une
 * consigne présente — sinon le thermostat refuserait proprement (on n'affiche pas
 * un bouton qui ment).
 */
export function canAdjustSetpoint(room: Room): boolean {
  return Boolean(
    room.writable &&
      room.climate_entity_id &&
      room.mode &&
      ADJUSTABLE_MODES.has(room.mode) &&
      room.setpoint != null,
  );
}

/** Consigne suivante après un pas (± SETPOINT_STEP), arrondie au pas. */
export function steppedSetpoint(current: number, direction: 1 | -1): number {
  const next = current + direction * SETPOINT_STEP;
  return Math.round(next / SETPOINT_STEP) * SETPOINT_STEP;
}

/** Une tête de la pièce ne suit plus son programme (propose « revenir au programme », R4). */
export function roomNeedsRestore(room: Room): boolean {
  return room.heads.some((h) => h.schedule_active === false);
}
