// 09 — Стенограмма «вопрос — ответ»: таблица вопрос сценария × респондент + «Выводы по сегменту».
// 09.1 — «Раскладываем ответы по сценарию» (задача stenogram), 09.2 — пока мало расшифрованных интервью.
import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router";

import { ActionBar, Button, Chip, EmptyState, ProcessingCard, SegmentTabs, SlotTag, useToast } from "../../components/ui";
import { useProject } from "../../store/project";

/** Минимум расшифрованных интервью в сегменте, при котором стенограмма имеет смысл без предупреждения. */
const MIN_TRANSCRIBED = 3;

export function StenogramPage() {
  const navigate = useNavigate();
  const { projectId } = useParams();
  const toast = useToast();
  const { view, segmentTabs: tabs, running, job, runStenogram, runInsights } = useProject();
  const [seg, setSeg] = useState(tabs[0]?.value ?? "");
  const current = tabs.some((t) => t.value === seg) ? seg : tabs[0]?.value ?? "";
  const [block, setBlock] = useState<string>("all");

  const sections = view.scenario[current] ?? [];
  const rows = useMemo(() => view.stenogram[current] ?? [], [view.stenogram, current]);
  const done = view.interviews.filter((i) => i.status === "transcribed");
  const inSeg = done.filter((i) => i.segmentId === current).length;
  const processing = running("stenogram");
  const stale = rows.length > 0
    && done.some((i) => i.segmentId === current && !rows.some((r) => r.answers[i.respondentId] !== undefined));

  const people = useMemo(() => {
    const ids = new Set(rows.flatMap((r) => Object.keys(r.answers)));
    return view.respondents.filter((r) => ids.has(r.id)).sort((a, b) => b.code.localeCompare(a.code));
  }, [rows, view.respondents]);

  const visibleSections = sections.filter((s) => block === "all" || s.id === block);
  const run = () => { runStenogram().catch((e: Error) => toast({ title: "Не удалось", text: e.message, tone: "error" })); };

  const exportCsv = () => {
    const esc = (s: string) => `"${s.replace(/"/g, '""')}"`;
    const head = ["Блок", "Вопрос", "Выводы по сегменту", ...people.map((p) => p.code)];
    const lines = [head.map(esc).join(";")];
    for (const s of sections) for (const q of s.questions) {
      const r = rows.find((x) => x.questionId === q.id);
      if (!r) continue;
      lines.push([s.title, q.text, r.summary, ...people.map((p) => r.answers[p.id] ?? "")].map(esc).join(";"));
    }
    const url = URL.createObjectURL(new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `стенограмма-${view.segmentLabel[current] ?? current}.csv`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  let body;
  if (processing) {
    body = <ProcessingCard title="Раскладываем ответы по сценарию" text="Сопоставляем ответы респондентов с вопросами сценария и формулируем выводы по сегменту. Это может занять несколько минут." />;
  } else if (rows.length === 0) {
    body = (
      <div className="card">
        {inSeg === 0 ? (
          <EmptyState title="В сегменте пока нет расшифрованных интервью" text={`Расшифровано интервью: ${done.length} из ${view.plannedInterviews}. Загрузите записи этого сегмента.`}>
            <Button onClick={() => navigate(`/projects/${projectId}/interviews`)}>Перейти к интервью</Button>
          </EmptyState>
        ) : (
          <EmptyState
            title={inSeg < MIN_TRANSCRIBED ? "Пока мало расшифрованных интервью" : "Стенограмма ещё не собрана"}
            text={`Расшифровано ${inSeg} интервью в этом сегменте, всего — ${done.length} из ${view.plannedInterviews}.`
              + (inSeg < MIN_TRANSCRIBED ? " Можно собрать стенограмму по имеющимся и пересобрать, когда загрузите остальные." : "")}
          >
            <Button variant="secondary" onClick={() => navigate(`/projects/${projectId}/interviews`)}>Перейти к интервью</Button>
            <Button onClick={run}>Разложить по сценарию</Button>
          </EmptyState>
        )}
        {job("stenogram")?.status === "error" && <p className="small" style={{ color: "var(--red)" }}>Прошлый запуск не удался: {job("stenogram")?.error}</p>}
      </div>
    );
  } else {
    body = (
      <>
        {stale && (
          <p className="small muted" style={{ marginBottom: 12 }}>
            Есть новые расшифрованные интервью. <button type="button" className="link-btn" onClick={run}>Пересобрать стенограмму</button>
          </p>
        )}
        <div className="row wrap" style={{ gap: 8, marginBottom: 16 }}>
          <Chip active={block === "all"} onClick={() => setBlock("all")}>Все блоки</Chip>
          {sections.map((s) => <Chip key={s.id} active={block === s.id} onClick={() => setBlock(s.id)}>{s.title}</Chip>)}
        </div>
        <div className="steno-wrap">
          <table className="steno">
            <thead>
              <tr>
                <th className="steno-q">Вопрос сценария</th>
                <th className="steno-sum">Выводы по сегменту</th>
                {people.map((p) => <th key={p.id}>{p.code}</th>)}
              </tr>
            </thead>
            <tbody>
              {visibleSections.map((s) => {
                const qs = s.questions.filter((qq) => rows.some((r) => r.questionId === qq.id));
                if (qs.length === 0) return null;
                return [
                  <tr key={s.id} className="steno-section"><td colSpan={2 + people.length}>{s.title}</td></tr>,
                  ...qs.map((qq) => {
                    const row = rows.find((r) => r.questionId === qq.id);
                    return (
                      <tr key={qq.id}>
                        <td className="steno-q">
                          <div style={{ whiteSpace: "pre-line" }}>{qq.text}</div>
                          <div className="row wrap" style={{ gap: 6, marginTop: 8 }}>{qq.checks.map((c) => <SlotTag key={c} slot={c} />)}</div>
                        </td>
                        <td className="steno-sum">{row?.summary}</td>
                        {people.map((p) => (
                          <td key={p.id}>
                            {row?.answers[p.id] ? <>«{row.answers[p.id]}»{row.times?.[p.id] && <div className="small muted">{row.times[p.id]}</div>}</> : <span className="muted">—</span>}
                          </td>
                        ))}
                      </tr>
                    );
                  }),
                ];
              })}
            </tbody>
          </table>
        </div>
      </>
    );
  }

  const disabled = processing || rows.length === 0;
  return (
    <>
      <div className="work">
        <div className="work-head"><h2 className="work-title">Стенограмма «вопрос — ответ»</h2></div>
        <div style={{ marginBottom: 16 }}><SegmentTabs items={tabs} value={current} onChange={(s) => { setSeg(s); setBlock("all"); }} /></div>
        {body}
      </div>
      <ActionBar>
        <Button variant="secondary" icon="download" disabled={disabled} onClick={exportCsv}>Выгрузить в Excel</Button>
        <Button disabled={disabled} loading={running("insights")} onClick={() => {
          runInsights().then(() => navigate(`/projects/${projectId}/insights`))
            .catch((e: Error) => toast({ title: "Не удалось", text: e.message, tone: "error" }));
        }}>Найти инсайты</Button>
      </ActionBar>
    </>
  );
}
