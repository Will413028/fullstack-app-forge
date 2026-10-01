export type User = { id: string; username: string; role: "user" | "admin" };
export type Application = {
  id: string; name: string; description: string; current_revision: string | null;
  updated_at: string; featured: boolean; public: boolean;
};
export type Run = {
  id: string; app_id: string; prompt: string; status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  artifact_revision: string | null; error_code: string | null; created_at: string;
};
export type ForgeEvent = {
  run_id: string; sequence: string; kind: string; attempt: number; timestamp: string;
  payload: { type: string; status?: string; text?: string; delta?: string; message?: string; path?: string };
};

let csrf = "";
export function setCsrf(token: string) { csrf = token; }

const errors: Record<string, string> = {
  INVALID_LOGIN: "帳號或密碼不正確。", USERNAME_TAKEN: "這個帳號名稱已被使用。",
  AUTH_RATE_LIMIT: "嘗試次數較多，請稍後再試。", UNAUTHENTICATED: "請先登入。",
  INVALID_INPUT: "請檢查輸入的內容。密碼至少需要 10 個字元。",
  APP_BUSY: "這個應用已有任務進行中。", STALE_REVISION: "版本已更新，請重新整理後再試。",
  RUN_RATE_LIMIT: "已達本小時生成上限。", INVALID_CSRF: "登入狀態已更新，請重新整理。",
  NOT_FOUND: "找不到這個項目，或你沒有存取權限。",
};

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const method = options.method ?? "GET";
  const response = await fetch(path, {
    ...options, credentials: "same-origin",
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(["POST", "PATCH", "PUT", "DELETE"].includes(method) ? { "X-CSRF-Token": csrf } : {}),
      ...options.headers,
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const code = body?.detail?.code;
    throw new Error(errors[code] ?? `請求未完成（${response.status}），請稍後再試。`);
  }
  return response.status === 204 ? undefined as T : await response.json() as T;
}
