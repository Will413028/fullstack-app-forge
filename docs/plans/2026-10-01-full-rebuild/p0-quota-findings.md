# P0b2：持久化 quota 實測與 runner profile

2026-10-01。Will 回覆「好，繼續」，依前一輪已明列的操作執行 quota spike；只使用本次256MiB image與隔離cached-image容器，不改Docker設定、不接既有DB、不讀credentials。

## 執行狀態與入口

第一輪掛載成功，bind-mount上的PG initdb約13分20秒才ready；後續writer的60秒wait超時，未取得ENOSPC/restart/remount證據。原始結果保留於 `p0-quota-attempt1.json`，normal detach回Resource busy；ownership/mount-reference核對後清理，另存 `p0-quota-attempt1-cleanup.json`。

第二輪採native volume乾淨初始化/停止後複製seed，readiness/copy/writer各設300秒上限。掛載、writer真ENOSPC（212,860,928 bytes）、PG釋放filler後重啟讀marker三項通過；正常detach仍Resource busy，**第四項remount未跑，probe exit 1**。原始失敗保留於 `p0-quota-results.json`，gate應拒絕。全部owned容器移除後，另核對精確image/mount與所有container Mounts無引用，僅force detach這個disposable test image，刪除image與暫存目錄；另存 `p0-quota-attempt2-cleanup.json`（全部cleanup true）。補做清理不把原失敗變成通過，不代表正常產品生命週期可用。

本次不採用 HFSX adapter，不解鎖 runner 驗收，也不重跑同一 host 路徑。[獨立 Linux spike](p0-linux-quota-proposal.md) 已依完整實作委託執行，VM 啟動逾時，尚未驗 quota；owned 資源已清理。P1a 平台核心可獨立實作，P1b runner 仍需硬 quota 證據。

```bash
python3 /Users/will/second-brain/.projects/personal/fullstack-app-forge/docs/plans/2026-10-01-full-rebuild/p0_quota_spike.py --execute --output /Users/will/second-brain/.projects/personal/fullstack-app-forge/docs/plans/2026-10-01-full-rebuild/p0-quota-results.json
python3 /Users/will/second-brain/.projects/personal/fullstack-app-forge/docs/plans/2026-10-01-full-rebuild/verify_quota.py
```

[probe](p0_quota_spike.py)、[result gate](verify_quota.py)、[gate mutation tests](test_verify_quota.py)。Gate核對四個不同測項、真ENOSPC與cleanup；缺enforcement以重複項替代、仍掛載、寫入已到請求容量均拒絕。4項gate tests通過；3項cleanup mock tests覆蓋timeout仍掛載/未知狀態保留image，不能代替實際quota驗證。

## 候選方式與責任

原候選是macOS固定容量、case-sensitive journaled HFS+ disk image；本次只驗到容量enforcement與乾淨PG重啟，正常卸載未通過，不能作產品adapter預設。下一批提案改驗專用Linux guest本地filesystem；adapter仍須提供同等hard cap。掛載不是generated code的權限，只有trusted controller能create/mount/unmount受限filesystem。

| 可寫範圍 | 有限profile提案 | enforcement與失敗處置 |
|---|---|---|
| build workspace | 512MiB tmpfs；/tmp64MiB；rootfs read-only | cgroup2CPU/3GiB，swap不額外增加；ENOSPC→DISK_LIMIT，OOMKilled→MEMORY_LIMIT；不在host工作目錄build |
| generated frontend | 1CPU/512MiB，/tmp32MiB，rootfs read-only | runtime不可寫source；必要Next cache明確導向bounded tmpfs；memory/profile實際性能P1驗 |
| generated API | 0.5CPU/256MiB，/tmp16MiB，rootfs read-only | 只持該app DML credentials，uploads新增scope才配置quota volume |
| app PostgreSQL | 0.5CPU/256MiB；data2GiB bounded filesystem，/tmp16MiB、/var/run/postgresql8MiB | 只trustedPG映像掛DB data；generated程式僅走該DB runtime role；滿盤先停writes，平台記DISK_LIMIT；不刪user data |
| revision artifacts | 全部app共用4GiB bounded pool，包含候選/失敗/已提升版本 | trusted controller複製manifest允許檔；不能繞過pool寫host；滿池拒絕新run，不自動刪用戶資料 |
| container logs | 每container10MiB×2 files，有限container數 | controller設定Dockerlog rotation；events/錯誤摘要保存在平台DB，公開輸出先sanitization |
| 程序與時間 | 單機1active run、2active previews；每workload pids128；run15分鐘、build5分鐘 | controller/reconciler使用DB deadline/epoch與owned labels；CPU飽和節流到deadline，不假定會立刻error |

上表是P1起始配置，資源mechanism已由P0a較小值驗cgroup/ENOSPC/OOM/deadline，持久化mechanism要由本次結果驗。沒有跑full Next build或2GiB/4GiB容量測試；現有verify_quota只驗固定256MiB的PG primitive。P1另建立adapter profile gate，記錄每項受測scope（DB/artifact/scratch）、配置容量、mount身份、CPU/RAM/pids/deadline/log限制讀回與實際ENOSPC，然後跑CRUD/restart/resource-failure E2E。改錯容量或移除mount enforcement必須讓新gate轉紅；不能拿本次gate直接驗2GiB/4GiB配置。profile數字不足時回報量測並調整，不能移除cap。

## 生命周期與證據界線

- 開始run先核owner/budget/app-active/quota capacity，create owned candidate workspace；generated容器不掛platform資料、host目錄或Docker socket，build禁止任意網路安裝，依赖來自固定template image。
- `succeeded`只提升有build/health/CRUD證據的artifact與revision；lease/deadline/epoch/base guards仍在平台DB transaction，不因磁碟操作成功而跳過。
- 停preview保留app DB image與已提升artifact；取消/失敗清候選與owned processes，不能把測試結束時刪image的cleanup邏輯套到產品DB。app刪除/資料清理另依明確產品操作與授權。
- Controller啟動先reconcileDB、owned labels及image metadata；掛載未知/卸載失敗不刪image。不得force detach別人volume；沒有證據時記cleanup incomplete。
- 本spike先乾淨停止PG，再由獨立writer填滿filesystem，釋放filler後restart/remount讀marker；這驗volume enforcement與乾淨重啟持久化，不能宣稱PG活躍寫入ENOSPC時的crash recovery已驗。P1另測真SQL/WAL滿盤與failure/cleanup/late-success。
- 第二輪seed是本次cached PG17 image在獨立native volume建立的空DB，fsync保留；只有乾淨stop後才copy，不複製任何既有資料/credentials。PG marker與後續writes仍在bounded filesystem執行。這是原型啟動策略候選，P1若採用須驗seed版本/完整性/無credentials與warm/cold startup時間，不從prototype推定template seed已產品化。

## D4與剩餘事項

D4 queue A 與保守資料政策已由 agent 依完整實作委託採用，來源比較見 [D4材料](p0-contracts.md)。硬 quota profile 與完整產品 OpenAPI 仍未驗收；不可宣稱 P0/P1 完成。
