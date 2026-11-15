// Каркас приложения: «Меню слева» (248 px, сворачивается) + «Верхняя панель» (64 px) с балансом токенов.
import { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router";

import { useDemo } from "../mocks/store";
import { Icon } from "./Icon";
import { Button, DEMO_NOTE, useToast } from "./ui";

export function Logo({ inverse }: { inverse?: boolean }) {
  return (
    <div className={`logo ${inverse ? "logo-inverse" : ""}`}>
      {!inverse && <span className="logo-mark">i</span>}
      <span className="logo-name">iCust</span>
      <span className="logo-sub">Discovery</span>
    </div>
  );
}

function Sidebar({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  const navigate = useNavigate();
  const toast = useToast();
  return (
    <aside className="sidebar">
      <div className="logo-row">
        <Logo />
        <button
          type="button"
          className="icon-btn"
          aria-label={collapsed ? "Показать панель" : "Скрыть панель"}
          title={collapsed ? "Показать панель" : "Скрыть панель"}
          onClick={onToggle}
        >
          <Icon name={collapsed ? "panelShow" : "panelHide"} />
        </button>
      </div>
      <Button icon="plus" className="sidebar-new" title="Новое исследование" onClick={() => navigate("/projects/new/context")}>
        <span className="sidebar-new-label">Новое исследование</span>
      </Button>
      <nav className="menu">
        <NavLink to="/projects" title="Проекты" className={({ isActive }) => `menu-item ${isActive ? "is-active" : ""}`}>
          <Icon name="folder" /> <span className="menu-label">Проекты</span>
        </NavLink>
      </nav>
      <nav className="menu menu-bottom">
        <NavLink to="/settings" title="Настройки" className={({ isActive }) => `menu-item ${isActive ? "is-active" : ""}`}>
          <Icon name="settings" /> <span className="menu-label">Настройки</span>
        </NavLink>
        <button type="button" className="menu-item" title="Поддержка" onClick={() => toast(DEMO_NOTE)}>
          <Icon name="chat" /> <span className="menu-label">Поддержка</span>
        </button>
      </nav>
    </aside>
  );
}

/** Баланс токенов в верхней панели (макет 13.11): «1 750 из 2 500 токенов» + шкала. */
export function TokenPill() {
  const navigate = useNavigate();
  const { tokens } = useDemo();
  const fmt = (n: number) => n.toLocaleString("ru-RU");
  return (
    <button
      type="button"
      className={`token-pill ${tokens.left === 0 ? "is-empty" : ""}`}
      title="Тариф и оплата"
      onClick={() => navigate("/settings/tariff")}
    >
      <Icon name="sparkles" size={16} />
      <span className="token-pill-text">
        <span><b>{fmt(tokens.left)}</b> из {fmt(tokens.total)} токенов</span>
        <span className="progress"><span style={{ width: `${(tokens.left / tokens.total) * 100}%` }} /></span>
      </span>
    </button>
  );
}

function TopBar() {
  const navigate = useNavigate();
  return (
    <div className="topbar">
      <div className="topbar-actions">
        <TokenPill />
        <button type="button" className="avatar" aria-label="Профиль" onClick={() => navigate("/settings/profile")}>
          ТМ
        </button>
      </div>
    </div>
  );
}

export function AppShell() {
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem("sidebar-collapsed") === "1"; } catch { return false; }
  });
  const toggle = () => setCollapsed((v) => {
    try { localStorage.setItem("sidebar-collapsed", v ? "0" : "1"); } catch { /* приватный режим */ }
    return !v;
  });
  return (
    <div className={`shell ${collapsed ? "is-collapsed" : ""}`}>
      <Sidebar collapsed={collapsed} onToggle={toggle} />
      <div className="shell-main">
        <TopBar />
        <Outlet />
      </div>
    </div>
  );
}
