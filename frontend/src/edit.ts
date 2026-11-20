/**
 * Opérations d'édition d'un programme (lot 5), pures et immuables.
 *
 * Ajouter / supprimer / déplacer / redimensionner une plage, saisie directe des
 * heures, copie d'un jour vers d'autres, et calcul des jours réellement modifiés
 * (pour n'envoyer que ceux-là, cf. cahier des charges lot 5). Aucune dépendance
 * au DOM ni à Home Assistant : testable par Vitest.
 *
 * Toutes les fonctions renvoient de nouveaux objets ; elles ne mutent jamais
 * leurs arguments.
 */
import { parseHHMM } from "./schedule";
import type { DayKey, TimeRange } from "./types";

/** Pas d'édition en minutes (contrat : programme au pas de 5 min). */
export const SNAP_MINUTES = 5;

/** Durée minimale d'une plage en minutes (un pas). */
export const MIN_RANGE_MINUTES = SNAP_MINUTES;

/** Dernière minute représentable (`23:59`). */
const LAST_MINUTE = 23 * 60 + 59;

/** Minutes depuis minuit → `HH:MM` (modulo 24 h, toujours deux chiffres). */
export function formatHHMM(minutes: number): string {
  const m = ((Math.round(minutes) % 1440) + 1440) % 1440;
  const h = Math.floor(m / 60);
  return `${String(h).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}

/** Arrondit au pas de 5 min et borne dans `[0, 23:59]`. */
export function snapMinutes(minutes: number): number {
  const snapped = Math.round(minutes / SNAP_MINUTES) * SNAP_MINUTES;
  return Math.max(0, Math.min(LAST_MINUTE, snapped));
}

function replace(ranges: TimeRange[], index: number, next: TimeRange): TimeRange[] {
  return ranges.map((r, i) => (i === index ? next : r));
}

/** Trie les plages par heure de début (les mal formées en fin, ordre stable). */
export function sortRanges(ranges: TimeRange[]): TimeRange[] {
  return [...ranges].sort(
    (a, b) => (parseHHMM(a.start) ?? Infinity) - (parseHHMM(b.start) ?? Infinity),
  );
}

/** Trie les plages par heure de début tout en conservant l'index d'origine dans `ranges`. */
export function sortIndexedRanges(
  ranges: TimeRange[],
): { range: TimeRange; index: number }[] {
  return ranges
    .map((range, index) => ({ range, index }))
    .sort(
      (a, b) => (parseHHMM(a.range.start) ?? Infinity) - (parseHHMM(b.range.start) ?? Infinity),
    );
}

/**
 * Premier créneau libre d'au moins `durationMin` minutes, ou `null` si la
 * journée est pleine. Sert à placer une nouvelle plage sans chevauchement.
 */
export function firstFreeSlot(
  ranges: TimeRange[],
  durationMin = 60,
): { start: number; end: number } | null {
  const parsed = ranges
    .map((r) => ({ s: parseHHMM(r.start), e: parseHHMM(r.end) }))
    .filter((r): r is { s: number; e: number } =>
      r.s !== null && r.e !== null && r.e > r.s,
    )
    .sort((a, b) => a.s - b.s);
  let cursor = 0;
  for (const r of parsed) {
    if (r.s - cursor >= durationMin) {
      return { start: cursor, end: cursor + durationMin };
    }
    cursor = Math.max(cursor, r.e);
  }
  if (1440 - cursor >= durationMin) {
    return { start: cursor, end: cursor + durationMin };
  }
  return null;
}

/**
 * Ajoute une plage : `08:00–17:00` si le jour est vide, sinon le premier
 * créneau libre d'une heure. Sans place, renvoie le jour inchangé.
 */
export function addRange(ranges: TimeRange[]): TimeRange[] {
  if (ranges.length === 0) {
    return [{ start: "08:00", end: "17:00" }];
  }
  const slot = firstFreeSlot(ranges, 60);
  if (!slot) {
    return ranges;
  }
  return sortRanges([
    ...ranges,
    { start: formatHHMM(slot.start), end: formatHHMM(slot.end) },
  ]);
}

/** Supprime la plage d'indice `index`. */
export function deleteRange(ranges: TimeRange[], index: number): TimeRange[] {
  return ranges.filter((_, i) => i !== index);
}

/**
 * Déplace une plage de `deltaMin` minutes (signé), en conservant sa durée et en
 * la bornant dans `[00:00, 23:59]`. Arrondi au pas de 5 min.
 */
export function moveRange(ranges: TimeRange[], index: number, deltaMin: number): TimeRange[] {
  const r = ranges[index];
  if (!r) {
    return ranges;
  }
  const s = parseHHMM(r.start);
  const e = parseHHMM(r.end);
  if (s === null || e === null) {
    return ranges;
  }
  const dur = e - s;
  let ns = snapMinutes(s + deltaMin);
  if (ns + dur > LAST_MINUTE) {
    ns = LAST_MINUTE - dur;
  }
  if (ns < 0) {
    ns = 0;
  }
  return replace(ranges, index, { start: formatHHMM(ns), end: formatHHMM(ns + dur) });
}

/**
 * Redimensionne une plage par un de ses bords (`start` ou `end`) de `deltaMin`
 * minutes, en gardant une durée minimale et les bornes du jour.
 */
export function resizeRange(
  ranges: TimeRange[],
  index: number,
  edge: "start" | "end",
  deltaMin: number,
): TimeRange[] {
  const r = ranges[index];
  if (!r) {
    return ranges;
  }
  const s = parseHHMM(r.start);
  const e = parseHHMM(r.end);
  if (s === null || e === null) {
    return ranges;
  }
  if (edge === "start") {
    const ns = Math.min(snapMinutes(s + deltaMin), e - MIN_RANGE_MINUTES);
    return replace(ranges, index, { start: formatHHMM(Math.max(0, ns)), end: r.end });
  }
  const ne = Math.max(snapMinutes(e + deltaMin), s + MIN_RANGE_MINUTES);
  return replace(ranges, index, { start: r.start, end: formatHHMM(Math.min(LAST_MINUTE, ne)) });
}

/**
 * Fixe directement une heure (saisie clavier / mobile). La valeur est posée
 * telle quelle ; l'ordre et les chevauchements sont laissés à la validation.
 */
export function setRangeTime(
  ranges: TimeRange[],
  index: number,
  edge: "start" | "end",
  value: string,
): TimeRange[] {
  const r = ranges[index];
  if (!r) {
    return ranges;
  }
  return replace(ranges, index, edge === "start" ? { ...r, start: value } : { ...r, end: value });
}

/** Clone profond d'un ensemble de jours (pour partir d'une copie éditable). */
export function cloneDays(days: Record<DayKey, TimeRange[]>): Record<DayKey, TimeRange[]> {
  const out = {} as Record<DayKey, TimeRange[]>;
  for (const [day, ranges] of Object.entries(days) as [DayKey, TimeRange[]][]) {
    out[day] = ranges.map((r) => ({ ...r }));
  }
  return out;
}

/** Recopie les plages d'un jour vers plusieurs jours cibles (clones). */
export function copyDay(
  days: Record<DayKey, TimeRange[]>,
  from: DayKey,
  targets: DayKey[],
): Record<DayKey, TimeRange[]> {
  const source = (days[from] ?? []).map((r) => ({ ...r }));
  const out = cloneDays(days);
  for (const target of targets) {
    if (target !== from) {
      out[target] = source.map((r) => ({ ...r }));
    }
  }
  return out;
}

function fingerprint(ranges: TimeRange[]): string {
  return sortRanges(ranges)
    .map((r) => `${r.start}-${r.end}`)
    .join("|");
}

/** Vrai si deux listes de plages décrivent le même jour (ordre ignoré). */
export function rangesEqual(a: TimeRange[], b: TimeRange[]): boolean {
  return fingerprint(a) === fingerprint(b);
}

/**
 * Jours dont les plages diffèrent entre l'original et le brouillon : ce sont les
 * seuls à envoyer (`set_schedule` ne touche que les jours fournis, contrat §5.2).
 */
export function modifiedDays(
  original: Record<DayKey, TimeRange[]>,
  draft: Record<DayKey, TimeRange[]>,
  dayKeys: readonly DayKey[],
): DayKey[] {
  return dayKeys.filter((day) => !rangesEqual(original[day] ?? [], draft[day] ?? []));
}
