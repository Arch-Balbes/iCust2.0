// 07 — Дизайн исследования: раздел 1 от модуля коллеги (описание продукта, проблема и потери, текущие способы,
// желаемый результат, цель) + выбранные гипотезы по сегментам, выгрузка .docx/.md.
// «Перейти к интервью» фиксирует дизайн: гипотезы и сценарий уходят в модуль анализа (шаг 0, шаг 3а).
import { useState } from "react";
import { useNavigate, useParams } from "react-router";

import { download } from "../../api/client";
import { HYPOTHESIS_TITLE, SlotTable } from "../../components/domain";
import { ActionBar, Button, Card, ProcessingCard, SegmentTabs, useToast } from "../../components/ui";
import { useProject } from "../../store/project";

export function DesignPage() {
  const navigate = useNavigate();
  const { projectId = "" } = useParams();
  const toast = useToast();
  const { view, hypothesis, segmentTabs: tabs, running, lock } = useProject();
  const [seg, setSeg] = useState(tabs[0]?.value ?? "");
  const [locking, setLocking] = useState(false);
  const current = tabs.some((t) => t.value === seg) ? seg : tabs[0]?.value ?? "";
  const segmentHyp = hypothesis(current);
  const valueHyps = (view.selectedValues[current] ?? []).map((id) => hypothesis(id)).filter((h) => h !== undefined);
  const v = view.context;
  const d = view.design;

  const facts: [string, string | undefined][] = [
    ["Название продукта или фичи", d?.product_name || v.product],
    ["Ключевая функция", d?.key_function || v.function],
    ["Проблема и потери", d?.problem_and_losses],
  ];
  const facts2: [string, string | undefined][] = [
    ["Текущие способы решения", d?.current_solutions || v.alternatives],
    ["Желаемый результат и эффект", d?.desired_outcome_and_effect],
    ["Цель исследования", d?.research_goal || v.decision],
  ];

  const toInterviews = async () => {
    if (view.locked) { navigate(`/projects/${projectId}/interviews`); return; }
    setLocking(true);
    try {
      await lock();
      navigate(`/projects/${projectId}/interviews`);
    } catch (e) {
      toast({ title: "Не удалось перейти к интервью", text: (e as Error).message, tone: "error" });
    } finally {
      setLocking(false);
    }
  };

  const save = (fmt: "docx" | "md") => {
    download(`/projects/${projectId}/export/design?fmt=${fmt}`).catch((e: Error) => toast({ title: "Не удалось скачать", text: e.message, tone: "error" }));
  };

  return (
    <>
      <div className="work">
        <div className="work-head"><h2 className="work-title">Дизайн исследования</h2></div>
        {running("scenario") ? (
          <ProcessingCard title="Собираем дизайн исследования" text="Описываем продукт, проблему и цель исследования по анкете." />
        ) : (
          <>
            <Card
              title="Описание продукта или фичи"
              action={view.locked ? undefined : <Button variant="text" onClick={() => navigate(`/projects/${projectId}/context`)}>Изменить</Button>}
            >
              <div className="grid-2" style={{ gap: 24 }}>
                {[facts, facts2].map((col, i) => (
                  <div key={i} className="stack">
                    {col.map(([k, val]) => (
                      <div key={k} className="stack-sm" style={{ gap: 4 }}>
                        <span className="small muted">{k}</span>
                        <span>{val || "—"}</span>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            </Card>
            <div style={{ margin: "20px 0" }}><SegmentTabs items={tabs} value={current} onChange={setSeg} /></div>
            <div className="grid-2">
              {segmentHyp && <Card title={HYPOTHESIS_TITLE.segment}><SlotTable hypothesis={segmentHyp} /></Card>}
              <div className="stack">
                {valueHyps.map((h) => <Card key={h.id} title={HYPOTHESIS_TITLE.value}><SlotTable hypothesis={h} /></Card>)}
              </div>
            </div>
          </>
        )}
      </div>
      <ActionBar left={!view.locked ? <span className="small muted">После перехода к интервью гипотезы и сценарий фиксируются</span> : undefined}>
        <Button variant="secondary" icon="download" disabled={!d} onClick={() => save("docx")}>Скачать .docx</Button>
        <Button variant="secondary" disabled={!d} onClick={() => save("md")}>.md</Button>
        <Button loading={locking} disabled={running("scenario") || !Object.keys(view.scenario).length} onClick={() => void toInterviews()}>Перейти к интервью</Button>
      </ActionBar>
    </>
  );
}
