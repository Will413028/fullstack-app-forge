---
title: 先固定全端模板與本機受控 runner
date: 2026-10-01
status: active
tags: [personal, decision, nextjs, fastapi, docker]
---

# 先固定全端模板與本機受控 runner

## Context

Will 要完整重做 AI 應用生成平台供學習與作品集，平台與產物均用 Next.js + FastAPI。尚無產品程式或既有部署；本次決定生成自由度與第一階段執行邊界，兩者獨立選擇。

**約束與來源：**

- `external` Will 本次指定全端生成、學習兼作品集；並選 Next.js + FastAPI + PostgreSQL 固定模板、本機 Docker 與公開案例展示。
- `external` 第一階段不開放匿名生成；這是 Will 對使用者範圍的選擇，不是缺乏需求證據就推定無需求。
- `inherited` 原產品生成、對話/視覺修改、預覽、分享與管理作為功能基準；完整重做要求仍成立，但其 Java/Vue、微服務與 host build 不構成限制。
- `inherited` 平台/generated app 資料與 credentials 分離、artifact revision 與成功證據契約仍成立：全端生成有不可信程式與持久化資料，不因固定模板消失。
- provider 能力、費率、生成成功率與本機資源尚未量測；不能用免費、完整隔離或更便宜作為選擇理由。

## Options Considered

### 生成範圍

- **A 固定全端模板（選用）**：鎖定依賴、runtime 與工具範圍；允許多頁 UI、API、資料模型及受控 migration 改變。較易建立可比較的行為基線，需求自由度較低。
- **B 固定核心與審核擴充**：逐項加入已驗證 package/integration adapter。可展示真實整合，但每項新增契約、credentials 與維護工作。
- **C 自由套件與第三方整合**：接近通用應用開發需求；增加 dependency、網路、副作用與費用的驗收組合。
- 工程基準是固定可重現 runtime，再按需求扩充；[Next.js 部署文件](https://nextjs.org/docs/app/getting-started/deploying) 可取回 runtime 能力來源，但不能據此宣稱 A 是 AI generator 市場主流。

### 執行邊界

- **L 本機受控 Docker（選用）**：獨立 controller 管理 frontend/API/app DB，限制 mount、network、process 與資源。方便觀察完整執行鏈，自行維護隔離與清理。
- **H 託管 sandbox**：可能減少本機操作並提供遠端 lifecycle；增加服務帳號與依賴，所需 DB、網路、持久化及費率尚待官方查證。
- **V 自管獨立 host/VM**：把 workload 與開發 host 分開且保留控制；增加 patching、network、容量与備份工作。
- 隔離基準依威脅模型選擇，公開執行不可信程式需另評估專用環境；[Docker security](https://docs.docker.com/engine/security/) 支持「一般容器需要額外設定」，不替 L/H/V 的安全性排名。

## Decision

- **D1**：先採 A，Next.js + FastAPI + PostgreSQL 固定模板，多頁與 CRUD；任意套件、付款與第三方整合延後。
- **D2**：先採 L，本機受控操作與 Docker 預覽，公开作品集展示案例；不開放匿名生成。公開生成與遠端發布不是本機隔離已驗證的推論。
- 以上由 Will 於 2026-10-01 明確選定。平台 persistence/queue、model/budget 與遠端 host 另決，不由本 ADR 推定。

## Rationale

- **D1**：第一條閉環已有 UI、API、PostgreSQL、版本與 migration，足以展示全端能力；先固定依賴能把模型品質與接線錯誤分開量測。相較 B/C，代價是能力範圍受限，模板成功不能外推自由生成。
- B 是有價值的中間路線，不與 C 一起永久排除；目前先驗完整閉環，再根據具體 integration 案例擴充，避免為未知整合先建 adapter 系統。
- 不選 C 的第一階段理由是目前承諾受限模板產品，而非通用自由需求；每個不支援的需求要明確拒絕，不能計入成功案例。
- **D2**：目前受控操作與案例展示不需要匿名遠端生成；本機可直接學習啟停、故障、持久化與清理，避免在第一切片同時加入 provider lifecycle 變因。代價是本機運維與 host 共存責任。
- H 的隔離/維運收益可能值得採用，但未有 provider 實證；本次不宣稱 L 比 H 更便宜或安全。V 有 host 分離收益，第一階段尚不承諾公共惡意 workload，暫不增加獨立 host 維運。
- 不預建通用多 backend abstraction；runner lifecycle 契約留清楚，只有第二 backend spike 通過才宣稱可替換。

## Expected Outcome

- 支援範圍內的 Todo 經 build、API health、CRUD、API 重啟持久化與加欄位保留資料驗收。
- fixture 與真模型結果分開，成功率按明列模板範圍計算；沒有品質/延遲/成本數值承諾。
- runner 通過 host/跨 app/path/symlink、資源與取消驗收；目前只是待驗，不宣稱 Docker 已提供完整 sandbox。

## Followup

- P0 產出 runner threat model、有限資源 profile 與實際 disk enforcement；P1 驗負向與停止/cleanup，不通過就阻擋生成執行。
- P2 量測固定案例，保留需求拒絕、失敗階段與成本；遇到有價值的整合需求時評估 B。
- P5 完成遠端發布與 DB lifecycle spike 後再選 host、費用與資料保留；本機驗收不代替遠端驗收。

## Revocation Triggers

- 案例反覆因缺少套件/整合而被拒，且有清楚的擴充收益 → 重評 D1，優先比較 B。
- 要開放陌生使用者/匿名生成、長期遠端預覽或本機容量不符需求 → 重評 D2。
- runner 無法證明 host/跨 app 隔離或有限資源限制 → 停止執行承諾並重評，不以模板受限為豁免。

## Review Notes

兩份未參與撰寫的獨立草稿核對替代方案；已納入審核擴充、獨立 host、兩維度正交與不預建多 backend 的論點。生成能力與隔離仍待實作驗收。

## Related

- 本 ADR 即原始決策紀錄，無外部來源文件；2026-10-01 Will 明確選 D1/D2。
- 實作計畫 `docs/plans/2026-10-01-full-rebuild.md`。
- [Next.js deployment](https://nextjs.org/docs/app/getting-started/deploying)、[Docker security](https://docs.docker.com/engine/security/)；查詢日期 2026-10-01，實作前重查。
- 未抽 tech：這是產品範圍與環境選擇，尚無本產品執行案例，不新增通用 Rule。
