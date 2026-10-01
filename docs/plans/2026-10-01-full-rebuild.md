# Fullstack App Forge：完整重做階段計畫

**Goal：** 使用者可生成、修改、預覽與分享完整 Next.js + FastAPI 應用；前端實際存取 API 與持久化 DB，具備原產品主要管理與視覺編輯能力，並有可重跑的驗收證據。

**上層：** 暫代主計畫；本文件是 implementation 進度的唯一清單。

**附件：** [需求/来源/沿用盤點](2026-10-01-full-rebuild/requirements.md)。規格見 [spec](../spec.md)。

## 全域約束與完成定義

- 學習兼作品集；平台與生成應用均用 Next.js + FastAPI，個人 monorepo。
- 完整重做是功能與行為重建，不照搬 reference 的 Java、Vue、微服務或 host build 結構。
- Will最新完整實作委託涵蓋必要目錄、依賴下載、隔離runner與本機測試，不再逐批請求權限；不操作無關專案或讀/輸出credential payload。付費服務未配置budget時不發出付費請求；本次不自行開帳號或commit。
- 完成定義：R01–R18 各有實作/驗收；fixture E2E 與真模型結果分開；全端案例實際通過 CRUD、修改與重啟；分享案例 frontend/API/DB 可運行；独立設計審查完成；每項列明已測/未測/已部署狀態。
- 目前的 P0–P7 是跨 session roadmap；每一步開工前細化逐檔 implementation plan，不能把未建立的指令宣稱已存在。

## 前提（2026-10-01）

- 會改到或取代的既有部署是否在線：無既有部署；本新系統不變更 reference 部署或資料。來源 U1 與本次新目錄；已確認。
- 學習/作品集、生成全端、personal 名稱與路徑：來源 U1，已確認。
- 原功能基準已 pin `893918c808ce7828cd4b9372967e064ed119bbaa`；盤點、consumer、授權 metadata 與去向见附件 `p0-inventory.json`/`p0-findings.md`，2026-10-01 已核對；不執行 reference。
- 硬體與工具 metadata 已核對、Docker 可用；版本與 spike 證據見附件 `p0-findings.md`。平台 build 與 FastAPI/PG 測試已執行，generated runtime 仍未驗。
- 工具鏈為 pnpm/uv/pytest/Playwright，已安裝並固定 lockfiles；桌面／手機 browser shell 已測。
- D1/D2已由Will確認A；最新完整實作委託下，agent依既有比較採D4的A及保守資料政策。D3實際provider/budget與D5遠端host仍需外部配置證據，不能虛構真模型/部署結果。

**驗收基線：** 初始化時 reference 未在本機 build；新目錄只有文件與 P0 spike/檢查腳本。P1a 已 init 獨立 Git（無commit/remote）、建立 CI 與平台 runtime；24 項backend tests含migrations、Next build與browser shell通過。產品進度見下表；不將平台基線當生成應用完成。

## 不變量與消費端

| 不變量 | 預計依賴模組 |
|---|---|
| owner/app/revision 權限隔離 | auth、apps、runs、events、downloads、admin、preview gateway |
| 平台/generated code/DB 分離 | runner controller、generated template、deployment adapter |
| 成功有 build/health 證據 | worker state machine、artifact promotion、frontend status |
| idempotency/lease/base revision 不重複提交 | run store、tools、worker、revision service、deployment adapter |
| event 重播不重啟生成 | event store、FastAPI SSE、Next.js event reducer |
| schema 修改保護既有 generated data | template migrations、revision service、deployment adapter |

平台核心已在 `backend/forge/{main,runs,db,security}.py` 與 `web/components/studio.tsx`；worker、runner 與 filesystem consumers 尚未接通。每步消費端 preflight 固定先跑 `rg --files /Users/will/second-brain/.projects/personal/fullstack-app-forge`，再以該步 wire/module 名稱 `rg -n` 搜全部 repo；記結果至該步驗收附件。

## 範圍

