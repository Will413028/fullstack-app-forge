# P0b2 候選：Docker Linux block-volume spike

## 前提與取捨

HFSX normal detach 失敗；獨立 Lima VM 啟動逾時，owned 資源已清理。主機目前 load89、約194MiB unused，不再加入4GiB VM。硬 quota 仍是需求，不以監測或 generic named volume 代替。

- 獨立 Linux VM：native filesystem、host 分離較明確，但多一個 VM 與記憶體生命週期，目前 boot 尚未驗證。
- Docker Linux 環境內固定大小 ext4 image：不增加 VM，Docker local driver 管 mount/unmount；trusted controller 需要建立／detach loop device，生成程式不取得特權。候選採此 spike，未採為產品 adapter。
- 專用實體 Linux／託管 sandbox：另需 host／帳號，本次維持已選本機受控 Docker。

[Docker 官方 block device 範例](https://docs.docker.com/engine/storage/volumes/#block-storage-devices) 說明 local driver 轉交 Linux mount syscall；loop device 重啟後需重建，且不是通用建議。必須實測 kernel／device node／mount 的可用性，不能從文件推定 Docker Desktop 適用。

## 受測機制與邊界

1. 固定 cached PG17 digest 建 trusted quota-tools image；實際 OS 核對為 Alpine3.24.2，僅 image 的官方 dl-cdn.alpinelinux.org/v3.24 APK 來源安裝 e2fsprogs/util-linux，來源不符就停止，不換 mirror／installer；保存 image ID與套件版本。第一輪誤用 APT 的 build failure保留。generated code 不在此 image 執行。
2. 新建 UUID label 的 backing volume；controller 只掛該 volume，建立兩個256MiB ext4 images。controller 無網路、不掛 Docker socket、host filesystem 或 platform data；只 controller 有 loop-device 所需特權，不用 host PID namespace／nsenter。
3. controller 以 losetup --find --show 將這兩個 image 接成獨占 loop devices；記錄 device、backing inode／size／filesystem UUID，不能使用任何既有 disk 或任意 path。
4. 新建兩個 UUID owned local volumes，type=ext4、device=各自 loop device、o=rw；Docker daemon 負責 mount/unmount。先做短 mount/marker/controller restart/unmount/remount probe，再做 PG／ENOSPC。
5. PG/writer 只掛 local filesystem volume、無特權、有限 CPU/RAM/pids/network。不把 backing parent volume或 block device 交给 untrusted workload。

## 驗收與清理

**Controller privilege profile（P0LOOP-D01 改）**：drop ALL，僅加 SYS_ADMIN、MKNOD；授予 `/dev/loop-control`（char10:237）與 block major7 minors0–31 的 rwm cgroup rules，只在容器自己的 `/dev` 建節點。無 `--privileged`／host PID／host network／nsenter／Docker socket／host mount，rootfs readonly、network none、128MiB RAM（swap不增加）、0.5CPU、pids64、/tmp16MiB。必需 flags 不支援或出現 EPERM／device node 不可用時保存失敗，不自動擴權。capabilities與loop allowlist仍能操作其他loop device：controller必須受信任，owned image/device/inode核對是程式邊界，不宣稱OS只能碰owned device。generated PG/writer不持此profile。

P0 full probe需驗8項：兩個 mount identity/capacity、兩scope ENOSPC、scope isolation、PG restart、正常 volume unmount/remount、controller停止再重建loop mapping後相同UUID與marker。controller restart證明mapping reconcile，不冒充整個Docker daemon／host reboot驗收；不能重啟共用Docker Desktop。

失敗保存 raw error及精確owned IDs。先停止移除全部owned PG/writers，再移除 local volumes，由daemon正常卸載。只對記錄的loop device核對backing inode/size後detach；mount仍在、identity矛盾或引用不明就保留image與parentvolume，不force、不prune。成功清理才刪owned backing volume；永遠不刪原失敗材料。

此路徑若不可用，返回短Lima boot診斷，不放寬硬quota。即使P0通過，P1仍需2GiB DB／4GiB artifacts、真SQL/WAL滿盤、loop mapping recover/fencing與完整 generated app E2E。產品首次建立持久化資源前還須 app tombstone/reconciler。

## 權限与來源

Will的完整實作委託已涵蓋本機隔離與必要下載；不再逐批詢問。特權只屬本次固定trusted controller；不讀credentials、不改Docker設定、不重啟共用daemon。主機受控範圍不變；不是公開惡意程式隔離聲明。

## 首輪實測與診斷

`p0-loop-quota-results.json` 保留首輪failure：兩個ext4 filesystem身分正確，配置268,435,456 bytes、filesystem可用總容量241,081,344 bytes，UUID與loop devices不同。PostgreSQL初始化、marker寫入及正常停止已執行，但DB填盤writer的Docker wait超過120秒，未取得ENOSPC；後續restart/remount/remap未驗。cleanup四項全true、remaining_loops/pending_attach空；按spike-id查container/volume皆空。這不是quota通過。

16MiB I/O診斷已完成，原結果 `p0-loop-io-diagnostic.json` 保持：write1.77秒、fsync1.71秒、總計3.54秒，cleanup全true；不足以支持一般I/O慢就是首輪root cause。下一個單一假設為較大量寫入後memory/page-cache壓力；[Linux cgroup v2官方文件](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html)說明memory與writeback計數機制，但未證本案根因。`--diagnose-io --io-mib 128`（default16）保存每16MiB進度與memory.events，再量測final fsync；結果預設各自為 `p0-loop-io-<size>m-diagnostic.json`，不啟PG、不驗quota、不覆寫首輪failure。timeout先保存自己State/tail logs再owned cleanup。browser隔離DB驗證結束後才執行下一輪I/O量測。

128MiB診斷已完成，write22.05秒、fsync0.49秒、總22.61秒、cleanup全true。外部保存own progress到 `p0-loop-128m-progress.log`：64MiB時memory.events max57、80MiB時max123、oom0，仍能完成，不將觸及limit計數當OOM或已證root cause。新full attempt2維持同profile與deadline，新增每16MiB進度及timeout State/log；結果另存 `p0-loop-quota-attempt2.json`，首輪failure不覆寫。

full attempt2取得5 checks：兩FS、DB真ENOSPC（196,259,840 bytes／21.26秒）、scope isolation、PG restart marker42；artifact writer非零退出，舊helper未保存exit/State，不能稱OOM或ENOSPC。cleanup四項全true，spike-id查無container/volume。新增 `--diagnose-fill` 單獨驗artifact填盤，保留非零exit/State/stdout/stderr，不啟PG，結果 `p0-loop-artifact-fill-diagnostic.json`；這是診斷，不是remount/remap驗收。

獨立correctness review R01/R02已改並回查：mutating Docker timeout／未確認nonzero記uncertain ledger，清理拒絕並保留，不能用一次losetup -j空結果排除晚到attach；backing device＋inode＋size與完整retained attachment核對後才能detach。7 safety regressions、10 gate tests與兩個unsafe mutations轉紅；49附件tests通過。實測結果尚未使用新ownership欄位完成full primitive，需診斷及後續fresh full驗收，不把review閉合當產品通過。

128MiB writer的單獨artifact診斷：120秒時still running、OOMKilled=false；80MiB耗時81秒、memory max164、oom0。兩FS與新backing identity讀回通過，cleanup全true，未知mutation/pending/loops空，spike-id查資源空。原128MiB結果不覆寫。下一輪僅writer/reader RAM cap改512MiB（swap同額，不增加swap）、其他CPU/pids/network/caps/disk/deadline不變，保存HostConfig readback與各自結果；controller128MiB／PG256MiB保持。比較驗reclaim-pressure假設，增加cache上限代價是較高記憶體峰值；未採產品profile。入口 `--diagnose-fill --writer-memory-mib 512 --output p0-loop-artifact-fill-512m-diagnostic.json`。

## 完整 primitive 第三輪

512MiB diagnostic 在 37.62秒、236,609,536 bytes 後取得 errno28，memory max/oom 最後皆0；支持 reclaim pressure 假設，不宣稱正式因果 benchmark。使用相同受限 writer profile 加新 ownership/uncertain guards 的 `p0-loop-quota-attempt3.json` 實測完整8checks通過：DB ENOSPC 196,259,840 bytes／15.09秒、artifact 236,605,440 bytes／22.19秒、scope隔離、PG restart42、normal volume remount、controller remap；兩個後續 lifecycle 均保持 DB UUID/marker42。HostConfig readback吻合；cleanup containers/volumes/loops/backing 全true，remaining_loops/pending_attach/uncertain_mutations 空。exact gate 通過，prefix `forge-loop-68bde5c1ce34` 的 `docker ps -a --filter name=…` 與 `docker volume ls --filter name=…` 皆空。

P0b2 primitive 完成，解除 P1b 技術 blocker。產品須另建 durable resource journal、實際2GiB DB/4GiB artifacts profile、SQL/WAL滿盤與生成CRUD/restart證據；本案未重啟共用Docker daemon/host，controller remap不代表host reboot驗收。
