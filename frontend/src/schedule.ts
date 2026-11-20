/**
 * Logique pure de présentation du programme (lot 4, lecture seule).
 *
 * Positionne les plages de confort sur une piste de 24 h. Aucune dépendance au
 * DOM ni à Home Assistant : testable par Vitest. La validation R1 (lot 5) viendra
 * dans un module séparé.
 */
import type { DayKey, TimeRange } from "./types";

/** Jours dans l'ordre d'affichage, lundi d'abord (contrat §3). */
export const DAY_KEYS: readonly DayKey[] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

const MINUTES_PER_DAY = 24 * 60;

/** `HH:MM` → minutes depuis minuit, ou `null` si mal formé / hors 00:00–23:59. */
export function parseHHMM(value: string): number | null {
  const m = /^(\d{2}):(\d{2})$/.exec(value);
  if (!m) {
    return null;
  }
  const hours = Number(m[1]);
  const minutes = Number(m[2]);
  if (hours > 23 || minutes > 59) {
    return null;
  }
  return hours * 60 + minutes;
}

/** Barre de confort positionnée en pourcentage de la piste 24 h. */
export interface Bar {
  start: string;
  end: string;
  leftPct: number;
  widthPct: number;
}

/** Barre d'édition : garde l'indice de sa plage dans la liste d'origine. */
export interface IndexedBar extends Bar {
  index: number;
}

/**
 * Comme `dayBars`, mais chaque barre garde l'indice de sa plage dans `ranges`.
 * L'éditeur en a besoin : les barres sont triées et les plages mal formées
 * ignorées, donc la position d'une barre n'est PAS l'indice de sa plage.
 */
export function indexedDayBars(ranges: TimeRange[]): IndexedBar[] {
  const bars: IndexedBar[] = [];
  ranges.forEach((range, index) => {
    const start = parseHHMM(range.start);
    const end = parseHHMM(range.end);
    if (start === null || end === null || end <= start) {
      return;
    }
    bars.push({
      index,
      start: range.start,
      end: range.end,
      leftPct: (start / MINUTES_PER_DAY) * 100,
      widthPct: ((end - start) / MINUTES_PER_DAY) * 100,
    });
  });
  bars.sort((a, b) => a.leftPct - b.leftPct);
  return bars;
}

/**
 * Convertit les plages d'un jour en barres positionnées (0–100 %). Les plages
 * mal formées ou vides (`start` ≥ `end`) sont ignorées, et les barres sont triées
 * par heure de début.
 */
export function dayBars(ranges: TimeRange[]): Bar[] {
  return indexedDayBars(ranges).map(({ start, end, leftPct, widthPct }) => ({
    start,
    end,
    leftPct,
    widthPct,
  }));
}

/** Vrai si le jour n'a aucune plage de confort valide (entièrement en réduit). */
export function isSetbackOnly(ranges: TimeRange[]): boolean {
  return dayBars(ranges).length === 0;
}

/**
 * Formate un horodatage ISO (`read_at`) pour l'affichage « dernière lecture »,
 * selon la langue. Renvoie `null` si l'horodatage est absent ou invalide.
 */
export function formatReadAt(iso: string | null | undefined, lang: string): string | null {
  if (!iso) {
    return null;
  }
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  return new Intl.DateTimeFormat(lang, {
    dateStyle: "short",
    timeStyle: "short",
  }).format(date);
}

/** Compte des états des têtes d'une pièce (pour un résumé rapide). */
export interface HeadSummary {
  total: number;
  online: number;
  scheduleActive: number;
  inconsistent: number;
  mounting: number;
}

interface HeadLike {
  online: boolean;
  schedule_active: boolean | null;
  inconsistent: boolean;
  mounting: boolean;
}

/** Résume les états d'une liste de têtes (nombre en ligne, incohérentes, etc.). */
export function summarizeHeads(heads: HeadLike[]): HeadSummary {
  const summary: HeadSummary = {
    total: heads.length,
    online: 0,
    scheduleActive: 0,
    inconsistent: 0,
    mounting: 0,
  };
  for (const head of heads) {
    if (head.online) {
      summary.online += 1;
    }
    if (head.schedule_active) {
      summary.scheduleActive += 1;
    }
    if (head.inconsistent) {
      summary.inconsistent += 1;
    }
    if (head.mounting) {
      summary.mounting += 1;
    }
  }
  return summary;
}
