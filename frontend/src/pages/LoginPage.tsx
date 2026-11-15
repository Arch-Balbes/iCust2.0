// 01 — Вход, 01.1 — неверная почта или пароль, 01.2–01.4 — восстановление пароля.
// Авторизация пока демо: вход проходит при почте с «@» и пароле от 6 символов, иначе — ошибка 01.1.
import { useState, type FormEvent, type ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router";

import { Logo } from "../components/AppShell";
import { Button, Checkbox, DEMO_NOTE, useToast } from "../components/ui";

export type AuthView = "login" | "forgot" | "sent" | "reset";

function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="login">
      <section className="login-about">
        <Logo inverse />
        <div className="login-pitch">
          <h1>Веб-сервис для подготовки и проведения CustDev-исследований</h1>
          <p>Проверьте идею до разработки: сервис подготовит интервью, разберёт записи и покажет, кому нужен продукт и зачем</p>
        </div>
      </section>
      <section className="login-side">
        <div className="login-col">
          {children}
          {/* Формулировка из макета; верна только при хранении и обработке данных в РФ — проверить до запуска */}
          <p className="small muted login-data">Данные хранятся на серверах в России (152-ФЗ)</p>
        </div>
      </section>
    </div>
  );
}

function Field({
  label, type = "text", value, onChange, error, autoComplete,
}: { label: string; type?: string; value: string; onChange: (v: string) => void; error?: boolean; autoComplete?: string }) {
  return (
    <label className="field">
      <span className="field-label" style={{ color: "var(--text)" }}>{label}</span>
      <input
        className={`input ${error ? "is-error" : ""}`}
        type={type}
        value={value}
        autoComplete={autoComplete}
        aria-invalid={error || undefined}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}

export function LoginPage({ view = "login" }: { view?: AuthView }) {
  const navigate = useNavigate();
  const location = useLocation();
  const toast = useToast();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const [remember, setRemember] = useState(true);
  const [error, setError] = useState(false);

  const login = (e: FormEvent) => {
    e.preventDefault();
    if (!email.includes("@") || password.length < 6) {
      setError(true);
      return;
    }
    navigate("/projects");
  };

  if (view === "forgot") {
    return (
      <AuthLayout>
        <form className="login-form" onSubmit={(e) => { e.preventDefault(); navigate("/login/forgot/sent", { state: { email } }); }}>
          <h2 className="h-section">Восстановление пароля</h2>
          <p className="muted">Укажите почту, с которой входите в iCust, — пришлём ссылку для сброса пароля.</p>
          <Field label="Почта" type="email" autoComplete="email" value={email} onChange={setEmail} />
          <Button type="submit" disabled={!email.includes("@")}>Отправить ссылку</Button>
          <p className="login-register"><span className="muted">Вспомнили пароль?</span> <Link to="/login" className="strong">Войти</Link></p>
        </form>
      </AuthLayout>
    );
  }

  if (view === "sent") {
    const to = (location.state as { email?: string } | null)?.email || "вашу почту";
    return (
      <AuthLayout>
        <div className="login-form">
          <h2 className="h-section">Проверьте почту</h2>
          <p className="muted">Мы отправили ссылку для сброса пароля на {to}. Если письма нет, проверьте папку «Спам».</p>
          <Button variant="secondary" onClick={() => toast({ title: "Письмо отправлено ещё раз", text: DEMO_NOTE })}>Отправить ещё раз</Button>
          <p className="login-register"><span className="muted">Вспомнили пароль?</span> <Link to="/login" className="strong">Вернуться ко входу</Link></p>
        </div>
      </AuthLayout>
    );
  }

  if (view === "reset") {
    const mismatch = password2.length > 0 && password !== password2;
    return (
      <AuthLayout>
        <form className="login-form" onSubmit={(e) => { e.preventDefault(); navigate("/projects"); }}>
          <h2 className="h-section">Новый пароль</h2>
          <p className="muted">Придумайте новый пароль для входа в iCust.</p>
          <Field label="Новый пароль" type="password" autoComplete="new-password" value={password} onChange={setPassword} />
          <Field label="Повторите пароль" type="password" autoComplete="new-password" value={password2} onChange={setPassword2} error={mismatch} />
          {mismatch && <p className="field-error">Пароли не совпадают</p>}
          <Button type="submit" disabled={password.length < 6 || password !== password2}>Сохранить и войти</Button>
        </form>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout>
      <form className="login-form" onSubmit={login} noValidate>
        <h2 className="h-section">Вход в iCust</h2>
        <p className="muted">Продолжите с того места, где остановились</p>
        <Field label="Почта" type="email" autoComplete="email" value={email} onChange={(v) => { setEmail(v); setError(false); }} error={error} />
        <Field label="Пароль" type="password" autoComplete="current-password" value={password} onChange={(v) => { setPassword(v); setError(false); }} error={error} />
        {error && <p className="field-error" role="alert">Неверная почта или пароль. Проверьте данные или восстановите пароль.</p>}
        <div className="row-between">
          <Checkbox checked={remember} onChange={setRemember}>Запомнить меня</Checkbox>
          <Link to="/login/forgot" className="strong">Забыли пароль?</Link>
        </div>
        <Button type="submit">Войти</Button>
        <div className="login-or"><span>или</span></div>
        <Button variant="secondary" onClick={() => toast(DEMO_NOTE)}>Войти через Яндекс ID</Button>
        <Button variant="secondary" onClick={() => toast(DEMO_NOTE)}>Войти через Google</Button>
        <p className="login-register">
          <span className="muted">Нет аккаунта?</span>{" "}
          <Button variant="text" size="sm" onClick={() => toast(DEMO_NOTE)}>Зарегистрироваться</Button>
        </p>
      </form>
    </AuthLayout>
  );
}
