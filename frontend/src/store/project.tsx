// Состояние открытого исследования: одно представление проекта с бэкенда (GET /projects/{id}/view)
// + действия экранов. Пока идут фоновые задачи (модуль коллеги, расшифровка, ИГ1, стенограмма, ИГ3) —
// представление опрашивается раз в 3 секунды, и экраны «идёт обработка» сами сменяются готовыми.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { apiGet, apiSend, uploadFile, type UploadHandle } from "../api/client";
import type { Hypothesis, Insight, Interview, JobKind, JobState, ProjectView } from "../domain/types";

type Uploading = Interview & { handle?: UploadHandle };

type ProjectState = {
  projectId: string;
  view: ProjectView;
  refresh: () => Promise<void>;
  job: (kind: JobKind) => JobState | undefined;
  running: (kind: JobKind) => boolean;
  hypothesis: (id: string) => Hypothesis | undefined;
  segmentTabs: { value: string; label: string }[];
  respondentLabel: (id: string) => string;

  setContextValue: (key: string, value: string) => void;
  saveContext: () => Promise<void>;
  generateHypotheses: () => Promise<void>;
  toggleSegment: (segmentId: string) => void;
  toggleValue: (segmentId: string, hypothesisId: string) => void;
  generateScenario: () => Promise<void>;
  lock: () => Promise<void>;

  interviews: Interview[];
  upload: (file: File, segmentId: string) => void;
  cancelUpload: (id: string) => void;
  removeInterview: (id: string) => Promise<void>;
  retryInterview: (id: string) => Promise<void>;

  runStenogram: () => Promise<void>;
  runInsights: () => Promise<void>;
  saveInsight: (insight: Insight, isNew: boolean, comment?: string) => Promise<void>;
  reformulate: () => Promise<void>;
};

const Ctx = createContext<ProjectState | null>(null);
const POLL_MS = 3000;

function busy(v: ProjectView | undefined): boolean {
  if (!v) return false;
  return Object.values(v.jobs).some((j) => j?.status === "running")
    || v.interviews.some((i) => i.status === "transcribing" || i.status === "processing");
}

