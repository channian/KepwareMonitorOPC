# IIS + WinSW 部署指南

本文件說明如何在 Windows Server 環境中，使用 IIS 反向代理 + WinSW 服務包裝，將 KepwareMonitorOPC 部署為正式服務。

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
    ├→ Kepware API Gateway (事件 polling)
    ├→ SQLite (資料儲存)
    └→ Email / Webhook (派報)
```

## 前置需求

| 項目 | 版本/說明 |
|------|----------|
| Windows Server | 2016 / 2019 / 2022 |
| Python | 3.8+ (建議 3.10+) |
| .NET Framework | 4.6.1+ (WinSW 需要，Windows Server 內建) |
| IIS | 選用，需安裝 ARR + URL Rewrite 模組 |
| 網路 | 可連線 Kepware OPC UA Server |

## 步驟 1：Python 環境

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

## 步驟 2：測試啟動

先手動確認程式可以正常運行：

```powershell
.\venv\Scripts\python.exe kepware_monitor.py
```

確認事項：
- OPC UA 連線成功
- WebUI 可在 `http://localhost:8080` 存取
- 健康檢查 API：`http://localhost:8080/api/health` 回傳 `{"status": "ok"}`

確認無誤後 `Ctrl+C` 停止程式。

## 步驟 3：WinSW 服務包裝

### 下載 WinSW

1. 前往 [WinSW Releases](https://github.com/winsw/winsw/releases)
2. 下載 `WinSW-x64.exe`
3. 重新命名為 `KepwareMonitor.exe`，放到專案目錄

```powershell
# 下載並重命名
curl -L -o C:\Services\KepwareMonitor\KepwareMonitor.exe https://github.com/winsw/winsw/releases/download/v3.0.0-alpha.11/WinSW-x64.exe
```

### 建立服務設定檔

在同一目錄建立 `KepwareMonitor.xml`（檔名必須與 exe 一致）：

```xml
<service>
  <id>KepwareMonitor</id>
  <name>Kepware Monitor OPC</name>
  <description>Kepware OPC UA 監控服務 — 設備數值監控、事件 Log 監控、Web UI</description>

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

### 安裝與管理

```powershell
cd C:\Services\KepwareMonitor

# 安裝服務
.\KepwareMonitor.exe install

# 啟動
.\KepwareMonitor.exe start

# 查看狀態
.\KepwareMonitor.exe status

# 停止
.\KepwareMonitor.exe stop

# 重啟
.\KepwareMonitor.exe restart

# 移除服務（需先停止）
.\KepwareMonitor.exe uninstall
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
| `PYTHONUNBUFFERED` | 確保 Python 輸出即時寫入日誌 |

## 步驟 4：IIS 反向代理（選用）

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

## 步驟 5：驗證

### 確認服務運行

```powershell
# 檢查 Windows 服務
Get-Service KepwareMonitor

# 檢查 WinSW 狀態
cd C:\Services\KepwareMonitor
.\KepwareMonitor.exe status

# 檢查 Port 監聽
netstat -an | findstr "8080"

# 查看服務日誌
type logs\KepwareMonitor.out.log
type logs\KepwareMonitor.err.log
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
type C:\Services\KepwareMonitor\logs\KepwareMonitor.err.log
type C:\Services\KepwareMonitor\logs\KepwareMonitor.wrapper.log

# 手動測試
cd C:\Services\KepwareMonitor
.\venv\Scripts\python.exe kepware_monitor.py
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

```powershell
cd C:\Services\KepwareMonitor

# 1. 停止服務
.\KepwareMonitor.exe stop

# 2. 更新檔案（保留 Config、data、logs）
xcopy /E /Y \\source\KepwareMonitorOPC . /EXCLUDE:exclude.txt

# 3. 更新套件（如有新增）
.\venv\Scripts\pip.exe install -r requirements.txt

# 4. 重啟服務
.\KepwareMonitor.exe start
```

## 目錄結構（部署後）

```
C:\Services\KepwareMonitor\
├── KepwareMonitor.exe       # WinSW 執行檔
├── KepwareMonitor.xml       # WinSW 服務設定
├── venv\                    # Python 虛擬環境
├── Config\
│   ├── settings.ini         # 設定檔
│   └── tags.csv             # 監控設備清單
├── data\
│   └── monitor.db           # SQLite 資料庫
├── logs\
│   ├── KepwareMonitor.out.log    # stdout（自動 rotate）
│   ├── KepwareMonitor.err.log    # stderr（自動 rotate）
│   ├── KepwareMonitor.wrapper.log # WinSW 本身日誌
│   └── *.log                     # 應用程式日誌
├── web\                     # Web UI
├── kepware_monitor.py       # 主程式
├── requirements.txt
└── ...
```
