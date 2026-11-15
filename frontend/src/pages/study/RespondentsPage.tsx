// 06 — Респонденты (модуль коллеги, этап «офферы»): кого ищем, сколько интервью, признаки отбора, фильтр-вопросы,
// где искать, рекомендованные и общие площадки, офферы. Модуль даёт два оффера — персональный и для посева.
import { useState } from "react";
import { useNavigate, useParams } from "react-router";

import { Icon } from "../../components/Icon";
import { ActionBar, Button, Card, EmptyState, ProcessingCard, SegmentTabs, Tag, useToast } from "../../components/ui";
import { OFFER_LABEL, type Channel, type OfferKind } from "../../domain/types";
import { useProject } from "../../store/project";

function ChannelCards({ items }: { items: Channel[] }) {
  return (
    <div className="channels-grid">
      {items.map((c, i) => (
        <div key={i} className="channel-card">
          <span className="strong">{c.name}</span>
          <span className="small muted">{c.description}</span>
          {c.url && (
            <a className="small row" style={{ gap: 6 }} href={c.url.startsWith("http") ? c.url : `https://${c.url}`} target="_blank" rel="noreferrer noopener">
              <Icon name="link" size={16} /> {c.url.replace(/^https?:\/\//, "")}
            </a>
          )}
        </div>
      ))}
    </div>
  );
}

export function RespondentsPage() {
  const navigate = useNavigate();
  const { projectId } = useParams();
  const toast = useToast();
  const { view, segmentTabs: tabs, running } = useProject();
  const [seg, setSeg] = useState(tabs[0]?.value ?? "");
  const current = tabs.some((t) => t.value === seg) ? seg : tabs[0]?.value ?? "";
  const plan = view.recruiting[current];
  const offerKinds = (Object.keys(OFFER_LABEL) as OfferKind[]).filter((k) => plan?.offers[k]);
  const [offer, setOffer] = useState<OfferKind>("personal");
  const activeOffer = offerKinds.includes(offer) ? offer : offerKinds[0] ?? "personal";

  const copy = async () => {
    const text = plan?.offers[activeOffer];
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      toast({ title: "Приглашение скопировано", text: "Вставьте его в сообщение респонденту." });
    } catch {
      toast("Не удалось скопировать — выделите текст вручную");
    }
  };

  return (
    <>
      <div className="work">
        <div className="work-head"><h2 className="work-title">Респонденты</h2></div>
        <div style={{ marginBottom: 20 }}><SegmentTabs items={tabs} value={current} onChange={setSeg} /></div>
        {running("scenario") ? (
          <ProcessingCard title="Подбираем респондентов" text="Формулируем, кого искать, где и с каким приглашением." />
        ) : !plan ? (
          <div className="card"><EmptyState icon="user" title="План поиска пока не готов" text="Он собирается вместе со сценарием интервью на шаге «Сценарий»." /></div>
        ) : (
          <Card title="Поиск респондентов">
            <div className="stack">
              <div className="stack-sm">
                <span className="strong">Кого ищем</span>
                <p>{plan.whom || "Не удалось сформулировать — соберите сценарий заново."}</p>
              </div>
              <div className="grid-2" style={{ gap: 24 }}>
                <div className="stack-sm">
                  <span className="small muted">Количество интервью</span>
                  <span>{plan.interviewsTarget || "—"}</span>
                  {plan.interviewsNote && <span className="small muted">{plan.interviewsNote}</span>}
                </div>
                <div className="stack-sm">
                  <span className="small muted">Вопросы для проверки соответствия сегменту</span>
                  {plan.filterQuestions.map((q) => <span key={q} style={{ whiteSpace: "pre-line" }}>{q}</span>)}
                </div>
              </div>
              {plan.criteria && plan.criteria.length > 0 && (
                <div className="stack-sm">
                  <span className="small muted">Признаки отбора</span>
                  <ul style={{ margin: 0, paddingLeft: 20 }}>{plan.criteria.map((c) => <li key={c}>{c}</li>)}</ul>
                </div>
              )}
              <hr className="divider" style={{ margin: "4px 0" }} />
              <div className="stack-sm">
                <span className="strong">Где искать</span>
                {plan.channels.map((c) => (
                  <div key={c.channel} className="channel-row">
                    <span className="small muted">{c.order}</span>
                    <span>{c.channel}</span>
                    <Tag tone="blue">{OFFER_LABEL[c.offer]}</Tag>
                  </div>
                ))}
              </div>
              {plan.recommended && plan.recommended.length > 0 && (
                <div className="stack-sm">
                  <span className="caps">Рекомендованные каналы</span>
                  <ChannelCards items={plan.recommended} />
                </div>
              )}
              {plan.fixed && plan.fixed.channels.length > 0 && (
                <div className="stack-sm">
                  <span className="caps">{plan.fixed.caption || "Общие площадки"}</span>
                  <ChannelCards items={plan.fixed.channels} />
                </div>
              )}
              <hr className="divider" style={{ margin: "4px 0" }} />
              <div className="row-between">
                <span className="strong">Приглашения для {(view.segmentLabel[current] ?? "").toLowerCase().replace("сегмент", "сегмента")}</span>
                <Button variant="text" onClick={() => void copy()}>Скопировать</Button>
              </div>
              <SegmentTabs items={offerKinds.map((k) => ({ value: k, label: OFFER_LABEL[k] }))} value={activeOffer} onChange={setOffer} />
              <div className="offer-text" style={{ whiteSpace: "pre-line" }}>{plan.offers[activeOffer]}</div>
            </div>
          </Card>
        )}
      </div>
      <ActionBar>
        <Button variant="secondary" onClick={() => navigate(`/projects/${projectId}/scenario`)}>Назад к сценарию</Button>
        <Button onClick={() => navigate(`/projects/${projectId}/design`)}>Собрать дизайн исследования</Button>
      </ActionBar>
    </>
  );
}
