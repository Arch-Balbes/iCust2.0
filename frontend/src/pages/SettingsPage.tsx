// 13 — Профиль (13.1 — изменения сохранены), 14 — Тариф и оплата (14.1 подтверждение перехода,
// 14.2 оплата не прошла, 14.3 тариф Free без платежей). Оплата — плацебо: CloudPayments не подключён.
import { useState } from "react";
import { useNavigate, useParams } from "react-router";

import { Icon } from "../components/Icon";
import { Button, Card, DEMO_NOTE, Modal, SegmentTabs, Tag, TextField, useToast } from "../components/ui";
import { payments, plans, type PlanId } from "../mocks/demo";
import { useDemo, useDemoState } from "../mocks/store";

type Tab = "profile" | "tariff";
const TABS: { value: Tab; label: string }[] = [
  { value: "profile", label: "Профиль" },
  { value: "tariff", label: "Тариф и оплата" },
];

export function SettingsPage() {
  const { tab = "profile" } = useParams();
  const navigate = useNavigate();
  const current = (TABS.some((t) => t.value === tab) ? tab : "profile") as Tab;

  return (
    <div className="page">
      <h1 className="page-title">Настройки</h1>
      <div style={{ marginBottom: 20 }}>
        <SegmentTabs items={TABS} value={current} onChange={(t) => navigate(`/settings/${t}`)} />
      </div>
      {current === "profile" ? <Profile /> : <Tariff />}
    </div>
  );
}

function Profile() {
  const toast = useToast();
  const [name, setName] = useState("Тагир Миннахметов");
  const [email, setEmail] = useState("tagir@example.ru");
  return (
    <div className="grid-2">
      <Card title="Профиль">
        <div className="stack">
          <div className="row" style={{ gap: 16 }}>
            <span className="avatar avatar-lg">ТМ</span>
            <Button variant="text" onClick={() => toast(DEMO_NOTE)}>Изменить фото</Button>
          </div>
          <TextField label="Имя и фамилия" value={name} onChange={(e) => setName(e.target.value)} />
          <TextField label="Почта" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          <div className="row" style={{ justifyContent: "flex-end" }}>
            <Button onClick={() => toast({ title: "Изменения сохранены", text: "Данные профиля обновлены." })}>Сохранить</Button>
          </div>
        </div>
      </Card>
      <Card title="Вход и безопасность">
        <div className="stack">
          <div className="row" style={{ alignItems: "flex-end" }}>
            <div style={{ flex: 1 }}><TextField label="Пароль" type="password" value="••••••••••" readOnly /></div>
            <Button variant="secondary" onClick={() => toast(DEMO_NOTE)}>Сменить пароль</Button>
          </div>
          <div className="stack-sm">
            <span className="small-strong">Вход через сервисы</span>
            <div className="service-row">
              <span>Яндекс ID</span>
              <Tag tone="green">Подключён</Tag>
              <Button variant="text" size="sm" onClick={() => toast(DEMO_NOTE)}>Отключить</Button>
            </div>
            <div className="service-row">
              <span>Google</span>
              <Tag>Не подключён</Tag>
              <Button variant="text" size="sm" onClick={() => toast(DEMO_NOTE)}>Подключить</Button>
            </div>
          </div>
          <div className="service-row" style={{ gridTemplateColumns: "1fr" }}>
            <button type="button" className="link-danger" onClick={() => toast(DEMO_NOTE)}>Выйти из аккаунта</button>
          </div>
        </div>
      </Card>
    </div>
  );
}

