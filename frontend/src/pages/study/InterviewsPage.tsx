// 08 — Интервью и расшифровка. Состояния макета: 08.1 выбор сегмента при загрузке, 08.2 фильтр сегментов,
// 08.3 записей пока нет, 08.4 идёт расшифровка, 08.5 недостаточно токенов, 08.6 ошибка загрузки,
// 08.7 в сегменте нет записей. Загрузка — в API (MinIO), дальше воркер: Nexara → обезличивание → ИГ1.
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";

import { apiGet } from "../../api/client";
import { Icon } from "../../components/Icon";
import { ActionBar, Button, EmptyState, Menu, MenuItem, Modal, ProcessingCard, ProgressBar, Tag, useToast } from "../../components/ui";
import type { Interview, Turn } from "../../domain/types";
import { useDemo } from "../../mocks/store";
import { useProject } from "../../store/project";

const MAX_BYTES = 2 * 1024 ** 3;
const ACCEPT = ".mp3,.wav,.mp4,.mov,.m4a";

function statusTag(i: Interview) {
  switch (i.status) {
    case "transcribed": return <Tag tone="green">Расшифровано</Tag>;
    case "uploading": return <Tag tone="blue">Загрузка {i.progress ?? 0}%</Tag>;
    case "transcribing": return <Tag tone="blue">Расшифровка…</Tag>;
    case "processing": return <Tag tone="blue">Анализ ответов…</Tag>;
    case "too_long": return <Tag tone="red">Длиннее 3 часов</Tag>;
    case "error": return <Tag tone="red">Ошибка</Tag>;
  }
}

function duration(min: number) {
  return min >= 60 ? `${Math.floor(min / 60)} ч ${min % 60} мин` : `${min} мин`;
}

/* ------------------------------------------------------------------ 08.1 Выбор сегмента перед загрузкой */
function SegmentDialog({
  file, onCancel, onConfirm,
}: { file: File | null; onCancel: () => void; onConfirm: (segmentId: string) => void }) {
  const { segmentTabs } = useProject();
  const [seg, setSeg] = useState<string | null>(segmentTabs.length === 1 ? segmentTabs[0]!.value : null);
  const label = segmentTabs.find((t) => t.value === seg)?.label;
  return (
    <Modal
      open={!!file}
      onClose={onCancel}
      title={<>В какой сегмент<br />добавить запись?</>}
      width={520}
      footer={
        <>
          <Button variant="secondary" onClick={onCancel}>Отмена</Button>
          <Button disabled={!seg} onClick={() => seg && onConfirm(seg)}>
            {seg ? `Загрузить в ${label?.toLowerCase()}` : "Выберите сегмент"}
          </Button>
        </>
      }
    >
      <p className="muted">Выберите сегмент перед началом загрузки.</p>
      <div className="file-pill">
        <Icon name="document" />
        <div>
          <div className="strong">{file?.name}</div>
          <div className="small muted">1 файл · готов к загрузке</div>
        </div>
      </div>
      <div className="strong" style={{ margin: "20px 0 8px" }}>Сегменты · {segmentTabs.length}</div>
      <div className="seg-list">
        {segmentTabs.map((s) => (
          <button key={s.value} type="button" className={`seg-option ${seg === s.value ? "is-active" : ""}`} onClick={() => setSeg(s.value)}>
            <Icon name={seg === s.value ? "check" : "document"} /> {s.label}
          </button>
        ))}
      </div>
      <p className="small muted" style={{ marginTop: 16 }}>
        Запись попадёт в выбранный сегмент. До подтверждения загрузка не начинается.
      </p>
    </Modal>
  );
}

