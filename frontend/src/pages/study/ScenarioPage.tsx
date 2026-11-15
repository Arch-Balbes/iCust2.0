// 05 — Сценарий интервью: вкладки сегментов, блоки SCORE/JTBD, у вопроса — подсказка интервьюеру и
// «Проверяет: <слоты>» (связь вопрос → компоненты появляется после фиксации дизайна, шаг 3а).
// 05.1 — «Собираем сценарий» (модуль коллеги: сценарий → офферы → дизайн).
import { useState } from "react";
import { useNavigate, useParams } from "react-router";

import { download } from "../../api/client";
import { ActionBar, Button, Card, EmptyState, ProcessingCard, SegmentTabs, SlotTag, useToast } from "../../components/ui";
import { useProject } from "../../store/project";

function plural(n: number) {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return "вопрос";
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return "вопроса";
  return "вопросов";
}

export function ScenarioPage() {
  const navigate = useNavigate();
  const { projectId = "" } = useParams();
  const toast = useToast();
  const { view, segmentTabs: tabs, running, job, generateScenario } = useProject();
  const [seg, setSeg] = useState(tabs[0]?.value ?? "");
  const current = tabs.some((t) => t.value === seg) ? seg : tabs[0]?.value ?? "";
  const sections = view.scenario[current] ?? [];
  const processing = running("scenario");
  const failed = job("scenario")?.status === "error";
  const regenerate = () => { generateScenario().catch((e: Error) => toast({ title: "Не удалось", text: e.message, tone: "error" })); };

  return (
    <>
      <div className="work">
        <div className="work-head row-between">
          <h2 className="work-title">Сценарий интервью</h2>
          {!view.locked && !processing && sections.length > 0 && (
            <Button variant="secondary" icon="sparkles" onClick={regenerate}>Собрать заново</Button>
          )}
        </div>
        <div style={{ marginBottom: 20 }}><SegmentTabs items={tabs} value={current} onChange={setSeg} /></div>
        {processing ? (
          <ProcessingCard title="Собираем сценарий интервью" text="Составляем вопросы по шаблону SCORE/JTBD, подбираем респондентов и офферы, собираем дизайн исследования. Обычно 3–6 минут." />
        ) : sections.length === 0 ? (
          <div className="card">
            {failed ? (
              <EmptyState icon="warning" tone="red" title="Не удалось собрать сценарий" text={job("scenario")?.error ?? "Сервис не ответил вовремя — попробуйте ещё раз."}>
                <Button onClick={regenerate}>Повторить попытку</Button>
              </EmptyState>
            ) : (
              <EmptyState icon="document" title="Сценария пока нет" text="Выберите гипотезы на шаге «Гипотезы» и нажмите «Собрать сценарий».">
                <Button onClick={() => navigate(`/projects/${projectId}/hypotheses`)}>К гипотезам</Button>
              </EmptyState>
            )}
          </div>
        ) : (
          <div className="stack">
            {sections.map((s) => (
              <Card key={s.id} title={s.title} action={<span className="small muted">{s.questions.length} {plural(s.questions.length)}</span>}>
                <div className="stack" style={{ gap: 20 }}>
                  {s.questions.map((q) => (
                    <div key={q.id} className="stack-sm">
                      {q.topic && <span className="small muted">{q.topic}</span>}
                      <div style={{ whiteSpace: "pre-line" }}>{q.text}</div>
                      {q.hint && <div className="small muted">Подсказка: {q.hint}</div>}
                      {q.checks.length > 0 && (
                        <div className="row small muted" style={{ gap: 6 }}>
                          Проверяет: {q.checks.map((c) => <SlotTag key={c} slot={c} />)}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </Card>
            ))}
          </div>
        )}
      </div>
      <ActionBar>
        <Button variant="secondary" icon="download" disabled={processing || sections.length === 0}
          onClick={() => { download(`/projects/${projectId}/export/scenario?fmt=docx`).catch((e: Error) => toast({ title: "Не удалось скачать", text: e.message, tone: "error" })); }}>
          Скачать сценарий .docx
        </Button>
        <Button disabled={processing || sections.length === 0} onClick={() => navigate(`/projects/${projectId}/respondents`)}>Перейти к респондентам</Button>
      </ActionBar>
    </>
  );
}
