# KepwareMonitorOPC 專案評估與交接計畫書

> 撰寫日期：2026-07-03
> 用途：本文件為 AI 協作交接文件。後續接手的模型（或工程師）請先完整閱讀本文件與 `CLAUDE.md`，再開始任何開發工作。
> 工作分支：`claude/admiring-wozniak-hiKU0`

---

## 1. 專案現況總覽

### 1.1 專案定位

Kepware OPC UA 監控告警系統，部署於 Windows 內網環境（測試機 Kepware API Gateway：`http://10.10.51.81:8000`）。功能包含：

- OPC UA 點位輪詢監控（asyncua）、閾值判斷、Email/Webhook 告警
- Kepware API Gateway 事件/交易紀錄監控（JWT 認證、去重、每日彙整日報）
- Kepware 專案排程備份（每週排程 + 手動觸發，透過 `POST /api/backup/save`）
- FastAPI Web UI（Dashboard、歷史查詢、告警紀錄、Tags 管理、事件、備份、帳號管理）
- SQLite 資料儲存（WAL 模式）

### 1.2 模組結構與規模

| 檔案 | 行數 | 職責 |
|---|---|---|
| `monitor_manager.py` | ~950 | 主監控迴圈、CSV 熱重載、告警評估、多 Server 管理 |
| `web/api.py` | ~870 | 所有 FastAPI routes（頁面 + REST API + SSE） |
| `db_service.py` | ~830 | SQLite 存取層（8 張表、密碼雜湊、清理） |
| `kepware_log_service.py` | ~630 | Gateway polling、事件分類、日報、備份觸發 |
| `webhook_service.py` | ~280 | Webhook 推播 |
| `diagnostic_service.py` | ~170 | 主機層診斷（ping/port check） |
| `kepware_monitor.py` | ~150 | 進入點、config 載入、uvicorn 啟動 |
| `opc_connection.py` | ~140 | OPC UA 連線封裝（安全策略、重連） |
| `web/auth.py` | ~80 | 記憶體 Session 管理 |
| `ase_email_service.py` | ~60 | Email 寄送 |

### 1.3 重要架構約定（違反會出問題）

1. **前端無框架**：HTML + CSS + Vanilla JS。互動邏輯 inline 在各 template 的 `{% block scripts %}` 中。
2. **按鈕樣式已全面改為「文字 pill」**，不再使用 Lucide 圖示（icon 尺寸在內網瀏覽器上無法可靠控制，歷經多次修復後放棄）。配色規範：
   - 主要動作（儲存/查詢/手動備份）：`background:var(--blue-soft);color:var(--blue);border:1px solid rgba(59,130,246,0.3)`
   - 新增類（新增點位/新增使用者）：`background:var(--accent-soft);color:var(--accent);border:1px solid rgba(34,211,238,0.3)`
   - 次要類（匯出/匯入/編輯）：`background:var(--muted-bg);color:var(--fg-2);border:1px solid var(--border-2)`
   - 危險類（刪除）：`background:var(--err-bg);color:var(--err);border:1px solid rgba(239,68,68,0.3)`
3. **Cache-busting**：改 CSS/JS 後必須升 `base.html` 內的版本參數（目前 `style.css?v=6`、`app.js?v=3`），並提醒使用者 Ctrl+Shift+R。
4. **多 Server 支援**：所有新監控功能必須支援多台 Kepware（config section 形如 `[KepwareLog.<server_name>]`）。
5. **commit 前必須跑 `python -m py_compile <修改的每個 .py>`**。
6. 設定檔為 INI（`Config/settings.example.ini`），使用者已明確決定不改用 .env。

### 1.4 部署方式

- 主要：PyInstaller 打包 exe + WinSW（`KepwareMonitorSvc.exe`）註冊 Windows 服務。文件在 `README.md` 與 `docs/deployment-iis.md`。
- Web UI 選用 IIS 反向代理。

---

## 2. 近期已完成工作（本 session）

