// Тонкий клиент API: все запросы идут на /api того же origin (gateway или прокси Vite).

export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, body: unknown) {
    super(errorText(status, body));
    this.status = status;
    this.body = body;
  }
}

function errorText(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  return `Сервис ответил ошибкой ${status}`;
}

export async function apiGet<T>(path: string): Promise<T> {
  const resp = await fetch(`/api${path}`, { credentials: "same-origin" });
  const body: unknown = await resp.json().catch(() => null);
  if (!resp.ok) throw new ApiError(resp.status, body);
  return body as T;
}

export async function apiSend<T>(method: "POST" | "PUT" | "PATCH" | "DELETE", path: string, data?: unknown): Promise<T> {
  const resp = await fetch(`/api${path}`, {
    method,
    credentials: "same-origin",
    headers: data === undefined ? undefined : { "Content-Type": "application/json" },
    body: data === undefined ? undefined : JSON.stringify(data),
  });
  const body: unknown = resp.status === 204 ? null : await resp.json().catch(() => null);
  if (!resp.ok) throw new ApiError(resp.status, body);
  return body as T;
}

export type UploadHandle = { promise: Promise<unknown>; abort: () => void };

/** Загрузка файла с прогрессом (XHR: у fetch нет событий прогресса отправки). */
export function uploadFile(path: string, form: FormData, onProgress: (percent: number) => void): UploadHandle {
  const xhr = new XMLHttpRequest();
  const promise = new Promise<unknown>((resolve, reject) => {
    xhr.open("POST", `/api${path}`);
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(Math.round((100 * e.loaded) / e.total)); };
    xhr.onload = () => {
      let body: unknown = null;
      try { body = JSON.parse(xhr.responseText); } catch { /* пустой ответ */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body);
      else reject(new ApiError(xhr.status, body));
    };
    xhr.onerror = () => reject(new ApiError(0, { detail: "Нет связи с сервером" }));
    xhr.onabort = () => reject(new ApiError(0, { detail: "Загрузка отменена" }));
    xhr.send(form);
  });
  return { promise, abort: () => xhr.abort() };
}

/** Скачивание выгрузки: файл отдаёт API, браузер сохраняет его под именем из Content-Disposition. */
export async function download(path: string): Promise<void> {
  const resp = await fetch(`/api${path}`, { credentials: "same-origin" });
  if (!resp.ok) throw new ApiError(resp.status, await resp.json().catch(() => null));
  const name = /filename="([^"]+)"/.exec(resp.headers.get("Content-Disposition") ?? "")?.[1] ?? "download";
  const url = URL.createObjectURL(await resp.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export type Health = {
  status: "ok" | "degraded";
  checks: Record<string, string>;
};
