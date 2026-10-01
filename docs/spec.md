# 產品規格

## 已確認目標

Will 於 2026-10-01 指定：學習兼作品集；完整重做 yu-ai-code-mother 的產品能力；平台與生成應用均使用 Next.js + FastAPI；個人 monorepo `fullstack-app-forge`。

這是獨立新系統，不搬移原專案資料或部署。不是學生範例或 reference clone；成果是可展示的個人產品。完整功能分階段完成，不以第一個切片宣稱完成全產品。

Will 同日確認：先固定 Next.js + FastAPI + PostgreSQL 全端模板，之後擴充；先本機受控 Docker 預覽，公開作品集展示案例，不開放匿名生成。平台 persistence/queue 已由 agent 依完整實作委託及 P0 比較採 PostgreSQL durable runs/events 與 DB leases。

## 完整功能基準

- 帳號、登入、使用者與管理員權限。
- 我的應用、應用資訊修改與刪除、精選案例與管理後台。
- 需求解析、生成策略路由、工具寫檔、串流文字及工具進度。
- Next.js 前端、FastAPI API、資料模型與可運行資料庫整合。
- 歷史對話、對話修改、檔案瀏覽、版本與回復。
- 前端/API/資料庫聯動預覽；選取頁面元素後用 AI 修改。
- Build、受限修正循環、封面截圖、原始碼下載、部署分享。
- 任務取消、故障恢復、權限隔離、限流、成本與執行監控。

原專案 HTML/MULTI_FILE/VUE_PROJECT 三種輸出改為全端 Next.js + FastAPI 目標；保留策略路由的產品能力，但具體策略集合在 D1 後定義。微服務拓撲與 Java design patterns 不作功能對等要求。

## 設計提案

以下是待驗證設計，不表示使用者已拍板所有實作取捨。

```text
Browser → Next.js platform UI → FastAPI control API → platform database
                                      ↓
                             durable runs + worker
                                      ↓
                           runner controller boundary
                                      ↓
                 generated Next.js + generated FastAPI + app database
```

- API 處理授權與任務狀態；worker 處理生成與檢查；runner controller 處理程序生命週期。不要求拆成獨立產品微服務。
- 工具鏈：TypeScript、Python 3.12、pnpm、uv、pytest、Playwright；實際版本固定於 manifests 與 lockfiles。平台 build、API/DB 測試已執行，generated runtime 尚未驗收。
- D4 採單一 PostgreSQL durable queue、lease/epoch fencing；同 app 一個 active run，最多兩次 attempt，事件保留七天而 terminal snapshot 長存。generated app DB 與平台 DB 分離，破壞性 schema 修改預設拒絕。
- 模型 adapter、工具契約與工作流解耦；先單一 provider，不預先引入多 agent 或 LangGraph。是否需要 graph 以分支與恢復需求判定。

## 預計契約

P0 產出可機械檢查的 OpenAPI 與事件 schema，以下只規定語意，不凍結 wire names。

- `create run` 是有副作用的 POST；同一 app/base revision 的重送有 idempotency key。GET events 不啟動生成。
- Run 包含 owner、app、base revision、attempt、狀態、停止原因、budget 與 artifact revision；狀態持久化是 SSOT，SSE 是可重播的通知。
- 事件包含 run ID、sequence、schema version、類型與 payload；文字 delta 與 final snapshot 明確區分。heartbeat 不形成業務事件。
- 訂閱断線不取消 run；取消透過獨立授權操作，終態禁止晚到的 worker 寫回成功。
- 同一 app 的修改以 base revision 做衝突檢查；不同 app 可獨立執行。
- 檔案變更進入新的 workspace/revision，成功檢查後才提升為可預覽版本；失敗保留可診斷結果，不覆蓋上個可用版本。
- 預覽 URL 包含 app 與 revision，獨立 origin；generated API 僅存取該 app 的 DB。平台 session 不流入生成應用。
- DOM 選取使用 template instrumentation 的穩定 component ID + revision，解析至允許修改的 source 範圍；不能直接相信任意網頁送來的路徑。訊息校驗 origin、source、schema 與 revision。
- 部署以 artifact revision 為單位，回報前端、API、資料庫/migration 與 health 狀態；DB schema 回復不能等同原始碼回復。

## 核心不變量

1. 未授權者不能讀取、修改、訂閱或下載他人的私有 app/run/artifact。
2. 平台管理資料與 generated app 資料不共用權限；generated code 無平台 credentials 或 host filesystem 存取。
3. tool paths 正規化並檢查 workspace containment，包括 absolute path、`..` 與 symlink；不得提供 unrestricted shell tool。
4. `succeeded` 必須有指定 revision 的檔案、build 與 health/behavior 證據；保存、build、API 啟動失敗均傳回失敗。
5. 重播/重送不重複執行副作用；取消、timeout 與 lease 過期後不能提交過時結果。
6. 模型文字、工具結果、編譯結果與 runtime 結果分開保存；不保存模型私有推理或輸出 secrets。

## 第一個真實切片

使用者要求「待辦清單」→ 生成 Next.js UI、FastAPI CRUD 與 DB model → build 與啟動 → 在預覽新增/查詢資料 → 重啟 generated API 後資料仍在 → 對話新增一個欄位 → migration 後原資料仍可讀。

P1 的 deterministic fixture 只證明接線；P2 的真模型 smoke 才證明模型整合，不能互相冒充。

## 非功能需求

| 項目 | 初始驗收 | 後續決策 |
|---|---|---|
| 隔離 | traversal、跨 app DB、未授權訂閱、越權 tool 均拒絕 | 公開生成前 runner threat model 必須通過 |
| 恢復 | 重整頁面重播事件，不新建 run；worker restart 有確定終態或恢復 | 事件保留期限於 P0 決定 |
| 資源 | 每次 run 有工具次數、修正次數、時間與 token 上限 | 真模型費用由 D3 決定；P0 定 runner 本機有限 CPU/RAM/disk/執行時間 profile，P1 驗超限終止 |
| 正確性 | fixture E2E 全過；真模型產物實際通過 build/API/CRUD | P2 spike 後定成功率與延遲目標 |
| 可觀測 | run/attempt/revision 可追蹤；未知費用標未知 | 不預先假定付費 dashboard |

## 待拍板

詳階段計畫 D3（真模型 provider/budget）與 D5（遠端發布）。未配置付費服務及遠端 host 時，只執行可獨立驗證的本機功能；不得虛構 live 或部署結果。D1/D2 已由 Will 確認，D4 由 agent 依完整實作委託採用。Will 暫不指定季度目標，不修改 goals。
