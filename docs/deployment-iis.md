# IIS + WinSW 部署指南

本文件說明如何在 Windows Server 環境中，使用 IIS 反向代理 + WinSW 服務包裝，將 KepwareMonitorOPC 部署為正式服務。支援兩種佈署方式：

- **方式 A：Python 虛擬環境** — 直接用 venv 執行（適合有 Python 環境的主機）
- **方式 B：PyInstaller 封裝** — 打包成單一 exe（適合無 Python 或 asyncua 需要特定 Python 版本的主機）

## 架構

```
外部使用者 (瀏覽器)
    ↓ HTTP/HTTPS (Port 80/443)
IIS (反向代理)           ← 選用，不用 IIS 可直接用 :8080 存取
    ↓ localhost:8080
uvicorn (FastAPI)
    ↓
kepware_monitor.py (主程式)
    ├→ OPC UA 連線 (讀取設備數值)
    ├→ Kepware API Gateway (事件 polling + 專案備份)
    ├→ SQLite (資料儲存)
    └→ Email / Webhook (派報)
```

## 前置需求

| 項目 | 版本/說明 |
|------|----------|
| Windows Server | 2016 / 2019 / 2022 |
| Python | 3.8+ (建議 3.10+)，方式 B 僅開發機需要 |
| .NET Framework | 4.6.1+ (WinSW 需要，Windows Server 內建) |
| IIS | 選用，需安裝 ARR + URL Rewrite 模組 |
| 網路 | 可連線 Kepware OPC UA Server |

## 方式 A：Python 虛擬環境佈署

### 步驟 A1：Python 環境

```powershell
# 建立專案目錄
mkdir C:\Services\KepwareMonitor
cd C:\Services\KepwareMonitor

# 複製專案檔案
xcopy /E /I \\source\KepwareMonitorOPC .

# 建立虛擬環境
python -m venv venv

# 啟動虛擬環境
.\venv\Scripts\activate

# 安裝相依套件
pip install -r requirements.txt

# 建立設定檔
copy Config\settings.example.ini Config\settings.ini
copy Config\tags.example.csv Config\tags.csv
```

編輯 `Config\settings.ini`，設定 OPC Server 連線、Email、WebUI 等資訊。

WebUI 設定建議：

```ini
[WebUI]
Enable = true
# 若使用 IIS 反向代理，綁定 localhost 即可
# 若不使用 IIS，改為 0.0.0.0 讓外部可直接存取
Host = 127.0.0.1
Port = 8080
```

### 步驟 A2：測試啟動

先手動確認程式可以正常運行：

```powershell
.\venv\Scripts\python.exe kepware_monitor.py
```

確認事項：
- OPC UA 連線成功
- WebUI 可在 `http://localhost:8080` 存取
- 健康檢查 API：`http://localhost:8080/api/health` 回傳 `{"status": "ok"}`

確認無誤後 `Ctrl+C` 停止程式。

### 步驟 A3：WinSW 服務包裝

#### 下載 WinSW