function Tariff() {
  const toast = useToast();
  const { plan: currentId, tokens } = useDemo();
  const { state } = useDemoState();
  const [confirm, setConfirm] = useState<PlanId | null>(null);
  const [failed, setFailed] = useState<PlanId | null>(state === "payment-failed" ? "max" : null);
  const [paying, setPaying] = useState(false);
  const current = plans.find((p) => p.id === currentId) ?? plans[2]!;
  const order: PlanId[] = ["free", "starter", "pro", "max"];
  const next = order[order.indexOf(current.id) + 1]; // следующий тариф — основная кнопка (как в макете)
  const pct = Math.round((tokens.left / tokens.total) * 100);
  const fmt = (n: number) => n.toLocaleString("ru-RU");
  const target = plans.find((p) => p.id === (confirm ?? failed));

  const pay = () => {
    setPaying(true);
    window.setTimeout(() => {
      setPaying(false);
      setConfirm(null);
      // Плацебо: платёжный провайдер не подключён, тариф не меняется
      toast({ tone: "error", title: "Оплата пока не подключена", text: `Тариф остался прежним — ${current.name}.` });
    }, 1200);
  };

  return (
    <div className="stack">
      <Card title="Текущий тариф">
        <div className="row" style={{ alignItems: "baseline", gap: 10, marginTop: -8 }}>
          <span className="h-section">{current.name}</span>
          <span className="muted">
            {current.price === 0
              ? `0 ₽ · ${current.tokens}, без ежемесячного списания`
              : `${fmt(current.price)} ₽ в месяц · ${current.tokens} · следующее списание 15 ноября`}
          </span>
        </div>
        <div className="row-between small-strong" style={{ marginTop: 16, marginBottom: 6 }}>
          <span>Осталось {fmt(tokens.left)} из {fmt(tokens.total)} токенов</span>
          <span>{pct}%</span>
        </div>
        <div className="progress"><span style={{ width: `${pct}%` }} /></div>
      </Card>

      <h2 className="h-block" style={{ marginTop: 8 }}>Тарифы</h2>
      <div className="plans">
        {plans.map((p) => {
          const isCurrent = p.id === current.id;
          return (
            <div key={p.id} className={`card plan ${isCurrent ? "is-current" : ""}`}>
              <div className="row" style={{ gap: 12 }}>
                <span className="h-block">{p.name}</span>
                {isCurrent && <span className="small-strong" style={{ color: "var(--accent)" }}>Текущий</span>}
              </div>
              <div className="small muted">{p.subtitle}</div>
              <div className="plan-price">
                <span className="number">{fmt(p.price)} ₽</span>
                {p.price > 0 && <span className="small muted"> / мес</span>}
              </div>
              <hr className="divider" style={{ margin: "4px 0 8px" }} />
              <ul className="plan-features">
                {p.features.map((f) => <li key={f}><Icon name="check" size={16} className="accent" /> {f}</li>)}
              </ul>
              <div className="plan-action">
                {isCurrent
                  ? <Button variant="secondary" disabled style={{ width: "100%" }}>Ваш тариф</Button>
                  : <Button variant={p.id === next ? "primary" : "secondary"} style={{ width: "100%" }} onClick={() => setConfirm(p.id)}>Перейти на {p.name}</Button>}
              </div>
            </div>
          );
        })}
      </div>
      <p className="small muted">
        Ориентир для интервью до 45 минут. Фактический расход зависит от длительности записей и количества сегментов.
        Точная стоимость обработки показывается до запуска. Токены — внутренняя единица стоимости генераций и обработки.
      </p>

      <div className="grid-2">
        <Card title="Способ оплаты">
          <div className="pay-row">
            <span>Карта «Мир» •••• 4821</span>
            <Tag>Основной</Tag>
            <Button variant="text" size="sm" onClick={() => toast(DEMO_NOTE)}>Изменить</Button>
          </div>
          <div className="pay-row">
            <span>СБП</span>
            <span />
            <Button variant="text" size="sm" onClick={() => toast(DEMO_NOTE)}>Подключить</Button>
          </div>
        </Card>
        <Card title="История платежей">
          {current.price === 0 ? (
            <p className="muted">Платежей пока нет — они появятся после первой оплаты тарифа.</p>
          ) : payments.map((p) => (
            <div key={p.date} className="pay-row">
              <span>{p.date}</span>
              <span className="row" style={{ gap: 10 }}>
                <span className="strong">{p.amount}</span>
                <Tag tone="green">Оплачено</Tag>
                <Button variant="text" size="sm" onClick={() => toast(DEMO_NOTE)}>Чек</Button>
              </span>
            </div>
          ))}
        </Card>
      </div>

      {/* 14.1 — подтверждение перехода */}
      <Modal
        open={!!confirm}
        onClose={() => setConfirm(null)}
        title={`Перейти на ${target?.name}?`}
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirm(null)}>Отмена</Button>
            <Button loading={paying} onClick={pay}>Перейти на {target?.name}</Button>
          </>
        }
      >
        <p className="muted">Проверьте условия нового тарифа.</p>
        {target && (
          <div className="file-pill">
            <Icon name="sparkles" />
            <div>
              <div className="strong">{target.name} · {fmt(target.price)} ₽ в месяц</div>
              <div className="small muted">{target.tokens} · {target.hint}</div>
            </div>
          </div>
        )}
        <p className="small muted" style={{ marginTop: 12 }}>Оплата с карты «Мир» •••• 4821.</p>
      </Modal>

      {/* 14.2 — оплата не прошла (демо: ?state=payment-failed) */}
      <Modal
        open={!!failed && !confirm}
        onClose={() => setFailed(null)}
        title="Оплата не прошла"
        footer={
          <>
            <Button variant="secondary" onClick={() => { setFailed(null); toast(DEMO_NOTE); }}>Изменить способ оплаты</Button>
            <Button onClick={() => { setConfirm(failed); setFailed(null); }}>Повторить оплату</Button>
          </>
        }
      >
        <p className="muted">Банк отклонил платёж. Тариф остался прежним — {current.name}.</p>
        {target && (
          <div className="file-pill is-error">
            <Icon name="warning" />
            <div>
              <div className="strong">{target.name} · {fmt(target.price)} ₽ в месяц</div>
              <div className="small muted">{target.tokens} · {target.hint}</div>
            </div>
          </div>
        )}
        <p className="small muted" style={{ marginTop: 12 }}>Карта «Мир» •••• 4821. Проверьте баланс и данные карты или выберите другой способ оплаты.</p>
      </Modal>
    </div>
  );
}
