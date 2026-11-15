// Правила ИГ2 для отображения (решения владельца 05.11 и 10.11.2026, IG1_PIPELINE.md).
// Источник истины будет на бэкенде; здесь те же правила, чтобы демо-данные показывали честные статусы.

import type { ComponentEvidence } from "./types";

export type ComponentStatus = "confirmed" | "refuted" | "ambiguous" | "insufficient" | "not_tested";

/** Пороги: подтверждён при k ≥ 5 и k ≥ 3c; опровергнут при c ≥ 5 и c ≥ 3k. */
export const MIN_VOTES = 5;
export const RATIO = 3;

export function componentStatus(e: Pick<ComponentEvidence, "k" | "c" | "riOnly" | "status">): ComponentStatus {
  if (e.status) return e.status; // посчитан бэкендом по полным правилам (вес чужого опыта, mixed, quantifier)
  if (e.k >= MIN_VOTES && e.k >= RATIO * e.c) return "confirmed";
  if (e.c >= MIN_VOTES && e.c >= RATIO * e.k) return "refuted";
  if (e.k === 0 && e.c === 0 && e.riOnly === 0) return "not_tested";
  // below_threshold: есть и «за», и «против» — неоднозначно; иначе данных мало
  if (e.k > 0 && e.c > 0) return "ambiguous";
  return "insufficient";
}

export const STATUS_META: Record<ComponentStatus, { label: string; tone: "green" | "red" | "yellow" | "gray" | "outline" }> = {
  confirmed: { label: "Подтверждено", tone: "green" },
  refuted: { label: "Опровергнуто", tone: "red" },
  ambiguous: { label: "Неоднозначно", tone: "yellow" },
  insufficient: { label: "Мало данных", tone: "gray" },
  not_tested: { label: "Не проверялось", tone: "outline" },
};

export type HypothesisSummary = {
  percent: number | null;   // null — ни один компонент не проверялся
  counts: Record<ComponentStatus, number>;
  total: number;
};

/**
 * X % = подтверждённые / (все компоненты − «не проверялось»).
 * Компонент без данных не влияет на гипотезу: его могут закрыть интервью, загруженные позже.
 */
export function summarize(components: Pick<ComponentEvidence, "k" | "c" | "riOnly" | "status">[]): HypothesisSummary {
  const counts: Record<ComponentStatus, number> = {
    confirmed: 0, refuted: 0, ambiguous: 0, insufficient: 0, not_tested: 0,
  };
  for (const c of components) counts[componentStatus(c)] += 1;
  const tested = components.length - counts.not_tested;
  return {
    percent: tested === 0 ? null : Math.round((100 * counts.confirmed) / tested),
    counts,
    total: components.length,
  };
}

export function summaryLine(s: HypothesisSummary): string {
  const parts: string[] = [];
  const order: ComponentStatus[] = ["confirmed", "ambiguous", "refuted", "insufficient", "not_tested"];
  const word: Record<ComponentStatus, string> = {
    confirmed: "подтверждено",
    ambiguous: "неоднозначно",
    refuted: "опровергнуто",
    insufficient: "мало данных",
    not_tested: "не проверялось",
  };
  for (const st of order) if (s.counts[st] > 0) parts.push(`${word[st]} ${s.counts[st]}`);
  const text = parts.join(" · ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function votesLine(e: Pick<ComponentEvidence, "k" | "c" | "riOnly">): string {
  if (e.k === 0 && e.c === 0) return e.riOnly > 0 ? `обсуждали ${e.riOnly}, без ясного ответа` : "";
  return `${e.k} за · ${e.c} против`;
}
