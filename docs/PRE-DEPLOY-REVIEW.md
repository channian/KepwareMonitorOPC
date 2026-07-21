# 正式環境上線前健診複查報告

> 複查日期：2026-07-08 · 複查方式：4 個 Sonnet agent 平行複查（部署完整性 / 連線韌性 / 資料層併發 / Web 安全），PM 彙整去重、交叉驗證
> 複查性質：唯讀盤點，複查過程未修改任何程式碼
> 複查基準 commit：`689fde5`

## 一句話結論

**不建議「無條件」直接上線；但只要先修掉 1 個核心 Blocker（服務靜默死）+ 確認 2 個上線閘門，即可進正式環境做測試。** 其餘 High/Medium 項多與「單一 event loop 被同步呼叫凍結」「多台 Server 互相阻塞」有關，屬長期常駐才會侵蝕可用性，建議納入上線後第一個修補批次。

---

## 修正進度（2026-07-08 更新，使用者確認：全新 DB + 加接第二台 Kepware）

### ✅ 測試前必修，已完成並驗收
- **B-1 服務靜默死**（commit `e84440e`）：main() 致命例外 `sys.exit(1)`（清理先跑完）、初次連線改非致命（一台連不上不拖垮另一台/整個服務）、`_monitor_loop` 最外層護欄自我復原、[Mail] 缺 key 加 fallback。以 mock 對真正的 main() 實測 exit-code 行為通過。
  - ⚠️ **依賴人工確認**：`sys.exit(1)` 只有在 WinSW XML 設定了 `<onfailure action="restart" .../>` 時才會真正重啟（M5：WinSW XML 未納版控，無法在 repo 驗證）。**上線前務必確認正式機的 WinSW XML 有此設定，否則 B-1 修正無效。**
- **H3 多台 dedup 納入 server_name** + **B-2 migration 順序**（commit `7588af4`）：第二台事件不再被靜默丟棄；全新 DB 建立與 per-server 去重實測通過。
- **H-負值 limit DoS** + **H-requirements 版本鎖**（commit `233d962`）：asyncio 鎖 `>=2.0.0,<3.0.0`（實測 2.0.1，**非**部署 agent 誤建議的 `<2.0.0`）。

### ☑️ 上線閘門（營運檢查，非程式修改）
- **B-3 改掉 admin/admin 預設密碼**：使用者上線前於 Web UI 自行修改。
- **B-2 migration**：使用者採全新 DB，本不觸發；仍已一併改正以防未來重用 DB。

### ⏳ 測試穩定後緊接批次（本次刻意未做，避免與 B-1 啟動重構疊加風險）
- **H2 多台互相阻塞**：一台斷線走完重連（~55s+）期間其他健康台排隊等。需把各 Server 包成併發 asyncio.Task。使用者已確認多台部署，這是下一個優先。
- **單一 event loop 同步阻塞主題**：email(smtplib)、手動備份、大查詢/匯出、cleanup 改走 `run_in_executor`。
- 其餘 Medium/Low 見下方各段。

---

## 最高可信度發現：跨維度收斂

以下兩點是「不同 agent 從不同角度獨立指出同一根因」，可信度最高，列為第一優先：

### ★ BLOCKER-1：例外被吞成 exit 0 → WinSW 不重啟 → 服務靜默死亡
（部署 agent 與連線韌性 agent 各自獨立指出，已由 PM 核實程式碼）

- **證據**：`kepware_monitor.py:131-132` `except Exception` 記一行 log 後走 `finally` 正常返回 → `asyncio.run(main())` 結束 → 行程 **exit code 0**，無 `sys.exit(1)` 也無 re-raise。配合 `monitor_manager.py` `start()` 初次 `await conn.connect()` 無重試、`_monitor_loop` while 主體無最外層護欄。
- **正式環境風險**：WinSW 的 `restart` 通常只在「非零退出/崩潰」觸發，exit 0 被視為「正常停止」→ **不重啟**。開機時 Kepware 未就緒、網路未通、DB 建立失敗、或執行期任一未預期例外，都會讓監控靜默停擺，只留一行 log、不自動恢復。這正是交接文件反覆強調、也是先前踩過的「以為在跑其實沒在跑」最嚴重失效。
- **建議修法（三段，建議都做）**：
  1. `main()` 捕捉致命例外後改以 `sys.exit(1)` 結束，讓 WinSW 能接手重啟；
  2. `_monitor_loop` while 主體最外層加 try/except，記錄後 `continue` 讓迴圈自癒；
  3. `start()` 初次連線改為「帶退避的持續重試」而非一次失敗就拋例外。
- **連帶**：`monitor_manager.py:118,120` 的 `[Mail] SmtpServer/From` 無 fallback，缺 key 會在初始化拋例外、經同一路徑變成靜默死——修 BLOCKER-1 時一起加 fallback。

