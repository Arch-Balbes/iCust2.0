// 11 — Валидация гипотез (ИГ2 на бэкенде, app/ig1/ig2.py); 11.1 — недостаточно данных; 11.2 — «Переформулируем гипотезы».
// Отличия от макета (решения 10.11.2026):
//  • статусы ИГ2: Подтверждено / Опровергнуто / Неоднозначно / Мало данных / Не проверялось — без «Частично»;
//  • пороги ИГ2: подтверждено при k ≥ 5 и k ≥ 3c, опровергнуто при c ≥ 5 и c ≥ 3k;
//  • X % = подтверждённые / (все − «не проверялось»), без половинных весов.
// Строка — атомарный компонент (слот может делиться на несколько утверждений, шаг 0 ИГ1).
import { useState } from "react";
import { useNavigate, useParams } from "react-router";

import { ComponentRow, HYPOTHESIS_TITLE } from "../../components/domain";
import { ActionBar, Button, Card, EmptyState, ProcessingCard, SegmentTabs, useToast } from "../../components/ui";
import { summarize, summaryLine } from "../../domain/ig2";
import type { ValidationResult } from "../../domain/types";
import { useProject } from "../../store/project";

function percentTone(p: number | null) {
  if (p === null) return "var(--text-secondary)";
  if (p >= 75) return "var(--green)";
  if (p >= 40) return "var(--yellow)";
  return "var(--red)";
}

function HypothesisValidation({ result }: { result: ValidationResult }) {
  const s = summarize(result.components);
  const percent = result.percent === undefined ? s.percent : result.percent === null ? null : Math.round(result.percent);
  return (
    <Card>
      <div className="row-between" style={{ alignItems: "flex-start" }}>
        <h3 className="h-block">{HYPOTHESIS_TITLE[result.kind]}</h3>
        <span className="number" style={{ color: percentTone(percent) }}>{percent === null ? "—" : `${percent}%`}</span>
      </div>
      <p className="small muted" style={{ marginTop: 4 }}>
        {percent === null ? "Нет данных: ни один элемент ещё не обсуждался" : summaryLine(s)}
        {" · "}{result.nInterviews} интервью
      </p>
      <div className="comp-list">
        {result.components.map((c) => (
          <ComponentRow key={c.componentId ?? c.slot} evidence={c} lead={c.lead ?? undefined} text={c.text ?? "—"} />
        ))}
      </div>
    </Card>
  );
}

export function ValidationPage() {
  const navigate = useNavigate();
  const { projectId } = useParams();
  const toast = useToast();
  const { view, segmentTabs: tabs, running, job, reformulate } = useProject();
  const [seg, setSeg] = useState(tabs[0]?.value ?? "");
  const current = tabs.some((t) => t.value === seg) ? seg : tabs[0]?.value ?? "";
  const reformulating = running("reformulate");

  const results = view.validation.filter((r) => r.segmentId === current);
  const done = view.interviews.filter((i) => i.status === "transcribed");
  const inSeg = done.filter((i) => i.segmentId === current).length;
  const tooFew = inSeg === 0 || results.length === 0;

  let body;
  if (reformulating) {
    body = <ProcessingCard title="Переформулируем гипотезы" text="Передаём результаты проверки и инсайты модулю генерации — он предложит уточнённые сегменты и гипотезы. Обычно 3–7 минут." />;
  } else if (tooFew) {
    body = (
      <div className="card">
        <EmptyState
          title="Недостаточно данных для проверки"
          text={`Расшифровано ${inSeg} интервью в этом сегменте, всего — ${done.length} из ${view.plannedInterviews}. Чтобы проверить гипотезы, загрузите и расшифруйте записи.`}
        >
          <Button onClick={() => navigate(`/projects/${projectId}/interviews`)}>Перейти к интервью</Button>
        </EmptyState>
      </div>
    );
  } else {
    body = (
      <>
        <p className="work-sub" style={{ margin: "-8px 0 16px" }}>
          Процент — доля подтверждённых элементов среди тех, что обсуждались в интервью. Элемент подтверждён,
          если «за» не меньше 5 человек и втрое больше, чем «против». Чужой опыт («у знакомых так») считается за половину голоса.
          {inSeg < 5 && ` Сейчас в сегменте ${inSeg} интервью — подтвердить элемент можно начиная с пяти.`}
        </p>
        {job("reformulate")?.status === "done" && view.reformulated[current] && (
          <p className="small" style={{ marginBottom: 12 }}>
            Гипотезы переформулированы — новые версии в отчёте, раздел «Сегменты и гипотезы».{" "}
            <button type="button" className="link-btn" onClick={() => navigate(`/projects/${projectId}/report`)}>Открыть</button>
          </p>
        )}
        <div className="grid-2">
          {results.map((r) => <HypothesisValidation key={r.hypothesisId} result={r} />)}
        </div>
      </>
    );
  }

  const disabled = reformulating || tooFew;
  return (
    <>
      <div className="work">
        <div className="work-head"><h2 className="work-title">Валидация гипотез</h2></div>
        <div style={{ marginBottom: 20 }}><SegmentTabs items={tabs} value={current} onChange={setSeg} /></div>
        {body}
        {job("reformulate")?.status === "error" && <p className="small" style={{ color: "var(--red)" }}>Переформулировать не удалось: {job("reformulate")?.error}</p>}
      </div>
      <ActionBar>
        <Button variant="secondary" loading={reformulating} disabled={disabled} onClick={() => {
          reformulate().catch((e: Error) => toast({ title: "Не удалось", text: e.message, tone: "error" }));
        }}>Переформулировать гипотезы</Button>
        <Button disabled={disabled} onClick={() => navigate(`/projects/${projectId}/report`)}>Собрать отчёт</Button>
      </ActionBar>
    </>
  );
}