/* ------------------------------------------------------------------ 08.5 Недостаточно токенов (тариф — плацебо) */
function NoTokensDialog({ fileName, onClose }: { fileName: string | null; onClose: () => void }) {
  const navigate = useNavigate();
  const { tokens } = useDemo();
  return (
    <Modal
      open={!!fileName}
      onClose={onClose}
      title="Недостаточно токенов"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>Отмена</Button>
          <Button onClick={() => navigate("/settings/tariff")}>Перейти к тарифам</Button>
        </>
      }
    >
      <p className="muted">Чтобы расшифровать запись, нужны токены, а на балансе их не осталось.</p>
      <div className="file-pill">
        <Icon name="document" />
        <div>
          <div className="strong">{fileName}</div>
          <div className="small muted">Ждёт расшифровки</div>
        </div>
      </div>
      <div className="token-warning">
        <Icon name="sparkles" size={16} />
        <span><b>{tokens.left}</b> из {tokens.total.toLocaleString("ru-RU")} токенов</span>
        <button type="button" className="link-btn" onClick={() => navigate("/settings/tariff")}>Пополнить</button>
      </div>
      <p className="small muted" style={{ marginTop: 12 }}>
        Пополните баланс или перейдите на другой тариф, затем запустите расшифровку снова.
      </p>
    </Modal>
  );
}

/* ------------------------------------------------------------------ Плеер записи */
const fmt = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

function Player({ src, audioRef, current, total, onTime, onReady }: {
  src: string; audioRef: React.RefObject<HTMLAudioElement | null>; current: number; total: number; onTime: (s: number) => void;
  onReady: (duration: number) => void;
}) {
  const [playing, setPlaying] = useState(false);
  const [rate, setRate] = useState(1);
  const toggle = () => {
    const a = audioRef.current;
    if (!a) return;
    if (a.paused) void a.play(); else a.pause();
  };
  return (
    <div className="player">
      <audio
        ref={audioRef}
        src={src}
        preload="metadata"
        onLoadedMetadata={(e) => onReady(e.currentTarget.duration)}
        onTimeUpdate={(e) => onTime(e.currentTarget.currentTime)}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
      />
      <button type="button" className="player-btn" aria-label={playing ? "Пауза" : "Воспроизвести"} onClick={toggle}>
        <Icon name={playing ? "pause" : "play"} size={16} />
      </button>
      <span className="small-strong">{fmt(current)}</span>
      <input
        type="range"
        min={0}
        max={Math.max(total, 1)}
        value={current}
        aria-label="Позиция записи"
        onChange={(e) => { const a = audioRef.current; if (a) a.currentTime = Number(e.target.value); onTime(Number(e.target.value)); }}
        className="player-range"
        style={{ "--p": `${(current / Math.max(total, 1)) * 100}%` } as React.CSSProperties}
      />
      <span className="small muted">{fmt(total)}</span>
      <button type="button" className="small-strong link-btn" onClick={() => {
        const next = rate >= 2 ? 1 : rate + 0.5;
        setRate(next);
        if (audioRef.current) audioRef.current.playbackRate = next;
      }}>{rate}×</button>
    </div>
  );
}