1. 前往 [WinSW Releases](https://github.com/winsw/winsw/releases)
2. 下載 `WinSW-x64.exe`
3. 重新命名為 `KepwareMonitorSvc.exe`，放到專案目錄

```powershell
# 下載並重命名
curl -L -o C:\Services\KepwareMonitor\KepwareMonitorSvc.exe https://github.com/winsw/winsw/releases/download/v3.0.0-alpha.11/WinSW-x64.exe
```

#### 建立服務設定檔

repo 內已附上可直接複製使用的範本：`deploy/winsw/venv/KepwareMonitorSvc.xml.example`。複製到專案目錄並改名（檔名必須與 WinSW exe 完全同名，僅副檔名不同）：

```powershell
copy deploy\winsw\venv\KepwareMonitorSvc.xml.example KepwareMonitorSvc.xml
```

內容如下（不需修改，`%BASE%` 由 WinSW 自動代換為 exe 所在目錄）：

```xml
<service>
  <id>KepwareMonitor</id>
  <name>Kepware Monitor OPC</name>
  <description>Kepware OPC UA 監控服務 — 設備數值監控、事件記錄、專案備份、Web UI</description>

  <!-- Python 執行檔與啟動參數 -->
  <executable>%BASE%\venv\Scripts\python.exe</executable>
  <arguments>kepware_monitor.py</arguments>
  <workingdirectory>%BASE%</workingdirectory>

  <!-- 服務啟動方式 -->
  <startmode>Automatic</startmode>
  <delayedAutoStart>true</delayedAutoStart>

  <!-- 異常退出時自動重啟 -->
  <onfailure action="restart" delay="10 sec" />
  <onfailure action="restart" delay="30 sec" />
  <onfailure action="restart" delay="60 sec" />
  <resetfailure>1 hour</resetfailure>

  <!-- 日誌設定（自動 rotate） -->
  <log mode="roll-by-size">
    <sizeThreshold>10240</sizeThreshold>
    <keepFiles>5</keepFiles>
    <logpath>%BASE%\logs</logpath>
  </log>

  <!-- 環境變數（選用） -->
  <env name="PYTHONUNBUFFERED" value="1" />
</service>
```

> **⚠️ `<onfailure>` 設定不可省略或移除。** 程式遇到未預期的致命例外時，會先完成清理再以 exit code 1 結束——這個設計就是依賴這裡的 restart 設定，讓 WinSW 接手自動重啟服務。若這段設定被拿掉，服務死掉後不會有任何機制自動復原，只能等人發現後手動重啟。

---

## 方式 B：PyInstaller 封裝佈署

適用於目標主機沒有 Python 環境，或 `asyncua` 套件僅相容特定 Python 版本的情況。在開發機打包後，僅需部署 exe + 設定檔。

### 步驟 B1：在開發機打包

打包設定已寫成 `KepwareMonitor.spec`（專案根目錄），不需要再手動組一長串 `--hidden-import` 參數：

```powershell
# 安裝 PyInstaller（開發機）
pip install pyinstaller

# 於專案根目錄執行，打包成單一執行檔
pyinstaller KepwareMonitor.spec
```

產出檔案在 `dist\KepwareMonitor.exe`。

> **為什麼改用 `.spec` 檔：** 原本用一長串 CLI `--hidden-import` 參數，容易複製貼上時漏行、漏打；`.spec` 是一份會被版控、可以 code review 的 Python 檔案，把所有打包設定集中在一處。`KepwareMonitor.spec` 已用 `collect_submodules()` 涵蓋 `uvicorn`/`asyncua`/`jinja2` 這幾個有動態載入子模組機制的套件（原本 CLI 指令只補了 uvicorn 的部分，並未涵蓋 asyncua 與登入表單需要的 `python-multipart`——若沿用舊指令，登入功能在打包後會直接壞掉），已用實測驗證過（含建立可執行檔並成功啟動 Web UI、驗證登入所需的 `multipart` 模組確實被打包進去）。
>
> 若未來新增相依套件後打包仍出現 `ModuleNotFoundError`，**請直接修改 `KepwareMonitor.spec`** 把缺少的模組加進 `hidden_imports`，不要只在當次手動加 CLI flag（那樣下次打包又會重現同樣的問題）。
>
> 打包後務必先在開發機手動執行 `dist\KepwareMonitor.exe` 確認無誤。

### 步驟 B2：測試啟動

```powershell
cd dist
mkdir Config
copy ..\Config\settings.example.ini Config\settings.ini
copy ..\Config\tags.example.csv Config\tags.csv

# 編輯 Config\settings.ini 後測試
.\KepwareMonitor.exe
```

確認 Web UI (`http://localhost:8080`) 與 OPC 連線正常後 `Ctrl+C` 停止。

### 步驟 B3：WinSW 服務包裝

#### 下載 WinSW

```powershell
curl -L -o C:\Services\KepwareMonitor\KepwareMonitorSvc.exe https://github.com/winsw/winsw/releases/download/v3.0.0-alpha.11/WinSW-x64.exe
```

#### 建立服務設定檔

repo 內已附上可直接複製使用的範本：`deploy/winsw/pyinstaller/KepwareMonitorSvc.xml.example`。複製到專案目錄並改名（檔名必須與 WinSW exe 完全同名，僅副檔名不同）：

```powershell
copy deploy\winsw\pyinstaller\KepwareMonitorSvc.xml.example KepwareMonitorSvc.xml
```

內容如下（不需修改）：

```xml
<service>
  <id>KepwareMonitor</id>
  <name>Kepware Monitor OPC</name>
  <description>Kepware OPC UA 監控服務 — 設備數值監控、事件記錄、專案備份、Web UI</description>

  <!-- PyInstaller 封裝的執行檔 -->
  <executable>%BASE%\KepwareMonitor.exe</executable>
  <workingdirectory>%BASE%</workingdirectory>

  <!-- 服務啟動方式 -->
  <startmode>Automatic</startmode>
  <delayedAutoStart>true</delayedAutoStart>

  <!-- 異常退出時自動重啟 -->
  <onfailure action="restart" delay="10 sec" />
  <onfailure action="restart" delay="30 sec" />
  <onfailure action="restart" delay="60 sec" />
  <resetfailure>1 hour</resetfailure>

  <!-- 日誌設定（自動 rotate） -->
  <log mode="roll-by-size">
    <sizeThreshold>10240</sizeThreshold>
    <keepFiles>5</keepFiles>
    <logpath>%BASE%\logs</logpath>
  </log>
</service>
```

> **方式 B 與 A 的差異：** `<executable>` 指向 `KepwareMonitor.exe`（PyInstaller 產出），不需 `<arguments>` 和 `venv`。
>
> **⚠️ `<onfailure>` 設定不可省略或移除**（原因同方式 A，見上方說明）。

## 安裝與管理服務（A / B 共用）

以**系統管理員**身分開啟命令提示字元：

```powershell
cd C:\Services\KepwareMonitor

# 安裝服務
.\KepwareMonitorSvc.exe install

# 啟動
.\KepwareMonitorSvc.exe start

# 查看狀態
.\KepwareMonitorSvc.exe status

# 停止
.\KepwareMonitorSvc.exe stop

# 重啟
.\KepwareMonitorSvc.exe restart

# 移除服務（需先停止）
.\KepwareMonitorSvc.exe uninstall
```

也可以用 Windows 標準指令管理：

```powershell
# 用 sc 查看
sc query KepwareMonitor

# 用 PowerShell
Get-Service KepwareMonitor

# 在 services.msc (服務管理員) 中也能看到
```

### WinSW XML 設定說明

| 標籤 | 說明 |
|------|------|
| `%BASE%` | 自動替換為 exe 所在目錄 |
| `delayedAutoStart` | 延遲啟動，等其他服務就緒後再啟動 |
| `onfailure` | 可設定多層重啟策略（10s → 30s → 60s） |
| `log mode="roll-by-size"` | 日誌自動 rotate，每 10MB 滾動，保留 5 個檔案 |
| `PYTHONUNBUFFERED` | 確保 Python 輸出即時寫入日誌（方式 A） |

## 啟用多台 Kepware Server

### 先理解：兩個各自獨立的設定區塊

| 區塊 | 負責 | 資料會出現在 |
|---|---|---|
| `[OPC] Servers` | OPC UA 點位數值監控（讀 tag、閾值告警） | Dashboard 連線狀態、設備列表、歷史查詢 |
| `[KepwareLog.<名稱>]` | Kepware API Gateway 監控（事件/交易 polling、專案備份） | 事件記錄頁、交易記錄頁、備份頁 |

兩者技術上**互相獨立**，可以只設其中一個（例如只監控 Gateway 事件、不接 OPC 點位）。但只要是同一台實體 Kepware，**名稱一定要取一致**——因為 Dashboard 的連線狀態來自 `[OPC] Servers`，備份頁的 Server 下拉選單來自 `[KepwareLog.*]`，名稱不一致不會壞掉，但你會在不同頁面看到兩組不同的名字，事後很難對帳。

---

### ⚠️ 加第二台之前必讀：CSV `Server` 欄位的行為會改變

這是加第二台最容易踩、而且**完全靜默**的地雷：

| 目前（單台） | 加了第二台之後 |
|---|---|
| CSV 的 `Server` 欄位**完全被忽略**，所有 `Enable=TRUE` 且有 NodeId 的設備都歸那一台 | 改成**嚴格比對**，`Server` 值必須與連線名稱完全相同，否則該設備**直接不被監控** |

也就是說：你現在 CSV 裡 `Server` 欄位不管填什麼（甚至留空）都能正常運作，但第二台一加上去，填錯或留空的那些設備會**無聲無息地停止監控**——不會報錯、Web UI 也不會標示，只有設備數量對不上。

實測確認的比對規則（`monitor_manager.py` `_parse_csv_row`）：

| CSV `Server` 欄位填法 | 實際解析結果 | 多台模式下 |
|---|---|---|
| `kepware_a` | `kepware_a` | ✅ 正常 |
| ` kepware_a `（前後空白） | `kepware_a`（自動 trim） | ✅ 正常 |
| `Kepware_A`（大小寫不同） | `Kepware_A` | ❌ **大小寫敏感，不匹配** |
| 留空 / 只有空白 | `''`（空字串，**不是** `default`） | ❌ **不匹配** |
| 整個欄位不存在 | `default` | ❌ 除非真的有一台叫 `default` |

**另一個要注意的點**：未匹配的警告**只在服務啟動時**檢查（`start()` 會記一筆 `logging.warning` 列出未匹配名稱）。之後從 Web UI 的 Tags 頁改 CSV，即使打錯 Server 名稱也**不會有任何警告**——熱重載不做這個檢查。所以改完 Tags 建議重啟一次服務，讓啟動檢查幫你把關。

---

### 步驟 1：先把 CSV 的 `Server` 欄位補正確

**在改 settings.ini 之前先做這一步**，因為單台模式下錯誤是看不出來的。打開 `Config/tags.csv`（或 Web UI 的 Tags 頁），確認每一列的 `Server` 欄位都填了正確、大小寫相符的名稱，沒有留空。

### 步驟 2：設定 `[OPC] Servers`

```ini
[OPC]
Servers = kepware_a|opc.tcp://192.168.1.10:49320,
          kepware_b|opc.tcp://10.0.0.5:49320
```

格式是 `名稱|opc.tcp://IP:Port`，多台用逗號分隔（可換行縮排，configparser 會接續）。

> 兩台共用同一組 `[OPC] SecurityPolicy` / `SecurityMode` / `Authentication` / `Username` / `Password`（全域設定，套用到所有連線）。若兩台認證方式不同，目前版本不支援分開設定，需先確認兩台能用同一種方式連線。

### 步驟 3：設定 `[KepwareLog.<名稱>]`

`Config/settings.example.ini` 裡第二台是註解起來的範本，取消註解並填入實際位址帳密。**section 名稱中 `.` 後面的字串就是 `server_name`**，要與步驟 2 的名稱一致：

```ini
[KepwareLog.kepware_b]
Enable = true
ApiBaseUrl = http://10.0.0.5:8000
Username = admin
Password = your_password
EventSubject = Kepware 事件監控通知
PollInterval = 600
# 其餘嚴重等級分類/閾值欄位比照 kepware_a，可用相同預設值
```

### 步驟 4：重啟服務並自檢

```powershell
KepwareMonitorSvc.exe restart
```

**(a) 看啟動 log**（`logs\*.log`），這三件事都要確認：

```
[kepware_a] 正在連線到 opc.tcp://... ←  兩台都要各出現一次
[kepware_b] 正在連線到 opc.tcp://...
已載入 N 個監控項目
```

如果出現這行，代表有設備的 `Server` 名稱對不上，**這些設備不會被監控**，回步驟 1 修正：

```
CSV 中有未匹配的 Server 名稱: {...}，可用連線: {...}，這些設備將不會被監控！
```

**(b) 用 `/api/health` 一次確認兩半邊**（這支不需登入）：

```powershell
curl http://localhost:8080/api/health
```

`opc_connections` 要有兩筆且 `connected: true`；`kepware_logs` 也要有兩筆：

```json
{
  "status": "ok",
  "opc_connections": [
    {"server": "kepware_a", "url": "opc.tcp://...", "connected": true},
    {"server": "kepware_b", "url": "opc.tcp://...", "connected": true}
  ],
  "kepware_logs": [
    {"server": "kepware_a", "poll_interval": 600, ...},
    {"server": "kepware_b", "poll_interval": 600, ...}
  ]
}
```

> `devices.total` / `enabled` 是**全部加總、不分 Server**，看不出第二台的設備有沒有被正確匹配——那要靠上面 (a) 的 log 或下面 (c) 的 Dashboard。

**(c) 開 Dashboard 目視確認**：設備列表有 `Server` 欄位，確認兩台的設備都出現、數量與 CSV 相符。

---

### 已知行為與限制

- **第二台還沒開通也可以先設定**：初次連線失敗不會中斷啟動，該台只會記一筆 warning 並標記為未連線，第一台照常監控，之後由主監控迴圈自動重試連線。所以可以先把設定寫好，等網路/port 開通後它會自己接上，不需要改設定或重啟。
- **一台斷線會拖慢另一台**：目前各 Server 是在同一個迴圈內**依序處理**，某台斷線時會走完重連流程（最壞情況約 1～2 分鐘）才輪到下一台，期間另一台健康的 Server 讀值與告警會被延後。這是已知限制（複查報告 H2），不影響正確性，只影響故障時的反應速度。
- **事件去重已按 Server 分開**：兩台送出時間與訊息內容完全相同的事件不會互相被當成重複而丟棄（去重雜湊已納入 `server_name`）。
- **告警信的 Server 標示位置不一致**（若你要用信件主旨設 Outlook 收信規則要注意）：
  - Kepware 事件告警、連線異常/復歸告警：**主旨就有** Server 名稱（例如 `[緊急] ... - [kepware_b] 關鍵事件`）
  - 設備數值告警：主旨只有設備名稱，Server 名稱在**信件內文**的「Kepware Server」欄位
  - 收件人三者都沿用 `[Mail]` 的全域設定（`To` / `Cc`），CSV 的 `MailTo` / `MailCc` 會再額外併入該設備的告警。

## IIS 反向代理（選用）

> 如果不需要自訂域名或 HTTPS，可以跳過此步驟，直接用 `http://伺服器IP:8080` 存取。

### 安裝必要模組

1. **ARR (Application Request Routing)**
   - 下載：https://www.iis.net/downloads/microsoft/application-request-routing
   - 或使用 Web Platform Installer 搜尋 "ARR"

2. **URL Rewrite**
   - 下載：https://www.iis.net/downloads/microsoft/url-rewrite
   - 通常安裝 ARR 時會自動安裝

### 啟用 Proxy 功能

開啟 IIS 管理員：

1. 點選最上層的**伺服器節點**
2. 雙擊 **Application Request Routing Cache**
3. 右側點選 **Server Proxy Settings**
4. 勾選 **Enable proxy**
5. 點右側 **套用**

### 建立 IIS 站台

1. 在 IIS 管理員，右鍵 **Sites** → **新增網站**
2. 設定：

| 欄位 | 值 |
|------|------|
| 站台名稱 | `KepwareMonitor` |
| 實體路徑 | `C:\inetpub\KepwareMonitor` (空目錄即可) |
| 繫結 Port | `80` (或 `443` 若使用 HTTPS) |
| 主機名稱 | `kepware-monitor.company.com` (依公司設定) |

### 設定 URL Rewrite 規則

在站台根目錄建立 `web.config`：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<configuration>
  <system.webServer>
    <rewrite>
      <rules>
        <rule name="ReverseProxyToKepwareMonitor" stopProcessing="true">
          <match url="(.*)" />
          <action type="Rewrite" url="http://localhost:8080/{R:1}" />
        </rule>
      </rules>
    </rewrite>
  </system.webServer>
</configuration>
```

> **不要加 `<webSocket enabled="true" />`。** 本專案的即時更新（Dashboard）使用 SSE（Server-Sent Events，`text/event-stream`），**沒有用到 WebSocket**；而 `system.webServer/webSocket` 區段在 IIS 預設是鎖定、不允許站台層級覆寫的，加了會讓整個站台回
> `HTTP 500.19 (0x80070021) — 設定區段在上層被鎖定`，連首頁都打不開。

### SSE 即時更新：關閉 ARR 回應緩衝

ARR 預設會緩衝後端回應才轉發，這會讓 SSE 的即時推播被卡住（Dashboard 數值不會即時更新，可能要等連線關閉才一次跳出來）。設定方式：

IIS 管理員 → 點選**最上層伺服器節點** → **Application Request Routing Cache** → 右側 **Server Proxy Settings** → 把 **Response buffer threshold (KB)** 改為 `0` → 套用。

（若 Dashboard 透過 IIS 存取時數值不即時、但直連 `http://IP:8080` 正常，就是這個設定沒關。）

### HTTPS 設定（建議）

1. 取得 SSL 憑證（公司內部 CA 或自簽）
2. 在 IIS 站台繫結中新增 HTTPS (443) 繫結
3. 選取憑證
4. （選用）新增 HTTP → HTTPS 重導向規則

## 驗證

### 確認服務運行

```powershell
# 檢查 Windows 服務
Get-Service KepwareMonitor

# 檢查 WinSW 狀態
cd C:\Services\KepwareMonitor
.\KepwareMonitorSvc.exe status

# 檢查 Port 監聽
netstat -an | findstr "8080"

# 查看服務日誌
type logs\KepwareMonitorSvc.out.log
type logs\KepwareMonitorSvc.err.log
```

### 健康檢查

```powershell
# 直連 Python 服務
curl http://localhost:8080/api/health

# 透過 IIS（若有設定）
curl http://kepware-monitor.company.com/api/health
```

回傳範例：

```json
{
  "status": "ok",
  "timestamp": "2026-05-07 14:30:00",
  "opc_connections": [
    {"server": "kepware_a", "url": "opc.tcp://192.168.1.10:49320", "connected": true}
  ],
  "database": {"path": "data/monitor.db", "size_mb": 12.5, "status": "ok"},
  "devices": {"total": 25, "enabled": 22},
  "kepware_logs": [
    {"server": "kepware_a", "poll_interval": 600, "daily_summary_sent": "2026-05-07"}
  ]
}
```

### 外部監控整合

可將 `/api/health` 加入公司監控平台（如 Uptime Kuma、PRTG）：

| 檢查項目 | 方法 |
|---------|------|
| 服務是否存活 | `GET /api/health`，確認 HTTP 200 |
| OPC 連線狀態 | 檢查 `status` 是否為 `ok`（`degraded` = 有連線斷開） |
| DB 大小 | 檢查 `database.size_mb`，設定告警門檻 |

## 常見問題

### 服務啟動失敗

```powershell
# 查看 WinSW 日誌
type C:\Services\KepwareMonitor\logs\KepwareMonitorSvc.err.log
type C:\Services\KepwareMonitor\logs\KepwareMonitorSvc.wrapper.log

# 手動測試（方式 A）
cd C:\Services\KepwareMonitor
.\venv\Scripts\python.exe kepware_monitor.py

# 手動測試（方式 B）
cd C:\Services\KepwareMonitor
.\KepwareMonitor.exe
```

### IIS 500.19（首頁完全打不開）

先看 IIS log（`C:\inetpub\logs\LogFiles\W3SVC<站台ID>\`）最後一欄的 `sc-win32-status`，不同代碼原因完全不同：

| win32 code | 意義 | 處理 |
|---|---|---|
| `13` | 設定區段無法辨識 | URL Rewrite 模組沒裝成功。到「控制台 → 程式和功能」確認有 `IIS URL Rewrite Module 2`；裝完後**要把 IIS 管理員視窗完全關閉再重開**才會出現圖示（只按 F5 或 `iisreset` 不會刷新介面） |
| `33` | 設定區段在上層被鎖定 | `web.config` 用到不允許站台層級覆寫的區段。最常見是誤加了 `<webSocket>`（本專案不需要，見上方說明）。若確認是 `<rewrite>` 被鎖，執行：`%windir%\system32\inetsrv\appcmd.exe unlock config -section:system.webServer/rewrite` |
| `5` | 存取被拒 | IIS 執行身分對 `web.config` 沒有讀取權限，檢查該檔案的 NTFS 權限 |

> **排查前先確認請求真的送到正確站台**：IIS log 資料夾 `W3SVC<N>` 的 `<N>` 是站台 ID（IIS 管理員 → Sites 清單的 ID 欄位）。若請求跑到 `Default Web Site` 的 log 裡，代表站台繫結的主機名稱沒對上，改設定 `KepwareMonitor` 站台的 `web.config` 是不會有任何效果的。

### IIS 502 Bad Gateway

1. 確認 Python 服務有在跑：`netstat -an | findstr "8080"`
2. 確認 ARR Proxy 已啟用
3. 檢查 IIS 錯誤日誌：`C:\inetpub\logs\LogFiles\`

### 用 hostname 連不上，但 `http://IP:8080` 正常

`http://IP:8080` 是**直接打到後端 uvicorn、完全繞過 IIS**，這條通不代表 IIS 反向代理有在運作（IIS 服務停掉它照樣會通）。要驗證 IIS，網址必須是**不帶 port** 的 `http://<hostname>`。

若 hostname 連不上，依序確認：

1. **DNS 有沒有解析**：在用戶端執行 `nslookup <hostname>`。若解析不到，在測試機的 `C:\Windows\System32\drivers\etc\hosts` 加一行 `<伺服器IP>  <hostname>`（只填 hostname，不含 `http://`），存檔後 `ipconfig /flushdns`。
   > hosts 只對編輯的那台電腦有效，僅適合自己驗證；要讓其他人也能用，需請網管在內部 DNS 加 A 記錄。
2. **站台繫結**：IIS 管理員 → 站台 → 繫結，確認有 `http` / port `80` / 主機名稱與網址列完全一致。
3. **確認是哪個站台在回應**：見上方 500.19 段落的站台 ID 說明。`Default Web Site` 通常是無主機名稱的 catch-all，會攔截沒對上其他站台的請求，排查時可暫時停用以排除干擾。

### OPC UA 連線失敗

1. 確認 Kepware 服務正在運行
2. 確認防火牆允許 Port 49320
3. 確認 `settings.ini` 中的 SecurityPolicy/SecurityMode 設定正確

### 程式更新

> **⚠️ 務必用整樹複製（`xcopy /E`），不要手動單檔複製。** 專案內的 `.py` 檔案彼此有相依關係（例如 `monitor_manager.py` 會呼叫 `opc_connection.py` 新增的方法），逐一手動複製容易漏掉其中一個檔案，導致新舊版本混用、行為異常且不易察覺（曾實際發生過：漏複製 `opc_connection.py` 導致監控誤判斷線、比修復前更不穩定）。若受限於環境只能單檔傳輸，更新後務必比對來源與目的地目錄下**所有** `.py` 檔案的修改時間/雜湊完全一致，不要只挑「這次改到的檔案」複製。

**方式 A（venv）：**

`/EXCLUDE` 需要的排除清單已附在 repo：`deploy\winsw\exclude.txt.example`（排除 `Config\settings.ini`、`Config\tags.csv`、`data\`、`logs\`，避免更新時覆蓋掉正式機的設定與資料）。第一次更新前複製一份到專案目錄：

```powershell
copy deploy\winsw\exclude.txt.example exclude.txt
```

```powershell
cd C:\Services\KepwareMonitor

# 1. 停止服務
.\KepwareMonitorSvc.exe stop

# 2. 更新檔案（保留 Config、data、logs，見上方 exclude.txt）
xcopy /E /Y \\source\KepwareMonitorOPC . /EXCLUDE:exclude.txt

# 3. 更新套件（如有新增，requirements.txt 已鎖定版本上限，不會意外裝到不相容新版）
.\venv\Scripts\pip.exe install -r requirements.txt

# 4. 重啟服務
.\KepwareMonitorSvc.exe start
```

**方式 B（PyInstaller）：**

```powershell
cd C:\Services\KepwareMonitor

# 1. 停止服務
.\KepwareMonitorSvc.exe stop

# 2. 替換執行檔（在開發機重新打包後複製過來）
copy /Y \\source\dist\KepwareMonitor.exe .

# 3. 重啟服務
.\KepwareMonitorSvc.exe start
```

## 目錄結構（部署後）

### 方式 A（venv）

```
C:\Services\KepwareMonitor\
├── KepwareMonitorSvc.exe    # WinSW 執行檔
├── KepwareMonitorSvc.xml    # WinSW 服務設定
├── venv\                    # Python 虛擬環境
├── Config\
│   ├── settings.ini         # 設定檔
│   └── tags.csv             # 監控設備清單
├── data\
│   ├── monitor.db           # SQLite 資料庫
│   └── backup_schedule.json # 備份排程設定
├── logs\
│   ├── KepwareMonitorSvc.out.log    # stdout（自動 rotate）
│   ├── KepwareMonitorSvc.err.log    # stderr（自動 rotate）
│   ├── KepwareMonitorSvc.wrapper.log # WinSW 本身日誌
│   └── *.log                        # 應用程式日誌
├── web\                     # Web UI
├── kepware_monitor.py       # 主程式
├── requirements.txt
└── ...
```

### 方式 B（PyInstaller）

```
C:\Services\KepwareMonitor\
├── KepwareMonitor.exe       # PyInstaller 封裝的主程式
├── KepwareMonitorSvc.exe    # WinSW 執行檔
├── KepwareMonitorSvc.xml    # WinSW 服務設定
├── Config\
│   ├── settings.ini         # 設定檔
│   └── tags.csv             # 監控設備清單
├── data\
│   ├── monitor.db           # SQLite 資料庫
│   └── backup_schedule.json # 備份排程設定
└── logs\
    ├── KepwareMonitorSvc.out.log    # stdout（自動 rotate）
    ├── KepwareMonitorSvc.err.log    # stderr（自動 rotate）
    ├── KepwareMonitorSvc.wrapper.log # WinSW 本身日誌
    └── *.log                        # 應用程式日誌
```

> **注意：** 方式 B 不需要 `venv\`、`web\`、`*.py` 等原始碼，PyInstaller 已將所有 Python 程式碼和靜態資源打包進 `KepwareMonitor.exe`。

## 設定檔安全性

`Config\settings.ini` 內含 OPC UA、Kepware API Gateway、SMTP 帳號密碼，皆為**明文儲存**（無加密）。部署時請務必限制此檔案的存取權限：

1. 用檔案總管右鍵點選 `Config\` 資料夾 → **內容** → **安全性** 頁籤
2. 移除 `Users`（一般使用者群組）的讀取權限，僅保留：
   - 執行此服務的帳號（例如 `NT AUTHORITY\SYSTEM` 或指定的服務帳號）
   - 本機系統管理員（`Administrators`）
3. 或用 PowerShell 一次設定（以系統管理員身分執行）：
   ```powershell
   icacls "C:\Services\KepwareMonitor\Config" /inheritance:r
   icacls "C:\Services\KepwareMonitor\Config" /grant:r "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)F"
   ```

此外，`data\monitor.db` 內含歷史監控資料與使用者帳號（密碼已雜湊），`logs\` 目錄可能記錄部分診斷資訊，建議一併套用相同的存取權限限制。
