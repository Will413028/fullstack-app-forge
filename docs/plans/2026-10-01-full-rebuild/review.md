# 初始化計畫與設計審查

2026-10-01，由未參與撰寫的唯讀 subagent 審查 spec、plan、requirements 與 AGENTS。沒有程式碼；本報告不能代表 reference 全庫 audit 或產品驗收。

## 累積 finding ledger

| ID | 類型 | 發現 | 處置 | 證據 |
|---|---|---|---|---|
| V01 | 計畫，中 | spec 檔案瀏覽未進需求 coverage | 已修 | 新增 R18；P3 加 revision file tree/content、owner/path 拒絕與 mutation |
| V02 | 計畫，中；設計 C，高信心 | runtime CPU/RAM/disk 上限誤指已決 D2，沒有產出責任 | 已修 | P0 產出 finite profile/enforcement；P1 注入飽和/OOM/disk/timeout、cleanup、late-commit 測試；spec 指向 P0/P1 |
| P0A-R01 | 腳本，中 | cleanup 失敗只印 false 仍 exit 0 | 已修 | 保存全部 cleanup 結果後，任何 removed=false 都 raise；本次重跑 cleanup 全 true |
| P0A-R02 | gate，中 | 16 checks 只驗數量，可用重複項掩蓋缺項 | 已修 | 固定 expected names + exact count；等量替換 OOM 為重複項 mutation 必須失敗 |
| P0B-R01 | quota腳本，高 | 第二次attach timeout可能仍掛載卻刪image；cleanup例外可能丟失結果 | 已修 | 每次attach前記待卸載；cleanup核對hdiutil metadata，未知/失敗時保留files且保存results；3個mock tests含仍掛載/未知/正常清理 |
| P0B-R02 | 契約，中 | 初始queued事件與attempt>=1不一致 | 已修 | 新增run.queued/attempt0、queued取消與deadline終態語意；Event envelope接受0，其他事件依kind限制；gate驗queued0 |
| P0B-R03 | 契約，中 | Event kind與payload/terminal status可矛盾 | 已修 | allOf分支綁kind/payload.type/terminal.status；成功artifact非null；缺correlation及nullable artifact mutations轉紅 |
| P0Q-R01 | 計畫，中 | 固定256MiB primitive gate不能直接驗P1 2GiB DB/4GiB artifact配置 | 已修 | P1另建adapter profile gate，含scope/capacity/mount身份、限制讀回、真SQL/WAL及artifact ENOSPC與容量/enforcement mutation；P0 gate保持自身範圍 |
| P0L-R01 | Linux提案，中 | 新下載來源與安裝方式需猜 | 已修 | 固定Ubuntu URL/digest、官方signed APT與套件/dependencies範圍、禁止installer/repository fallback；獨立回查確認 |
| P0L-R02 | Linux提案，中 | probe/gate入口與永久結果位置未指定 | 已修 | 補待建立腳本/命令、exact測項/mutation、結果在暫存目錄外、保存failure/cleanup後nonzero；獨立回查確認 |
| P1A-D01 | 設計A，高信心 | soft-delete沿用未定外部資源生命週期 | 記 | requirements補tombstone/7天保留/owned purge；P1b首次持久化資源前接reconciler，P5首次部署前share/deployment清理；相關實作未完成前不能驗收P1b/P5 |
| P1A-D02 | 設計C，高信心 | 重跑bootstrap DDL不代表可升級schema | 改 | db.py改有序純SQL migrations，成功transaction才記版本，拒絕version gap或DB新於runtime、失敗關pool；改由host TCP SQL readiness後12項store tests含兩項migration通過，原timeout材料保留 |
| P0LOOP-D01 | 設計C，高信心 | loop controller所需特權未明定，共用VM故障域不同 | 改 | 提案及spike明列drop ALL＋SYS_ADMIN/MKNOD、loop-control及block major7 minors0–31；禁止privileged/host PID/nsenter，失敗不擴權；owned核對是程式邊界；原reviewer唯讀回查確認可關閉，不代表quota實测通過 |
| P0LOOP-R01 | correctness，高 | Docker CLI mutation逾時不代表daemon端已停止，一次-j空不能排除晚到attach | 已修，獨立回查閉合 | timeout／未確認nonzero mutation記uncertain ledger，cleanup先拒絕保留；gate拒unknown even clean flags；late attach／nonzero run／readonly timeout regression；回到unsafe cleanup mutation測試轉紅 |
| P0LOOP-R02 | correctness，高 | inode跨filesystem可碰撞，ownership未核backing device | 已修，獨立回查閉合 | file device＝owned mount device＋mountinfo major/minor＝BACK-MAJ:MIN，再核inode/size；detach比完整原attachment；foreign collision拒detach/purge與positive tests過；回到inode-only mutation轉紅 |
| P1B-D01 | 設計C，高信心 | run cleanup 未分持久資料與 preview，promotion 沒有 resource adoption | 改，設計回查閉合 | p1b resource lifetime matrix、preview/run/app/revision retention；finish 同 transaction adoption；tombstone 立即停 runtime、資料保留七天；產品 adapter 尚待整合 |
| P1B-D02 | 設計C，高信心 | unknown 保留沒有 settlement 證據／處理出口 | 改，設計回查閉合 | 明列 mutation settlement evidence、quarantine/unresolved diagnostics與 trusted 維護邊界；不提供公開 force-success API、不定時重送；adapter 實際證據另驗 |
| P1B-T01 | 設計A，中信心 | trusted dependency images用pip/npm、lock/export/image同步未盤點 | 記 | p1b-runner四欄表採uv.lock→frozen export→pip hashes/binary與package-lock→npm ci/ignore-scripts；依賴/base/architecture變更重建，首次runner接入核對image依賴；未宣稱generated runtime已驗 |

