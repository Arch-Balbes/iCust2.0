// 02 — Проекты: поиск, фильтр по статусу, карточки с этапом «N из 9», закрепление, лента «Последние исследования».
// 02.1 — проектов нет, 02.2 — поиск без результатов. Данные — GET /api/projects.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router";

import { apiGet, apiSend } from "../api/client";
import { Icon } from "../components/Icon";
import { STUDY_STEPS } from "../components/StudyLayout";
import { Button, Chip, EmptyState, StepScale, Tag } from "../components/ui";
import type { Project, ProjectStatus } from "../domain/types";

type Filter = "all" | ProjectStatus;
const STAGES = 9; // в макете шкала из 9 делений; «Дизайн исследования» отдельным этапом не считается

export function ProjectsPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const { data: projects = [], isLoading, isError } = useQuery({ queryKey: ["projects"], queryFn: () => apiGet<Project[]>("/projects") });

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return projects
      .filter((p) => filter === "all" || p.status === filter)
      .filter((p) => !q || p.name.toLowerCase().includes(q))
      .sort((a, b) => Number(b.pinned) - Number(a.pinned));
  }, [projects, query, filter]);

  const count = (f: Filter) => projects.filter((p) => f === "all" || p.status === f).length;
  const togglePin = async (p: Project) => {
    qc.setQueryData<Project[]>(["projects"], (xs) => xs?.map((x) => (x.id === p.id ? { ...x, pinned: !x.pinned } : x)));
    await apiSend("PATCH", `/projects/${p.id}`, { pinned: !p.pinned });
    await qc.invalidateQueries({ queryKey: ["projects"] });
  };

  if (isLoading) return <div className="page"><h1 className="page-title">Проекты</h1><p className="muted">Загружаем…</p></div>;

  // 02.1 — проектов ещё нет
  if (isError || projects.length === 0) {
    return (
      <div className="page">
        <h1 className="page-title">Проекты</h1>
        <div className="card">
          <EmptyState
            icon={isError ? "warning" : "folder"}
            tone={isError ? "red" : undefined}
            title={isError ? "Не удалось загрузить проекты" : "Здесь появятся ваши исследования"}
            text={isError ? "Сервис не ответил — обновите страницу через минуту." : "Опишите продукт и потребителя — iCust сформулирует гипотезы, соберёт сценарий интервью и поможет разобрать ответы респондентов."}
          >
            <Button icon="plus" onClick={() => navigate("/projects/new/context")}>Новое исследование</Button>
          </EmptyState>
        </div>
      </div>
    );
  }

  const recent = projects.slice(0, 5);

  return (
    <div className="page">
      <h1 className="page-title">Проекты</h1>
      <div className="row wrap" style={{ marginBottom: 20 }}>
        <label className="search">
          <Icon name="search" />
          <input placeholder="Найти проект по названию или ключевому слову" value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
        <Chip active={filter === "all"} onClick={() => setFilter("all")}>Все · {count("all")}</Chip>
        <Chip active={filter === "in_progress"} onClick={() => setFilter("in_progress")}>В работе · {count("in_progress")}</Chip>
        <Chip active={filter === "done"} onClick={() => setFilter("done")}>Завершён · {count("done")}</Chip>
      </div>

      <div className="project-grid">
        {visible.map((p) => {
          const done = p.status === "done";
          // Как в макете: «Дизайн исследования» (шаг 5) не считается отдельным этапом → Стенограмма = 6 из 9
          const stage = p.stepIndex < 4 ? p.stepIndex + 1 : Math.max(p.stepIndex, 4);
          const path = STUDY_STEPS[p.stepIndex]?.path ?? "context";
          return (
            <article
              key={p.id}
              className="card project-card"
              role="link"
              tabIndex={0}
              onClick={() => navigate(`/projects/${p.id}/${path}`)}
              onKeyDown={(e) => e.key === "Enter" && navigate(`/projects/${p.id}/${path}`)}
            >
              <div className="row-between">
                <Tag tone={done ? "green" : "blue"}>{done ? "Завершён" : "В работе"}</Tag>
                <button
                  type="button"
                  className={`icon-btn pin ${p.pinned ? "is-pinned" : ""}`}
                  aria-label={p.pinned ? "Открепить" : "Закрепить"}
                  onClick={(e) => { e.stopPropagation(); void togglePin(p); }}
                >
                  <Icon name="pin" />
                </button>
              </div>
              <h3 className="h-block project-name">{p.name}</h3>
              <div className="row-between small">
                <span className="small-strong">Этап «{STUDY_STEPS[p.stepIndex]?.label}»</span>
                <span className="muted">{stage} из {STAGES}</span>
              </div>
              <StepScale total={STAGES} done={stage} tone={done ? "green" : "blue"} />
              <div className="row small muted" style={{ gap: 16 }}>
                <span>{p.interviews ? `${p.segments > 1 ? `${p.segments} сегмента · ` : ""}${p.interviews} интервью` : "Нет интервью"}</span>
                <span>{p.updatedAt}</span>
              </div>
            </article>
          );
        })}
      </div>
      {visible.length === 0 && (
        <div className="card">
          <EmptyState icon="search" title="Ничего не нашлось" text={`По запросу «${query}» проектов нет. Попробуйте другое название или ключевое слово.`}>
            <Button variant="secondary" onClick={() => { setQuery(""); setFilter("all"); }}>Сбросить поиск</Button>
          </EmptyState>
        </div>
      )}

      <h2 className="h-block" style={{ margin: "32px 0 12px" }}>Последние исследования</h2>
      <div className="card activity">
        {recent.map((p) => (
          <Link key={p.id} to={`/projects/${p.id}/${STUDY_STEPS[p.stepIndex]?.path ?? "context"}`} className="activity-row">
            <span className="small muted">{p.updatedAt.replace("Обновлено ", "")}</span>
            <span className="strong">{p.name}</span>
            <span>Этап «{STUDY_STEPS[p.stepIndex]?.label}»</span>
            <Tag tone={p.status === "done" ? "green" : "yellow"}>{p.status === "done" ? "Готово" : "В работе"}</Tag>
            <Icon name="chevronRight" className="muted" />
          </Link>
        ))}
      </div>
    </div>
  );
}
