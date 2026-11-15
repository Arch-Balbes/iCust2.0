// Предметные компоненты, общие для нескольких экранов.
import { useState } from "react";
import { useNavigate } from "react-router";

import { componentStatus, votesLine } from "../domain/ig2";
import type { ComponentEvidence, Hypothesis, Quote } from "../domain/types";
import { SLOT_LABEL } from "../domain/types";
import { useProject } from "../store/project";
import { Icon } from "./Icon";
import { SlotTag, StatusBadge, Tag } from "./ui";

export const HYPOTHESIS_TITLE = {
  segment: "Гипотеза потребительского сегмента",
  value: "Гипотеза ценности продукта",
} as const;

/** Таблица «слот → текст» (экраны 04, 07). */
export function SlotTable({ hypothesis }: { hypothesis: Hypothesis }) {
  return (
    <div className="slot-table">
      {hypothesis.lines.map((l) => (
        <div key={l.slot} style={{ display: "contents" }}>
          <SlotTag slot={l.slot} />
          <div>
            {l.lead && <span className="slot-lead">{l.lead} </span>}
            {l.text}
          </div>
        </div>
      ))}
    </div>
  );
}

/** Респондент в цитате — по коду (R01…): имена после обезличивания не показываем. */
export function respondentLabel(id: string): string {
  return id ? `Респондент ${id}` : "Респондент";
}

/** «MM:SS» или «H:MM:SS» → секунды; пустая строка → null. */
export function timeToSeconds(t: string): number | null {
  if (!t) return null;
  const parts = t.split(":").map(Number);
  if (parts.some((x) => Number.isNaN(x))) return null;
  return parts.reduce((acc, x) => acc * 60 + x, 0);
}

export function QuoteCard({ quote, tone, label }: { quote: Quote; tone?: "green" | "red"; label?: string }) {
  const navigate = useNavigate();
  const { projectId, view } = useProject();
  // запись цитаты — интервью этого респондента (код R01… уникален в проекте)
  const interview = view.interviews.find((i) => i.respondentId === quote.respondentId);
  const seconds = timeToSeconds(quote.time);
  const canOpen = !!interview && seconds !== null;
  return (
    <div className={`quote-card ${tone ? `tone-${tone}` : ""}`}>
      <div className="quote-head">
        <span className="row" style={{ gap: 8 }}>
          {label && <Tag tone={tone === "red" ? "red" : "green"}>{label}</Tag>}
          <span className="speaker">{respondentLabel(quote.respondentId)}</span>
        </span>
        <button
          type="button"
          className="timecode"
          title={canOpen ? "Открыть запись на этом месте" : "Время реплики неизвестно"}
          disabled={!canOpen}
          onClick={() => canOpen && navigate(`/projects/${projectId}/interviews?iv=${interview.id}&t=${seconds}`)}
        >
          <Icon name="play" size={14} /> {quote.time || "—"}
        </button>
      </div>
      <div className="quote-text">«{quote.text}»</div>
    </div>
  );
}

/** Строка компонента в валидации (экран 11): слот, текст, статус ИГ2, «N за · M против», раскрытие с цитатами. */
export function ComponentRow({ evidence, text, lead }: { evidence: ComponentEvidence; text: string; lead?: string }) {
  const [open, setOpen] = useState(false);
  const status = componentStatus(evidence);
  const hasQuotes = evidence.supporting.length + evidence.contradicting.length > 0;
  return (
    <div className="comp-row">
      <div className="comp-main">
        <div className="comp-slot"><SlotTag slot={evidence.slot} /></div>
        <div className="comp-text">
          {lead && <span className="slot-lead">{lead} </span>}
          {text}
        </div>
        {/* Пилотные элементы (Функция) проблемным интервью не проверяются — подпись из макета 11 */}
        <div className="comp-status">
          {status === "not_tested" && evidence.pilot
            ? <Tag tone="gray">Не проверяется</Tag>
            : <StatusBadge status={status} />}
          <span className="small muted">{votesLine(evidence)}</span>
        </div>
        <button
          type="button"
          className="icon-btn comp-toggle"
          aria-label={open ? "Свернуть" : "Показать ответы"}
          disabled={!hasQuotes}
          onClick={() => setOpen((v) => !v)}
          style={{ visibility: hasQuotes ? "visible" : "hidden", transform: open ? "rotate(180deg)" : undefined }}
        >
          <Icon name="chevronDown" />
        </button>
      </div>
      {open && (
        <div className="comp-quotes">
          {evidence.supporting.map((q) => <QuoteCard key={`s${q.respondentId}${q.time}`} quote={q} tone="green" label="за" />)}
          {evidence.contradicting.map((q) => <QuoteCard key={`c${q.respondentId}${q.time}`} quote={q} tone="red" label="против" />)}
          <span className="small muted">
            Все ответы · {evidence.k + evidence.c + evidence.riOnly}. Слот «{SLOT_LABEL[evidence.slot]}» — один голос на респондента.
          </span>
        </div>
      )}
    </div>
  );
}
