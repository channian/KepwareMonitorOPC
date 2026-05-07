# IIS + NSSM 部署指南

本文件說明如何在 Windows Server 環境中，使用 IIS 反向代理 + NSSM 服務包裝，將 KepwareMonitorOPC 部署為正式服務。

## 架構

```
外部使用者 (瀏覽器)
    ↓ HTTP/HTTPS (Port 80/443)
IIS (反向代理)
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
| IIS | 需安裝 ARR + URL Rewrite 模組 |
| NSSM | 最新版 (nssm.cc) |
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

確認 WebUI 設定：

```ini
[WebUI]
Enable = true
Host = 127.0.0.1    # 只綁定 localhost，由 IIS 對外
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

## 步驟 3：NSSM 服務包裝

### 安裝 NSSM

1. 從 [nssm.cc](https://nssm.cc/download) 下載最新版
2. 解壓縮到 `C:\Tools\nssm\`（或加入系統 PATH）

### 建立 Windows 服務

```powershell
# 安裝服務
C:\Tools\nssm\nssm.exe install KepwareMonitor

# NSSM GUI 設定畫面會彈出，填入以下資訊：
```

| Tab | 欄位 | 值 |
|-----|------|------|
| Application | Path | `C:\Services\KepwareMonitor\venv\Scripts\python.exe` |
| Application | Startup directory | `C:\Services\KepwareMonitor` |
| Application | Arguments | `kepware_monitor.py` |
| Details | Display name | `Kepware Monitor OPC` |
| Details | Description | `Kepware OPC UA 監控服務` |
| Details | Startup type | `Automatic` |
| I/O | Output (stdout) | `C:\Services\KepwareMonitor\logs\service-stdout.log` |
| I/O | Error (stderr) | `C:\Services\KepwareMonitor\logs\service-stderr.log` |
| Exit actions | Restart Action | `Restart application` |
| Exit actions | Delay (ms) | `10000` (10 秒後重啟) |

或使用命令列模式：

```powershell
nssm install KepwareMonitor "C:\Services\KepwareMonitor\venv\Scripts\python.exe" "kepware_monitor.py"
nssm set KepwareMonitor AppDirectory "C:\Services\KepwareMonitor"
nssm set KepwareMonitor DisplayName "Kepware Monitor OPC"
nssm set KepwareMonitor Description "Kepware OPC UA 監控服務"
nssm set KepwareMonitor Start SERVICE_AUTO_START
nssm set KepwareMonitor AppStdout "C:\Services\KepwareMonitor\logs\service-stdout.log"
nssm set KepwareMonitor AppStderr "C:\Services\KepwareMonitor\logs\service-stderr.log"
nssm set KepwareMonitor AppRestartDelay 10000
```

### 服務管理

```powershell
# 啟動
nssm start KepwareMonitor

# 停止
nssm stop KepwareMonitor

# 重啟
nssm restart KepwareMonitor

# 查看狀態
nssm status KepwareMonitor

# 移除服務（需先停止）
nssm remove KepwareMonitor confirm
```

## 步驟 4：IIS 反向代理

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

1. 選取剛建立的站台
2. 雙擊 **URL Rewrite**
3. 右側 **新增規則** → **反向 Proxy**
4. 填入：`localhost:8080`
5. 或手動建立規則：

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

# 檢查 Port 監聽
netstat -an | findstr "8080"
```

### 確認 IIS 反向代理

```powershell
# 直連 Python 服務
curl http://localhost:8080/api/health

# 透過 IIS
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
# 查看 NSSM 日誌
type C:\Services\KepwareMonitor\logs\service-stderr.log

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
# 1. 停止服務
nssm stop KepwareMonitor

# 2. 更新檔案
xcopy /E /Y \\source\KepwareMonitorOPC C:\Services\KepwareMonitor

# 3. 更新套件（如有新增）
.\venv\Scripts\pip.exe install -r requirements.txt

# 4. 重啟服務
nssm start KepwareMonitor
```

## 目錄結構（部署後）

```
C:\Services\KepwareMonitor\
├── venv\                    # Python 虛擬環境
├── Config\
│   ├── settings.ini         # 設定檔
│   └── tags.csv             # 監控設備清單
├── data\
│   └── monitor.db           # SQLite 資料庫
├── logs\
│   ├── service-stdout.log   # NSSM stdout
│   ├── service-stderr.log   # NSSM stderr
│   └── *.log                # 應用程式日誌
├── web\                     # Web UI
├── kepware_monitor.py       # 主程式
├── requirements.txt
└── ...
```
