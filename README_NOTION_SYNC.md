# Notion 同步至觀影清單網站指南

本文件供開發者或 GPT 檢查與維護此專案的 Notion 自動同步機制。

---

## 1. 架構說明
* **資料來源**：Notion 資料庫「電影清單」
  * **Notion 頁面**：https://app.notion.com/p/3ea28413d5c0807ea5f8de2bb341b0f3
  * **Database ID**：`3ea28413-d5c0-8104-a40b-eceb3681a290`
* **同步腳本**：`scripts/sync_notion_movies.py`
  * 讀取 Notion 中的片單資訊（`片名`、`上映年份`、`分類`、`已觀看`、`喜愛`、`按爛`、`系列名稱`、`系列順序`、`年度順序`、`IMDb ID`）。
  * 保持現有 `movies.json` 中已快取的 TMDb 海報、背景圖、IMDb 評分資料不遺失。
  * 支援以首部電影上映年份自動排序系列大分類，並自動重整整數順序。
* **輸出目標**：`/movies.json`（React 前端直接讀取渲染）。

---

## 2. GitHub Secrets 設定需求
若要在 GitHub Actions 自動執行，需至儲存庫 **Settings > Secrets and variables > Actions** 新增以下機密：
* `NOTION_TOKEN`：Notion 整合權杖
* `NOTION_DATABASE_ID`：`3ea28413-d5c0-8104-a40b-eceb3681a290`
* `TMDB_API_KEY`：（可選）若有設定，新增片單時會自動向 TMDb 補齊最新海報與背景圖路徑。

---

## 3. GitHub Action 啟用方式
* 範本檔案位於 `scripts/sync_movies.yml`。
* 若要啟用自動排程，請將該檔案移動或複製到 `.github/workflows/sync_movies.yml`（需確認 GitHub PAT 具備 `workflow` 權限）。
