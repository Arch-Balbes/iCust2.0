// 03 — Контекст исследования: анкета А–Ж (блоки «Продукт и потребитель», «Проблема и решение»,
// «Результат и текущие способы», «Рамки исследования»). Вопросы — contextBlocks, ответы — проект в API.
// 03.1 — «Собираем гипотезы» (идёт задача модуля коллеги), 03.2 — не заполнены обязательные поля.
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router";

import { ActionBar, Button, Card, ProcessingCard, Tag, useToast } from "../../components/ui";
import type { ContextField } from "../../domain/types";
import { contextBlocks } from "../../mocks/demo";
import { useProject } from "../../store/project";

function Question({ field, warn, locked }: { field: ContextField; warn: boolean; locked: boolean }) {
  const { view, setContextValue } = useProject();
  const value = view.context[field.key] ?? "";
  return (
    <div className="q-field">
      <div className="row" style={{ gap: 8, alignItems: "flex-start" }}>
        {field.tag && <Tag tone="blue" className="q-tag">{field.tag}</Tag>}
        <span className="strong">{field.question}</span>
      </div>
      {field.hint && <div className="small muted">{field.hint}</div>}
      <textarea
        className={`textarea ${warn ? "is-warning" : ""}`}
        rows={Math.max(1, Math.ceil(value.length / 52))}
        placeholder={warn ? "Не заполнено" : "Введите ответ"}
        value={value}
        readOnly={locked}
        aria-invalid={warn || undefined}
        onChange={(e) => setContextValue(field.key, e.target.value)}
      />
      {warn && <div className="field-warning">Заполните поле: {field.required ?? "без него не получится собрать гипотезы."}</div>}
      <div className="small muted">Например: {field.example}</div>
    </div>
  );
}

export function ContextPage() {
  const navigate = useNavigate();
  const { projectId } = useParams();
  const toast = useToast();
  const { view, running, job, saveContext, generateHypotheses } = useProject();
  const [showWarnings, setShowWarnings] = useState(false);
  const [waiting, setWaiting] = useState(false);
  const processing = running("hypotheses");

  const fields = contextBlocks.flatMap((b) => b.fields);
  const isEmpty = (f: ContextField) => !(view.context[f.key] ?? "").trim();
  const missing = fields.filter((f) => !f.optional && isEmpty(f));

  // модуль коллеги закончил — к выбору гипотез (и при ошибке: там экран 04.1)
  const status = job("hypotheses")?.status;
  useEffect(() => {
    if (waiting && status && status !== "running") navigate(`/projects/${projectId}/hypotheses`);
  }, [waiting, status, navigate, projectId]);

  const submit = async () => {
    if (missing.length > 0) {
      setShowWarnings(true);
      return;
    }
    setWaiting(true);
    try {
      await generateHypotheses();
    } catch (e) {
      setWaiting(false);
      toast({ title: "Не удалось запустить генерацию", text: (e as Error).message, tone: "error" });
    }
  };

  return (
    <>
      <div className="work">
        <div className="work-head">
          <h2 className="work-title">Контекст исследования</h2>
          <p className="work-sub">
            Ответьте на вопросы о потребителе и продукте — по ним сервис сформулирует гипотезы и, если нужно,
            разделит потребителей на сегменты. Несколько групп потребителей в поле «Роль» пишите с новой строки.
          </p>
        </div>
        {processing ? (
          <ProcessingCard title="Собираем гипотезы" text="Формулируем сегменты и гипотезы ценности и проверяем их по критериям. Обычно это занимает 3–7 минут." />
        ) : (
          <div className="grid-2">
            {contextBlocks.map((b) => (
              <Card key={b.title} title={b.title}>
                <div className="stack" style={{ gap: 20 }}>
                  {b.fields.map((f) => <Question key={f.key} field={f} locked={view.locked} warn={showWarnings && !f.optional && isEmpty(f)} />)}
                </div>
              </Card>
            ))}
          </div>
        )}
      </div>
      <ActionBar left={view.locked
        ? <span className="small muted">Анкета зафиксирована: по ней уже идут интервью</span>
        : showWarnings && missing.length > 0 ? <span className="small" style={{ color: "var(--yellow)" }}>Заполните обязательные поля: {missing.length}</span> : undefined}>
        <Button variant="secondary" disabled={processing || view.locked} onClick={() => {
          void saveContext().then(() => toast({ title: "Черновик сохранён", text: "Вернуться к анкете можно в любой момент." }));
        }}>
          Сохранить черновик
        </Button>
        {view.locked
          ? <Button onClick={() => navigate(`/projects/${projectId}/hypotheses`)}>К гипотезам</Button>
          : <Button loading={processing} disabled={showWarnings && missing.length > 0} onClick={() => void submit()}>
              {view.segmentVariants.length ? "Собрать гипотезы заново" : "Собрать гипотезы"}
            </Button>}
      </ActionBar>
    </>
  );
}
