# 完整重做續作

先讀 `AGENTS.md`、`docs/spec.md`、主計畫 `docs/plans/2026-10-01-full-rebuild.md` 及附件 `review.md`。Will 已委託完成全部功能，必要目錄／下載／本機隔離操作不再逐批請權限；不讀／輸出 secrets、不動無關專案、不自行付費／開帳號或 commit。

## 已有產品與證據

- Next.js 工作室與 FastAPI auth/apps/runs/events、PostgreSQL durable queue 核心；manifests/lockfiles、Makefile check-unit/check-db/check-web/check-browser/check 已存在。獨立Git已init main，沒有commit/remote；CI/actionlint已建但未遠端執行。沒有實際worker、generated template、preview runner、模型、visual editor、分享／部署或完整admin。P1a仍待收口，P1b被硬quota證據擋住。
- 24 backend tests含兩項migration通過：`p1a-store-tests-tcp.log`有12store tests，security12；Ruff／TypeScript／runtime proxy Next build、1440/390 browser shell通過。make check-unit的Ruff/12security/41附件tests通過。舊migration setup failure原件保持，不再代表最新補驗狀態。
- PG image改可攜index digest，make prepare-db及CI先準備；readiness走實際host TCP SELECT1，避免initdb暫時Unix server假ready。真browser round-trip第1輪driver API誤用已修；第2/3輪120秒PG readiness失敗，第三輪log證明暫時server於約116秒才啟動、正式TCP未起且無OOM。fixture startup改有界240秒，產品deadline不變；第4輪1test通過180.21秒，owned API/web/browser groups與PG finally cleanup無error。`p1a-browser-flow.json/png`及attempt4.log證明註冊/app CRUD/queued SSE/cancel/reload/owner404/413/logout-login。截圖已視覺檢視。沒有active browser job；不再重跑舊failure。proxy runtime URL、64KiB、Set-Cookie/SSE均由此路徑驗。
- 首次平台 DB 由 API startup migrations 修改，勿使用 default localhost5432 接任何既有 DB。需獨立 test DB；fixtures 使用 UUID owned container，無真 credentials。不要讀 .env／process argv。

## 前提與決策

D1/D2 Will 已選固定 Next.js + FastAPI + PostgreSQL 模板、本機受控 Docker、公開案例展示，不開放匿名生成。D4 agent 依完整實作委託採 PostgreSQL durable state、自管 bounded lease queue；兩份 fresh ADR drafts已比較，理由與 alternatives落本機專案決策紀錄，不代表 Will 逐項選 A。D3 真模型 provider/budget、D5 實際遠端 host 未配置；不能用 fixture 代替 live/deploy。考慮免費本機模型可另做可行性量測，目前 command -v ollama 無結果、沒有模型。

design-review core2 findings已分流並独立回查：tombstone/7天保留/purge，P1b首次持久化資源前接reconciler，P5首次部署前cleanup；schema bootstrap改有序migration，兩項補測已通過。fresh runtime proxy/CI reviewer NO DESIGN FINDINGS；loop controller privilege finding補明確profile後原reviewer確認可關閉。四欄沿用表、review ledger已有證據邊界。

## quota 證據與下一步

HFSX raw failure保持（ENOSPC與乾淨PG restart過，normal detach busy、remount未驗）；兩輪owned cleanup完成。Linux前兩輪深路徑socket過長，第三輪短 `/private/tmp/fq-*` VM啟動1260秒逾時、SSH拒絕連線，未進quota checks。`p0-linux-quota-results.json` 不改，補做 `p0-linux-quota-cleanup.json` 記 VM/disks/tmp 全true；目前沒有該VM或磁碟。P0 exact gate 9tests不是實測通過。

Lima boot參數假設未證實；因host資源飽和，新增候選Docker existing Linux＋固定ext4 image／local driver。`p0-loop-quota-proposal.md`明列trusted controller的drop ALL＋SYS_ADMIN/MKNOD、loop-control/major7 minors0–31，禁止privileged/hostPID/nsenter/socket/hostmount，失敗不擴權。tools image `sha256:35175b730c0fb88c24d2dcbd5869cee7d8cb8913638f2ec1fdb338e10dd117dd`已build；核對Alpine3.24.2後只官方APK，不用APT。controller能操作其他loops，owned核對是程式邊界，不假稱OS只有owned device權限。

loop首輪raw `p0-loop-quota-results.json`保持DB writer120秒timeout與cleanup全true。16MiB diagnostic總3.54秒、128MiB總22.61秒，皆cleanup全true；觸及memory max計數不是OOM／root cause。full attempt2獨立 `p0-loop-quota-attempt2.json`取得5checks：兩FS、DB ENOSPC196,259,840 bytes／21.26秒、scope isolation、PG restart marker42。artifact writer非零退出，當時helper未保存exit/State，不能猜OOM；remount/remap未進。cleanup四項全true、spike-id 8c843883a642查container/volume皆空。

