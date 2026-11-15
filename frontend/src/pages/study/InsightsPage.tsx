// 10 — Инсайты (ИГ3): «Дополняют / Опровергают», карточки с уровнем (устойчивый от 3 респондентов / кандидат),
// правка, панель «Цитаты к инсайту» с контрпримерами. 10.1 — «Ищем инсайты» (задача insights),
// 10.2 — новый инсайт, 10.3 — редактирование. Правки человека повторный поиск не перезаписывает.
import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router";

import { HYPOTHESIS_TITLE, QuoteCard } from "../../components/domain";
import { Icon } from "../../components/Icon";
import { ActionBar, Button, Caps, Chip, EmptyState, Modal, ProcessingCard, SegmentTabs, Tag, useToast } from "../../components/ui";
import { SLOT_LABEL, type HypothesisKind, type Insight, type InsightRelation, type SlotCode } from "../../domain/types";
import { useProject } from "../../store/project";

const SLOTS: Record<HypothesisKind, SlotCode[]> = {
  segment: ["role", "situation", "job", "outcome"],
  value: ["role", "situation", "problem", "job", "losses", "function", "outcome", "effect"],
};

const KIND_SHORT: Record<HypothesisKind, string> = { segment: "Гипотеза сегмента", value: "Гипотеза ценности" };

function plural(n: number, one: string, few: string, many: string) {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
  return many;
}

function quoteStats(i: Insight) {
  const people = [...new Set(i.quotes.filter((q) => !q.counter).map((q) => q.respondentId))];
  const n = i.nSupporting ?? people.length;
  const of = i.nSegment ? ` из ${i.nSegment}` : "";
  return {
    people,
    text: `${i.quotes.length} ${plural(i.quotes.length, "цитата", "цитаты", "цитат")} · ${n}${of} ${plural(n, "респондент", "респондента", "респондентов")}`,
  };
}

