# P1b：受控全端 runner implementation plan

本文件細化主計畫 P1b；進度仍只更新主計畫。P0b2 第三輪完整 8 checks 已過，但 256MiB primitive 不等於產品 profile。

## 執行順序與驗收

1. **Durable resource intent 與 reconciler。** 在首次建立產品持久化資源之前，新增有序 migration、resource store 與 adapter-independent reconciler。每項資源有 UUID、固定種類、受控外部名稱、app/run/epoch、retention、operation token 與狀態；平台 tombstone、run terminal、epoch 失效會要求清理。先提交建立意圖，再發外部 mutation；未知結果保留，不能因 CLI timeout 或一次 lookup absent 而假稱清理完成。adapter 只有在操作已確定結束時才能 acknowledge。重啟只處理確定未開始或可安全清理的資源，creating/unknown 不重送 mutation。真 PostgreSQL tests 驗 cancel/create race、app tombstone、old epoch、兩個 reconciler claim fencing、unknown 保留、token 不可晚到，並做移除 fencing 的 mutation。
2. **Product loop adapter 與 profile。** 從 primitive 重新設計持久化所有權與恢復，不 import 計畫 spike 當產品 library。trusted controller 專用 image 固定 digest，cap drop ALL 僅 SYS_ADMIN/MKNOD、major7 minors0–31；generated workloads 沒有 controller capabilities、Docker socket 或 host mounts。容量為 DB 2GiB／artifacts 4GiB；CPU/RAM/pids/tmpfs/deadline/log caps 各由 HostConfig/cgroup/實際 filesystem 讀回。先串入 journal，再建產品資源。建立、normal stop、mount/unmount、remap 與 cleanup 必須有 owned identity 證據；unknown operation 不自動擴權或刪 backing。
3. **固定 Todo 全端 template 與 fixture worker。** 生成 Next.js frontend、FastAPI CRUD、PostgreSQL schema；build 與執行都在受限容器。平台 credentials 不進 generated runtime。worker heartbeat/epoch/base revision 沿用已測 domain predicates，artifact 只有 build/health/CRUD 通過才 promote。預覽獨立 origin，平台 cookie 不流入生成應用。模板 migrations 保留 app data，source workspace 與 DB scope 分離。
4. **整合驗收。** 建立 `make e2e-fixture`：平台 UI 建 run → SSE tool progress → generated UI CRUD → API restart → 原資料仍可讀；另一 owner 不能取得預覽。實際 profile 注入 CPU/OOM、SQL/WAL/artifact ENOSPC、timeout、cancel/crash，核對限制與終態、禁止晚到 promote、資源回收。上述證據取得前不勾 P1 完成。

## 沿用與替代

| 機制 | 原本原因 | 今天從零設計 | 結論／重評條件 |
|---|---|---|---|
| PostgreSQL durable state/lease | D4 已比較單 DB 與 framework/Redis | domain fencing 與外部資源 intent 同 DB transaction；Docker 不在 transaction 中呼叫 | 沿用 D4；有 worker 規模與維護成本證據時重評 framework |
| fixed ext4 loop images | 普通 Docker volume 未證硬 quota；HFSX/Lima 路徑未過 | 本機受控 Docker 下使用已驗 primitive，但建產品 journal、身份與 profile gates | 僅採為 P1b 待驗 adapter；產品實際容量或恢復 gate 失敗就停止此 adapter，不能移除 hard cap |
| resource reconciliation | app tombstone 不代表外部容器已停 | durable intent、operation token、已確認與未知結果分開；有 fresh lease 才能開始建立 | 新增；未知 daemon operation 必須保留至可證已 settled，不能任意定時重試 |
| UUID external names | 控制平台目前採 UUID | 固定 prefix/kind/UUID，拒絕 client path/name authority | 沿用 ID primitive；name 由 server 產生，不讓 user 指任意容器 |
| trusted dependency images 安裝器 | 平台用 uv/pnpm；固定 generated template 不必攜帶兩個管理器 | Python 以 uv.lock 為SSOT，frozen export requirements.txt後pip hash/binary-only；Web以package-lock.json為SSOT、npm ci且ignore-scripts | 採目前方式；模板依賴、base digest或target architecture變更時同步lock/export並重建images，runner首次接入驗image與template依賴吻合 |

