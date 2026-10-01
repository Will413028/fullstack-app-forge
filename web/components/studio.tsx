"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useRef, useState } from "react";
import { api, Application, ForgeEvent, Run, setCsrf, User } from "@/lib/api";

const states = { queued: "等待執行", running: "正在生成", succeeded: "已完成", failed: "未完成", cancelled: "已取消" };

export default function Studio({ applicationId }: { applicationId?: string }) {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const [mode, setMode] = useState<"login" | "register">("login");
  const [apps, setApps] = useState<Application[]>([]);
  const [app, setApp] = useState<Application | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [events, setEvents] = useState<ForgeEvent[]>([]);
  const [prompt, setPrompt] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const stream = useRef<EventSource | null>(null);
  const seen = useRef(new Set<string>());
  const active = runs.find((run) => run.status === "queued" || run.status === "running");

  async function reload() {
    const list = await api<Application[]>("/v1/apps");
    setApps(list);
    if (applicationId) {
      const selected = await api<Application>(`/v1/apps/${applicationId}`);
      setApp(selected);
      setRuns(await api<Run[]>(`/v1/apps/${applicationId}/runs`));
    }
  }

  useEffect(() => {
    let disposed = false;
    api<{ user: User; csrf_token: string }>("/v1/auth/session")
      .then((session) => { if (!disposed) { setCsrf(session.csrf_token); setUser(session.user); } })
      .catch(() => {})
      .finally(() => { if (!disposed) setReady(true); });
    return () => { disposed = true; stream.current?.close(); };
  }, []);

  useEffect(() => { if (user) reload().catch((reason) => setError(reason.message)); }, [user, applicationId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    stream.current?.close();
    if (!active || !applicationId) return;
    const source = new EventSource(`/v1/apps/${applicationId}/runs/${active.id}/events`);
    stream.current = source;
    source.addEventListener("forge", (message) => {
      const event = JSON.parse((message as MessageEvent).data) as ForgeEvent;
      const key = `${event.run_id}:${event.sequence}`;
      if (seen.current.has(key)) return;
      seen.current.add(key);
      setEvents((current) => [...current.slice(-199), event]);
      if (["run.succeeded", "run.failed", "run.cancelled"].includes(event.kind)) {
        source.close();
        reload().catch((reason) => setError(reason.message));
      }
    });
    return () => source.close();
  }, [active?.id, applicationId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function perform(action: () => Promise<void>) {
    setError(""); setBusy(true);
    try { await action(); } catch (reason) { setError(reason instanceof Error ? reason.message : "操作未完成。"); }
    finally { setBusy(false); }
  }

  async function authenticate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    await perform(async () => {
      const session = await api<{ user: User; csrf_token: string }>(`/v1/auth/${mode}`, {
        method: "POST", body: JSON.stringify({ username: data.get("username"), password: data.get("password") }),
      });
      setCsrf(session.csrf_token); setUser(session.user);
    });
  }

  async function createApplication(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    await perform(async () => {
      const created = await api<Application>("/v1/apps", { method: "POST", body: JSON.stringify({ name: data.get("name"), description: data.get("description") }) });
      form.reset(); router.push(`/apps/${created.id}`);
    });
  }

  async function generate(event: FormEvent) {
    event.preventDefault();
    if (!app) return;
    await perform(async () => {
      await api<Run>(`/v1/apps/${app.id}/runs`, { method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({ prompt, base_revision: app.current_revision }) });
      setPrompt(""); setEvents([]); seen.current.clear(); await reload();
    });
  }

  if (!ready) return <div className="loading">正在開啟工作室…</div>;
  if (!user) return <main className="welcome">
    <section className="welcome-copy"><div className="wordmark">◈ FORGE</div><span className="eyebrow">YOUR IDEAS, BUILT.</span>
      <h1>從一個想法，<br />到可運行的應用。</h1><p>描述需求、查看成果、繼續修改。<br />讓前端、API 與資料一起工作。</p>
      <div className="welcome-note"><span>01 / 描述</span><span>02 / 生成</span><span>03 / 分享</span></div>
    </section>
    <form className="auth-card" onSubmit={authenticate}><span className="eyebrow">WELCOME TO THE STUDIO</span>
      <h2>{mode === "login" ? "回到你的工作室" : "建立你的工作室"}</h2>
      <label>帳號<input name="username" autoComplete="username" minLength={3} maxLength={64} required /></label>
      <label>密碼<input name="password" type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} minLength={10} maxLength={128} required /></label>
      {error && <p role="alert" className="error">{error}</p>}
      <button disabled={busy}>{busy ? "處理中…" : mode === "login" ? "登入工作室 →" : "建立帳號 →"}</button>
      <button type="button" className="text-button" onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(""); }}>
        {mode === "login" ? "還沒有帳號？建立一個" : "已有帳號？直接登入"}</button>
    </form>
  </main>;

  return <div className="studio"><aside className="sidebar"><Link href="/" className="wordmark">◈ FORGE</Link>
    <p className="nav-label">工作室</p><Link href="/" className={!applicationId ? "nav-item selected" : "nav-item"}>▦ 我的應用</Link>
    <p className="nav-label">最近的應用</p><nav>{apps.slice(0, 10).map((item) => <Link key={item.id} href={`/apps/${item.id}`} className={`nav-item ${item.id === applicationId ? "selected" : ""}`}><span className="app-dot" />{item.name}</Link>)}</nav>
    <div className="profile"><span className="avatar">{user.username[0].toUpperCase()}</span><span>{user.username}<small>{user.role === "admin" ? "管理員" : "創作者"}</small></span>
      <button className="icon-button" aria-label="登出" onClick={() => perform(async () => { await api("/v1/auth/logout", { method: "POST" }); setCsrf(""); setUser(null); router.push("/"); })}>↪</button></div>
  </aside><main className="workspace"><header className="topbar"><span>工作室 / {app?.name ?? "我的應用"}</span><span className="small">FULLSTACK APP FORGE</span></header>
    {error && <div className="error notice" role="alert">{error}</div>}
    {!applicationId ? <><div className="page-heading"><div><span className="eyebrow">YOUR WORKSPACE</span><h1>把下一個想法做出來。</h1><p>所有應用、對話與版本，都在這裡。</p></div><span className="count">{apps.length} 個應用</span></div>
      <form className="new-app" onSubmit={createApplication}><div><h2>＋ 建立新應用</h2><p>先為你的想法取個名字。</p></div><label>應用名稱<input name="name" placeholder="例如：我的待辦清單" maxLength={100} required /></label><label>簡短描述<input name="description" placeholder="這個應用要解決什麼問題？" maxLength={2000} /></label><button disabled={busy}>開始建立 →</button></form>
      <section className="app-grid" aria-label="我的應用">{apps.map((item, index) => <Link href={`/apps/${item.id}`} key={item.id} className="app-card"><div className={`app-art art-${index % 4}`}><span>{item.name[0]}</span><small>{item.current_revision ? "已有可用版本" : "等待第一個版本"}</small></div><div className="card-copy"><h2>{item.name}</h2><p>{item.description || "讓想法從這裡開始。"}</p><footer><span>{new Date(item.updated_at).toLocaleDateString("zh-TW")}</span><span>開啟 ↗</span></footer></div></Link>)}</section>
      {apps.length === 0 && <p className="empty">第一個應用，從上面的名字開始。</p>}</> : app ? <><div className="page-heading"><div><span className="eyebrow">APPLICATION STUDIO</span><h1>{app.name}</h1><p>{app.description || "描述你想做的內容，或繼續修改目前版本。"}</p></div><span className="count">{runs.length} 次任務</span></div>
      <div className="editor-grid"><section className="conversation"><h2>需求與對話</h2><div className="history">{runs.slice().reverse().map((run) => <article key={run.id} className="message"><p>{run.prompt}</p><span className={`status ${run.status}`}>{states[run.status]}</span>{run.error_code && <small>停止原因：{run.error_code}</small>}</article>)}{runs.length === 0 && <div className="empty"><h3>你想做什麼？</h3><p>例如：一個可以新增、完成與刪除待辦事項的清單。</p></div>}</div>
        <form onSubmit={generate} className="prompt-form"><textarea aria-label="應用需求" value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder={app.current_revision ? "描述下一個修改…" : "描述你的應用需求…"} rows={4} maxLength={12000} required /><div><span className="small">{app.current_revision ? "修改會建立新版本" : "建立第一個版本"}</span><button disabled={busy || !!active || !prompt.trim()}>{active ? "任務執行中…" : "生成版本 ↑"}</button></div></form>
        {active && <button className="text-button" disabled={busy} onClick={() => perform(async () => { await api(`/v1/apps/${app.id}/runs/${active.id}/cancel`, { method: "POST" }); await reload(); })}>取消這次任務</button>}
      </section><section className="progress-panel"><header><h2>生成進度</h2><span className="status">{active ? states[active.status] : "就緒"}</span></header><div className="timeline">{events.map((event) => <div className="event" key={`${event.run_id}:${event.sequence}`}><span className="event-dot" /><div><strong>{event.payload.message ?? event.payload.path ?? event.kind}</strong>{(event.payload.text ?? event.payload.delta) && <p>{event.payload.text ?? event.payload.delta}</p>}<small>{new Date(event.timestamp).toLocaleTimeString("zh-TW")}</small></div></div>)}{events.length === 0 && <div className="empty">執行後會在這裡顯示進度。<br />離開頁面不會取消任務。</div>}</div></section></div>
      <details className="settings"><summary>應用設定</summary><form onSubmit={(event) => { event.preventDefault(); const data = new FormData(event.currentTarget); perform(async () => { await api(`/v1/apps/${app.id}`, { method: "PATCH", body: JSON.stringify({ name: data.get("name"), description: data.get("description") }) }); await reload(); }); }}><label>名稱<input name="name" defaultValue={app.name} required maxLength={100} /></label><label>描述<input name="description" defaultValue={app.description} maxLength={2000} /></label><button disabled={busy}>儲存設定</button></form><button className="text-button danger" disabled={busy || !!active} onClick={() => { if (window.confirm(`刪除「${app.name}」？`)) perform(async () => { await api(`/v1/apps/${app.id}`, { method: "DELETE" }); router.push("/"); }); }}>刪除應用</button></details>
    </> : <p className="empty">正在開啟應用…</p>}
  </main></div>;
}
