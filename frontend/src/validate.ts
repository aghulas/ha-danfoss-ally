/**
 * Validation du programme côté interface (lot 5).
 *
 * Porte fidèlement la règle **R1** du contrat (docs/interface-contract.md §2) en
 * TypeScript, plus les contrôles de forme des plages (§5.4). Logique pure, sans
 * DOM ni Home Assistant : testable par Vitest. Les codes d'erreur sont ceux du
 * contrat (§5.4) ; le texte est traduit par la carte, pas ici.
 *
 * L'interface valide localement ET par la commande `schedule/validate` : ce
 * module est le miroir fidèle du décompte serveur (`compter_transitions`), pour
 * un retour immédiat sans aller-retour réseau.
 */
import { parseHHMM } from "./schedule";
import type { TimeRange } from "./types";

/** Nombre maximal de transitions qu'une tête garde pour un jour (R1). */
export const MAX_TRANSITIONS_PER_DAY = 6;

/** Codes d'erreur stables du contrat §5.4 que l'interface peut produire localement. */
export type ErrorCode =
  | "invalid_time"
  | "empty_or_reversed"
  | "overlap"
  | "too_many_transitions";

/** Une erreur de validation rattachée à un jour (contrat §5.4). */
export interface ValidationError {
  code: ErrorCode;
  /** Jour concerné, ou `null` si transversal. */
  day: string | null;
}

/** Bilan de validation d'un jour. */
export interface DayValidation {
  /**
   * Transitions demandées par le jour, **hors** celle implicite de 00:00
   * (miroir exact de `compter_transitions` côté serveur). C'est le nombre
   * affiché par le compteur « n / 6 ». Trois plages séparées = 6.
   */
  transitions: number;
  /**
   * Vrai si aucune plage ne commence à 00:00 : la tête ajoute alors une
   * transition « réduit » à 00:00 s'il lui reste de la place, et l'abandonne à 6.
   */
  impliedMidnight: boolean;
  /** Le jour respecte R1 et la forme des plages. */
  valid: boolean;
  /** Erreurs du jour (peut en contenir plusieurs). */
  errors: ValidationError[];
}

interface ParsedRange {
  start: number;
  end: number;
}

/**
 * Décompte des transitions d'un jour selon R1, à partir de plages déjà validées
 * (minutes depuis minuit). Miroir de `compter_transitions` (pilote_tuya.py) :
 * - chaque plage compte son début, sauf s'il vaut 00:00 ;
 * - chaque plage compte sa fin, sauf si une autre plage commence à cette heure ;
 * - `impliedMidnight` : aucune plage ne commence à 00:00.
 */
export function countTransitions(ranges: ParsedRange[]): {
  count: number;
  impliedMidnight: boolean;
} {
  const starts = new Set(ranges.map((r) => r.start));
  let count = 0;
  for (const r of ranges) {
    if (r.start !== 0) {
      count += 1;
    }
    if (!starts.has(r.end)) {
      count += 1;
    }
  }
  return { count, impliedMidnight: ranges.length > 0 && !starts.has(0) };
}

/**
 * Valide les plages d'un seul jour : forme (heures, ordre, chevauchement) puis
 * R1. Les plages mal formées n'empêchent pas le décompte des plages valides.
 */
export function validateDay(ranges: TimeRange[], day: string | null = null): DayValidation {
  const errors: ValidationError[] = [];
  const parsed: ParsedRange[] = [];

  for (const range of ranges) {
    const start = parseHHMM(range.start);
    const end = parseHHMM(range.end);
    if (start === null || end === null) {
      errors.push({ code: "invalid_time", day });
      continue;
    }
    if (start >= end) {
      errors.push({ code: "empty_or_reversed", day });
      continue;
    }
    parsed.push({ start, end });
  }

  parsed.sort((a, b) => a.start - b.start);
  for (let i = 1; i < parsed.length; i += 1) {
    if (parsed[i].start < parsed[i - 1].end) {
      errors.push({ code: "overlap", day });
      break;
    }
  }

  const { count, impliedMidnight } = countTransitions(parsed);
  if (count > MAX_TRANSITIONS_PER_DAY) {
    errors.push({ code: "too_many_transitions", day });
  }

  return {
    transitions: count,
    impliedMidnight,
    valid: errors.length === 0,
    errors,
  };
}

/**
 * Valide un ensemble de jours (`mon`..`sun`). Renvoie le bilan par jour, la
 * validité globale et les transitions par jour (même forme que la réponse de la
 * commande `schedule/validate`, pour comparer serveur et local).
 */
export function validateDays(days: Record<string, TimeRange[]>): {
  valid: boolean;
  byDay: Record<string, DayValidation>;
  transitions: Record<string, number>;
  errors: ValidationError[];
} {
  const byDay: Record<string, DayValidation> = {};
  const transitions: Record<string, number> = {};
  const errors: ValidationError[] = [];
  let valid = true;

  for (const [day, ranges] of Object.entries(days)) {
    const result = validateDay(ranges, day);
    byDay[day] = result;
    transitions[day] = result.transitions;
    errors.push(...result.errors);
    if (!result.valid) {
      valid = false;
    }
  }

  return { valid, byDay, transitions, errors };
}