- 做：R01–R18，採全端生成替代原三種輸出；功能逐項來源見附件。
- 不做：Java/Vue 保留、reference 正式資料移轉、逐行翻譯、教學專用微服務拓撲；不符合本次技術與學習目標。
- 延後：任意套件/外部服務與匿名公開生成（Will 已確認 D1/D2）。觸發條件分別為核心案例通過且 provider/依賴政策決定、runner threat model 與費用上限通過。
- 商業付款、团队協作、生成应用 OAuth 等沒有明確需求；新增時另定 scope，不塞入第一切片。

## 步驟

- [ ] **P0. 盤點與設計 spike**（被擋於：下載 reference 時需授權；其餘唯讀不擋）
  - P0a 盤點與 primitive spike：本次驗收完成；來源/去向與可重跑入口見 [P0 findings](2026-10-01-full-rebuild/p0-findings.md)。
  - P0b1 契約草稿與 DB 邊界：10項 DB role/fresh-lease/base/epoch probe 與契約結構gate；獨立review三項已修，詳細語意在 [contract draft](2026-10-01-full-rebuild/p0-contracts.md)，OpenAPI未凍結。
  - P0b2 持久化 quota primitive 已通過：HFSX/Lima 舊失敗保持原件；[Docker loop候選](2026-10-01-full-rebuild/p0-loop-quota-proposal.md) 第三輪取得完整 8 checks，含兩 scope 真 ENOSPC、隔離、PG restart、normal remount 與 controller remap。`p0-loop-quota-attempt3.json` 的 exact gate 通過、cleanup 全 true，spike-id 容器與 volumes 皆空。此證據解除 primitive blocker；P1b 仍須驗產品實際容量、SQL/WAL、完整限制與 reconciler。
  - P0b3 D4：agent依完整實作委託採A與既有保守政策；實際API契約由產品OpenAPI與tests證明後凍結，不把草稿10 operations當完整產品API。
  - 範圍：pin reference revision，盤點全部 controller/前端 routes/schema/tool/部署鏈與 license；補每項去向。核對本機工具 metadata；比較 run persistence、queue、app DB 與 runner 方案，產出 D4 材料；草擬事件/錯誤/OpenAPI 契約，D4 後凍結。
  - Runner 產出：實作者依本機能力選定有限 CPU/RAM/disk/執行時間 profile，寫出數值、enforcement 方式、終止/cleanup 與超限錯誤契約，不重開 D2。disk 限制需證明實際 filesystem/volume enforcement，不能假定一般 Docker volume 自帶 quota；做不到就回報並阻擋 P1，不能移除上限。
  - 消費端：目前無程式；`rg --files /Users/will/second-brain/.projects/personal/fullstack-app-forge`。取得 reference 後補 absolute-path 搜尋指令與 snapshot。
  - 不能動：reference code、其他專案與正式環境。
  - 驗收：所有盤點列有來源與去向、每個 R ID 對應階段；新增附件 `verify_plan.py` 能检查覆盖/去向/決定 blockers，刪掉 R15 對應或清空一個去向必須失敗。來源不可取回就保留局部盤點狀態。
  - 停止：完整功能無法核對、license 不支持預計使用；報具體差異，不宣稱 inventory complete。

- [ ] **P1. Walking skeleton 與受控全端預覽**（產品runner受P0b2與實際profile驗收阻擋；平台核心P1a可獨立實作，D1/D2/D4已確定）
  - P1a 平台核心：建立FastAPI auth/apps/runs/events、PostgreSQL schema/leases與Next.js工作室；與runner無關的API/DB測試在隔離PG執行。資料庫guard tests通過不等於fullstack generated preview驗收。
  - P1b runner與fixture：在P0b2通過後接全端template、hard profile與generated CRUD/restart驗收；P1未完成前不宣稱walking skeleton完成。
  - 範圍：建立 Git/manifest/lockfiles/CI、平台 auth/app/run/events 與最小 worker；deterministic fixture 產出 Todo 全端模板，在 runner 啟動前端/API/DB。`make check` 已建立，串unit/DB/web/browser；`make e2e-fixture` 尚待P1b建立。
  - 消費端：platform browser、API、worker、runner、template；開工用前述 `rg` 列新增 consumer，契約 fixture 共用。
  - 不能動：owner boundary、GET 不生成、平台資料隔離。
  - 驗收：乾淨環境啟動；UI 建 app/run；SSE 工具進度；generated UI 新增/查詢 Todo，API restart 後資料仍在；另一 owner 訂閱被拒。另建立adapter profile gate，記錄DB/artifact/scratch的受測scope、配置容量/mount身份與CPU/RAM/pids/deadline/log限制讀回，再注入CPU飽和、OOM、真SQL/WAL及artifact disk滿、timeout，驗ceiling、停止/失敗與cleanup，不能晚到提交成功。移除API寫入、owner guard、timeout/mount enforcement或改錯容量時測試必須轉紅；P0固定256MiB gate不代替此產品驗收。
  - 停止：只能 fake UI/API 或 runner 沒有隔離；不得記全端切片完成。