1. **備份 API 實作**：`kepware_log_service.trigger_backup()` 呼叫 `POST /api/backup/save`（無參數，Gateway 自動產生 `Project Backups\KepwareBackup_{timestamp}.opf`），成功/失敗皆寫入 `kepware_backups` 表。使用者已實測通過。
2. **UI 按鈕全面改版**：所有頁面按鈕改為文字 pill（見 1.3 第 2 點）。
3. **重大 bug 修復**：`web/api.py` 變更密碼 API 的 `user["user_id"]` → `user["id"]`（原本所有使用者改密碼都會 500）。
4. **效能修復**（commit `ae3f19a`）：
   - SQLite 啟用 WAL + `synchronous=NORMAL`
   - 補 5 個索引（`server_name` × 4 張表、`kepware_transactions` 去重複合索引）
   - `kepware_log_service` 改用 `requests.Session`（TCP 連線重用；login 時同步更新 session headers）
   - 備份 marker 改為「先寫 marker 再備份」，避免 crash 造成重複備份
   - `asyncio.get_event_loop()` → `get_running_loop()`（monitor_manager 兩處）
5. **文件更新**：README、deployment-iis.md 加入備份功能、多 Server 帳密、PyInstaller+WinSW 步驟。

---

## 3. 已知未解決問題（Backlog，依優先級排序）

### 已完成（2026-07-03，Sonnet 5 三 agent 平行處理）

- ✅ **P0-1 OPC UA 斷線偵測強化**：新增 `OPCConnection.is_alive()`（`opc_connection.py`），主迴圈讀值前先檢查，斷線可提早感知；新增連續失敗次數追蹤 + 首次/第 5 次告警降噪機制；重連成功寄送復歸通知。詳見 commit `6685698`。**尚待實機驗證**（見下方新增的 P0-3）。
- ✅ **P1-1 `kepware_backups` 清理**：`db_service.py` `cleanup_old_records()` 已補上。
- ✅ **P1-2 定期清理排程**：`monitor_manager.py` `_monitor_loop()` 改為每日執行一次，不再只在 `start()` 執行一次。
- ✅ **P2-1 XSS escape 統一**：`history/alerts/dashboard/kepware_events/tags/users.html` 全數補上 `escapeHtml()`；`users.html`/`tags.html` 的 onclick 屬性注入風險改用 `data-*` 屬性傳值。詳見 commit `cfe657d`。
- ✅ **P2-4 核心純函式單元測試**：新增 `tests/`，96 個測試全數通過，涵蓋 timestamp 解析、事件嚴重度分類、CSV 解析、`evaluate()` 閾值判斷全部條件分支。詳見 commit `783d315`。

### 已完成（2026-07-06，Sonnet 5 後續處理）

- ✅ **P0-4 重連成功後立即重試讀值**：原本 `continue` 只會跳到 for 迴圈下一台 Server，多台部署時要等下一輪整體週期才真正重試。改為重連成功後立即對該連線重試一次 `read_values()`，成功則直接沿用既有流程往下處理數據。單台部署行為不受影響。詳見 commit `69825b4`。
- ✅ **P2-3 移除未使用的 `secret_key`**：`web/auth.py` 的 `SessionManager.secret_key` 從未被用於簽名、也從未被呼叫端傳入，純屬死碼，已移除參數。
- ✅ **P2-2 設定檔權限文件化**：`docs/deployment-iis.md` 新增「設定檔安全性」章節，說明 `icacls` 限制 `Config/data/logs` 存取權限的做法（明文密碼未做加密，改用 DPAPI 等方案風險/複雜度較高，故採檔案權限限制作為務實方案）。

### P0 — 待實機驗證

**P0-3.（新）`is_alive()` 的 asyncua API 相容性尚未在正式部署環境驗證**

`is_alive()` 依序嘗試 `client.check_connection()` → `client.uaclient.state` → 都沒有則保守回傳 `True`（fail-open，不影響原有行為）。這個相容性寫法已在 sandbox 安裝的 asyncua（`2.0.1`）驗證過可正確運作，但 sandbox 版本可能與你正式機器上安裝的 asyncua 版本不同（`requirements.txt` 只釘了 `asyncua>=1.0.0`，沒有上限）。**建議部署後觀察一段時間的 log，確認 `is_alive()` 有沒有誤判（例如連線正常卻頻繁報斷線）**，若有異常屬於程式判斷邏輯問題，需要回報實際 log 內容才能進一步除錯。

**P0-2. 實機驗證排程備份 end-to-end**

手動備份已驗證，但**排程備份**（`check_weekly_backup`）尚未在實機跑過完整週期。驗證點：
- 到達設定的星期/時間後是否觸發一次且僅一次
- marker 檔 `data/.backup_done_{server}` 正確寫入
- 跨天/重啟後不重複觸發

### P1 — 功能完整性

