// «Шапка исследования» из Figma: хлебные крошки, заголовок, «Сохранено», этапы
// «Проектирование» (1–5) и «Анализ интервью» (6–10). Этапы до текущего — с галочкой.
// Данные исследования — из API (store/project.tsx); /projects/new/* создаёт новое исследование.
import { useEffect, useRef } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate, useParams } from "react-router";

import { apiSend } from "../api/client";
import type { Project } from "../domain/types";
import { ProjectProvider, useProject } from "../store/project";
import { Icon } from "./Icon";
import { Button, EmptyState } from "./ui";

export const STUDY_STEPS = [
  { path: "context", label: "Контекст", group: "design" },
  { path: "hypotheses", label: "Гипотезы", group: "design" },
  { path: "scenario", label: "Сценарий", group: "design" },
  { path: "respondents", label: "Респонденты", group: "design" },
  { path: "design", label: "Дизайн исследования", group: "design" },
  { path: "interviews", label: "Интервью", group: "analysis" },
  { path: "stenogram", label: "Стенограмма", group: "analysis" },
  { path: "insights", label: "Инсайты", group: "analysis" },
  { path: "validation", label: "Валидация", group: "analysis" },
  { path: "report", label: "Отчёт", group: "analysis" },
] as const;

function Step({ index, current, path, label }: { index: number; current: number; path: string; label: string }) {
  const state = index < current ? "done" : index === current ? "current" : "ahead";
  return (
    <NavLink to={path} className={`step step-${state}`}>
      <span className="step-dot">{state === "done" ? <Icon name="check" size={14} /> : index + 1}</span>
      {label}
    </NavLink>
  );
}

function StudyHead() {
  const { projectId = "" } = useParams();
  const { pathname } = useLocation();
  const { view } = useProject();
  const current = STUDY_STEPS.findIndex((s) => pathname.endsWith(`/${s.path}`));
  const base = `/projects/${projectId}`;
  return (
    <header className="study-head">
      <div className="crumbs">
        <Link to="/projects">Проекты</Link> / <span>{view.name}</span>
      </div>
      <div className="study-title-row">
        <h1 className="study-title">Custdev-исследование</h1>
        <span className="saved">Сохранено · {view.updatedAt.toLowerCase()}</span>
      </div>
      <div className="steps">
        <div className="steps-group">
          <div className="caps">Проектирование</div>
          <div className="steps-row">
            {STUDY_STEPS.slice(0, 5).map((s, i) => (
              <Step key={s.path} index={i} current={current} path={`${base}/${s.path}`} label={s.label} />
            ))}
          </div>
        </div>
        <div className="steps-group">
          <div className="caps">Анализ интервью</div>
          <div className="steps-row">
            {STUDY_STEPS.slice(5).map((s, i) => (
              <Step key={s.path} index={i + 5} current={current} path={`${base}/${s.path}`} label={s.label} />
            ))}
          </div>
        </div>
      </div>
    </header>
  );
}

/** «Новое исследование»: создаём проект и переходим к его анкете. */
function NewProject() {
  const navigate = useNavigate();
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    apiSend<Project>("POST", "/projects", { name: "Новое исследование" })
      .then((p) => navigate(`/projects/${p.id}/context`, { replace: true }))
      .catch(() => navigate("/projects", { replace: true }));
  }, [navigate]);
  return <div className="work"><div className="card"><p className="muted">Создаём исследование…</p></div></div>;
}

export function StudyLayout() {
  const { projectId = "" } = useParams();
  const navigate = useNavigate();
  if (projectId === "new") return <NewProject />;
  return (
    <ProjectProvider
      key={projectId}
      projectId={projectId}
      fallback={() => (
        <div className="work">
          <div className="card">
            <EmptyState icon="warning" tone="red" title="Исследование не найдено" text="Возможно, его удалили или ссылка устарела.">
              <Button onClick={() => navigate("/projects")}>К списку проектов</Button>
            </EmptyState>
          </div>
        </div>
      )}
    >
      <div className="study">
        <StudyHead />
        <Outlet />
      </div>
    </ProjectProvider>
  );
}