- [ ] **P2. 真模型生成與 bounded 檢查**（被擋於：P1、D3）
  - 範圍：model adapter、spec planner、constrained tools、compile/test/health、有限修正與成本 trace；真模型 small spike 測固定案例生成能力。
  - 消費端：worker/tool layer、events reducer、artifact promotion；用 `rg -n 'run|event|artifact|tool' <repo-absolute-path>` 留清單。
  - 不能動：平台 credentials 不注入 generated runtime；budget 不能無上限。
  - 驗收：`make check`；`make e2e-fixture`；新增手動 `make smoke-live`（需已授權 provider 與 budget）。Todo、簡易 CRM、筆記三個案例各保存輸入、版本、artifact、build/CRUD 結果與成本；首次量測後才提交模型品質採用門檻。transport partial 後斷線形成 failed；永遠失敗 checker 在預算內停止。吞掉保存錯誤或忽略 build 結果，回歸測試必須失敗。
  - 停止：達 budget、費用未知無法限定、外部服務未授權；fixture 綠不能取代真模型證據。

- [ ] **P3. 對話修改、版本與恢復**（被擋於：P2、D4）
  - 範圍：revision context、app/revision 檔案樹與內容讀取、source diff、DB migrations、code rollback、cancel、worker lease/recovery、SSE replay。
  - 消費端：history、editor、worker、event store、runner/template migrations；`rg -n 'revision|history|lease|sequence|migration|cancel' <repo-absolute-path>`。
  - 不能動：舊可用 artifact 不被失敗覆蓋；source rollback 不謊稱回復 DB。
  - 驗收：`make check`/`make e2e-fixture` 擴充修改 Todo 加欄位且原資料保留；檔案瀏覽顯示指定 revision 的樹/內容，越權與 path traversal 讀取拒絕；stale base revision 衝突；斷線重播不重複 run；worker crash/cancel race 不晚到提交；移除 file owner/path、lease/base-revision 校驗或重播去重測試轉紅。破壞性 migration 拒絕並要求明確授權。
  - 停止：無法證明 migration 保留資料；schema rollback 未定義。

- [ ] **P4. 視覺化編輯**（被擋於：P3）
  - 範圍：template source instrumentation、iframe selection bridge、穩定 component IDs、revision-aware source mapping 與局部修改。
  - 消費端：generated frontend instrumentation、preview gateway、selection UI、source mapper、patch tools；`rg -n 'component_id|postMessage|selection|source_map|revision' <repo-absolute-path>`。
  - 不能動：origin/source 校驗；選取資料不能直接成為 filesystem authority。
  - 驗收：選取 Todo 按鈕改標題/樣式後只改對應 source，CRUD 仍過；舊 revision/偽造 origin/任意 path 拒絕；移除 revision 或 origin guard 時測試轉紅。`make check`/`make e2e-fixture`。
  - 停止：只能全頁重生成或 DOM 無法映射 source；不得宣稱視覺化編輯完成。

