/**
 * Logique pure des tuiles de pièce du panneau (vue d'ensemble, contrat §3.6 / §8.2).
 * Aucune dépendance au DOM ni à Home Assistant : testable par Vitest.
 *
 * Une pièce de l'app qui n'a qu'UNE tête n'a pas de groupe-programme : le backend
 * la rend avec `kind: "single_head"`. Elle s'affiche comme les autres pièces, avec
 * « 1× » ; aucune écriture de pièce n'existe pour elle (ses écritures sont celles
 * d'une tête isolée), le panneau n'en propose donc aucune.
 */
import type { FleetRoom } from "./types";

/** Pièce d'une seule tête, sans groupe. */
export function isSingleHead(room: FleetRoom): boolean {
  return room.kind === "single_head";
}

/** Pièce sans alerte (ni hors ligne, ni batterie faible, ni défaut, ni fenêtre ouverte). */
export function isHealthy(room: FleetRoom): boolean {
  return room.offline === 0 && room.low_battery === 0 && room.faults === 0 && !room.window_open;
}

function norm(name: string | undefined): string {
  return (name ?? "").toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");
}

/**
 * Nom de la tête à montrer sous le nom de la pièce, ou `null` s'il n'apporte rien
 * (pièce groupée, nom identique, ou pièce déjà nommée d'après la tête).
 */
export function headNameHint(room: FleetRoom): string | null {
  if (!isSingleHead(room) || room.name_source === "head" || !room.head_name) {
    return null;
  }
  return norm(room.head_name) === norm(room.name) ? null : room.head_name;
}

/** Pièce nommée d'après sa tête faute d'avoir retrouvé la pièce de l'app (repli signalé). */
export function namedAfterHead(room: FleetRoom): boolean {
  return isSingleHead(room) && room.name_source === "head";
}

function degrees(value: number): string {
  return `${Number.isInteger(value) ? value : value.toFixed(1)} °C`;
}

/** Ligne de climat « 19.5 °C → 20 °C » (mesure → consigne active), `null` si rien à montrer. */
export function climateLine(room: FleetRoom): string | null {
  const temp = room.temperature ?? null;
  const setpoint = room.setpoint ?? null;
  if (temp === null && setpoint === null) {
    return null;
  }
  const left = temp === null ? "–" : degrees(temp);
  return setpoint === null ? left : `${left} → ${degrees(setpoint)}`;
}
