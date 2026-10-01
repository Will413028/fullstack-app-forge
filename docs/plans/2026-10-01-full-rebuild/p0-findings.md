# P0a：固定來源盤點與隔離 spike

2026-10-01。這是技術可行性證據，不是平台完成或完整 sandbox 驗收。P0b 尚需完成契約、DB 權限隔離與持久化磁碟政策；P1 不開工。

## 固定來源與可重跑入口

Reference revision：`893918c808ce7828cd4b9372967e064ed119bbaa`。只讀來源，不執行原碼、不讀設定或 credentials。完整結構列及來源行號見 [inventory](p0-inventory.json)，抽取器見 [p0_inventory.py](p0_inventory.py)。

```bash
python3 /Users/will/second-brain/.projects/personal/fullstack-app-forge/docs/plans/2026-10-01-full-rebuild/p0_inventory.py --reference /Users/will/second-brain/.projects/personal/fullstack-app-forge/docs/plans/2026-10-01-full-rebuild/reference --output /Users/will/second-brain/.projects/personal/fullstack-app-forge/docs/plans/2026-10-01-full-rebuild/p0-inventory.json
python3 /Users/will/second-brain/.projects/personal/fullstack-app-forge/docs/plans/2026-10-01-full-rebuild/verify_plan.py
```

計數來源是上述固定 revision 的 `git ls-files` 與抽取結果。386 tracked files；monolith 30、microservice 26 個 HTTP method mapping，共 56 宣告、30 種 method/path；6 個 entity 宣告；16 個 tool 宣告；8 個 UI routes；27 個 API wrappers。Microservice 是重複產品能力，拓撲不搬。抽取器不是通用 Java parser；新增 revision 必須重做人工交叉檢查。

License metadata 查詢：`git -C /Users/will/second-brain/.projects/personal/fullstack-app-forge/docs/plans/2026-10-01-full-rebuild/reference ls-files '*LICENSE*' '*license*' '*COPYING*' '*NOTICE*'` 回傳空。README 不作授權替代；本專案依行為獨立實作，不複製原碼或素材。此結果不是法律結論。

## 行為補充與去向

| 原能力與來源（reference-relative） | 去向 |
|---|---|
| `AppController.java` 的 chat/deploy/download、owner CRUD、精選與 admin；詳列 inventory | R02/R04/R10/R12/R13，改成 FastAPI；生成改 POST run，GET stream 只讀 |
| `UserController.java` 10 方法、`ChatHistoryController.java` 2 方法 | R01/R05/R13；保留 owner history 與 admin history 查詢/filters，角色只由伺服器授權 |
| `WorkflowSseController.java:23,32,41` 三種 execute 入口 | R03/R04；整合為持久化 run + event stream，不保留 GET 啟動副作用；前端沒有對應 wrapper |
| `yu-ai-code-mother-frontend/src/pages/app/AppChatPage.vue:496,620` | 直接 EventSource 與 ZIP fetch 也是 consumer；Next.js 改成可授權、可重播 run stream 與 download |
| `yu-ai-code-mother-frontend/src/pages/app/AppEditPage.vue:124` | metadata 編輯屬 R02/R13；視覺編輯在 AppChat，不能混為一頁 |
| `yu-ai-code-mother-frontend/src/pages/admin/ChatManagePage.vue:72,130` | R13/P6：保留查詢/filters；現有刪除 handler 只提示成功再 reload，沒有真刪除 API；列 F06，不複製假成功 |
| `yu-ai-code-mother-frontend/src/utils/visualEditor.ts:120,141,148,238,348` | R07/P4：獨立 preview origin，驗 origin/source/schema；穩定 component ID + revision source map；不沿用同源 contentDocument 注入與 `*` target origin |
| `src/main/java/dev/langchain4j/` 8 檔；microservice 同類 8 檔 | R04/P2：評估 tool index/arguments delta 組裝與完成回呼；完整參數通過驗證才執行 tool，不搬 shadow Java 類；未比 upstream，不宣稱全部都是作者修改 |
| `langgraph4j/CodeGenWorkflow.java`、concurrent/subgraph 示範 | R03/R08/R17：保留素材→prompt→策略→生成→品質→build 的責任與有限修正；不照搬教學 graph/topology |
| `AppServiceImpl.java:142–196,207–215`、`StaticResourceController.java:33–61` | R09/R10/R11：靜態發布改全端 health/migration/immutable revision；截圖使用受限來源 |
| SQL user/app/chat_history，entity fields 11/13/8，microservice 同構 | R01/R02/R05：新平台 schema；不移 reference 資料；generated app DB 額外由 R15/D4 定隔離與 migration |

上述 Java 短檔名位於 `src/main/java/com/yupi/yuaicodemother/` 的對應 controller/service/langgraph4j 目錄；精確 controller/tool 路徑在 inventory。Consumer 搜尋可重跑：`rg -n 'from.*@/api/|new EventSource|await fetch' /Users/will/second-brain/.projects/personal/fullstack-app-forge/docs/plans/2026-10-01-full-rebuild/reference/yu-ai-code-mother-frontend/src --glob '*.vue' --glob '*.ts'`。

Already protected：`AiCodeGeneratorServiceFactory.java:116` 已有連續工具次數 20 上限；`ProjectDownloadServiceImpl.java:27–32,50` 已排除 node_modules、.git、dist、.env。新實作仍驗實際 archive，不把 reference 描述成完全沒有保護。

## 本機與執行證據