export function InterviewsPage() {
  const navigate = useNavigate();
  const { projectId } = useParams();
  const toast = useToast();
  const { view, interviews, upload, cancelUpload, removeInterview, retryInterview, segmentTabs, runStenogram, running } = useProject();
  const { tokens } = useDemo();
  const [pending, setPending] = useState<File | null>(null);
  const [noTokensFor, setNoTokensFor] = useState<string | null>(null);
  // «Открыть запись на этом месте» из цитат (валидация, инсайты, отчёт): ?iv=<интервью>&t=<секунды>
  const [params, setParams] = useSearchParams();
  const [activeId, setActiveId] = useState<string | null>(params.get("iv"));
  const pendingSeek = useRef<number | null>(params.get("t") !== null ? Number(params.get("t")) : null);
  const [seekTick, setSeekTick] = useState(0);
  const [audioDuration, setAudioDuration] = useState(0);
  const [segFilter, setSegFilter] = useState<string>("all");
  const [filterOpen, setFilterOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [position, setPosition] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const [drag, setDrag] = useState(false);

  const label = (seg: string) => view.segmentLabel[seg] ?? seg;
  const visible = interviews.filter((i) => segFilter === "all" || i.segmentId === segFilter);
  const active = visible.find((i) => i.id === activeId) ?? visible.find((i) => i.status === "transcribed") ?? visible[0];
  const hasText = !!active && (active.status === "transcribed" || active.status === "processing") && !active.id.startsWith("up-");
  const transcript = useQuery({
    queryKey: ["transcript", active?.id],
    queryFn: () => apiGet<Turn[]>(`/interviews/${active!.id}/transcript`),
    enabled: hasText,
  });
  const turns = useMemo(() => transcript.data ?? [], [transcript.data]);
  const q = query.trim().toLowerCase();
  const total = audioDuration || (active?.durationMin ?? 0) * 60;
  const canProceed = view.interviews.some((i) => i.status === "transcribed");
  const preparing = running("prepare");

  useEffect(() => { setPosition(pendingSeek.current ?? 0); setQuery(""); setAudioDuration(0); }, [active?.id]);

  // запись загрузилась — перематываем на момент цитаты и убираем параметры из адреса
  const onReady = (duration: number) => {
    if (Number.isFinite(duration)) setAudioDuration(duration);
    const t = pendingSeek.current;
    if (t === null || !audioRef.current) return;
    audioRef.current.currentTime = t;
    setPosition(t);
    pendingSeek.current = null;
    setSeekTick((x) => x + 1);
    setParams((p) => { p.delete("iv"); p.delete("t"); return p; }, { replace: true });
  };

  // после перемотки показываем подсвеченную реплику
  useEffect(() => {
    if (!seekTick || turns.length === 0) return;
    document.querySelector(".turn.is-current")?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [seekTick, turns.length]);

  const activeTurn = useMemo(() => {
    let idx = -1;
    turns.forEach((t, i) => { if ((t.seconds ?? 0) <= position) idx = i; });
    return idx;
  }, [turns, position]);

  const pick = (files: FileList | null) => {
    const f = files?.[0];
    if (!f) return;
    if (f.size > MAX_BYTES) {
      toast({ tone: "error", title: "Файл больше 2 ГБ", text: "Разделите запись или загрузите её по частям." });
      return;
    }
    setPending(f);
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDrag(false);
    pick(e.dataTransfer.files);
  };

  const seek = (t: Turn) => {
    const s = t.seconds ?? 0;
    setPosition(s);
    if (audioRef.current) audioRef.current.currentTime = s;
  };

  const saveTranscript = () => {
    if (!active) return;
    const name = active.respondentId || "Респондент";
    const text = turns.map((t) => `[${t.time}] ${t.speaker === "respondent" ? name : "Интервьюер"}: ${t.text}`).join("\n\n");
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `${name}-расшифровка.txt`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const toStenogram = async () => {
    try {
      await runStenogram();
      navigate(`/projects/${projectId}/stenogram`);
    } catch (e) {
      toast({ title: "Не удалось запустить", text: (e as Error).message, tone: "error" });
    }
  };

  const filterLabel = segFilter === "all" ? "Все сегменты" : label(segFilter);
  const titleOf = (i: Interview) => i.respondentId ? `${i.respondentId} · ${i.fileName?.replace(/\.[^.]+$/, "") ?? ""}` : i.fileName ?? "Новая запись";

  return (
    <>
      <div className="interviews">
        <aside className="iv-list">
          <div
            className={`dropzone ${drag ? "is-drag" : ""}`}
            role="button"
            tabIndex={0}
            onClick={() => inputRef.current?.click()}
            onKeyDown={(e) => e.key === "Enter" && inputRef.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
            onDragLeave={() => setDrag(false)}
            onDrop={onDrop}
          >
            <Icon name="upload" />
            <span className="small-strong" style={{ color: "var(--accent)" }}>Перетащите записи или выберите файлы</span>
            <span className="small muted">mp3, wav, mp4, mov, m4a · до 2 ГБ и 3 часов</span>
            <span className="small muted">Сегмент выберете перед загрузкой</span>
            <input ref={inputRef} type="file" accept={ACCEPT} hidden onChange={(e) => { pick(e.target.files); e.target.value = ""; }} />
          </div>

          {preparing && <p className="small muted" style={{ marginTop: 12 }}>Готовим анализ: раскладываем гипотезы на компоненты и связываем вопросы сценария с ними.</p>}

          {interviews.length > 0 && (
            <div className="row-between" style={{ margin: "20px 0 8px" }}>
              <span className="strong">Записи · {visible.length}</span>
              <div className="menu-anchor">
                <button type="button" className="select-btn" aria-haspopup="menu" aria-expanded={filterOpen} onClick={() => setFilterOpen((v) => !v)}>
                  {filterLabel} <Icon name="chevronDown" size={16} />
                </button>
                <Menu open={filterOpen} onClose={() => setFilterOpen(false)}>
                  <MenuItem selected={segFilter === "all"} onClick={() => { setSegFilter("all"); setFilterOpen(false); }}>Все сегменты</MenuItem>
                  {segmentTabs.map((s) => (
                    <MenuItem key={s.value} selected={segFilter === s.value} onClick={() => { setSegFilter(s.value); setFilterOpen(false); }}>{s.label}</MenuItem>
                  ))}
                </Menu>
              </div>
            </div>
          )}

          {interviews.length > 0 && visible.length === 0 && (
            <div className="card">
              <EmptyState compact title={`В ${label(segFilter).toLowerCase().replace("сегмент", "сегменте")} пока нет записей`} text="Загрузите запись и выберите этот сегмент или переключите фильтр.">
                <Button variant="text" onClick={() => setSegFilter("all")}>Показать все сегменты</Button>
              </EmptyState>
            </div>
          )}

          <div className="iv-items">
            {visible.map((i) => {
              const meta = [label(i.segmentId), i.fileType, i.durationMin ? duration(i.durationMin) : null, i.sizeMb ? `${i.sizeMb} МБ` : null].filter(Boolean).join(" · ");
              return (
                <div
                  key={i.id}
                  className={`iv-item ${i.id === active?.id ? "is-active" : ""}`}
                  role="button"
                  tabIndex={0}
                  onClick={() => setActiveId(i.id)}
                  onKeyDown={(e) => e.key === "Enter" && setActiveId(i.id)}
                >
                  <div className="row-between">
                    <span className="strong">{titleOf(i)}</span>
                    {statusTag(i)}
                  </div>
                  <div className="small muted">{meta}</div>
                  {i.status === "uploading" && (
                    <>
                      <ProgressBar value={i.progress ?? 0} />
                      <div className="row small" style={{ gap: 12 }}>
                        <button type="button" className="link-muted" onClick={(e) => { e.stopPropagation(); cancelUpload(i.id); }}>Отменить</button>
                      </div>
                    </>
                  )}
                  {(i.status === "transcribing" || i.status === "processing") && i.progress != null && (
                    <>
                      <ProgressBar value={i.progress} />
                      <div className="row-between small muted">
                        <span>{i.stageLabel}</span>
                        <span>{i.progress} %</span>
                      </div>
                    </>
                  )}
                  {i.status === "error" && (
                    <>
                      <div className="small" style={{ color: "var(--red)" }}>{i.error || "Не удалось обработать запись."}</div>
                      <div className="row small" style={{ gap: 12 }}>
                        {!i.id.startsWith("up-") && (
                          <Button variant="text" size="sm" onClick={(e) => {
                            e.stopPropagation();
                            retryInterview(i.id).catch((err: Error) => toast({ title: "Повтор не запущен", text: err.message, tone: "info" }));
                          }}>Повторить</Button>
                        )}
                        <button type="button" className="link-muted" onClick={(e) => { e.stopPropagation(); void removeInterview(i.id); }}>Удалить</button>
                      </div>
                    </>
                  )}
                </div>
              );
            })}
          </div>
        </aside>

        <section className="iv-transcript">
          {interviews.length === 0 ? (
            <EmptyState title="Записей пока нет" text="Загрузите запись интервью слева — здесь появится расшифровка с репликами и таймкодами." />
          ) : !active ? (
            <EmptyState title="Здесь появится расшифровка" text="Выберите запись в списке слева." />
          ) : (
            <>
              <div className="iv-head">
                <div className="row-between">
                  <div>
                    <h2 className="h-block">{titleOf(active)}</h2>
                    <div className="small muted">
                      {active.recordedAt}{active.durationMin ? ` · ${duration(active.durationMin)}` : ""} · {label(active.segmentId)}
                      {active.claims ? ` · утверждений: ${active.claims}` : ""}
                    </div>
                  </div>
                  {searchOpen ? (
                    <label className="search search-sm">
                      <Icon name="search" />
                      <input autoFocus placeholder="Найти в тексте" value={query} onChange={(e) => setQuery(e.target.value)} onBlur={() => !query && setSearchOpen(false)} />
                    </label>
                  ) : (
                    <Button variant="secondary" icon="search" disabled={!hasText} onClick={() => setSearchOpen(true)}>Найти в тексте</Button>
                  )}
                </div>
                {hasText && <Player src={`/api/interviews/${active.id}/media`} audioRef={audioRef} current={position} total={total} onTime={setPosition} onReady={onReady} />}
              </div>
              {active.status === "uploading" || active.status === "transcribing" ? (
                <ProcessingCard
                  title="Расшифровываем запись"
                  text={`Распознаём речь и разделяем собеседников. Обычно это занимает несколько минут.${active.progress != null ? ` Готово примерно на ${active.progress} %.` : ""}`}
                />
              ) : active.status === "error" ? (
                <EmptyState icon="warning" tone="red" title="Запись не обработана" text={active.error ?? "Попробуйте ещё раз."} />
              ) : (
                <div className="turns">
                  {active.status === "processing" && <p className="small muted">Расшифровка готова, идёт разбор ответов на утверждения (ИГ1).</p>}
                  {transcript.isLoading && <p className="muted">Загружаем расшифровку…</p>}
                  {turns.filter((t) => !q || t.text.toLowerCase().includes(q)).map((t) => (
                    <button
                      key={t.index}
                      type="button"
                      className={`turn ${isCurrentPair(turns, turns.indexOf(t), activeTurn) ? "is-current" : ""}`}
                      onClick={() => seek(t)}
                    >
                      <span className="small muted turn-time">{t.time}</span>
                      <span>
                        <span className={`small-strong ${t.speaker === "respondent" ? "speaker" : "speaker-int"}`}>
                          {t.speaker === "respondent" ? active.respondentId : "Интервьюер"}
                        </span>
                        <span className="turn-text">{highlight(t.text, q)}</span>
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </>
          )}
        </section>
      </div>
      <ActionBar>
        <Button variant="secondary" icon="download" disabled={!hasText || turns.length === 0} onClick={saveTranscript}>
          Скачать расшифровку
        </Button>
        <Button disabled={!canProceed} loading={running("stenogram")} onClick={() => void toStenogram()}>
          Разложить по сценарию
        </Button>
      </ActionBar>
      <SegmentDialog
        key={pending?.name ?? "none"}
        file={pending}
        onCancel={() => setPending(null)}
        onConfirm={(seg) => {
          if (!pending) return;
          if (tokens.left === 0) {
            setNoTokensFor(pending.name);
            setPending(null);
            return;
          }
          upload(pending, seg);
          toast({ title: "Загрузка началась", text: `Запись попадёт в ${label(seg).toLowerCase()}.` });
          setPending(null);
        }}
      />
      <NoTokensDialog fileName={noTokensFor} onClose={() => setNoTokensFor(null)} />
    </>
  );
}

function isCurrentPair(turns: { speaker: string }[], idx: number, active: number) {
  if (active < 0) return false;
  // Пара «вопрос → ответ»: если позиция на ответе, начало пары — предыдущий вопрос
  const start = turns[active]?.speaker === "respondent" && turns[active - 1]?.speaker === "interviewer" ? active - 1 : active;
  return idx === start || (idx === start + 1 && turns[start + 1]?.speaker === "respondent");
}

function highlight(text: string, q: string) {
  if (!q) return text;
  const i = text.toLowerCase().indexOf(q);
  if (i < 0) return text;
  return <>{text.slice(0, i)}<mark>{text.slice(i, i + q.length)}</mark>{text.slice(i + q.length)}</>;
}