新correctness R01/R02已修且獨立回查閉合：mutating Docker timeout／未知nonzero記uncertain，cleanup保留資源；gate拒unknown even clean flags；own raw file device＝mount device、mountinfo major/minor＝losetup BACK-MAJ:MIN，再比inode/size，detach比完整attachment。7 safety＋10 gate tests過、退回unsafe兩項mutations轉紅；make check-unit的49附件tests過。新helper非零writer取exit/State/stdout/stderr。

128MiB writer單獨artifact fill失敗：120秒時running／OOMKilled=false，80MiB耗81秒且memory max164，已清理。512MiB對照 `p0-loop-artifact-fill-512m-diagnostic.json`通過：236,609,536 bytes／37.62秒ENOSPC，最後memory max/oom皆0，HostConfig Memory/Swap536,870,912、CPU0.5/pids32/readonly/none/capdropALL讀回符合，cleanup全true。支持reclaim-pressure假設，不宣稱正式benchmark根因；只writer/reader cap改，controller128／PG256／disk256保持。

fresh full attempt3 已完成（writer512＋新 ownership/uncertain guard）：`p0-loop-quota-attempt3.json` 全 8 checks 與 exact gate 通過。DB ENOSPC 196,259,840 bytes／15.09秒，artifact 236,605,440 bytes／22.19秒；normal remount/controller remap 保持 filesystem UUID 與 PG marker42。cleanup 四項全 true、remaining loops/pending attach/uncertain mutations 皆空；`docker ps -a --filter name=forge-loop-68bde5c1ce34` 與同 prefix volume ls 皆空。解除 P0b2 primitive blocker，未驗 host/daemon reboot；P1 實際 2GiB/4GiB profile 另驗。不要覆寫舊 failure 或重開已通過的 primitive。

接續 P1b：先建立 durable resource journal/reconciler，再接 template/worker/profile，驗 generated Next.js→FastAPI CRUD→DB→restart persistence。P1 另驗實際 2GiB DB/4GiB artifact 與真 SQL/WAL 滿盤；256MiB primitive 不代替產品驗收。P1a browser 已通過，完整 API/event retention/cursor lifecycle 仍待收口；CI 未遠端跑。完整功能 P2–P7 仍未完成。

主目標保持 active，完整功能尚未達成；已落daily／專案摘要／D4 ADR，不需要再次詢問是否繼續。

## P1b resource foundation

新增 `p1b-runner.md` implementation plan、migration002 resources、`forge/resources.py` intent store/reconciler、`RunStore.finish` atomic resource adoption。run/preview/app/revision retention 分開；tombstone 立即要求停止 runtime、已 adoption 資料保留七天。unknown 不重送 mutation，trusted adapter acknowledgement 必須另證 settled operation 與 owned identity；unresolved diagnostics 沒有環境／credential／任意 logs。

fresh design reviewer 2 findings（P1B-D01/D02）改後可設計關閉；fresh correctness review NO CORRECTNESS FINDINGS。最終21 store tests 62.86秒通過，12 security與49附件tests過；epoch mutation移除run epoch guard讓negative regression轉紅（65.11秒），mutation工具exit0代表正確拒絕unsafe variant。產品 Docker adapter 尚未實作，不能由 store tests 推定 runner 恢復通過。

已開始 `forge/templates.py` 與 `template_assets/`：TodoSpec固定title/description/theme、Next.js頁面/API proxy、FastAPI PostgreSQL CRUD與version1 schema；render只讀模板／產生文字，沒有在host執行generated code。13檔共75,094 bytes，Python AST parse通過；npm/uv locks來源核對僅官方registry/PyPI，不含URLcredentials/query。可信依賴 images build通過：web `sha256:64f6717b76771ccfe7d9b47947e40cdc7f924e7bd919b88037200cd58c62541d`，API `sha256:48eb8752b64fe4e108118b6bb726c5428c045aeea438ac854a21ec3365534f68`；固定Node24/Python3.12 index digest、nonroot1000、npm ignore-scripts及pip hash/binary enforcement。generated source build／CRUD／worker尚未接；依賴image成功不當generated E2E成功。所有build/test handles已終止，沒有待收job。

Will要求關閉session並commit/recording/decision-log；不再開工產品adapter。下次從 `p1b-runner.md` 第2項產品loop adapter/profile接續，將資源journal串入硬quota scopes，再用已備template與依賴images驗完整CRUD/restart。完整功能仍未達成。

closing template design review 1項P1B-T01已記四欄表：uv/pnpm平台工具不強套進固定模板image，Python uv.lock→frozen requirements export→pip hash/binary，Web package-lock→npm ci/ignore-scripts；依賴/base/architecture變動重建，首次runner使用核对template/image一致。其餘render/schema/proxy/dependency機制未有新finding。原始test/build logs包含工具輸出空白，保持字節原件；source diff whitespace檢查另跑，不改寫failure evidence。
