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

```powershell
# 安裝 PyInstaller（開發機）
pip install pyinstaller

# 打包成單一執行檔
pyinstaller --onefile --name KepwareMonitor ^
    --add-data "web/templates;web/templates" ^
    --add-data "web/static;web/static" ^
    --hidden-import uvicorn.logging ^
    --hidden-import uvicorn.loops.auto ^
    --hidden-import uvicorn.protocols.http.auto ^
    --hidden-import uvicorn.protocols.websockets.auto ^
    --hidden-import uvicorn.lifespan.on ^
    kepware_monitor.py
```

產出檔案在 `dist\KepwareMonitor.exe`。

> **注意：** 若執行時出現 `ModuleNotFoundError`，需追加對應的 `--hidden-import`。常見需要追加的模組：
> - `asyncua` 的子模組（如 `asyncua.crypto`）
> - `jinja2.ext`
> - `email.mime.multipart`、`email.mime.text`（Email 相關）
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

`Config/settings.example.ini` 已內建雙台範例，兩個區塊要對應同一台 Server：

1. **`[OPC] Servers`**：OPC UA 連線清單，格式 `名稱|opc.tcp://IP:Port`，多台用逗號分隔：

   ```ini
   [OPC]
   Servers = kepware_a|opc.tcp://192.168.1.10:49320,
             kepware_b|opc.tcp://10.0.0.5:49320
   ```

2. **`[KepwareLog.<名稱>]`**：每台 Kepware 各自的 API Gateway 監控設定（事件/交易 polling、專案備份）。`<名稱>` 必須與上面 `Servers` 裡的名稱**完全一致**（例如 `kepware_b`），這個名稱就是系統內部用來區分兩台資料的 `server_name`。example 檔案裡第二台是註解起來的範本，取消註解並填入實際的 API Gateway 位址、帳密即可：

   ```ini
   [KepwareLog.kepware_b]
   Enable = true
   ApiBaseUrl = http://10.0.0.5:8000
   Username = admin
   Password = your_password
   EventSubject = Kepware 事件監控通知
   PollInterval = 600
   # ... 其餘欄位比照 kepware_a，可用相同預設值
   ```

3. 兩台名稱只要一致對應，Web UI（Tags/歷史/事件/備份）與告警信都會自動依 `server_name` 分開顯示與統計，不需要額外設定。

> 兩台 Server 用同一組 `[OPC] SecurityPolicy/SecurityMode/Authentication`（全域設定，套用到全部連線）；若兩台認證方式不同，目前版本尚不支援分開設定，需先確認兩台可用同一種認證方式連線。

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
    <webSocket enabled="true" />
  </system.webServer>
</configuration>
```

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

### IIS 502 Bad Gateway

1. 確認 Python 服務有在跑：`netstat -an | findstr "8080"`
2. 確認 ARR Proxy 已啟用
3. 檢查 IIS 錯誤日誌：`C:\inetpub\logs\LogFiles\`

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
