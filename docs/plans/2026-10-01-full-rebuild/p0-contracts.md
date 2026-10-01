# P0b 契約草稿與 D4 決策材料

2026-10-01 初始草稿；D4 已由 agent 依完整實作委託採 A，平台核心已有產品實作。此草稿 wire/schema 尚未與完整產品 OpenAPI 收口，不能作目前 API 全量清單。範圍為 P1 walking skeleton；P3–P6 保留 roadmap。

## D4：平台 queue 與資料政策

| 選項 | 取捨與必要工作 |
|---|---|
| A PostgreSQL runs/events + 自管 DB leases | 可在單一 transaction 保存任務、事件、結果；便於學習可靠性，只有一種中介服務；須自己維護 heartbeat、fencing、retry、取消與垃圾清理 |
| B PostgreSQL + Procrastinate | 成熟 worker lifecycle/排程；domain run、artifact fencing 仍需自管，stalled job 須明確安排 recovery，增加框架 schema 與相容性責任 |
| C PostgreSQL + Redis/Celery | 生態與工具成熟；多一個服務，DB/broker 有 delivery 一致性與重送責任，仍需 domain idempotency/fencing |

建議 A：個人作品集第一切片只有單一 bounded run queue，先保持最小依賴與可追蹤 transaction。不是認為自管可靠性免費；P1/P3 必須用本次 spike 的 negative cases 與 race integration 守住。B/C 沒有安装或 benchmark；比較是官方機制與本案需求的推論，不是效能結論。[PostgreSQL SKIP LOCKED](https://www.postgresql.org/docs/17/sql-select.html)、[Procrastinate stalled recovery](https://procrastinate.readthedocs.io/en/stable/howto/production/retry_stalled_jobs.html)、[Celery acknowledgement](https://docs.celeryq.dev/en/stable/userguide/tasks.html)。Workflow engine 等跨服務 durable workflow 出現再評估。

D4 採 queue A 及下列資料政策：同 app 同時只允許一個 active run；事件保留 7 天，終態 snapshot 隨 app/revision 保留；最多2次 worker attempt；非破壞性 schema 預設，破壞性 schema 拒絕。採用者為 agent，依据 Will 的完整實作委託，並非 Will 逐項選 A；實作與驗收以主計畫為準。

## Ownership、auth 與 DB

- Public app/run/revision/user IDs 用 UUID 字串，不沿用 Java bigint。內部 DB sequence 使用 bigint，wire sequence 是十進位字串，Next.js 以 BigInt 比較，避免 JS 精度損失。
- API 所有 app/run GET/POST 都先驗 session→owner→app/run 關聯；越權與不存在統一404。Admin 另外驗伺服器角色；不接受 request 指定 owner/role。
- 平台獨立 PostgreSQL cluster；每 app 獨立 PostgreSQL container/容量受限 volume。每 app 有 migration owner 與 runtime DML role；runtime 只允許既有表 CRUD/必要 sequence，不授 CREATE、SUPERUSER、CREATEROLE、CREATEDB 或 server-file roles。migration credentials 僅 trusted controller 使用，不注入 generated API。
- P0 DB spike 在單一測試 cluster 驗跨 database CONNECT 拒絕與 runtime role 限制；產品跨 cluster/network/password 隔離仍由 P1 驗，不以 trust-mode 測試代替 authentication。[PostgreSQL privileges](https://www.postgresql.org/docs/17/ddl-priv.html)。
- 安全預設：密碼 Argon2id 至少19 MiB、2 iterations、parallelism1；32 random-byte opaque session，DB 只保存 hash；HttpOnly/host-only cookie、SameSite=Lax，HTTPS加Secure，正式環境用 `__Host-forge_session`；本機 HTTP 用 `forge_session`。絕對期限7天、idle12小時，logout撤銷。先前來源的多種時間值不直接搬入。
- 同 origin platform UI/API proxy，generated preview 使用另一 hostname，避免 cookie 依 port 無法隔離。Authenticated writes 要 CSRF token，所有 auth/write requests 驗 Origin allowlist，login/register 限流；不把 SameSite 當唯一 CSRF 保護。[OWASP session](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)、[password storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)。期限為本案預設，OWASP不替本案指定這些時數。

## Run state、lease、commit

`queued → running → succeeded | failed | cancelled`；retry 仍同 run，attempt/epoch 增加，不復活終態。claim 用 SKIP LOCKED；lease30秒、heartbeat10秒，clock 由 DB 給定；恢復時先驗絕對 deadline/attempt cap，超限轉 failed。run wall deadline15分鐘，build5分鐘、工具20次、修正2次；模型 token/費用尚待D3，P1 fixture不產生模型費用。

CreateRun：POST `/v1/apps/{app_id}/runs`，body prompt/base_revision，`Idempotency-Key` 以 owner+app 為 namespace。Canonical request hash 包含 prompt/base/template version；同 key 同 hash 回傳原 run（202），不同 hash409 IDEMPOTENCY_CONFLICT。相同 key 查詢先於 active-run 檢查；另一 key 在同 app active 時409 APP_BUSY。stale base409 STALE_REVISION。initial base為null且app無current revision。檢查、insert run、初始event在同 transaction；GET不建run。

完成 transaction 固定先鎖 app 再鎖 run；驗 owner/app、running、目前 epoch、fresh lease、deadline、base == app current revision，再驗 artifact checks。一次更新 current revision、run terminal status、append terminal event；失敗 rollback全部。取消同鎖順序，以先成功commit者為準：已終態cancel返回409 RUN_TERMINAL；其他轉 cancelled並通知controller停止。外部 build/啟動不包在 DB transaction 裡，以(run,epoch)命名候選資源、controller/reconciler清理，stale candidate不得提升。artifact成功也不能替代lease/deadline檢查。

所有 event allocate sequence 在鎖定 run 的 transaction，`UNIQUE(run_id,sequence)`；status/event transaction不一致不得提交。沒有 exactly-once 外部程序承諾，只有 at-least-once attempt + fenced artifact promotion。P0 SQL predicate probe 不證明 app/run lock race 已實作，P1/P3另驗。

## SSE 與 snapshot

GET `/v1/apps/{app_id}/runs/{run_id}/events`；SSE `id`為sequence、`event`為kind、`data`為Event JSON。重播只讀 sequence > Last-Event-ID，保持順序；consumer 去重，state以 GET run snapshot為SSOT。斷線不取消，heartbeat comments不占sequence。先授權再檢查cursor；負數/非數字400 INVALID_CURSOR；超過last sequence400 CURSOR_AHEAD；cursor已過保留窗口410 CURSOR_EXPIRED，client讀run snapshot後以current last sequence續接。live/replay切換須避免訂閱窗口漏事件（DB持續查詢或subscribe後補查），不依記憶體queue提供唯一證據。

text.delta只append；text.snapshot替換該attempt的完整display text。tool.arguments.delta僅顯示/組裝診斷，call_id依adapter的tool index穩定化；只有完整解析且schema/path通過的tool call才發tool.started並執行。tool結果與模型文字分開，stage成功不等於run成功。terminal event內含Run snapshot；run.succeeded的artifact_revision不得null，failed/cancelled不得把失敗候選當可用revision。模型私有推理不保存。raw args不得含secret，公共events不輸出credentials或host path。

CreateRun初始事件為run.queued，attempt=0；首次claim增至1。queued取消/排隊deadline失敗可在attempt0發終態，run.started/工具/check與成功必須attempt>=1。Event.kind必須等於payload.type；終態snapshot.status必須對應kind，succeeded需非null artifact且stop_code=null，failed需非空stop_code；OpenAPI allOf已描述此關聯。

## OpenAPI 與錯誤

草稿：[p0-openapi.json](p0-openapi.json)，OpenAPI3.1，10 operations。P1實作後由FastAPI export產生對照，不能用手寫草稿冒充實際API。文件預設cookie名稱，本機/public差異由environment設定；不為未實作admin/files/deploy捏造endpoint。

| HTTP | code | 行為 |
|---|---|---|
| 400 | INVALID_CURSOR / CURSOR_AHEAD / INVALID_REQUEST | 參數無效，不啟動工作 |
| 401 | AUTH_REQUIRED | session無效 |
| 404 | NOT_FOUND | 不存在或非owner，不洩漏私有資源存在 |
| 409 | IDEMPOTENCY_CONFLICT / APP_BUSY / STALE_REVISION / RUN_TERMINAL | 回原狀態或衝突，不重複副作用 |
| 410 | CURSOR_EXPIRED | 讀snapshot恢復，不重新生成 |
| 429 | QUOTA_EXCEEDED | 不建立新run |
| run failed | DISK_LIMIT / MEMORY_LIMIT / DEADLINE_EXCEEDED / ATTEMPTS_EXHAUSTED / BUILD_FAILED / HEALTH_FAILED | run持久化failed；deadline/cap/cancel/stale-worker禁止late success |

CPU飽和是節流而非立即錯誤，達deadline才停止。disk ENOSPC與OOM分別映射DISK_LIMIT/MEMORY_LIMIT；container exit137本身不能單獨推定OOM，需inspect OOMKilled。PG滿容量時domain worker在平台DB記失敗，先停app writes/DB、清理可重建候選；不得自動刪使用者資料。備份/restore與DB-full recovery仍須quota spike/P1integration證明。

## P1 profile 提案與驗收入口

單機同時最多1個run、最多2個active preview；build2CPU/3GiB、scratch512MiB+/tmp64MiB，rootfs read-only；runtime frontend1CPU/512MiB、API0.5CPU/256MiB、app PG0.5CPU/256MiB；每app PG durable filesystem2GiB。所有 scratch/DB/產物/log 可寫位置必須有 cap，controller不允許未受限 mount；Docker日志限制每container10MiB×2檔，產物儲存獨立4GiB受限池。平台資料、dependency images與host caches不在generated寫入範圍。這些是容量提案，P0 primitive僅驗較小數值，full build/CRUD性能在P1量測，不能宣稱數值已足夠。

P0驗收命令在同附件：`p0_db_spike.py --output <absolute-results-path>`、`p0_quota_spike.py --execute --output <absolute-results-path>`（mount需授權）；契約gate只驗OpenAPI結構/refs/安全/header/事件種類，不是完整規格conformance或API執行。

P1預計tests：`test_owner_cannot_subscribe_other_run`、`test_retry_same_key_returns_original_run`、`test_changed_payload_conflicts`、`test_expired_lease_cannot_promote`、`test_cancel_completion_race`、`test_sse_replay_does_not_create_run`、`test_generated_crud_survives_api_restart`、`test_disk_full_blocks_late_success`。fixture以真API/DB/容器跑；去掉owner/fresh-lease guard、把GET改啟動、移除bounded mount時必須轉紅。這些test IDs待建立，不宣稱已執行。
