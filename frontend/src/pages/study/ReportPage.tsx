// 12 — Отчёт и выгрузка (структура макета 14.11.2026): Продукт → Сегменты и гипотезы (актуальные + исходные
// с результатами проверки) → Аналитика: А1 Что проверяли, А2 Инсайты, А3 Как изменились гипотезы.
// Состояния: 12.1 выбор формата, 12.3 готовим файл, 12.4 не удалось скачать. Статусы и % — ИГ2 с бэкенда.
import { useState, type ReactNode } from "react";
import { useParams } from "react-router";

import { download } from "../../api/client";
import { ComponentRow, HYPOTHESIS_TITLE, QuoteCard } from "../../components/domain";
import { Icon } from "../../components/Icon";
import { Button, Caps, EmptyState, Menu, MenuItem, SegmentTabs, SlotTag, Tag, useToast } from "../../components/ui";
import { summarize } from "../../domain/ig2";
import { SLOT_LABEL, type HypothesisKind, type SlotLine } from "../../domain/types";
import { useProject } from "../../store/project";

const TOC = [
  { id: "product", label: "Продукт" },
  { id: "segments", label: "Сегменты и гипотезы" },
  { id: "analytics", label: "Аналитика" },
  { id: "a1", label: "А1. Что проверяли", sub: true },
  { id: "a2", label: "А2. Инсайты", sub: true },
  { id: "a3", label: "А3. Как изменились гипотезы", sub: true },
];

const METHOD_NOTE =
  "Как считали процент: доля подтверждённых элементов среди тех, что обсуждались в интервью. Элемент подтверждён, " +
  "если «за» не меньше 5 человек и втрое больше, чем «против»; опровергнут — наоборот. Не обсуждавшиеся элементы " +
  "и функция, которую проблемные интервью не проверяют, в процент не входят.";

function Collapsible({ id, title, hint, children, defaultOpen = false }: { id: string; title: string; hint: string; children: ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section id={id} className="card report-collapsible">
      <button type="button" className="collapse-head" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span className="stack-sm" style={{ gap: 4, textAlign: "left" }}>
          <span className="report-h">{title}</span>
          <span className="small muted">{hint}</span>
        </span>
        <Icon name="chevronDown" className="muted" />
      </button>
      {open && <div className="collapse-body">{children}</div>}
    </section>
  );
}

function HypothesisLines({ lines }: { lines: SlotLine[] }) {
  return (
    <div className="report-lines">
      {lines.map((l) => (
        <div key={l.slot} className="report-line">
          <SlotTag slot={l.slot} />
          <span>{l.lead && <span className="slot-lead">{l.lead} </span>}{l.text}</span>
        </div>
      ))}
    </div>
  );
}

const lc = (s?: string) => (s ? s.charAt(0).toLowerCase() + s.slice(1) : "");

