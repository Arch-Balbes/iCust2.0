// UI-кит по странице «Компоненты» Figma: Кнопка, Метка, Пункт меню, Этап, Поле ввода, Чекбокс,
// Переключатель, Переключатель сегментов, Сегмент шкалы, Панель действий.
import {
  createContext, useCallback, useContext, useEffect, useState,
  type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode,
} from "react";

import { STATUS_META, type ComponentStatus } from "../domain/ig2";
import { SLOT_LABEL, type SlotCode } from "../domain/types";
import { Icon, type IconName } from "./Icon";

/* ------------------------------------------------------------------ Кнопка */
type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "text";
  icon?: IconName;
  size?: "md" | "sm";
  /** Идёт операция: иконка заменяется индикатором загрузки, кнопка недоступна (макет 03.1, 12.3). */
  loading?: boolean;
};

export function Button({ variant = "primary", icon, size = "md", loading, className, children, disabled, ...rest }: ButtonProps) {
  return (
    <button
      type="button"
      className={`btn btn-${variant} btn-${size} ${loading ? "is-loading" : ""} ${className ?? ""}`}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? <Icon name="spinner" className="spin" /> : icon && <Icon name={icon} />}
      {children}
    </button>
  );
}

/* ------------------------------------------------------------------ Метка */
export type Tone = "gray" | "blue" | "green" | "yellow" | "red" | "outline";

export function Tag({ tone = "gray", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return <span className={`tag tag-${tone} ${className ?? ""}`}>{children}</span>;
}

export function SlotTag({ slot }: { slot: SlotCode }) {
  return <Tag tone="blue">{SLOT_LABEL[slot]}</Tag>;
}

export function StatusBadge({ status }: { status: ComponentStatus }) {
  const meta = STATUS_META[status];
  return <Tag tone={meta.tone}>{meta.label}</Tag>;
}

/* ------------------------------------------------------------------ Карточка */
export function Card({
  title, action, children, className, active,
}: { title?: ReactNode; action?: ReactNode; children?: ReactNode; className?: string; active?: boolean }) {
  return (
    <section className={`card ${active ? "card-active" : ""} ${className ?? ""}`}>
      {(title || action) && (
        <header className="card-head">
          {title && <h3 className="card-title">{title}</h3>}
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

export function Caps({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={`caps ${className ?? ""}`}>{children}</div>;
}

/* ------------------------------------------------------------------ Переключатель сегментов / вкладки */
export function SegmentTabs<T extends string>({
  items, value, onChange,
}: { items: { value: T; label: string }[]; value: T; onChange: (v: T) => void }) {
  return (
    <div className="seg-tabs" role="tablist">
      {items.map((it) => (
        <button
          key={it.value}
          type="button"
          role="tab"
          aria-selected={it.value === value}
          className={`seg-tab ${it.value === value ? "is-active" : ""}`}
          onClick={() => onChange(it.value)}
        >
          {it.label}
        </button>
      ))}
    </div>
  );
}

/** Фильтр-чипы (стенограмма, инсайты): чёрный — выбран. */
export function Chip({
  active, onClick, children,
}: { active?: boolean; onClick?: () => void; children: ReactNode }) {
  return (
    <button type="button" className={`chip ${active ? "is-active" : ""}`} onClick={onClick}>
      {children}
    </button>
  );
}

/* ------------------------------------------------------------------ Поля */
export function TextField({
  label, ...rest
}: InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      <input className="input" {...rest} />
    </label>
  );
}

export function Checkbox({
  checked, onChange, children,
}: { checked: boolean; onChange: (v: boolean) => void; children: ReactNode }) {
  return (
    <label className="checkbox">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className="checkbox-box">{checked && <Icon name="check" size={14} />}</span>
      <span>{children}</span>
    </label>
  );
}

export function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      className={`toggle ${checked ? "is-on" : ""}`}
      onClick={() => onChange(!checked)}
    >
      <span className="toggle-knob" />
    </button>
  );
}

/* ------------------------------------------------------------------ Шкала прогресса */
export function StepScale({ total, done, tone = "blue" }: { total: number; done: number; tone?: "blue" | "green" }) {
  return (
    <div className="scale">
      {Array.from({ length: total }, (_, i) => (
        <span key={i} className={`scale-seg ${i < done ? `is-done tone-${tone}` : ""}`} />
      ))}
    </div>
  );
}

export function ProgressBar({ value }: { value: number }) {
  return (
    <div className="progress">
      <span style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </div>
  );
}

/* ------------------------------------------------------------------ Панель действий (низ экрана) */
export function ActionBar({ children, left }: { children: ReactNode; left?: ReactNode }) {
  return (
    <div className="action-bar">
      <div className="action-bar-left">{left}</div>
      <div className="action-bar-right">{children}</div>
    </div>
  );
}

/* ------------------------------------------------------------------ Модальное окно и боковая панель */
function useEscape(open: boolean, onClose: () => void) {
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, onClose]);
}

export function Modal({
  open, onClose, title, children, footer, width = 520,
}: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; footer?: ReactNode; width?: number }) {
  useEscape(open, onClose);
  if (!open) return null;
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal style={{ width }}>
        <header className="modal-head">
          <h2>{title}</h2>
          <Button variant="text" onClick={onClose}>Закрыть</Button>
        </header>
        <div className="modal-body">{children}</div>
        {footer && <footer className="modal-foot">{footer}</footer>}
      </div>
    </div>
  );
}