## Consumers preflight

`rg --files /Users/will/second-brain/.projects/personal/fullstack-app-forge/backend/forge`；`rg -n 'deleted_at|epoch|lease_until|finish|recover' /Users/will/second-brain/.projects/personal/fullstack-app-forge/backend/forge`。

目前 consumers：`main.py` app tombstone、`runs.py` claim/heartbeat/cancel/finish/recover、`db.py` migration、`test_run_store.py` 實際 PG fixture；新增 resource store/reconciler 與後續 worker/runner。lock order 固定 app → run → resource，與現有 cancel/finish/recover 一致；不能在持 DB lock 時等待 Docker。

## 邊界

本步為獨立新系統、無正式資料搬移。D3 paid model 與 D5 remote host 沒有配置，fixture 不當 live/deployment。無 commit/remote 操作。P0 failures 保留原件；產品 module 不回寫 spike evidence。

## Resource lifetime 與 settlement

| Retention | 資源用途 | Run 終態／promotion | App tombstone |
|---|---|---|---|
| run | builder、checker、暫存容器 | 任意終態後清理；永不 adoption | 立即要求清理 |
| preview | preview container/network | 只有原子 promotion adoption 後繼續服務 | 立即停止並清理 |
| app | app DB 固定 filesystem scope | promotion 原子 adoption；後續 run 從 app 取穩定 scope，creation run 只是來源 | 先停 preview/DB runtime；資料七天後 purge |
| revision | immutable source/artifact scope | promotion 原子 adoption；失败 candidate 清理，舊可用版本保留 | 七天後 purge；revision GC 政策於 P3 明定後才接 |

`RunStore.finish` 在 app → run → resource lock order 下驗本 run/epoch、ready、無 cleanup intent，與 revision insertion/current revision update 在同一 transaction 更新 adopted_revision；過期或取消不能 adoption。持久資料生命週期以 app/adopted revision 為準，不以原 creation run 是否仍 running 判斷。未 adoption 的候選在 run 終止或失去 lease 時回收。DB runtime 的 container 用 preview retention，DB filesystem 用 app retention，避免資料七天保留變成繼續執行。

**未知結果的結論是 quarantine，沒有定時重送。** creating/deleting 的 initiating process 消失時不能用一次 lookup absent 自動解除。store 列出 creating/deleting/unknown 及 operation UUID；新 worker 不重用它、不 promotion，也不假称 cleanup 完成。reconciler 可以繼續處理其他已確定資源。

| Mutation | 可接受的 settled 證據 | 缺少證據時的處理 |
|---|---|---|
| Docker create/remove container/volume/network | initiating request 已完成並返回結果；adapter 再核對 server-generated name/id/labels。lookup 只驗身份，不單獨證 request 結束 | 保留 intent/token，標 outcome unknown；診斷只含本資源 identity/operation/state |
| controller attach/detach/format/mount | initiating controller process 結束及 exit status，且完整 backing identity/mount readback 符合；正常 detach 必須已 unbind | 保留 backing 與相關 consumer；禁止刪 raw image或重新 attach，禁止擴權 |
| lost initiating process | operator 在受控維護窗口確認該 operation 已停止：停止並確認本 controller 所有進程結束、隔離本資源 consumers，再核對 owned loop/mount/object identity；只能針對確定身份操作 | 此版採安全保留；證據不可證時維持 quarantine，輸出人工處理診斷，不清掉 journal |

Resource store 的 acknowledgement 只由 trusted adapter／維護工具呼叫，沒有公開 HTTP「強制成功」入口。實際 adapter 落地時，必須驗上述 identity/settlement 後才能 complete_create/complete_delete；單純傳入 UUID 不是證據。此選擇讓未知故障停在可診斷狀態，代價是需受控維護，不能宣稱所有 daemon 故障自動恢復。