export function ProjectProvider({ projectId, children, fallback }: { projectId: string; children: ReactNode; fallback: (error: unknown) => ReactNode }) {
  const qc = useQueryClient();
  const key = useMemo(() => ["project", projectId], [projectId]);
  const q = useQuery({
    queryKey: key,
    queryFn: () => apiGet<ProjectView>(`/projects/${projectId}/view`),
    refetchInterval: (query) => (busy(query.state.data) ? POLL_MS : false),
  });
  const [draft, setDraft] = useState<Record<string, string> | null>(null);
  const [uploads, setUploads] = useState<Uploading[]>([]);
  const saveTimer = useRef<number | undefined>(undefined);

  const refresh = useCallback(async () => { await qc.invalidateQueries({ queryKey: key }); }, [qc, key]);
  const patch = useCallback((fn: (v: ProjectView) => ProjectView) => {
    qc.setQueryData<ProjectView>(key, (v) => (v ? fn(v) : v));
  }, [qc, key]);

  // анкета: правки копятся локально и сохраняются с задержкой (автосохранение «Сохранено · только что»)
  const saveContext = useCallback(async () => {
    window.clearTimeout(saveTimer.current);
    const values = draft;
    if (!values) return;
    await apiSend("PUT", `/projects/${projectId}/context`, { values });
    patch((v) => ({ ...v, context: values }));
    setDraft(null);
  }, [draft, projectId, patch]);

  useEffect(() => {
    if (!draft) return;
    saveTimer.current = window.setTimeout(() => { void saveContext(); }, 1500);
    return () => window.clearTimeout(saveTimer.current);
  }, [draft, saveContext]);

  const view = q.data;
  const selection = useCallback(async (segments: string[], values: Record<string, string[]>) => {
    patch((v) => ({ ...v, selectedSegments: segments, selectedValues: values }));
    await apiSend("PUT", `/projects/${projectId}/selection`, { segments, values });
  }, [patch, projectId]);

  const startJob = useCallback(async (kind: JobKind, path: string) => {
    patch((v) => ({ ...v, jobs: { ...v.jobs, [kind]: { status: "running" } } }));
    try {
      await apiSend("POST", `/projects/${projectId}/${path}`);
    } finally {
      await refresh();
    }
  }, [patch, projectId, refresh]);

  const upload = useCallback((file: File, segmentId: string) => {
    const id = `up-${Date.now()}`;
    const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
    const form = new FormData();
    form.append("file", file);
    form.append("segment", segmentId);
    const handle = uploadFile(`/projects/${projectId}/interviews`, form, (progress) =>
      setUploads((xs) => xs.map((x) => (x.id === id ? { ...x, progress } : x))));
    setUploads((xs) => [{
      id, respondentId: "", segmentId, fileType: ext, fileName: file.name, durationMin: 0,
      sizeMb: Math.round((file.size / 1024 ** 2) * 10) / 10, status: "uploading", progress: 0, recordedAt: "Сейчас", handle,
    }, ...xs]);
    handle.promise
      .then(async () => { setUploads((xs) => xs.filter((x) => x.id !== id)); await refresh(); })
      .catch((e: unknown) => {
        setUploads((xs) => xs.map((x) => (x.id === id ? { ...x, status: "error", error: (e as Error).message } : x)));
      });
  }, [projectId, refresh]);

  const value = useMemo<ProjectState | null>(() => {
    if (!view) return null;
    const v: ProjectView = draft ? { ...view, context: draft } : view;
    const all = [...v.segmentVariants, ...v.valueVariants];
    return {
      projectId,
      view: v,
      refresh,
      job: (kind) => v.jobs[kind],
      running: (kind) => v.jobs[kind]?.status === "running",
      hypothesis: (id) => all.find((h) => h.id === id),
      segmentTabs: v.selectedSegments.map((s) => ({ value: s, label: v.segmentLabel[s] ?? s })),
      respondentLabel: (id) => {
        const r = v.respondents.find((x) => x.id === id);
        return r ? `${r.code} · ${r.name}` : id;
      },
      setContextValue: (k, val) => setDraft((d) => ({ ...(d ?? v.context), [k]: val })),
      saveContext,
      generateHypotheses: async () => { await saveContext(); await startJob("hypotheses", "hypotheses/generate"); },
      toggleSegment: (seg) => {
        const segs = v.selectedSegments.includes(seg) ? v.selectedSegments.filter((x) => x !== seg) : [...v.selectedSegments, seg];
        void selection(segs, v.selectedValues);
      },
      toggleValue: (seg, hid) => {
        const cur = v.selectedValues[seg] ?? [];
        void selection(v.selectedSegments, { ...v.selectedValues, [seg]: cur.includes(hid) ? cur.filter((x) => x !== hid) : [...cur, hid] });
      },
      generateScenario: () => startJob("scenario", "scenario/generate"),
      lock: async () => { await apiSend("POST", `/projects/${projectId}/lock`); await refresh(); },
      interviews: [...uploads, ...v.interviews],
      upload,
      cancelUpload: (id) => {
        uploads.find((x) => x.id === id)?.handle?.abort();
        setUploads((xs) => xs.filter((x) => x.id !== id));
      },
      removeInterview: async (id) => {
        if (id.startsWith("up-")) { setUploads((xs) => xs.filter((x) => x.id !== id)); return; }
        await apiSend("DELETE", `/interviews/${id}`);
        await refresh();
      },
      retryInterview: async (id) => {
        // сразу убираем ошибку и кнопку: повторные нажатия больше не ставят лишних платных обработок
        patch((pv) => ({
          ...pv,
          interviews: pv.interviews.map((x) => (x.id === id
            ? { ...x, status: "transcribing", error: null, progress: 0, stageLabel: "В очереди на обработку" } : x)),
        }));
        try {
          await apiSend("POST", `/interviews/${id}/retry`);
        } finally {
          await refresh();
        }
      },
      runStenogram: () => startJob("stenogram", "stenogram/run"),
      runInsights: () => startJob("insights", "insights/run"),
      saveInsight: async (ins, isNew, comment) => {
        const body = {
          segmentId: ins.segmentId, hypothesisKind: ins.hypothesisKind, slot: ins.slot, relation: ins.relation,
          title: ins.title, expected: ins.expected, observed: ins.observed,
          quotes: ins.quotes.map((x) => ({ respondentId: x.respondentId, time: x.time, text: x.text })), comment,
        };
        if (isNew) await apiSend("POST", `/projects/${projectId}/insights`, body);
        else await apiSend("PUT", `/projects/${projectId}/insights/${ins.id}`, body);
        await refresh();
      },
      reformulate: () => startJob("reformulate", "reformulate"),
    };
  }, [view, draft, projectId, refresh, patch, saveContext, startJob, selection, uploads, upload]);

  if (q.isError) return <>{fallback(q.error)}</>;
  if (!value) return <div className="work"><div className="card"><p className="muted">Загружаем исследование…</p></div></div>;
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useProject(): ProjectState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useProject вне ProjectProvider");
  return v;
}