修正只代表文件已更新；驗收仍待 P0/P1/P3 執行。沒有駁回項。

## 審查覆蓋

前提、消費端、驗收、依賴順序、不變量、決定、範圍/收尾與新系統部署/資料邊界均檢查。

沿用機制檢查包含 Java/Vue 替換、生成模式、service cache、chat memory/history、workflow graph、微服務、靜態發布、host build/write、lease/queue/transaction、cache invalidation、錯誤模型與外部呼叫。具體 ID/schema/index 尚未設計，留待相依實作審查，不作無問題宣稱。

P0a 新鮮唯讀 reviewer 核對8項計畫面向與腳本；確認 primitive 不冒充產品驗收，D4/persistent disk 仍阻擋 P1。兩项新 finding 已按上表修正；P0b contracts/schema/完整 profile 尚未審查。

P0b1 reviewer再核對三項修正，NO PLAN FINDINGS；重跑structural gate與9 contract tests通過，cleanup mocks只核讀，orchestrator本機重跑3 tests通過。quota實際掛載/完整profile不在已驗收範圍。

主 agent 指令檔對帳：README/AGENTS 所指 spec/plan 已存在；只宣稱文件，未虛構執行命令或部署。已有其他 session dirty files，不 commit、不 stage、不清除。

P0b2 profile修正與新Linux批次各獨立回查，NO PLAN FINDINGS（修正範圍）。HFSX raw failure保持，补清理另存全true。Linux批次已依完整實作委託執行，VM啟動逾時、owned cleanup另存全true；P0b2仍未完成。

P1a fresh reviewer覆蓋ID/schema/defaults/constraints、helpers、auth/session/CSRF、admin bootstrap、限流、queue/lease/transaction、idempotency、cache、SSE、paths與API helper；2 findings處置為改1／記1／提0／駁回0。回查 NO DESIGN FINDINGS（兩項修正範圍），不是migration integration通過。主agent對帳AGENTS所指spec/plan存在，更新過時README/spec/plan/handoff；AGENTS現行規則無需改。

Runtime proxy/CI的fresh唯讀design reviewer覆蓋target環境變數、same-origin cookie/CSRF、headers/body cap、SSE/cancel/cache、錯誤模型、standalone assets、共同Makefile入口及browser process生命週期：NO DESIGN FINDINGS。合理新機制補requirements四欄盤點；不是browser整合或遠端CI通過。P0LOOP-D01由原reviewer核對proposal及spike，確認可關閉；quota runtime驗收另記。