### ★ 架構主題：單一 event loop 被同步呼叫凍結（3 個 agent 收斂）
uvicorn Web UI 與監控主迴圈跑在**同一個 asyncio event loop**。以下同步阻塞呼叫會凍結「整個服務」（監控 + Web UI + 所有排程）：

| 來源 | 位置 | 凍結時間 |
|---|---|---|
| 寄信 smtplib（連線韌性 H1） | `ase_email_service.py:46`，呼叫端 `monitor_manager.py:573,675` | 每封最長 ~30s，多台同時告警可累積數分鐘 |
| Web 查詢直接同步跑（資料層 H1） | `web/api.py` 各 handler 未包 `run_in_executor` | 大表查詢/匯出數百 ms~數秒 |
| 手動備份（連線韌性 M3） | `web/api.py:826-851` `trigger_backup` 未包 executor | 最長 60s |
| 清理長交易（資料層 H2） | `db_service.py:796-839` 六表單交易 | 大量刪除時可 >30s，會觸發 `database is locked` |

**統一修法方向**：所有同步阻塞（smtplib、trigger_backup、大查詢/匯出、cleanup）改走 `await loop.run_in_executor(...)`；webhook 已用 daemon thread 是好範例。此主題不是上線閘門，但是長期穩定的關鍵，建議列上線後第一批。

---

## Blocker 清單（三項，均已 PM 核實）

| # | 發現 | 觸發條件 | 是否擋「測試上線」 |
|---|---|---|---|
| B-1 | 例外吞成 exit 0、服務靜默死（上方 ★） | 開機依賴未就緒 / 執行期意外例外 | **是**——測試結果不可信 |
| B-2 | Migration 順序錯：索引建在 migration 補欄位之前（`db_service.py:151-162`，PM 核實） | **僅**「舊版 DB 已存在再升級」路徑，`no such column: server_name` 開不了機 | **視情況**——全新測試環境不觸發；沿用舊 DB 才擋 |
| B-3 | 預設帳號 `admin/admin` 自動建立（`db_service.py:204`，PM 核實） | 未改密即上線，任何內網使用者可取得最高權限 | **是（閘門）**——屬營運檢查，改密即解 |

---

## High 清單（建議上線前處理，多為一行~小改）

- **H-限制值 DoS（Web H-1）**：`web/api.py:302,362` `limit=min(limit,5000)` 無下限，`?limit=-1` → SQLite `LIMIT -1` 等同無限制，低權限 viewer 即可撈爆記憶體。修法：`max(1, min(limit, 5000))`。**一行、強烈建議上線前修。**
- **H-版本無上限（部署 H1）**：`requirements.txt` 全部只有下限。`asyncua>=1.0.0` 1.x/2.x API 不同（`is_alive()` 註解已自證），全新 pip install 可能裝到不相容新版 →「開發機好好的、正式機壞掉」。修法：`asyncua>=1.0.0,<2.0.0`，其餘鎖已驗證版本。**一行、強烈建議。**
- **H-手動部署漏檔防呆（部署 H2）**：部署文件假設全樹複製，但實際是手動單檔複製（先前漏 `opc_connection.py` 事故根因）。文件未列「哪些檔案必須一起更新」，`README.md` 部署目錄也沒列全 .py。修法：文件補「整組更新 .py 清單」或強制 `xcopy /E` + 一鍵腳本。**直接對應先前事故。**
- **H-多台互相阻塞（連線韌性 H2）**：`monitor_manager.py:769` 各 Server 在單一 task 依序 `await`，一台斷線走完 3×重連(~55s+)期間其他健康台全排隊等。修法：每台包獨立 `asyncio.Task` 併發，或加 `asyncio.wait_for` 總逾時。**若確定多台部署則升為必修。**
- **H-弱密碼雜湊（Web H-2）**：`db_service.py:174-180` 單輪 SHA-256+salt 無 stretching，DB 檔外洩可離線爆破。修法：改 `pbkdf2_hmac`/bcrypt。可排程。

---

## Medium 清單（上線後第一批）

