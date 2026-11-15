// Служебная страница: состояние сервисов стека (/api/health). Не из макета.
import { useQuery } from "@tanstack/react-query";

import { ApiError, apiGet, type Health } from "../api/client";
import { Card, Tag } from "../components/ui";

export function SystemPage() {
  const { data, error, isPending } = useQuery({
    queryKey: ["health"],
    queryFn: () =>
      apiGet<Health>("/health").catch((e: unknown) => {
        if (e instanceof ApiError && e.body) return e.body as Health;
        throw e;
      }),
    refetchInterval: 10_000,
  });

  return (
    <div className="page">
      <h1 className="page-title">Состояние системы</h1>
      <Card>
        {isPending && <p>Проверяем сервисы…</p>}
        {error && <Tag tone="red">API недоступен</Tag>}
        {data && (
          <div className="stack-sm">
            <Tag tone={data.status === "ok" ? "green" : "red"}>{data.status === "ok" ? "Всё работает" : "Есть проблемы"}</Tag>
            {Object.entries(data.checks).map(([name, value]) => (
              <div key={name} className="row"><span className="strong" style={{ width: 100 }}>{name}</span><span>{value}</span></div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
