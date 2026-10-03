---
title: 平台採 PostgreSQL durable state 與自管 bounded queue
date: 2026-10-01
status: active
tags: [personal, decision, postgresql, ai-agent]
---

# 平台採 PostgreSQL durable state 與自管 bounded queue

## Context

平台原無程式、部署或待搬移資料。需要保存 app/run/event/revision，worker 重啟後有明確狀態，取消及 lease 過期不能晚到提升 artifact。persistence 與 queue framework 是兩個選擇；生成模板用 PostgreSQL 不代表平台必須跟隨。

- `external` Will 指定學習兼作品集、Next.js + FastAPI、受控本機 Docker；完整實作委託要求完成功能並記錄決策，未指定 queue framework。
- `inherited` run snapshot 為 SSOT、SSE 可重播、owner/base revision/epoch 保護仍成立：外部 build/runtime 有可重送副作用，換 framework 也不能免除。
- `inherited` 初始一個全機 active run、同 app 一個 active run、有限 attempts/deadline：適合受控本機起步；並非永久吞吐限制。
- 既有自管實作是 prior state，不拿「已寫好」當排除 framework 的理由。

## Options Considered

- **A PostgreSQL durable state + 自管 DB leases（採用）**：domain transition、event append、promotion 可在同一 transaction 內檢查；直接學習 lease/fencing/recovery。代價是自己維護 heartbeat、重試、取消、清理與診斷。
- **B PostgreSQL + Procrastinate（框架基準）**：同樣只有一種資料服務，提供成熟 task lifecycle/retry；增加框架 schema、版本與 domain/job 映射。仍須安排 stalled recovery，domain fencing 另做。[官方 stalled recovery](https://procrastinate.readthedocs.io/en/stable/howto/production/retry_stalled_jobs.html)。
- **C PostgreSQL + Celery/broker**：routing、排程與 worker 生態完整；增加 broker 維運及 DB/enqueue 一致性邊界，可能需 outbox。[官方 task acknowledgement](https://docs.celeryq.dev/en/stable/userguide/tasks.html)。
- **D durable workflow engine**：適合長期等待、分支、補償與跨服務恢復；增加服務、SDK 與工作流約束。目前未確認這類需求，不永久排除。

## Decision

- **D4a** 平台 relational domain state 採 PostgreSQL；generated DB 的權限與資料另行隔離。
- **D4b** 初始 queue 採 A：DB-backed claim/lease/epoch，最多兩次 attempt、有限 deadline；不承諾外部程序 exactly-once。
- 資料政策：同 app 一個 active run；事件七天、terminal snapshot 長存；破壞性 generated schema 修改預設拒絕。
- 採用者為 agent，依 Will 的完整實作委託；並非 Will 逐項選定 A。此決定不代表 runner/profile、真模型或遠端部署已驗收。

## Rationale

- PostgreSQL 的 relation/constraint/transaction 可直接表達 run/event/revision/current revision 的一致性；選擇來自 domain 需求，而非生成模板沿用。
- 相較 B，A 刻意把可恢復執行作為學習與作品集可解釋的成果，有限 queue 可逐一量測。代價是通用 lifecycle 維護會占用功能交付時間；少 package 不等於少維護。
- B 不是多一個中介服務，也不因仍需 domain fencing 就失去價值。若 queue 維護主導工作，B 的成熟 lifecycle 收益應優先重評。
- 不選 C 作第一階段，是目前無 broker routing、多 consumer 或獨立吞吐需求；不主張 C 更慢或必然更貴。
- D 在長期等待／補償需求出現時有收益；目前單 bounded attempt queue 不足以抵銷其新增維運。
- 三條 queue 路線都需 idempotency、外部資源 reconcile 與 fenced promotion；task acknowledgement 不能替代成功證據。

## Expected Outcome

平台重送返回同一 run；取消、timeout、過期 attempt 不提升 revision；restart 後能恢復或確定失敗。以真 PostgreSQL 行為測試及 worker/runner 故障驗收判定，不能從 SQL 機制存在推定全部完成。

## Followup

- P1a 收口完整 API/event lifecycle；P1b 將已建立的resource journal接入worker/adapter，驗 crash、DB failure、claim race、取消／完成競賽與外部資源清理。
- P3 首次啟用 event prune 前一併驗 expired cursor 與 terminal snapshot；generated migration 保留既有資料。
- P1b 前完成硬 quota/profile/E2E；本 ADR 不解除該 blocker。

## Revocation Triggers

- 多任務 routing、跨服務長期等待／補償，或自管 recovery 的維護工作開始主導功能交付時，重評 B/C/D。
- 開放匿名生成或擴大 workload 時，重評初始 concurrency、attempt 與資源政策。

## Review Notes

兩份 fresh 唯讀草稿均要求分開 persistence/queue 判斷，指出 B 同樣無第二資料服務；以上 rationale 已採納，沒有把既有實作當限制。

## Related

- 本 ADR 即 2026-10-01 agent 採用決策的原始紀錄，無外部會議來源文件；非 SDD compression。
- [固定模板與本機受控 runner](2026-10-01-fixed-template-local-runner.md)：先前 D1/D2，未由該 ADR 推定 D4。
- [PostgreSQL 17 SELECT / SKIP LOCKED](https://www.postgresql.org/docs/17/sql-select.html)：可重取的 queue locking 機制來源，非效能比較。

## Updates (2026-10-01)

產品基礎已提交 `dcdf481`（以 `git show dcdf481` 取回）；33 backend tests與resource epoch mutation通過，P0b2 primitive解除，產品adapter/worker/完整profile仍待驗，D4選擇不變。