- [ ] **P5. 全端發布分享**（被擋於：P3、D2，host/cost spike 後的部署決定 D5）
  - 範圍：部署 adapter spike、health/TLS/DB backup 與 migrations、immutable revision 發布、分享權限、封面、ZIP。D5 在 spike 後提交 host/費用/資料保留/備份與發布可見性選項，不先開帳號。
  - 消費端：deployment API/worker、runner、generated frontend/API/DB、share page、screenshot、download；`rg -n 'deploy|share|download|screenshot|migration' <repo-absolute-path>`。
  - 不能動：不發布 credentials；截圖 fetch 禁止內網/metadata；平台 cookie 不流入 app origin。
  - 驗收：`make check`/`make e2e-fixture`，新增 `make e2e-deploy` 先對本機 adapter；發布 URL 新增/查詢資料，API restart 保留；失敗 revision 不替換 live；ZIP 可重啟且不含 secrets；越權下載/內網截圖拒絕。破壞 API health 或 archive exclusion 時測試轉紅。
  - 需要人做：D5 與實際 host/付費/公開部署授權，授權後才跑遠端 smoke。遠端尚未跑就標本機完成待部署。
  - 回滾：切回上個 artifact；涉及 schema 則先驗相容性或 backup restore，不能只換 image。

- [ ] **P6. 原產品管理與生成輔助功能**（被擋於：P2、P4、P5；素材 provider 若付費另拍板）
  - 範圍：精選/公開案例、admin user/app/history management（history 查詢與 filters）、策略路由、prompt 增強、授權素材收集、限流與監控 dashboard；對照 P0 inventory 補所有 R01–R18 剩餘項；不複製假刪除成功 UI。
  - 消費端：admin、gallery、router/enhancer/collector、metrics、API auth；`rg -n 'admin|gallery|route|enhance|collect|metric|quota' <repo-absolute-path>`。
  - 不能動：管理員權限不可由 client payload 指定；素材不得無條件 fetch 任意 URL。
  - 驗收：`make check`/`make e2e-fixture`；一般帳號不能修改精選與使用者角色；路由不同複雜度 fixture；自備素材可進入產物且保留來源；quota 超限不啟動 run；移除 admin/quota guard 時測試轉紅。
  - 停止：盤點有遺漏未分類；不得以功能名稱相同代替行為驗收。

- [ ] **P7. 收尾與作品集證據**（被擋於：P0–P6）
  - 範圍：逐項完成定義、獨立 code/design review、長期契約檢查接 CI、操作/故障/部署文件與展示；延後項留本計畫附觸發條件，不另建進度表。
  - 消費端：全部 `rg --files <repo-absolute-path>` 對照 coverage 與 P0 inventory。
  - 驗收：`make check`/`make e2e-fixture` + 已授權 live/deploy suites；所有 R ID 可追到實作與測試；在 fixture 去掉 API persistence/跨 owner guard/事件去重時 gate 失敗；review 每項有處置與證據。沒有遠端驗收就不能宣稱發布完成。

`<repo-absolute-path>` 固定為 `/Users/will/second-brain/.projects/personal/fullstack-app-forge`；此佔位只是表內短寫，逐步 implementation plan 寫完整命令。P0 先把下一步驗收指令與 test IDs 具體化。

## 決定

- **D1 生成範圍**（已決 2026-10-01，Will：A；解除此題對 P1/P2/P6 的阻擋；ADR：本機專案決策紀錄 2026-10-01-fixed-template-local-runner）
  - A 固定 Next.js + FastAPI + PostgreSQL 模板、多頁 CRUD：便於量測與完整驗收，但依賴自由度較低（建議）。
  - B 任意套件與第三方整合：自由度高，需額外 credentials/依賴/網路政策，成本與成功率較難控制。
- **D2 runner 與使用者邊界**（已決 2026-10-01，Will：A；解除此題對 P1/P5 的阻擋；ADR：本機專案決策紀錄 2026-10-01-fixed-template-local-runner）
  - A 本機受控 Docker 預覽，公開作品集展示案例：便於起步，不開放匿名生成；公開執行另做 sandbox 評估（建議）。
  - B 第一版使用託管 sandbox：隔離產品化較早，增加帳號/費用/限制依賴。
- **D3 真模型與預算**（未決；P0/P1 後交 Will；擋 P2/live tests）
  - A 先單一 provider/model + 每 run 與總額硬上限：可比較，品質上限受單模型影響（建議）。
  - B 多模型路由：可能改善品質/費用，增加契約與變因。
  - 需 spike 事實：可用官方契約/費率與最小任務 token 估算；不得讀/輸出本機 credentials。金額與 provider 要由 Will 確認。
