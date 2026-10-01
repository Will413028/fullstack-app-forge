# P0b2：獨立 Linux quota spike（啟動失敗，已清理）

完整實作委託已授權必要下載、目錄及本機隔離操作，不再等待逐批確認。前兩輪 Unix socket 路徑過長；第三輪改短 `/private/tmp/fq-*`，VM start 逾時、SSH connection refused，尚未進 quota 測項。`p0-linux-quota-results.json` 保留 raw failure，`p0-linux-quota-cleanup.json` 另記 owned VM、兩磁碟、暫存檔全部已清理；不可合併成通過。下一輪先診斷 boot，不直接重跑 20 分鐘 quota job。

官方 Lima 2.2.0 `_images/ubuntu-lts.yaml` 有 `internal_netplanOptional: "true"`，註解指出 Ubuntu 26.04 NIC rename 會阻擋 boot 120 秒；自訂 YAML 漏了這個參數。這只是一個待驗證假設，未證明足以解釋本次 1260 秒逾時。2026-10-01 21:40 host metadata 顯示 load 62.34、15GiB memory used、113MiB unused；不在負載持續飽和時增加新 VM。

## 為何換驗證路徑

macOS 256MiB HFSX image已觀察ENOSPC（writer寫212,860,928 bytes）及PG marker重啟保留，但正常detach在容器移除後仍Resource busy；缺remount證據，原始失敗不可改成通過。先不採用這個adapter，也不重跑同一假設。

| 路徑 | 取捨與狀態 |
|---|---|
| macOS image經Docker Desktop bind | 不另建VM，但本次啟動延遲與正常卸載未通過；保留證據，不作產品預設 |
| 專用Linux VM內的固定block disk | 多一個VM與生命週期；filesystem在guest本地，可維持本機Docker方向；建議下一個spike，尚未驗證 |
| 託管sandbox | 另有帳號與費用；D2已選本機，本次不重開此題 |

2026-10-01本機metadata：`limactl --version`為2.2.0；執行前 instance metadata 回 No instance found。僅操作专用 `LIMA_HOME`，未查看既有設定或 keys。受測 VM 設定為 [p0-linux-quota.yaml](p0-linux-quota.yaml)。

## 授權操作批次

- 在短路徑 `/private/tmp/fq-*` 建立唯一暫存目錄，專用 `LIMA_HOME`，永久 evidence 存本附件；不得使用或修改既有 Lima/Colima instances。
- 使用已安裝Lima的VZ、aarch64，VM 2CPU/4GiB RAM/12GiB primary disk；不共享host目錄，無業務ports。為本VM自產SSH key，只交給Lima使用，不讀/印key內容，不使用既有credentials。
- 下載官方Ubuntu cloud image：`https://cloud-images.ubuntu.com/releases/resolute/release-20260720/ubuntu-26.04-server-cloudimg-arm64.img`，digest `sha256:7bcf159e29ad0000bfed9c57875908c39268f5ed1257f4958fa6a9f5f60edd54`（取自本機官方2.2.0模板，尚未下載或驗可用）；無fallback。Lima若需guest-agent，只允許已安裝版本相符的官方Lima release artifact。guest套件只用image內官方Ubuntu signed APT來源（arm64為`ports.ubuntu.com`），`apt-get update`及`apt-get install -y --no-install-recommends docker.io e2fsprogs util-linux python3`與必要dependencies；保存實際套件版本。guest新APT來源先核來源，非官方來源立即停止。來源或digest不可用就停止，不自行換repository/installer；不用`get.docker.com | sh`。
- 用兩個短名、唯一owned additional disks（各256MiB，ext4）分開DB與artifact scope。只在guest格式化這批新disk；不傳host `/dev/disk*`，不改host sudoers或Docker Desktop設定。
- 透過guest CLI使用專用rootful Docker，不切換host Docker context；既有cached PG17/Python3.12以owned暫存archive轉入guest，記錄原image ID與載入後ID；不下載reference或執行原碼。測試容器`network=none`、有限CPU/RAM/pids，無generated code/外部DB/業務資料。
- 收尾停止並刪除owned VM、owned additional disks與專用暫存目錄；先核metadata與停機狀態。失敗則保留不能安全清理的資源與結果，不force解鎖未知disk，不掃全域prune。

## 驗收與停止條件

授權後先建立附件內`p0_linux_quota_spike.py`、`verify_linux_quota.py`與`test_verify_linux_quota.py`，先跑gate mutation tests再執行。永久結果存附件的`p0-linux-quota-results.json`，在專用暫存目錄之外；全部raw failure/cleanup先保存，再依任一失敗回非零。Gate固定完整測項身份（DB/artifact mount與各scope ENOSPC、scope isolation、PG restart、guest remount、VM restart、cleanup），不沿用HFS四項gate。入口：

```bash
python3 /Users/will/second-brain/.projects/personal/fullstack-app-forge/docs/plans/2026-10-01-full-rebuild/p0_linux_quota_spike.py --execute --output /Users/will/second-brain/.projects/personal/fullstack-app-forge/docs/plans/2026-10-01-full-rebuild/p0-linux-quota-results.json
python3 /Users/will/second-brain/.projects/personal/fullstack-app-forge/docs/plans/2026-10-01-full-rebuild/verify_linux_quota.py
```

上列入口已建立並執行，VM 啟動失敗；exact gate 9 tests 通過，但實測未通過。`limactl validate` 回 OK 只代表設定有效；2個 additional disks 先建立再 start。建立到 cleanup 必須完成，未知狀態保存資源，不能刪證據。P0L-R01/R02 review 見 `review.md`。

1. 讀回兩scope的block device、filesystem UUID、容量與mount identity；Docker bind必須指向guest受限filesystem。
2. DB啟動/create marker/乾淨stop；獨立writer在DB disk回真ENOSPC，釋放filler後PG restart讀marker。artifact disk另觀察ENOSPC，並驗另一scope容量不受影響。
3. 全部容器停止/移除後正常unmount/remount，PG資料與filesystem UUID保留；VM正常stop/start後再驗。不得將force detach當正常生命週期驗收。
4. 結果保存實際耗時、錯誤與cleanup；scope缺項、容量錯配、mount enforcement移除的mutation須被gate拒絕。

任一失敗維持P1 blocker，保存失敗材料，不增加特權繞過、不取消硬quota。即使primitive通過，P1仍須另驗2GiB DB/4GiB artifact實際profile、真SQL/WAL滿盤、完整Next build與E2E；本批不是產品驗收。

## 官方依據

- [Lima additional disks](https://lima-vm.io/docs/config/disk/)：獨立固定大小disk及guest ext4；只使用additionalDisks，不使用文件中要求Lima2.3的host block-device功能。
- [Lima Docker](https://lima-vm.io/docs/examples/containers/docker/)：支援專用Docker guest；不採示例的全域context切換。
- [Ubuntu arm64 docker.io套件](https://packages.ubuntu.com/resolute-updates/arm64/docker.io)：使用Ubuntu signed APT提供的Docker與必要dependencies，不執行遠端convenience installer。
- 本機2.2.0 `docker-rootful.yaml`與`_images/ubuntu-lts.yaml`已核讀；執行前產出並validate明確VM設定，移除預設host mounts，不直接執行未核讀的遠端install script。