- **M-假復歸告警（連線韌性 M1）**：`monitor_manager.py:847-848` 復歸通知與計數歸零在「立即重讀成功」之前，半恢復時會發假復歸→再異常，造成告警抖動。修法：把復歸與歸零移到 `:854` 重讀成功之後。
- **M-Session 並發（連線韌性 M2）**：`requests.Session` 被 executor 執行緒（poll）與 event loop（手動備份 `web/api.py:848`）並用，非執行緒安全。修法：手動備份走 executor，Session 單一序列化路徑。
- **M-備份失敗跳過整週（連線韌性 M4）**：`kepware_log_service.py:599-601` 先寫 marker 再備份，單次 Gateway 暫時錯誤會整週不重試。（與 P1-3 日報 marker 是不同檔不同權衡，不受 P1-3 結案影響。）修法：成功才寫 marker，或失敗刪 marker + 當日重試上限。
- **M-WinSW 設定未納版控（連線韌性 M5）**：repo 找不到 WinSW xml，無法驗證 `onfailure restart` 與 graceful stop（與 B-1 連動）。修法：XML 納版控並確認含 `<onfailure action="restart"/>`。
- **M-CWD 路徑假設（部署 M1）**：程式大量寫死相對路徑（`Config/`、`data/`、`logs/`），`README.md` 的 WinSW XML 缺 `<workingdirectory>`（與 deployment-iis.md 不一致）。WinSW CWD 不保證是專案根 → 讀不到設定（觸發 B-1）或寫錯位置。修法：文件統一補 `<workingdirectory>`，或入口 `os.chdir` 鎖定。
- **M-dedup 未含 server_name（資料層 H3）**：`_make_hash` 與 `*_exists` 未依 server_name 分流，多台送相同 timestamp/message 事件會被跨機誤判重複、**靜默丟事件**。修法：hash 與查詢納入 server_name（+ 建 UNIQUE 索引兜底）。**多台部署則升級。**
- **M-timestamp 無法解析永不清理（資料層 M2）**：`_normalize_timestamp` 最終 fallback 回傳原字串，非標準格式 `julianday` 回 NULL → 該列永不被清、無限成長。修法：fallback 改回 `datetime.now()` 標準格式 + warning。
- **M-daily summary 全表掃描（資料層 M1）**：`get_daily_event_summary` 用 `substr(timestamp,1,10)` 使索引失效。修法：改範圍條件 `timestamp >= ? AND < ?`。
- **M-role 白名單不一致（Web M-2）**：`PUT /api/users/{id}` 未驗 role（POST 有驗）。修法：PUT 補同一白名單。
- **M-session 不失效（Web M-1）**：刪帳號/降權/改密後舊 cookie 最長 8h 仍有效。修法：連帶清該 user 的 session。
- **M-無登入失敗鎖定（Web M-4）**：無速率限制 + 帳號列舉時間差，配合 B-3 暴力破解無阻力。

## Low / 建議（擇期）

Web：`/api/health` 洩漏 DB 絕對路徑與 OPC URL（可公開存取）、Cookie 未設 `SameSite`、`/logout` 為 GET、部分端點回 `str(ex)`、改密無長度要求。
連線韌性：週期內即時恢復的斷線完全無告警（flap 靜默，觀測性）、Email 送失敗仍記為已派報、webhook thread 無池化上限、asyncua client 重連重用同一實例（長駐 FD/thread 觀察）。
部署：Web UI port 佔用僅靜默失效（監控續跑，尚可）、`urllib3` 未顯式列 requirements、PyInstaller 打包前須加 `--hidden-import multipart`（否則登入必壞）、OPC `SecurityPolicy` 讀了但從未 `set_security()` 套用（設 Sign/Encrypt 會連不上）、deployment-iis.md 引用未提供的 `exclude.txt`。

## 各 agent 明確「已檢查、無發現」（提高信心）

- **認證授權**：全 route 盤點，無需保護 endpoint 漏檢查，viewer 無法呼叫 admin API。
- **XSS**：前一輪統一修復落實到位；Jinja2 autoescape 有開。
- **SQL 注入**：全參數化，無字串拼接。
- **敏感資訊**：密碼/hash/salt 未外洩到前端或 log；`/api/settings` 密碼類 key 有遮罩。
- **read_values 錯位**：asyncua 2.0.1 壞節點回 None 逐一對齊，None-slot 還原映射正確，不會把 A 設備值配到 B 設備。
- **連線洩漏**：db_service 全 25 方法每路徑都 `finally close`，無洩漏。
- **清理涵蓋度**：六表已涵蓋完整（P1-1 到位）。

---

## PM 上線決策建議

考量使用者目標是「進正式環境**做測試**」（非無人值守長期上線），分三檔：

**① 測試上線前必做（門檻）**
- 修 **B-1**（exit-0 靜默死：sys.exit(1) + 迴圈護欄 + 初次連線重試 + Mail fallback）——否則測試中服務靜默死，測試結果不可信。
- 確認 **B-3**（改掉 admin/admin 預設密碼）——營運檢查，不需改碼。
- 若測試環境**沿用舊 DB** 才需先修 **B-2**（migration 順序）；全新 DB 可暫緩。
- 修 **H-限制值 DoS** 與 **H-版本上限**（各一行，順手做掉）。

**② 測試期間並行處理（不擋上線，但影響測試品質）**
- H-手動部署漏檔防呆（文件）、H-多台阻塞（若多台）、單一 event loop 同步阻塞主題（email/backup/查詢 executor 化）。

**③ 上線後第一個修補批次**
- 全部 Medium + 選擇性 Low。

> 建議：若時間只夠做一件事，做 **B-1**。它是「正式環境起不來/半夜靜默死卻查不出原因」的單點根源，也最貼合本專案先前的事故教訓。