export function ReportPage() {
  const toast = useToast();
  const { projectId = "" } = useParams();
  const { view, hypothesis, segmentTabs: tabs } = useProject();
  const [seg, setSeg] = useState(tabs[0]?.value ?? "");
  const current = tabs.some((t) => t.value === seg) ? seg : tabs[0]?.value ?? "";
  const [active, setActive] = useState("product");
  const [formatOpen, setFormatOpen] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const v = view.context;
  const d = view.design;

  const save = (path: string) => {
    setFormatOpen(false);
    setPreparing(true); // 12.3 — готовим файл
    download(path)
      .catch(() => toast({
        tone: "error",
        title: "Не удалось скачать отчёт",
        text: "Проверьте подключение к интернету и попробуйте ещё раз.",
        action: { label: "Повторить", onClick: () => save(path) },
      }))
      .finally(() => setPreparing(false));
  };

  const go = (id: string) => {
    setActive(id);
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const original = (s: string, kind: HypothesisKind) => hypothesis(kind === "segment" ? s : (view.selectedValues[s] ?? [])[0] ?? "");
  const resultsOf = (s: string) => view.validation.filter((r) => r.segmentId === s);
  const changes = tabs.flatMap((t) => (view.reformulated[t.value]?.changes ?? []).map((c) => ({ ...c, seg: t.label })));

  return (
    <div className="work report">
      <nav className="report-toc">
        <div className="caps" style={{ marginBottom: 8 }}>Содержание</div>
        {TOC.map((t) => (
          <button key={t.id} type="button" className={`toc-item ${t.sub ? "is-sub" : ""} ${active === t.id ? "is-active" : ""}`} onClick={() => go(t.id)}>
            {t.label}
          </button>
        ))}
      </nav>

      <div className="report-body">
        <div className="row-between" style={{ alignItems: "flex-start", gap: 24 }}>
          <h1 className="report-title">Отчёт CustDev-исследования. {view.name}</h1>
          <div className="menu-anchor">
            <Button icon="download" loading={preparing} aria-haspopup="menu" aria-expanded={formatOpen} onClick={() => setFormatOpen((x) => !x)}>
              Скачать
            </Button>
            <Menu open={formatOpen} onClose={() => setFormatOpen(false)}>
              <MenuItem icon="document" onClick={() => save(`/projects/${projectId}/export/report?fmt=docx`)}>Word (.docx)</MenuItem>
              <MenuItem icon="document" onClick={() => save(`/projects/${projectId}/export/report?fmt=md`)}>Markdown (.md)</MenuItem>
              <MenuItem icon="chart" onClick={() => save(`/projects/${projectId}/export/package`)}>Пакет результатов (.json)</MenuItem>
            </Menu>
          </div>
        </div>

        <section id="product" className="card report-section">
          <h2 className="report-h">Продукт</h2>
          <p>{d?.product_name || v.product}. Ключевая функция — {lc(d?.key_function || v.function)}.</p>
          {d?.problem_and_losses && <p>{d.problem_and_losses}</p>}
          <p><b>Цель исследования:</b> {lc(d?.research_goal || v.decision)}</p>
        </section>

        <section id="segments" className="report-plain">
          <h2 className="report-h">Сегменты и гипотезы</h2>
          <p>Каждый сегмент — на своей вкладке. Сверху актуальные гипотезы, уточнённые по данным интервью, ниже — результаты проверки исходных гипотез.</p>
          <SegmentTabs items={tabs} value={current} onChange={setSeg} />
          {(() => {
            const actual = view.reformulated[current];
            const results = resultsOf(current);
            return (
              <>
                <h3 className="h-block" style={{ marginTop: 8 }}>Актуальные гипотезы</h3>
                {actual ? (
                  <>
                    <p className="muted">Уточнены по инсайтам интервью и согласованы с собранными данными.</p>
                    <div className="card"><h4 className="h-block">{HYPOTHESIS_TITLE.segment}</h4><HypothesisLines lines={actual.segment} /></div>
                    {actual.value.length > 0 && <div className="card"><h4 className="h-block">{HYPOTHESIS_TITLE.value}</h4><HypothesisLines lines={actual.value} /></div>}
                  </>
                ) : (
                  <div className="card"><EmptyState compact title="Пока совпадают с исходными" text="Нажмите «Переформулировать гипотезы» на шаге «Валидация», когда наберётся достаточно интервью." /></div>
                )}
                <h3 className="h-block" style={{ marginTop: 8 }}>Проверка исходных гипотез</h3>
                {results.length === 0 || results.every((r) => r.nInterviews === 0) ? (
                  <div className="card"><EmptyState compact title="Нет результатов проверки" text="Гипотезы этого сегмента ещё не проверялись на интервью." /></div>
                ) : results.map((r) => {
                  const p = r.percent === undefined ? summarize(r.components).percent : r.percent === null ? null : Math.round(r.percent);
                  return (
                    <div key={r.hypothesisId} className="card">
                      <div className="row-between">
                        <h4 className="h-block">{HYPOTHESIS_TITLE[r.kind]}</h4>
                        <span className="h-section">{p === null ? "—" : `${p} %`}</span>
                      </div>
                      <p className="small muted">{r.nInterviews} интервью</p>
                      <div className="comp-list">
                        {r.components.map((c) => <ComponentRow key={c.componentId ?? c.slot} evidence={c} lead={c.lead ?? undefined} text={c.text ?? "—"} />)}
                      </div>
                    </div>
                  );
                })}
                <p className="small muted">{METHOD_NOTE}</p>
              </>
            );
          })()}
        </section>

        <section id="analytics" className="report-plain">
          <h2 className="report-h">Аналитика</h2>
          <p className="muted">Обоснование ключевых выводов: что проверяли, какие выводы прошли проверку и как из них получились актуальные формулировки.</p>
        </section>

        <Collapsible id="a1" title="А1. Что проверяли" hint="Гипотезы, с которыми начинали исследование. Их сформулировали на шаге «Гипотезы» до интервью.">
          {tabs.map((t) => (
            <div key={t.value} className="stack">
              <Caps>{t.label}</Caps>
              {(["segment", "value"] as HypothesisKind[]).map((k) => {
                const h = original(t.value, k);
                return h ? <div key={k}><div className="strong" style={{ marginBottom: 6 }}>{HYPOTHESIS_TITLE[k]}</div><HypothesisLines lines={h.lines} /></div> : null;
              })}
            </div>
          ))}
        </Collapsible>

        <Collapsible id="a2" title="А2. Инсайты" hint="Выводы из интервью, которые дополняют или опровергают элементы гипотез: что предполагали, что увидели и почему.">
          {view.insights.length === 0 && <p className="muted">Инсайты ещё не найдены — запустите поиск на шаге «Инсайты».</p>}
          {tabs.map((t) => {
            const items = view.insights.filter((i) => i.segmentId === t.value);
            if (items.length === 0) return null;
            return (
              <div key={t.value} className="stack">
                <Caps>{t.label}</Caps>
                {items.map((i, n) => (
                  <div key={i.id} className="report-insight">
                    <div className="row" style={{ gap: 8 }}>
                      <span className="small-strong">Инсайт {n + 1}</span>
                      <Tag tone={i.relation === "contradicts" ? "red" : "green"}>{i.relation === "contradicts" ? "Опровергает" : "Дополняет"}</Tag>
                      {i.level && i.source !== "user" && <Tag tone={i.level === "stable" ? "blue" : "yellow"}>{i.level === "stable" ? "устойчивый" : "кандидат"}</Tag>}
                    </div>
                    <div className="strong" style={{ margin: "2px 0 6px" }}>{i.title}</div>
                    <div className="small muted">{HYPOTHESIS_TITLE[i.hypothesisKind]} · {SLOT_LABEL[i.slot]}</div>
                    <div className="diff-row" style={{ marginTop: 8 }}><span className="small muted">В гипотезе</span><span>{i.expected}</span></div>
                    <div className="diff-row"><span className="small muted">По данным</span><span>{i.observed}</span></div>
                    {i.explanation && <div className="diff-row"><span className="small muted">Почему</span><span>{i.explanation}</span></div>}
                    <div className="stack-sm" style={{ gap: 8, marginTop: 8 }}>
                      {i.quotes.slice(0, 2).map((q) => (
                        <QuoteCard key={q.respondentId + q.time + q.text.slice(0, 12)} quote={q} tone={q.counter ? "red" : undefined} label={q.counter ? "против" : undefined} />
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            );
          })}
        </Collapsible>

        <Collapsible id="a3" title="А3. Как изменились гипотезы" hint="Только изменённые элементы: как было до интервью и как стало после переформулировки по данным.">
          {changes.length === 0 && <p className="muted">Гипотезы ещё не переформулированы по итогам интервью.</p>}
          {changes.map((c) => (
            <div key={c.seg + c.kind + c.slot} className="report-insight">
              <div className="small-strong" style={{ marginBottom: 6 }}>{c.seg} · {HYPOTHESIS_TITLE[c.kind]} · {SLOT_LABEL[c.slot]}</div>
              <div className="diff-row"><span className="small muted">Было</span><span>{c.before}</span></div>
              <div className="diff-row"><span className="small muted">Стало</span><span>{c.after}</span></div>
            </div>
          ))}
        </Collapsible>
      </div>
    </div>
  );
}