Darwin arm64、8 CPU、16 GiB RAM；Docker server 29.1.3、VM 8 CPU/約 11.67 GiB，overlay2/extfs；Node 26.10.0、pnpm 11.2.2、Python 3.14.7、uv 0.7.2、psql 16.15。這是 metadata，不是 P1 套件相容性驗收。P1 應選固定受支援版本並建立 lockfiles，不直接把 host Python 當模板版本。

使用既有官方 PostgreSQL 17-alpine/Python 3.12-slim-bookworm images，按 image ID 固定；本次未拉新 image。ID 與逐項結果見 [runtime results](p0-runtime-results.json)，入口 [p0_runtime_spike.py](p0_runtime_spike.py)。重跑需符合 session 下載/執行授權；腳本 `--pull=never`，不自動下載。

```bash
python3 /Users/will/second-brain/.projects/personal/fullstack-app-forge/docs/plans/2026-10-01-full-rebuild/p0_runtime_spike.py --output /Users/will/second-brain/.projects/personal/fullstack-app-forge/docs/plans/2026-10-01-full-rebuild/p0-runtime-results.json
```

16 項實測通過：同 key 單一 durable run、changed digest 可偵測、兩 worker 不重複 claim、有效 lease 不重領、過期重領/epoch、stale worker/cancel 不晚到成功、cursor 重播/唯一序號、transaction 中斷讓成功與事件一起 rollback、PG restart 保留 runs、cgroup CPU/RAM、tmpfs ENOSPC、OOM、rootfs 寫入拒絕、deadline 終止。全部本次擁有的容器與匿名測試 volume 已 cleanup。

測試修正兩個 harness 前提：ON CONFLICT 仍消耗 identity，ID 不一定連號；PG 初始化階段的 pg_isready 可能只看到 temporary server，須另確認主 process name。這不是產品 bug。沒有接既有 DB、publish ports、host bind mount 或 credentials。

## 資源限制：證實與未證實

| 項目 | spike 數值/enforcement | 證據邊界 |
|---|---|---|
| CPU | 0.25 CPU，cgroup `cpu.max=25000 100000` | 驗 controller 設定讀回，尚未做 full Next build 或 CPU 壓測 |
| RAM | 64 MiB、swap=64 MiB；256 MiB 分配被 OOM kill | 實測上限，exit 137 + OOMKilled |
| scratch | workspace tmpfs 16 MiB、tmp 4 MiB，read-only rootfs | 寫 20 MiB 得 ENOSPC；tmpfs 使用 RAM，非 durable storage |
| deadline | 1 秒停止 30 秒工作 | controller 只 kill 自己創建的容器；實際產品 timeout 數值 P0b 設定 |
| 持久化 app DB disk | 未證實硬上限 | PG volume 只證明 restart 保留資料；一般 volume 不因 scratch cap 自帶 quota |

產出有限 profile 的責任仍在 P0b。當前 overlay2/extfs 不滿足 Docker `--storage-opt size` 的 overlay2 XFS+pquota 條件，而且 rootfs size 不是 named volume quota。[Docker 官方說明](https://docs.docker.com/reference/cli/docker/container/run/#set-storage-driver-options-per-container-storage-opt)。因此不能把此 spike 宣稱完整 CPU/RAM/disk profile 已完成。

持久化 disk 的取捨供 Will 決定：A 維持原本硬上限，P0b 驗證 quota-capable volume/專用 VM，增加本機配置工作（保持原不變量）；B 第一版本機受控 DB 採容量監測、超閾值停止與清理，scratch 仍硬上限，較快但監測有時間窗、不能保證物理硬上限（需明確修改原要求）。建議先選 A，不改 D2，P0b 先驗可行性，尚不授权安裝或調整 host。

2026-10-01 Will 確認 A：維持硬 quota，下一步驗證可行方案。這是維持原要求，不新增替代架構 ADR；實際 quota 機制尚未選定。

## D4 比較與 P0b 待驗收

| 方案 | 取捨 | 證據 |
|---|---|---|
| PostgreSQL 自管 leases/queue | 少中介軟體，可與 run/events 共用 transaction；需自管 retry/fencing/heartbeat/維護 | 本次 primitive spike 通過；不是 production worker 已完成 |
| PostgreSQL worker framework（例如 Procrastinate） | 沿用成熟 worker lifecycle，仍須驗其 crash recovery 與 domain fencing | 僅查官方文件，未安裝/跑框架 |
| PostgreSQL + Redis/Celery | 生態成熟，額外服務；broker delivery 與 domain transaction 仍要一致性設計 | 僅查官方文件，未跑對照 benchmark |
| Workflow engine | recovery/可觀測較完整，增加依賴與運維 | 第一切片需求尚不足以採用；後續跨服務長流程才重評 |

官方依據：[PostgreSQL SKIP LOCKED](https://www.postgresql.org/docs/17/sql-select.html)、[Procrastinate](https://procrastinate.readthedocs.io/en/stable/discussions.html)、[Celery task acknowledgement](https://docs.celeryq.dev/en/stable/userguide/tasks.html)、[Redis visibility timeout](https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/redis.html)。這些來源支持機制與取捨，不支持任一方案 exactly-once 的結論。

P0b：補每 app DB role/跨 DB 拒絕驗收；completion 要同時驗有效 lease、epoch、status/base revision；定義 attempt budget、event retention/snapshot/expired cursor、auth/session 與非破壞性 schema 政策；草擬 OpenAPI/event/error 並獨立 review 後交 D4 拍板。D4 未決、不從 primitive 測試推定架構已選；disk 維持硬 quota，機制未驗，P1 仍阻擋。
