# Fullstack App Forge

以 Next.js + FastAPI 重做 AI 應用生成平台，供學習與作品集展示。生成結果也是 Next.js + FastAPI 全端應用。

## 現況

平台核心已有 Next.js 工作室、FastAPI auth/apps/runs/events 與 PostgreSQL durable run store。平台 build、33 項後端測試（含 migrations/resource journal）、桌面／手機 browser shell，以及真瀏覽器→API→隔離 PostgreSQL 的註冊/app CRUD/run SSE/取消/重整/登入流程通過。硬 quota primitive 的 8 checks 已通過；resource journal／原子 adoption 與固定 Todo 模板已有實作，依賴 images 已 build。生成 worker、preview runner、產品實際容量與 generated build/CRUD 尚未接通，完整產品未完成。

## 本機開發與驗證

需要 Python 3.12、uv、pnpm 11 與 Docker。`make install` 安裝 lockfile 中的依賴；`make prepare-db` 取得固定 digest 的 PostgreSQL image。安裝 Playwright Chromium 後，`make check` 檢查 backend、隔離 PostgreSQL 行為、web build 與真瀏覽器平台流程。DB tests 建立自己的容器並在收尾移除；`.github/workflows/check.yml` 執行相同入口，尚未推送或取得遠端 CI 結果。

執行平台前，以環境變數 `FORGE_DATABASE_URL` 指向本專案獨立 PostgreSQL database，`FORGE_PLATFORM_ORIGIN` 設定瀏覽器使用的完整 origin。API 入口為 `forge.main:app`；從 backend 執行 `.venv/bin/uvicorn forge.main:app --host 127.0.0.1 --port 8000`。前端從根目錄執行 `pnpm dev`，以 `FORGE_API_URL` 指定 API 位址。請使用專屬開發 DB；啟動 API 會套用有序 SQL migrations。

目前尚未建立 `make e2e-fixture`；`make check` 不代表 generated app build、CRUD 或 runner 驗收。

- [產品規格](docs/spec.md)
- [階段計畫與進度](docs/plans/2026-10-01-full-rebuild.md)
- [需求與來源盤點](docs/plans/2026-10-01-full-rebuild/requirements.md)
- [P0 實測與待確認事項](docs/plans/2026-10-01-full-rebuild/p0-findings.md)
- [API／事件契約草稿與 queue 選項](docs/plans/2026-10-01-full-rebuild/p0-contracts.md)
- [開始實作的交接](docs/handoff.md)

## 目標流程

需求 → 全端規格 → 生成檔案 → 檢查與修正 → 隔離啟動 → 預覽操作資料 → 對話與視覺修改 → 發布分享。

功能參考 [liyupi/yu-ai-code-mother](https://github.com/liyupi/yu-ai-code-mother)。這是獨立重新實作；固定來源只供唯讀行為盤點，不將參考程式碼、prompt 或素材納入產品。