**P1-3. 每日彙整 marker 寫入順序**

`_check_daily_summary()`（`kepware_log_service.py:300`）為「先寄信、成功後寫 marker」。若寄信成功但寫 marker 前 crash，重啟後會重寄一次日報。
- 注意 trade-off：改成「先寫 marker」則寄信失敗當天不會重試。
- 建議維持現狀或改為「先寫 marker + 寄信失敗時刪除 marker」。此項風險低，可與使用者討論後再決定。

### P2 — 品質與安全（內網環境，風險較低）

**P2-5. PyInstaller 打包實測**

文件已寫，但打包流程尚未在目標 Windows 機器實測（hidden imports：`uvicorn` 的 loop/protocol 子模組常漏）。首次打包預留除錯時間。

**P2-6.（新，測試過程中發現的邊界行為，非 bug，僅供參考）**

寫單元測試時發現三處既有設計的邊界行為，皆已確認不影響目前實際資料流，暫不需修正：
- `MonitorManager._parse_csv_row` 的 `Enable` 欄位只認可字串 `"true"`（不分大小寫）為 `True`，其餘（含 `"1"`、`"yes"`）一律視為 `False`；若未來 CSV 維護者誤填 `"1"`/`"yes"` 到 Enable 欄位，設備會被靜默停用而不會報錯。
- `evaluate()` 對 `condition` 字串比對是大小寫敏感的，但實際資料流一定先經過 `_parse_csv_row`（會 `.lower()`），故無實際影響。
- `evaluate()` 的 `device_type=="log"` 分支與頂層 `raw_value is None` 檢查對 `None` 輸入的結果剛好一致，不影響行為。

---

## 4. 建議執行順序（給接手模型的路線圖）

```
第一階段（穩定性，P0-1/P0-4/P1-1/P1-2/P2-1/P2-2/P2-3/P2-4 已完成，見上方勾選清單）
  ├─ P0-3 is_alive() 實機觀察（需使用者配合看 log）
  └─ P0-2 排程備份實機驗證（需使用者配合觀察）

第二階段（維運完整性）
  └─ P1-3 日報 marker（需與使用者確認取捨後才動手）

第三階段（品質）
  └─ P2-5 PyInstaller 實測支援（需使用者配合在目標機器打包）
```

---

## 5. 交接注意事項（務必遵守）

1. **語言**：使用者以繁體中文溝通，回覆一律用繁體中文。
2. **遵守 `CLAUDE.md`**：commit 前 `python -m py_compile`；push 失敗以 2s/4s/8s/16s 指數退避重試；相關變更歸同一 commit。
3. **分支**：所有開發在 `claude/admiring-wozniak-hiKU0`，`git push -u origin claude/admiring-wozniak-hiKU0`。未經同意不開 PR、不推其他分支。
4. **不要重新引入按鈕圖示**：Lucide icon 尺寸問題已確認無法在使用者環境可靠解決，按鈕一律純文字 pill（配色見 1.3）。
5. **改前端後**：升 cache-busting 版本號 + 提醒使用者 hard-refresh（Ctrl+Shift+R）。
6. **使用者無法即時提供的資訊**：實機 log、Kepware Gateway 行為（如 API 回應格式）需請使用者實測回報，不要假設。備份 API 回應格式為 `{"success": bool, "message": "<檔名或錯誤>"}`。
7. **測試環境**：使用者的 Kepware API Gateway 在 `http://10.10.51.81:8000`（內網，開發環境連不到，只能靠使用者驗證）。
8. **Python 版本**：目標環境為新版 Python（舊版才能用的 opcua 套件已棄用，本專案用 asyncua）；部署走 PyInstaller 打包。

---

## 6. 資料庫結構速查

8 張表：`monitor_history`、`alert_log`、`users`、`webhook_log`、`kepware_events`、`kepware_transactions`、`kepware_backups`、（`sqlite_sequence`）。

- 連線 pattern：每次操作 `_get_conn()` 開新連線、finally close（執行緒安全，WAL 模式已啟用）。
- `users` 表主鍵是 `id`（**不是 `user_id`** — 曾因此出過 500 bug，寫程式時注意）。
- 密碼：salt + SHA-256 雜湊。
- marker 檔案在 `data/`：`.daily_summary_sent_{server}`、`.backup_done_{server}`。
- 備份排程設定在 `data/backup_schedule.json`（非 INI）。
