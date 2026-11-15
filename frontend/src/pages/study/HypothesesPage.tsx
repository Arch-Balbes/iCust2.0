// 04 — Гипотезы. Отличие от макета (решение 10.11.2026): как в модуле коллеги — несколько вариантов,
// пользователь ВЫБИРАЕТ, кнопки «Редактировать» нет. Варианты, не прошедшие проверку оценщика, помечены причинами.
// 04.1 — модуль генерации не ответил (задача hypotheses завершилась ошибкой).
import { useState } from "react";
import { useNavigate, useParams } from "react-router";

import { HYPOTHESIS_TITLE, SlotTable } from "../../components/domain";
import { Icon } from "../../components/Icon";
import { ActionBar, Button, Card, Caps, Checkbox, EmptyState, ProcessingCard, useToast } from "../../components/ui";
import type { Hypothesis } from "../../domain/types";
import { useProject } from "../../store/project";

function VariantCard({
  h, title, selected, onToggle, locked,
}: { h: Hypothesis; title: string; selected: boolean; onToggle: () => void; locked: boolean }) {
  return (
    <Card
      className="variant-card"
      active={selected}
      title={title}
      action={
        <div className="row" style={{ gap: 16 }}>
          {/* Как в макете: «Редактировать» есть, но пока недоступно (решение 10.11) */}
          <Button variant="text" size="sm" icon="pencil" disabled title="Редактирование появится позже">Редактировать</Button>
          <Checkbox checked={selected} onChange={locked ? () => undefined : onToggle}>Выбрать</Checkbox>
        </div>
      }
    >
      <SlotTable hypothesis={h} />
      {!h.check.passed && (
        <div className="check-warn">
          <Icon name="warning" size={18} />
          <div>
            Не прошёл автоматическую проверку — можно взять как есть или сгенерировать заново.
            <ul>{h.check.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
          </div>
        </div>
      )}
    </Card>
  );
}

export function HypothesesPage() {
  const navigate = useNavigate();
  const { projectId } = useParams();
  const toast = useToast();
  const { view, running, job, toggleSegment, toggleValue, generateHypotheses, generateScenario } = useProject();
  const [starting, setStarting] = useState(false);
  const { segmentVariants, valueVariants, selectedSegments, selectedValues, locked } = view;

  const chosen = segmentVariants.filter((s) => selectedSegments.includes(s.id));
  const ready = chosen.length > 0 && chosen.every((s) => (selectedValues[s.id] ?? []).length > 0);
  const hasScenario = Object.keys(view.scenario).length > 0;
  const regenerate = () => { generateHypotheses().catch((e: Error) => toast({ title: "Не удалось", text: e.message, tone: "error" })); };

  const toScenario = async () => {
    if (locked || hasScenario) {
      navigate(`/projects/${projectId}/scenario`);
      return;
    }
    setStarting(true);
    try {
      await generateScenario();
      navigate(`/projects/${projectId}/scenario`);
    } catch (e) {
      toast({ title: "Не удалось собрать сценарий", text: (e as Error).message, tone: "error" });
    } finally {
      setStarting(false);
    }
  };

  const head = (
    <div className="work-head row-between">
      <div>
        <h2 className="work-title">Гипотезы</h2>
        <p className="work-sub">Выберите сегменты, которые будете проверять, и для каждого — гипотезу ценности продукта.</p>
      </div>
      {!locked && segmentVariants.length > 0 && !running("hypotheses") && (
        <Button variant="secondary" icon="sparkles" onClick={regenerate}>Сгенерировать заново</Button>
      )}
    </div>
  );

  if (running("hypotheses")) {
    return <div className="work">{head}<ProcessingCard title="Собираем гипотезы" text="Формулируем сегменты и гипотезы ценности и проверяем их по критериям. Обычно это занимает 3–7 минут." /></div>;
  }

  // 04.1 — модуль генерации не ответил; без вариантов — анкета ещё не отправлена
  const failed = job("hypotheses")?.status === "error";
  if (failed || segmentVariants.length === 0) {
    return (
      <>
        <div className="work">
          {head}
          <div className="card">
            {failed ? (
              <EmptyState icon="warning" tone="red" title="Не удалось собрать гипотезы" text="Сервис не ответил вовремя. Ответы из анкеты сохранены — попробуйте ещё раз.">
                <Button variant="secondary" onClick={() => navigate(`/projects/${projectId}/context`)}>Вернуться к контексту</Button>
                <Button onClick={regenerate}>Повторить попытку</Button>
              </EmptyState>
            ) : (
              <EmptyState icon="sparkles" title="Гипотез пока нет" text="Заполните анкету на шаге «Контекст» и нажмите «Собрать гипотезы».">
                <Button onClick={() => navigate(`/projects/${projectId}/context`)}>Перейти к контексту</Button>
              </EmptyState>
            )}
          </div>
        </div>
        <ActionBar>
          <Button variant="secondary" onClick={() => navigate(`/projects/${projectId}/context`)}>Назад к контексту</Button>
          <Button disabled>Собрать сценарий</Button>
        </ActionBar>
      </>
    );
  }

  return (
    <>
      <div className="work">
        {head}
        {view.generationNote && <p className="small muted" style={{ marginBottom: 12 }}>{view.generationNote}</p>}
        <Caps className="section-caps">{HYPOTHESIS_TITLE.segment} · варианты</Caps>
        <div className="grid-2">
          {segmentVariants.map((s) => (
            <VariantCard
              key={s.id}
              h={s}
              locked={locked}
              title={view.segmentLabel[s.id] ? `${view.segmentLabel[s.id]} · вариант ${s.variantNo}` : `Вариант ${s.variantNo}`}
              selected={selectedSegments.includes(s.id)}
              onToggle={() => toggleSegment(s.id)}
            />
          ))}
        </div>

        {chosen.map((s) => {
          const variants = valueVariants.filter((v) => v.segmentId === s.id);
          return (
            <div key={s.id}>
              <Caps className="section-caps">{view.segmentLabel[s.id] ?? `Вариант ${s.variantNo}`} · {HYPOTHESIS_TITLE.value}</Caps>
              {variants.length === 0 ? (
                <Card><p className="muted">Гипотезы ценности для этого сегмента не получены — сгенерируйте заново.</p></Card>
              ) : (
                <div className="grid-2">
                  {variants.map((v) => (
                    <VariantCard
                      key={v.id}
                      h={v}
                      locked={locked}
                      title={`Вариант ${v.variantNo}`}
                      selected={(selectedValues[s.id] ?? []).includes(v.id)}
                      onToggle={() => toggleValue(s.id, v.id)}
                    />
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
      <ActionBar left={locked ? <span className="small muted">Выбор зафиксирован: по этим гипотезам уже идут интервью</span>
        : !ready ? <span className="small muted">Выберите хотя бы один сегмент и гипотезу ценности для каждого</span> : undefined}>
        <Button variant="secondary" onClick={() => navigate(`/projects/${projectId}/context`)}>Назад к контексту</Button>
        <Button disabled={!ready} loading={starting} onClick={() => void toScenario()}>
          {locked || hasScenario ? "К сценарию" : "Собрать сценарий"}
        </Button>
      </ActionBar>
    </>
  );
}