- **D4 persistence、queue 與 schema 政策**（agent依Will完整實作委託採A；2026-10-01；不表示Will逐項選過A）
  - A 平台PostgreSQL durable runs/events、自管DB-backed leases/queue、generated app DB分離：少一種中介服務，需自管recovery/fencing；依既有spike採用，產品DB行為另實測。
  - B 平台 PostgreSQL + Procrastinate：worker lifecycle成熟，仍需domain fencing、明確stalled recovery與框架schema維護（候選）。
  - C 平台 PostgreSQL + Redis/Celery worker queue：生態成熟，增加運維與跨儲存一致性（候選）。
  - 採同app一個active run、事件7天/終態snapshot長存、最多2attempt、預設拒絕破壞性schema；來源比較與API語意見`p0-contracts.md`，實際實作與測試收口後用decision-log記ADR。
  - generated app DB 已由 D1 選 PostgreSQL；D4 不重開此題，只選平台 persistence/queue 與 schema 政策。
  - 需 spike：崩潰重啟、重送與隔離驗證；比較既有 worker framework 與自己維護 lease 的成本，拍板時凍結 auth/session、事件保留與破壞性 schema 操作契約。
- **D5 發布目標**（未決；P5 spike 後交 Will；擋遠端發布）
  - A 單一受控 host 全端發布：部署一致，需自行維運與隔離（候選）。
  - B 分離 frontend/API/DB 託管：維運較少，增加服務帳號、費用與跨 provider 設定（候選）。
  - 需 spike：全端 URL/TLS、每 app DB 隔離、保留/備份/停用與預算；未選前只跑本機 adapter。

拍板順序：D1/D2 已決且 ADR 落地；D4 在 P0 證據後；D3 在 P1 可跑 fixture 後；D5 在 P5 spike 後。與需求不衝突且不改 scope/契約的工具鏈細節由實作者決定。D1/D2 決策紀錄見本機專案脈絡；後續決定另依 decision-log 記錄。

## 進度

| 步驟 | 狀態 | 已跑的驗收 | 未跑的驗收與原因 | commit |
|---|---|---|---|---|
| 文件初始化 | 完成 | 路徑 metadata、18 項需求對應/本機 Markdown targets、lint-rules/check-links；獨立審查 V01/V02 修正，D1/D2 ADR 83 行 | reference 完整盤點及產品執行留待 P0–P7；本列只指文件初始化 | 無 |
| P0a | 完成 | pinned inventory/consumer 去向、16 項 PG/Docker primitive spike、cleanup；verify_plan 與 mutation | 不包含产品 runtime、DB role isolation、持久化 disk cap | 無 |
| P0b1 | 完成 | DB CRUD擴充後10項role/predicate重驗與cleanup；契約結構gate與9 tests、quota cleanup3 mock tests；review三項已修並獨立確認 | API/worker/完整JSON Schema conformance不在本子步驟驗收；D4未決未凍結 | 無 |
| P0b2 | primitive 完成 | loop 第三輪 8 checks/exact gate 通過；DB ENOSPC 196,259,840 bytes、artifact 236,605,440 bytes；normal remount/remap、PG marker42、cleanup 全 true與 owned Docker absence；7 safety/10 gate/49附件tests及 unsafe mutations | 產品 2GiB/4GiB、真 SQL/WAL 與 host/daemon reboot 不在此 primitive 驗收 | 無 |
| P0b3 | 進行中 | D4採A與保守政策；平台API/DB測試已執行 | 完整OpenAPI與event retention/cursor生命周期未凍結 | 無 |
| P1a | 平台核心驗收已取得，契約收口中 | 24後端tests含migrations、Ruff/TS/Next build、兩viewport shell；真browser/API/PG round-trip 1test過（第4輪180秒）；Git/CI/actionlint、make check-unit/41附件tests；fresh proxy review無finding | CI未遠端執行；平台契約與event cursor生命周期後續收口；P1b/generated-app E2E尚無 | 無 |
| P1b | resource foundation 完成，template 準備中 | P0b2 full primitive；21 store＋12 security tests、49附件tests、epoch mutation、fresh design 2項改後閉合及correctness無finding | Docker adapter/settlement、template build、worker、實際 profile 與 generated CRUD/restart E2E 尚未完成 | 無 |
| P2–P7 | 未開始 | 無 | 相依步驟及外部配置未完成 | 無 |