export function Drawer({
  open, onClose, title, children,
}: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode }) {
  useEscape(open, onClose);
  if (!open) return null;
  return (
    <div className="overlay overlay-drawer" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <aside className="drawer" role="dialog" aria-modal>
        <header className="drawer-head">
          <h3>{title}</h3>
          <button type="button" className="icon-btn" aria-label="Закрыть" onClick={onClose}>×</button>
        </header>
        <div className="drawer-body">{children}</div>
      </aside>
    </div>
  );
}

/* ------------------------------------------------------------------ Уведомления (макет: «Уведомление «Изменения сохранены»») */
export type ToastInput =
  | string
  | { title: string; text?: string; tone?: "success" | "error" | "info"; action?: { label: string; onClick: () => void } };

type ToastItem = Exclude<ToastInput, string> & { id: number };

const ToastCtx = createContext<(t: ToastInput) => void>(() => undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const close = useCallback((id: number) => setItems((xs) => xs.filter((x) => x.id !== id)), []);
  const push = useCallback((t: ToastInput) => {
    const id = Date.now() + Math.random();
    const item: ToastItem = typeof t === "string" ? { id, title: t, tone: "info" } : { id, tone: "success", ...t };
    setItems((xs) => [...xs, item]);
    window.setTimeout(() => close(id), item.action ? 7000 : 4000);
  }, [close]);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className="toast">
            {t.tone !== "info" && (
              <span className={`toast-icon tone-${t.tone}`}>
                <Icon name={t.tone === "error" ? "warning" : "check"} size={18} />
              </span>
            )}
            <div className="toast-body">
              <div className="strong">{t.title}</div>
              {t.text && <div className="small muted">{t.text}</div>}
            </div>
            {t.action && (
              <Button variant="text" size="sm" onClick={() => { t.action?.onClick(); close(t.id); }}>{t.action.label}</Button>
            )}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

/* ------------------------------------------------------------------ Состояния экрана: обработка, пусто, ошибка */
export function ProcessingCard({ title, text }: { title: string; text: string }) {
  return (
    <div className="state-wrap">
      <div className="card processing-card" role="status" aria-live="polite">
        <Icon name="spinner" size={28} className="spin accent" />
        <h3 className="h-block">{title}</h3>
        <p className="muted">{text}</p>
        <div className="indeterminate"><span /></div>
      </div>
    </div>
  );
}

export function EmptyState({
  icon = "document", title, text, children, tone = "accent", compact,
}: { icon?: IconName; title?: string; text: ReactNode; children?: ReactNode; tone?: "accent" | "red"; compact?: boolean }) {
  return (
    <div className={`empty-state ${compact ? "is-compact" : ""}`}>
      <span className={`empty-icon tone-${tone}`}><Icon name={icon} /></span>
      {title && <h3 className={compact ? "strong" : "h-section"}>{title}</h3>}
      <p className="muted">{text}</p>
      {children && <div className="row" style={{ gap: 12, justifyContent: "center" }}>{children}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------ Выпадающее меню (фильтр сегмента, формат файла) */
export function Menu({
  open, onClose, children, align = "right",
}: { open: boolean; onClose: () => void; children: ReactNode; align?: "left" | "right" }) {
  useEscape(open, onClose);
  useEffect(() => {
    if (!open) return;
    const h = () => onClose();
    window.addEventListener("mousedown", h);
    return () => window.removeEventListener("mousedown", h);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className={`menu-pop align-${align}`} role="menu" onMouseDown={(e) => e.stopPropagation()}>
      {children}
    </div>
  );
}

export function MenuItem({
  children, selected, icon, onClick,
}: { children: ReactNode; selected?: boolean; icon?: IconName; onClick: () => void }) {
  return (
    <button type="button" role="menuitem" className={`menu-pop-item ${selected ? "is-selected" : ""}`} onClick={onClick}>
      {icon && <Icon name={icon} className="muted" />}
      <span>{children}</span>
      {selected && <Icon name="check" size={18} />}
    </button>
  );
}

export function useToast() {
  return useContext(ToastCtx);
}

/** Плашка «демо-режим» для функций без бэкенда. */
export const DEMO_NOTE = "Демо: функция подключится вместе с бэкендом";
