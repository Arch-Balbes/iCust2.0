// Состояние демо-режима (в памяти браузера). При подключении бэкенда методы заменяются вызовами API
// с теми же сигнатурами — страницы менять не придётся.
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router";

import type { Hypothesis, Insight, Interview, SlotCode } from "../domain/types";
import * as demo from "./demo";

type HypothesisVersion = { version: number; hypothesis: Hypothesis };

type DemoState = {
  projectName: (id: string) => string;

  /* Анкета */
  contextValues: Record<string, string>;
  setContextValue: (key: string, value: string) => void;

  /* Гипотезы: выбор вариантов (решение 10.11.2026 — как у коллеги: выбор, не правка) */
  selectedSegments: string[];
  toggleSegment: (segmentId: string) => void;
  selectedValues: Record<string, string[]>;
  toggleValue: (segmentId: string, hypothesisId: string) => void;
  /** Текущая версия гипотезы (с учётом правок через editHypothesisSlot). */
  hypothesis: (id: string) => Hypothesis | undefined;
  /**
   * Правка слота гипотезы → новая версия. В UI кнопки нет (решение 10.11.2026);
   * функция готова, чтобы позже добавить только кнопку «Редактировать».
   */
  editHypothesisSlot: (hypothesisId: string, slot: SlotCode, text: string) => number;
  hypothesisVersion: (id: string) => number;

  /* Интервью */
  interviews: Interview[];
  addUpload: (fileName: string, segmentId: string) => string;
  setUpload: (id: string, patch: Partial<Interview>) => void;
  removeInterview: (id: string) => void;

  /* Инсайты */
  insights: Insight[];
  addInsight: (insight: Insight) => void;
  updateInsight: (insight: Insight) => void;

  /* Тариф и баланс токенов (плацебо: оплата не подключена) */
  plan: demo.PlanId;
  tokens: { left: number; total: number };
};

const Ctx = createContext<DemoState | null>(null);

export function DemoProvider({ children }: { children: ReactNode }) {
  const [contextValues, setContextValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(demo.contextBlocks.flatMap((b) => b.fields.map((f) => [f.key, f.value]))),
  );
  const [selectedSegments, setSelectedSegments] = useState<string[]>(["SEG01", "SEG02"]);
  const [selectedValues, setSelectedValues] = useState<Record<string, string[]>>({
    SEG01: ["SEG01-H01"],
    SEG02: ["SEG02-H01"],
  });
  const [versions, setVersions] = useState<Record<string, HypothesisVersion[]>>({});
  const [interviews, setInterviews] = useState<Interview[]>(demo.interviews);
  const [insights, setInsights] = useState<Insight[]>(demo.insights);
  // Демо-состояния макета включаются параметром ?state=… (список — README, раздел «Демо-состояния»)
  const demoState = new URLSearchParams(window.location.search).get("state");
  const demoPlan: demo.PlanId = demoState === "free" ? "free" : "pro";

  const baseHypothesis = useCallback(
    (id: string) => [...demo.segmentVariants, ...demo.valueVariants].find((h) => h.id === id),
    [],
  );

  const hypothesis = useCallback(
    (id: string) => versions[id]?.at(-1)?.hypothesis ?? baseHypothesis(id),
    [versions, baseHypothesis],
  );

  const hypothesisVersion = useCallback((id: string) => versions[id]?.at(-1)?.version ?? 1, [versions]);

  const editHypothesisSlot = useCallback(
    (hypothesisId: string, slot: SlotCode, text: string) => {
      const current = versions[hypothesisId]?.at(-1);
      const base = current?.hypothesis ?? baseHypothesis(hypothesisId);
      if (!base) throw new Error(`Нет гипотезы ${hypothesisId}`);
      const next: Hypothesis = { ...base, lines: base.lines.map((l) => (l.slot === slot ? { ...l, text } : l)) };
      const version = (current?.version ?? 1) + 1;
      setVersions((v) => ({ ...v, [hypothesisId]: [...(v[hypothesisId] ?? []), { version, hypothesis: next }] }));
      return version;
    },
    [versions, baseHypothesis],
  );

  const value = useMemo<DemoState>(
    () => ({
      projectName: (id) => demo.projects.find((p) => p.id === id)?.name ?? "Новое исследование",
      contextValues,
      setContextValue: (key, v) => setContextValues((s) => ({ ...s, [key]: v })),
      selectedSegments,
      toggleSegment: (id) =>
        setSelectedSegments((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id])),
      selectedValues,
      toggleValue: (seg, id) =>
        setSelectedValues((s) => {
          const cur = s[seg] ?? [];
          return { ...s, [seg]: cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id] };
        }),
      hypothesis,
      editHypothesisSlot,
      hypothesisVersion,
      interviews,
      addUpload: (fileName, segmentId) => {
        const id = `u${Date.now()}`;
        const ext = fileName.split(".").pop()?.toLowerCase() ?? "mp4";
        setInterviews((xs) => [
          { id, respondentId: "", segmentId, fileType: ext, durationMin: 0, sizeMb: 0, status: "uploading", progress: 0, recordedAt: "Сейчас" },
          ...xs,
        ]);
        return id;
      },
      setUpload: (id, patch) => setInterviews((xs) => xs.map((x) => (x.id === id ? { ...x, ...patch } : x))),
      removeInterview: (id) => setInterviews((xs) => xs.filter((x) => x.id !== id)),
      insights,
      addInsight: (ins) => setInsights((xs) => [ins, ...xs]),
      updateInsight: (ins) => setInsights((xs) => xs.map((x) => (x.id === ins.id ? ins : x))),
      plan: demoPlan,
      tokens: demoPlan === "free" ? { left: 600, total: 600 } : demoState === "no-tokens" ? { left: 0, total: 2500 } : { left: 1750, total: 2500 },
    }),
    [contextValues, selectedSegments, selectedValues, hypothesis, editHypothesisSlot, hypothesisVersion, interviews, insights, demoPlan, demoState],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useDemo(): DemoState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useDemo вне DemoProvider");
  return v;
}

/**
 * Демо-состояние экрана из URL (?state=processing | empty | error | no-tokens | upload-error | transcribing | free | payment-failed).
 * `clear()` убирает параметр — так «обработка» сама переходит в готовый экран.
 */
export function useDemoState() {
  const [params, setParams] = useSearchParams();
  const state = params.get("state");
  const clear = useCallback(() => {
    setParams((p) => { p.delete("state"); return p; }, { replace: true });
  }, [setParams]);
  return { state, clear };
}

/** «Обработка» с имитацией длительности: показывает карточку, затем снимает ?state=processing. */
export function useProcessing(ms = 2200) {
  const { state, clear } = useDemoState();
  const processing = state === "processing";
  useEffect(() => {
    if (!processing) return;
    const t = window.setTimeout(clear, ms);
    return () => window.clearTimeout(t);
  }, [processing, clear, ms]);
  return processing;
}

/** Выбранные сегменты в виде вкладок «Сегмент 1 / Сегмент 2». */
export function useSegmentTabs() {
  const { selectedSegments } = useDemo();
  return selectedSegments
    .filter((s) => demo.segmentLabel[s])
    .sort()
    .map((s) => ({ value: s, label: demo.segmentLabel[s] ?? s }));
}
