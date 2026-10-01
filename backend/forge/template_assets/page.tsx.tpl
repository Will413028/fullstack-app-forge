"use client";

import {useEffect, useState, type FormEvent} from "react";

const spec = __FORGE_SPEC_JSON__;
type Todo = {id: string; title: string; done: boolean};

export default function Page() {
  const [todos, setTodos] = useState<Todo[]>([]);
  const [title, setTitle] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState<"all" | "active" | "done">("all");

  async function refresh() {
    const response = await fetch("/api/todos", {cache: "no-store"});
    if (!response.ok) throw new Error("無法讀取待辦，請稍後重試。");
    setTodos(await response.json());
  }
  useEffect(() => {refresh().catch(e => setError(e.message));}, []);

  async function mutate(path: string, method: string, body?: object) {
    setBusy(true); setError("");
    try {
      const response = await fetch(path, {method, headers: {"Content-Type": "application/json"},
        body: body ? JSON.stringify(body) : undefined});
      if (!response.ok) throw new Error("更新失敗，資料尚未儲存。");
      await refresh(); return true;
    } catch (e) {setError(e instanceof Error ? e.message : "更新失敗。"); return false;}
    finally {setBusy(false);}
  }
  async function add(event: FormEvent) {
    event.preventDefault();
    if (title.trim() && await mutate("/api/todos", "POST", {title: title.trim()})) setTitle("");
  }
  const remaining = todos.filter(todo => !todo.done).length;
  const visible = todos.filter(todo => filter === "all" || (filter === "done" ? todo.done : !todo.done));

  return <main data-theme={spec.theme}>
    <header><span className="eyebrow">YOUR DAILY SPACE</span><span className="mark">✦</span></header>
    <section className="intro"><p className="eyebrow">MAKE ROOM FOR WHAT MATTERS</p>
      <h1 data-component-id="todo-heading">{spec.title}</h1><p>{spec.description}</p>
      <div className="stats"><strong>{remaining}</strong><span>件事，等待下一步</span></div>
    </section>
    <section className="workspace">
      <form onSubmit={add}><label className="sr-only" htmlFor="new-todo">新增待辦</label>
        <input id="new-todo" placeholder="寫下你想完成的事…" value={title} maxLength={200}
          onChange={e => setTitle(e.target.value)} disabled={busy}/>
        <button data-component-id="todo-add-button" disabled={busy || !title.trim()}>新增待辦 <span>＋</span></button>
      </form>
      {error && <p role="alert" className="error">{error}</p>}
      <nav aria-label="待辦篩選">{(["all", "active", "done"] as const).map((value, i) =>
        <button key={value} aria-pressed={filter === value} onClick={() => setFilter(value)}>
          {["全部", "待完成", "已完成"][i]}</button>)}</nav>
      <ul>{visible.map(todo => <li key={todo.id} className={todo.done ? "done" : ""}>
        <input aria-label={`完成 ${todo.title}`} type="checkbox" checked={todo.done} disabled={busy}
          onChange={() => mutate(`/api/todos/${todo.id}`, "PATCH", {done: !todo.done})}/>
        <span>{todo.title}</span><button className="delete" aria-label={`刪除 ${todo.title}`} disabled={busy}
          onClick={() => mutate(`/api/todos/${todo.id}`, "DELETE")}>×</button>
      </li>)}</ul>
      {!visible.length && <div className="empty"><span>◌</span><h2>留一點空間，開始下一件事。</h2>
        <p>新增一個待辦，讓今天的進展有個起點。</p></div>}
      <footer>一步一步，讓想法成為日常。</footer>
    </section>
  </main>;
}
