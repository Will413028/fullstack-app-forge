# 需求、來源與沿用盤點

## 來源與重查

查閱日期：2026-10-01。P0a 已將來源固定在 [revision 893918c](https://github.com/liyupi/yu-ai-code-mother/tree/893918c808ce7828cd4b9372967e064ed119bbaa)，結構盤點見 [p0-inventory.json](p0-inventory.json)，行為去向與證據邊界見 [p0-findings.md](p0-findings.md)。以下 S1–S7 master URLs 保留最初探索來源；驗收以固定 revision 同名檔案為準，不以變動中的 master 為 SSOT。未執行原碼，不宣稱完整安全 audit。

- S1：[README](https://github.com/liyupi/yu-ai-code-mother/blob/master/README.md)：生成、視覺編輯、部署分享與管理。
- S2：[AppController](https://github.com/liyupi/yu-ai-code-mother/blob/master/src/main/java/com/yupi/yuaicodemother/controller/AppController.java)：生成 stream、部署、下載、應用 CRUD、我的列表、精選與 admin endpoints。
- S3：[UserController](https://github.com/liyupi/yu-ai-code-mother/blob/master/src/main/java/com/yupi/yuaicodemother/controller/UserController.java)：帳號功能；細部尚待 P0 inventory。
- S4：[AiCodeGeneratorFacade](https://github.com/liyupi/yu-ai-code-mother/blob/master/src/main/java/com/yupi/yuaicodemother/core/AiCodeGeneratorFacade.java)：生成模式、tool stream、保存與 build。
- S5：[AiCodeGeneratorServiceFactory](https://github.com/liyupi/yu-ai-code-mother/blob/master/src/main/java/com/yupi/yuaicodemother/ai/AiCodeGeneratorServiceFactory.java)：Caffeine service cache、Redis memory、DB history、tool 次數限制。
- S6：[CodeGenWorkflow](https://github.com/liyupi/yu-ai-code-mother/blob/master/src/main/java/com/yupi/yuaicodemother/langgraph4j/CodeGenWorkflow.java)：素材、prompt、路由、生成、品質檢查與 build。
- S7：[FileWriteTool](https://github.com/liyupi/yu-ai-code-mother/blob/master/src/main/java/com/yupi/yuaicodemother/ai/tools/FileWriteTool.java)、[VueProjectBuilder](https://github.com/liyupi/yu-ai-code-mother/blob/master/src/main/java/com/yupi/yuaicodemother/core/builder/VueProjectBuilder.java)：寫檔與執行邊界。
- U1：本次對話，Will 指定完整重做、Next.js + FastAPI、學習兼作品集與 personal 路徑，並同意專案名稱/文件目錄。

重查方式：執行 findings 內的 absolute-path inventory 命令；腳本先核對固定 HEAD 再抽取，拒絕不同 revision。來源不含 application config、.env 或 connection notes。

## 需求對應

| ID | 分類與需求 | 來源 | 去向 | 驗收階段 |
|---|---|---|---|---|
| R01 | 畫面/API：帳號、登入、權限、使用者管理 | S3/U1 | FastAPI auth + Next.js UI | P1/P6 |
| R02 | 畫面/API：應用建立/修改/刪除/我的列表 | S2 | 重寫並驗 owner boundaries | P1/P6 |
| R03 | 流程：需求分析、路由與生成 | S1/S6/U1 | 改成全端模板策略；D1 定 scope | P2/P6 |
| R04 | 流程/API：工具寫檔與串流事件 | S4/S7 | constrained tools + durable events | P1/P2 |
| R05 | 實體：對話歷史與生成 context | S5 | DB history + revision context；admin history filters 在 R13；不照搬實例 cache | P3/P6 |
| R06 | 流程：對話修改 | S1/U1 | revision patch + migration 檢查 | P3 |
| R07 | 畫面/流程：視覺化選取與修改 | S1 | DOM/component/source 對應 | P4 |
| R08 | 流程：build 與品質修正 | S4/S6 | 編譯/測試/health 的 bounded loop | P2/P3 |
| R09 | 流程：即時預覽 | S1/U1 | frontend + API + app DB | P1/P2 |
| R10 | API/流程：部署分享 | S2/U1 | 全端 revision deployment | P5 |
| R11 | 畫面/流程：封面截圖 | S1 | 受限 browser screenshot | P5 |
| R12 | API：原始碼下載 | S2 | app/revision 授權 ZIP；排除 credentials | P5 |
| R13 | 畫面/API：精選案例與 admin 管理 | S2 | 展示列表、精選、角色驗證 | P6 |
| R14 | 實體/流程：任務與成本監控、限流 | S1/S2/U1 | run trace、quota、metrics | P2/P6 |
| R15 | 實體/API：FastAPI model 與持久化 DB | U1 | 新能力；DB isolation/migrations | P1/P3/P5 |
| R16 | 流程：檔案版本、取消與恢復 | 推論：完整修改與长任務可靠性 | D4 後凍結 persistence 語意 | P1/P3 |
| R17 | 流程：素材收集與 prompt 增強 | S6 | 授權素材或受限 fetch；不自動接付費搜尋 | P6 |
| R18 | 畫面/API：檔案瀏覽 | U1/spec 完整功能基準 | app/revision 檔案樹、內容讀取與 source diff；owner/path 權限 | P3 |

## 沿用重新評估

| 原機制 | 原目的 | 今日條件/替代方案 | 處置與重評條件 |
|---|---|---|---|
| Java/Spring/Vue | reference 技術棧 | U1 已選 Next.js/FastAPI | 重寫；不搬 Java adapter |
| HTML/MULTI_FILE/VUE_PROJECT | 不同複雜度輸出 | U1 要求完整全端 | 改為全端策略；D1 定固定/自由範圍 |
| Caffeine AI service cache | 避免反覆建立 service | 是否昂貴尚無量測 | 不先建；只有 profiling 顯示瓶頸才重評 |
| Redis chat memory + DB history | 對話 context | durable revision/history 可從 DB 組裝 | 重写；D4 決定持久化，cache 僅在量測後加 |
| LangGraph4j | 顯式工作流分支 | Python 可用 state machine 或 graph | 先明確狀態契約；P0 比較恢復需求後選实现 |
| 微服務/Dubbo | 教學與服務拆分 | 個人作品集無已知團隊/流量拆分需求 | 不照搬；獨立擴展/故障域需求出現才重評 |
| 靜態發布 | 網頁生成 | 全端有 API、DB、migration | 重寫成全端部署契約，不假定 static export 足夠 |
| 直接 host build/write | 快速教學實作 | generated code 為不可信輸入 | runner boundary；D2 決定執行方式 |
| App logical delete（App.java `isLogicDelete=true`） | 原controller透過ORM removeById；當初保留理由未由盤點證明 | 新系統有app DB/artifact/deployment實體資源，需要刪除意圖與cleanup分離 | 保留tombstone；刪除即拒絕新任務/分享，P1b首次持久化資源前接reconciler停owned runtime並保存資料7天再owned purge；P5首次部署前接share/deployment停止，失敗可重試不假成功 |
| 平台schema bootstrap（本次新機制） | 空白DB建立v1，不搬reference資料 | 既有平台資料後續需可升級，不能以重跑IF NOT EXISTS判定migration成功 | 改成有序純SQL migrations，同transaction成功後記版本，拒絕版本gap或DB比runtime新；首次平台schema變更新增序號migration，不能改已套用檔案 |
| 固定大小ext4 loop image（本次spike） | 對持久化DB/artifact提供filesystem硬上限 | 獨立VM多一個記憶體生命週期；Docker local driver可管理mount，但controller仍有跨loop權限 | 只採候選spike，controller trusted且有限capabilities；失敗不擴權；P0 quota/remount/remap及P1完整profile均通過後才採產品adapter，公開不可信生成前重新評估故障域 |
| Runtime API proxy（本次新機制） | 同origin保持session/CSRF並串流SSE | build-time rewrites凍結API URL，無法共用build於不同runtime；Next Route Handler可request時讀環境 | 採runtime trusted API target、header allowlist、64KiB body cap與Web Stream，不另存事件／身份；新增大檔上传或跨origin部署時重評契約 |
| Makefile/CI共同驗收入口（本次新機制） | 可重跑unit/DB/web/browser流程 | 本機cached config ID不具跨architecture可攜性，CI需要依賴準備 | 固定PG index digest、prepare-db與Playwright runtime，CI呼叫相同make check；首次remote CI結果獨立記錄，不以actionlint代替CI green |

## 已見缺陷與處置建議

| ID | 原碼證據 | 建議處置 | 必須能失敗的驗收 |
|---|---|---|---|
| F01 | S4 processCodeStream 保存例外只記 log | 修：保存失敗不得 succeeded | 注入 disk failure；恢復 swallow 行為測試轉紅 |
| F02 | S4 忽略 builder boolean | 修：build success 與 health 都納入终態 | build 返回失敗；忽略結果時測試轉紅 |
| F03 | S7 writeFile absolute path/containment 未限於 method | 修：path/symlink containment | absolute/../symlink escape fixture；移除 guard 轉紅 |
| F04 | S7 host npm 執行 | 修：不可信程式與平台分離 | generated process 讀平台/host sentinel 被拒；移除 boundary 轉紅 |
| F05 | S6 failed quality edge 未在 graph 顯式計次 | 修：應用層 budget；不推定框架無上限 | 永遠失敗的 checker 在上限停止；移除 budget 轉紅 |
| F06 | fixed revision ChatManagePage 的 delete handler 只提示成功/reload；30 種 endpoint 無 history delete | 修：不展示假成功；保留真實查詢/filter 能力，不擅增 history-delete 契約 | P6 UI 不含無 API 的成功刪除操作；恢復原假成功 handler 時測試轉紅 |

這些是特定讀到方法的證據，不宣稱整個 reference 沒有其他保護。建議處置與新成功/失敗契約一併在 P0 審查。

## 外部介面與證據邊界

- [Next.js deployment](https://nextjs.org/docs/app/getting-started/deploying)：Node/Docker 可作全端 runtime；static export 不支援所有 server 功能。實際版本與打包方式 P0 再核對。
- [FastAPI Background Tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/)：重工作可使用跨 process 的 worker 工具；不據此假定某特定 queue 已選。
- [Docker security](https://docs.docker.com/engine/security/)：容器/daemon 邊界需額外配置，不把一般容器當成可公開執行任意程式的完整 sandbox。
- LLM provider/model、定價、token 限制、帳號與付款：未選，D3；不接真 provider 前先官方查證。
- 遠端 runner、物件儲存、DNS/TLS 與平台 host：未選，D2/P5 spike；不從教學使用 COS 推定本產品也用 COS。

查詢日期皆為 2026-10-01；實作前重查官方文件並留下實際版本。費率沒有取得，沒有估算為零。

## 產品風險

目標是學習與作品集，不以付費市場驗證阻擋技術切片。是否有人願意使用、自由需求成功率與部署總成本尚無證據；P2/P5 用案例與量測回答，不宣稱商業可行。