export function InsightsPage() {
  const navigate = useNavigate();
  const { projectId } = useParams();
  const toast = useToast();
  const { view, segmentTabs: tabs, running, job, runInsights, saveInsight, hypothesis } = useProject();
  const processing = running("insights");
  const [seg, setSeg] = useState(tabs[0]?.value ?? "");
  const current = tabs.some((t) => t.value === seg) ? seg : tabs[0]?.value ?? "";
  const [rel, setRel] = useState<"all" | InsightRelation>("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editing, setEditing] = useState<Insight | "new" | null>(null);
  const [showAll, setShowAll] = useState(false);

  const ofSegment = view.insights.filter((i) => i.segmentId === current);
  const visible = ofSegment.filter((i) => rel === "all" || i.relation === rel);
  const selected = ofSegment.find((i) => i.id === selectedId) ?? visible[0];
  const groups = useMemo(
    () => (["segment", "value"] as HypothesisKind[]).map((k) => ({ kind: k, items: visible.filter((i) => i.hypothesisKind === k) })),
    [visible],
  );
  const hasInterviews = view.interviews.some((i) => i.segmentId === current && i.status === "transcribed");

  // «В гипотезе» для нового инсайта — текст выбранного элемента гипотезы
  const expectedFor = (kind: HypothesisKind, slot: SlotCode) => {
    const id = kind === "segment" ? current : (view.selectedValues[current] ?? [])[0];
    return id ? hypothesis(id)?.lines.find((l) => l.slot === slot)?.text.replace(/[,.]$/, "") ?? "" : "";
  };
  const find = () => { runInsights().catch((e: Error) => toast({ title: "Не удалось", text: e.message, tone: "error" })); };

  return (
    <>
      <div className="insights">
        <div className="work">
          <div className="work-head row-between">
            <h2 className="work-title">Инсайты</h2>
            {!processing && ofSegment.length > 0 && <Button variant="secondary" icon="sparkles" onClick={find}>Найти заново</Button>}
          </div>
          <div style={{ marginBottom: 16 }}><SegmentTabs items={tabs} value={current} onChange={(s) => { setSeg(s); setShowAll(false); setSelectedId(null); }} /></div>

          {processing ? (
            <ProcessingCard title="Ищем инсайты" text="Сравниваем ответы респондентов с гипотезами сегмента, объединяем повторы и проверяем каждый вывод по всем интервью. Обычно 3–8 минут." />
          ) : ofSegment.length === 0 ? (
            <div className="card">
              <EmptyState
                title="Инсайтов пока нет"
                text={hasInterviews
                  ? "Запустите поиск: сервис найдёт расхождения между гипотезой и тем, что рассказали респонденты. Можно добавить инсайт вручную."
                  : "Они появятся, когда в сегменте будут расшифрованные интервью. Можно добавить инсайт вручную."}
              >
                <Button variant="secondary" onClick={() => setEditing("new")}>Добавить инсайт</Button>
                {hasInterviews && <Button onClick={find}>Найти инсайты</Button>}
              </EmptyState>
              {job("insights")?.status === "error" && <p className="small" style={{ color: "var(--red)" }}>Прошлый поиск не удался: {job("insights")?.error}</p>}
            </div>
          ) : (
            <>
              <div className="row wrap" style={{ gap: 8, marginBottom: 4 }}>
                <Chip active={rel === "all"} onClick={() => setRel("all")}>Все · {ofSegment.length}</Chip>
                <Chip active={rel === "extends"} onClick={() => setRel("extends")}>
                  <span className="chip-dot" style={{ background: "var(--accent)" }} /> Дополняют · {ofSegment.filter((i) => i.relation === "extends").length}
                </Chip>
                <Chip active={rel === "contradicts"} onClick={() => setRel("contradicts")}>
                  <span className="chip-dot" style={{ background: "var(--red)" }} /> Опровергают · {ofSegment.filter((i) => i.relation === "contradicts").length}
                </Chip>
              </div>
              {visible.length === 0 && <p className="muted" style={{ marginTop: 20 }}>Инсайтов по выбранному фильтру нет.</p>}
              {groups.filter((g) => g.items.length).map((g) => (
                <div key={g.kind}>
                  <Caps className="section-caps">{HYPOTHESIS_TITLE[g.kind]}</Caps>
                  <div className="stack">
                    {g.items.map((ins) => (
                      <InsightCard
                        key={ins.id}
                        n={ofSegment.indexOf(ins) + 1}
                        insight={ins}
                        active={selected?.id === ins.id}
                        onClick={() => { setSelectedId(ins.id); setShowAll(false); }}
                        onEdit={() => setEditing(ins)}
                      />
                    ))}
                  </div>
                </div>
              ))}
            </>
          )}
        </div>

        <aside className="quotes-panel">
          {selected && !processing ? (
            <>
              <div className="row-between">
                <h3 className="h-block">Цитаты к инсайту</h3>
                <span className="count-pill">{selected.quotes.length}</span>
              </div>
              <div className="small muted" style={{ margin: "6px 0 16px" }}>
                Инсайт {ofSegment.indexOf(selected) + 1} · {HYPOTHESIS_TITLE[selected.hypothesisKind]} · {SLOT_LABEL[selected.slot]}
              </div>
              {selected.explanation && <p className="small" style={{ marginBottom: 12 }}><b>Почему так:</b> {selected.explanation}</p>}
              <div className="stack-sm" style={{ gap: 12 }}>
                {(showAll ? selected.quotes : selected.quotes.slice(0, 4)).map((q) => (
                  <QuoteCard key={q.respondentId + q.time + q.text.slice(0, 12)} quote={q} tone={q.counter ? "red" : undefined} label={q.counter ? "против" : undefined} />
                ))}
              </div>
              {!showAll && selected.quotes.length > 4 && (
                <Button variant="text" size="sm" onClick={() => setShowAll(true)}>
                  ещё {selected.quotes.length - 4} {plural(selected.quotes.length - 4, "цитата", "цитаты", "цитат")}
                </Button>
              )}
              {selected.boundaries && selected.boundaries.length > 0 && (
                <div className="small" style={{ marginTop: 16 }}><b>Границы:</b> {selected.boundaries.join("; ")}</div>
              )}
              {selected.actions && selected.actions.length > 0 && (
                <div className="small" style={{ marginTop: 8 }}><b>Что сделать:</b> {selected.actions.join("; ")}</div>
              )}
              <div className="small muted" style={{ marginTop: 16 }}>Комментарии · {selected.comments}</div>
            </>
          ) : !processing ? <p className="muted">Выберите инсайт</p> : null}
        </aside>
      </div>
      <ActionBar>
        <Button variant="secondary" disabled={processing} onClick={() => setEditing("new")}>Добавить инсайт</Button>
        <Button disabled={processing} onClick={() => navigate(`/projects/${projectId}/validation`)}>Проверить гипотезы</Button>
      </ActionBar>
      {editing && (
        <InsightModal
          key={editing === "new" ? "new" : editing.id}
          insight={editing === "new" ? null : editing}
          segmentLabel={tabs.find((t) => t.value === current)?.label ?? ""}
          onClose={() => setEditing(null)}
          onSave={(draft) => {
            const base: Insight = editing === "new"
              ? { id: "", segmentId: current, quotes: [], comments: 0, expected: expectedFor(draft.kind, draft.slot), observed: "",
                  hypothesisKind: draft.kind, slot: draft.slot, relation: draft.relation, title: "" }
              : editing;
            const next: Insight = { ...base, title: draft.title, hypothesisKind: draft.kind, slot: draft.slot, relation: draft.relation,
              observed: draft.observed, expected: base.expected || expectedFor(draft.kind, draft.slot) };
            saveInsight(next, editing === "new", draft.comment || undefined)
              .then(() => toast({ title: editing === "new" ? "Инсайт добавлен" : "Инсайт сохранён" }))
              .catch((e: Error) => toast({ title: "Не удалось сохранить", text: e.message, tone: "error" }));
            setEditing(null);
          }}
        />
      )}
    </>
  );
}

function InsightCard({ insight, n, active, onClick, onEdit }: { insight: Insight; n: number; active: boolean; onClick: () => void; onEdit: () => void }) {
  const { text } = quoteStats(insight);
  return (
    <div className={`card insight-card ${active ? "card-active" : ""}`} role="button" tabIndex={0} onClick={onClick} onKeyDown={(e) => e.key === "Enter" && onClick()}>
      <div className="row-between" style={{ alignItems: "flex-start" }}>
        <div className="stack-sm" style={{ gap: 4 }}>
          <span className="small-strong">
            Инсайт {n}
            {insight.level && insight.source !== "user" && <> · {insight.level === "stable" ? "устойчивый" : "кандидат"}</>}
            {insight.source === "user" && " · проверен исследователем"}
          </span>
          <span className="h-block">{insight.title}</span>
        </div>
        <button type="button" className="icon-btn" aria-label={`Редактировать инсайт ${n}`} title="Редактировать" onClick={(e) => { e.stopPropagation(); onEdit(); }}>
          <Icon name="pencil" size={18} />
        </button>
      </div>
      <div className="insight-diff">
        <div className="row" style={{ gap: 8 }}>
          <span className="small muted">{KIND_SHORT[insight.hypothesisKind]}</span>
          <Tag tone="blue">{SLOT_LABEL[insight.slot]}</Tag>
          <Tag tone={insight.relation === "contradicts" ? "red" : "green"}>{insight.relation === "contradicts" ? "Опровергает" : "Дополняет"}</Tag>
          {insight.level === "candidate" && insight.source !== "user" && <Tag tone="yellow">Проверить на следующих интервью</Tag>}
        </div>
        <div className="diff-row"><span className="small muted">В гипотезе</span><span>{insight.expected}</span></div>
        <div className="diff-row"><span className="small muted">По данным</span><span>{insight.observed}</span></div>
      </div>
      <div className="row small" style={{ gap: 8 }}>
        <Icon name="quote" size={16} className="muted" />
        <span className="small-strong">{text}</span>
      </div>
    </div>
  );
}

type Draft = { title: string; kind: HypothesisKind; slot: SlotCode; relation: InsightRelation; observed: string; comment: string };

function InsightModal({
  insight, segmentLabel, onClose, onSave,
}: { insight: Insight | null; segmentLabel: string; onClose: () => void; onSave: (d: Draft) => void }) {
  const [title, setTitle] = useState(insight?.title ?? "");
  const [kind, setKind] = useState<HypothesisKind | "">(insight?.hypothesisKind ?? "");
  const [slot, setSlot] = useState<SlotCode | "">(insight?.slot ?? "");
  const [relation, setRelation] = useState<InsightRelation>(insight?.relation ?? "extends");
  const [observed, setObserved] = useState(insight?.observed ?? "");
  const [comment, setComment] = useState("");
  const ok = title.trim() && kind && slot && observed.trim();
  const subtitle = insight
    ? `${segmentLabel} · ${quoteStats(insight).text}`
    : `${segmentLabel} · свяжите инсайт с элементом гипотезы.`;
  return (
    <Modal
      open
      onClose={onClose}
      title={insight ? "Инсайт" : "Новый инсайт"}
      width={480}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>Отмена</Button>
          <Button disabled={!ok} onClick={() => ok && onSave({ title, kind, slot, relation, observed, comment })}>
            {insight ? "Сохранить" : "Добавить инсайт"}
          </Button>
        </>
      }
    >
      <p className="muted" style={{ marginBottom: 16 }}>{subtitle}</p>
      <div className="stack">
        <label className="field"><span className="field-label">Формулировка инсайта</span>
          <textarea className="textarea" rows={insight ? 3 : 2} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Например: подготовка начинается только после первого отказа" />
        </label>
        <label className="field"><span className="field-label">Гипотеза</span>
          <select className="input" value={kind} onChange={(e) => { setKind(e.target.value as HypothesisKind); setSlot(""); }}>
            <option value="" disabled>Выберите гипотезу</option>
            <option value="segment">{HYPOTHESIS_TITLE.segment}</option>
            <option value="value">{HYPOTHESIS_TITLE.value}</option>
          </select>
        </label>
        <div className="grid-2" style={{ gap: 12 }}>
          <label className="field"><span className="field-label">Элемент</span>
            <select className="input" value={slot} disabled={!kind} onChange={(e) => setSlot(e.target.value as SlotCode)}>
              <option value="" disabled>Выберите элемент</option>
              {(kind ? SLOTS[kind] : []).map((s) => <option key={s} value={s}>{SLOT_LABEL[s]}</option>)}
            </select>
          </label>
          <label className="field"><span className="field-label">Связь</span>
            <select className="input" value={relation} onChange={(e) => setRelation(e.target.value as InsightRelation)}>
              <option value="extends">Дополняет</option>
              <option value="contradicts">Опровергает</option>
            </select>
          </label>
        </div>
        <label className="field"><span className="field-label">Что показали данные</span>
          <textarea className="textarea" rows={2} value={observed} onChange={(e) => setObserved(e.target.value)} placeholder="Что сказали респонденты своими словами" />
        </label>
        <label className="field"><span className="field-label">Комментарий (необязательно)</span>
          <textarea className="textarea" rows={2} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Почему поправили или что проверить" />
        </label>
      </div>
    </Modal>
  );
}
