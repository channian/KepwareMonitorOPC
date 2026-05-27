# Kepware OPC UA 監控系統

透過 OPC UA 協定定期讀取 Kepware Server 的設備數值，當數值超出閾值時自動發送 Email 與 Webhook 推播通知，並提供 Web UI 管理介面。

## 功能特色

- **多台 Kepware Server** — 同時監控多台 OPC UA Server
- **彈性閾值設定** — 支援數值比較（大於/小於/等於）、布林判斷、數值不變偵測、動態閥值（移動平均 ± k*σ）、純記錄模式
- **Kepware Event Log 監控** — 整合 Kepware API Gateway，自動分類事件嚴重等級（Critical/Warning/Advisory），自適應閥值派報
- **Kepware 專案備份** — 透過 API Gateway 執行 Kepware 專案備份，支援手動觸發與每週排程，備份記錄可追溯
- **累積觸發機制** — 連續 N 次異常才派報，避免瞬間抖動誤報
- **復歸通知** — 設備恢復正常時自動發送復歸通知
- **三層式網路診斷** — Ping 主機、TCP Port 檢測、設備 IP 檢測，定位斷線層級
- **Email 派報** — HTML 格式，支援全域/設備獨立收件人
- **Webhook 推播** — 支援自訂 JSON Body 模板，Token 驗證，Proxy 設定
- **Web UI 管理介面** — 即時儀表板（SSE）、歷史紀錄查詢匯出、設定管理、帳號管理、深/淺色模式切換
- **CSV 匯入/匯出** — Web UI 支援 CSV 整批上傳與下載，修改後自動偵測並重新載入，無需重啟
- **OPC UA 安全設定** — 支援 SecurityPolicy、SecurityMode、帳號密碼認證

## 專案結構

```
KepwareMonitorOPC/
├── kepware_monitor.py        # 主程式進入點
├── monitor_manager.py        # 監控核心邏輯
├── opc_connection.py         # OPC UA 連線管理
├── ase_email_service.py      # Email 派報服務
├── webhook_service.py        # Webhook 推播服務
├── diagnostic_service.py     # 三層式網路診斷
├── kepware_log_service.py    # Kepware Event Log 監控服務
├── db_service.py             # SQLite 資料庫服務
├── requirements.txt          # Python 套件相依
├── Config/
│   ├── settings.example.ini  # 設定檔範例
│   └── tags.example.csv      # 監控設備 CSV 範例
└── web/
    ├── api.py                # FastAPI Web 後端
    ├── auth.py               # 登入驗證
    ├── static/               # 靜態資源
    └── templates/            # Jinja2 頁面模板
```

## 快速開始

### 1. 安裝相依套件

```bash
pip install -r requirements.txt
```

### 2. 建立設定檔

```bash
cp Config/settings.example.ini Config/settings.ini
cp Config/tags.example.csv Config/tags.csv
```

編輯 `Config/settings.ini`，設定 OPC Server 連線、Email、Webhook 等資訊。

### 3. 設定監控設備

編輯 `Config/tags.csv`，每一行代表一個監控設備：

| 欄位 | 說明 | 範例 |
|------|------|------|
| Name | 設備名稱 | K21GMS |
| NodeId | OPC UA Node ID | ns=2;s=K21GMS.GMS._System._SecondsInError |
| Description | 描述（用於通知內容） | K21GMS |
| MailTo | 指定收件人（選填，覆蓋全域） | user@company.com |
| MailCc | 指定副本（選填） | |
| Type | 監控類型：number / bool / log | number |
| Condition | 比較條件：greater / less / equal / not_equal / unchanged / dynamic | greater |
| Threshold | 閾值 | 300 |
| CountNeeded | 累積幾次才派報 | 1 |
| Enable | 是否啟用：TRUE / FALSE | TRUE |
| Server | 指定 Server 名稱（多台時使用） | |
| DeviceIP | 設備 IP（用於三層診斷） | |
| DevicePort | 設備 Port（用於三層診斷） | |

### 4. 啟動

```bash
python kepware_monitor.py
```

## 設定說明

### OPC UA 連線

```ini
[OPC]
# 多台 Server
Servers = kepware_a|opc.tcp://192.168.1.10:49320,
          kepware_b|opc.tcp://10.0.0.5:49320

# 安全設定
SecurityPolicy = None
SecurityMode = None
Authentication = anonymous
```

### Email 派報

```ini
[Mail]
SmtpServer = smtp.example.com
Port = 25
From = kepware-monitor@example.com
To = it-admin@example.com
Subject = Kepware 設備監控通知
```

### Webhook 推播

```ini
[Webhook]
Enable = true
Url = https://your-api.com/notify
Token = your_token_here
Timeout = 10
BodyTemplate = {"token": "{{$token}}", "push_para": {"message": "{{$message}}"}}
VerifySSL = false
UseProxy = false
```

**BodyTemplate 可用變數：**

| 變數 | 說明 | 範例 |
|------|------|------|
| `{{$token}}` | 設定檔中的 Token | 2b8672a4... |
| `{{$message}}` | 完整通知訊息 | [異常] K21GMS\nServer: ... |
| `{{$server_name}}` | Server 名稱 | kepware_a |
| `{{$device_name}}` | 設備名稱 | K21GMS |
| `{{$value}}` | 當前數值 | 350 |
| `{{$threshold}}` | 閾值 | 300 |
| `{{$condition}}` | 比較條件 | greater |
| `{{$counter}}` | 累積次數 | 3 |
| `{{$accumulate}}` | 累積需求 | 3 |
| `{{$diagnostic}}` | 診斷訊息 | Host unreachable |
| `{{$timestamp}}` | 時間戳記 | 2025-02-17 14:30:45 |
| `{{$status}}` | 狀態 | 異常 / 復歸 |

### Web UI

```ini
[WebUI]
Enable = true
Host = 0.0.0.0
Port = 8080
```

啟用後瀏覽 `http://your-ip:8080`，首次啟動需建立管理員帳號。

**功能頁面：**

| 頁面 | 說明 |
|------|------|
| 儀表板 | 即時監控狀態（SSE 自動更新） |
| 歷史紀錄 | 查詢與匯出設備數值歷史（CSV） |
| 派報紀錄 | 查詢異常/復歸通知紀錄 |
| Kepware 事件 | 事件記錄 / 操作記錄查詢（依日期、Channel、嚴重等級篩選） |
| 專案備份 | 手動 / 排程備份管理，備份記錄查詢 |
| Tags 管理 | 線上編輯 tags.csv |
| 系統設定 | 線上編輯 settings.ini（含 Webhook 測試按鈕） |
| 帳號管理 | 使用者 CRUD、角色權限 |

## 監控流程

```
讀取 OPC 數值 → 比對閾值 → 累積計數 → 觸發派報
                                         ├→ Email（含三層診斷）
                                         ├→ Webhook 推播（背景執行緒）
                                         └→ 資料庫紀錄

數值恢復正常 → 發送復歸通知 → 重置計數器
```

## 三層式網路診斷

當設備數值異常時，自動執行網路診斷，定位問題層級：

| 層級 | 檢測項目 | 失敗訊息 |
|------|---------|---------|
| Layer 1 | Ping Kepware 主機 | 主機無法連線 |
| Layer 2 | TCP 連線 OPC Port | OPC 服務未回應 |
| Layer 3 | Ping 設備 IP / TCP Port | 設備無法連線 / IGS 服務未回應 |

## 自訂通知內容

### 修改位置總覽

| 要改什麼 | 檔案 | 位置 | 需改程式 |
|---------|------|------|---------|
| Email 主旨 | `monitor_manager.py` | 約第 401 行 | 是 |
| Email HTML 內容 | `monitor_manager.py` | 約第 402~417 行 | 是 |
| Webhook Body 結構 | `Config/settings.ini` | `[Webhook]` BodyTemplate | 否 |
| Webhook `{{$message}}` 格式 | `webhook_service.py` | `build_variables` 方法，約第 169~176 行 | 是 |
| 三層診斷訊息 | `diagnostic_service.py` | 第 141、151、157 行 | 是 |

### Email 信件

信件的 HTML 內容定義在 `monitor_manager.py` 的 `send_device_alert` 方法中：

- **主旨**（約第 401 行）：`subject = f"{status_tag} {self.mail_subject} - {device.name}"`
- **HTML 本文**（約第 402~417 行）：`html_body = f"""..."""`

可在 f-string 中使用的變數：`device.name`、`device.server_name`、`device.condition`、`device.threshold`、`device.counter`、`device.accumulate`、`value`、`color_hex`、`title_text`、`diag_html`

### Webhook 推播

1. **BodyTemplate**（`settings.ini`，不需改程式）：透過 `[Webhook]` 的 `BodyTemplate` 組合變數，可用變數見上方「BodyTemplate 可用變數」表格
2. **message 變數內容**（需改程式）：定義在 `webhook_service.py` 的 `build_variables` 方法（約第 169~176 行）

### 三層診斷訊息

診斷訊息定義在 `diagnostic_service.py` 的以下位置：

| 行號 | 訊息 | 說明 |
|------|------|------|
| 141 | `iFIX/IGS 機台 {ip} 無法連線 (Ping 失敗，可能已關機)` | 設備 Ping 失敗 |
| 151 | `iFIX/IGS 機台 {ip} 正常但 IGS 服務 (Port {port}) 無回應` | 設備 Port 不通 |
| 157 | `iFIX/IGS 機台 {ip} 與 IGS 服務正常` | 設備正常 |

將 `iFIX/IGS 機台`、`IGS 服務` 替換為你實際的設備名稱即可。

## Kepware Event Log 監控

透過獨立的 Kepware API Gateway 服務，定期 polling 事件與交易紀錄，自動分類嚴重等級並依規則派報。

### 架構

```
Kepware Server A / B
    ↕
Kepware API Gateway（獨立服務，每台 Kepware 各一個）
    ↕  REST API + JWT 認證
本專案（KepwareMonitorOPC）
    ├→ 定期 polling events / transactions
    ├→ 事件分類 + 去重 + 異常偵測
    ├→ 派報（Email / Webhook）
    ├→ Web UI 查詢
    └→ 專案備份（手動 / 排程）
```

### 事件嚴重等級分類規則

系統根據事件 `message` 內容中的關鍵字，自動分類為以下嚴重等級：

| 等級 (severity) | 關鍵字 | 說明 | 派報行為 |
|-----------------|--------|------|---------|
| **Critical** | `Device not responding` | 物理斷線 / 設備斷電 | 立即派報（1 次即觸發） |
| **Warning** | `Timeout`、`Add item failed` | 通訊擁塞 / 連線數過載 | 自適應閥值（學習正常基準後判斷） |
| **Advisory** | `Failed to remove item` | 系統資源未釋放 | 僅記錄，不派報 |
| **Unclassified** | （不符合以上任何關鍵字） | 其他事件 | 固定閥值（預設 5 次 / 小時） |

> **注意：** severity 欄位是本系統的二次分類，與 Kepware 原始的 event 等級（Error / Warning / Info）獨立存在，不會混淆。

#### 關鍵字設定

分類關鍵字可在 `settings.ini` 中自行擴充：

```ini
[KepwareLog.kepware_a]
SeverityCritical = Device not responding
SeverityWarning = Timeout,Add item failed
SeverityAdvisory = Failed to remove item
```

另有 `CriticalKeywords`（如 `Runtime stopped, License error, Server shutdown`）為**不分等級的即時告警**，命中即立即派報。

### 自適應閥值

Warning 等級事件使用自適應閥值，避免固定門檻無法適應不同環境：

```
告警門檻 = max(過去 N 天每小時平均錯誤數 × 倍數, 最低門檻)
```

| 參數 | 設定鍵 | 預設值 | 說明 |
|------|--------|--------|------|
| 學習窗口 | `AdaptiveBaselineDays` | 7 天 | 從 DB 取過去 N 天的數據 |
| 倍數 | `AdaptiveMultiplier` | 3.0 | 超過基準 × 倍數才告警 |
| 最低門檻 | `AdaptiveMinThreshold` | 3 次/小時 | 避免基準太低而過度敏感 |
| 重算頻率 | — | 每 24 小時 | 自動重新計算基準線 |

### Tag 讀取異常偵測

系統自動解析事件 message 中的 `Channel.Device` 和 `Tag address`：

```
K12GMSIFIX.GMS | Add item failed on device. | Tag address = 'ns=2;s=11$AA...', Status code = 0X808D0000.
  ↑ Channel   ↑ Device                        ↑ Tag Address
```

同一 Channel.Device 連續出現 Warning/Error 事件達門檻（預設 6 次）時派報。

### 設定範例

```ini
# 每台 Kepware 各一個 section
[KepwareLog.kepware_a]
Enable = true
ApiBaseUrl = http://192.168.1.10:8000
Username = admin
Password = your_password
EventSubject = Kepware 事件監控通知
PollInterval = 600
```

### Web UI 功能

| Tab | 說明 |
|-----|------|
| 事件記錄 | 依日期/Channel/事件等級/嚴重等級篩選，顯示 Server、Severity、Tag Address |
| 操作記錄 | Kepware Config API 操作紀錄（GET/POST/PUT/DELETE） |

### 多台 Kepware 帳號設定

每台 Kepware 的 API Gateway 帳號密碼**各自獨立**，在對應的 `[KepwareLog.xxx]` section 中分別設定：

```ini
[KepwareLog.kepware_a]
Enable = true
ApiBaseUrl = http://192.168.1.10:8000
Username = admin_a
Password = password_a

[KepwareLog.kepware_b]
Enable = true
ApiBaseUrl = http://10.0.0.5:8000
Username = admin_b
Password = password_b
```

佈署第二台時，只需新增一個 `[KepwareLog.kepware_b]` section，填入該台 Gateway 的連線資訊與帳密即可。

## Kepware 專案備份

透過 API Gateway 呼叫 Kepware ProjectSave 服務，定期備份專案檔。

### 功能

- **手動觸發** — Web UI 選擇 Server 後一鍵備份
- **每週排程** — 可設定每週幾、幾點自動執行（預設週日 02:00）
- **備份記錄** — 每次備份結果（成功/失敗、檔名、耗時、錯誤訊息）寫入 DB 可追溯
- **多台支援** — 排程會自動對所有已啟用的 Kepware Server 執行備份

### 排程設定

排程設定儲存在 `data/backup_schedule.json`，可在 Web UI「專案備份」頁面調整：

```json
{"day_of_week": 6, "time": "02:00"}
```

> `day_of_week`: 0=週一 ... 6=週日

### 備份檔案

備份檔自動存放在 Kepware 資料目錄的 `Project Backups\` 子資料夾，檔名格式：`KepwareBackup_YYYYMMDD_HHMMSS.opf`。

## 動態閥值（Tag 監控）

適用於監控 Kepware 連線數、通訊狀態等會隨環境波動的指標。

### 原理

使用移動平均 ± k 倍標準差偵測異常：

```
基準線 = 過去 N 筆歷史讀值的平均值 (μ)
標準差 = 過去 N 筆歷史讀值的標準差 (σ)
當 |當前值 - μ| > k × σ 時觸發告警
```

### CSV 設定

```csv
Name,NodeId,Type,Condition,Threshold,CountNeeded,Enable
連線數,ns=2;s=...,number,dynamic,3,2,TRUE
```

- `Condition = dynamic` — 啟用動態閥值
- `Threshold = 3` — k 值（幾倍標準差，可選，預設取 `[Monitor] DynamicK`）
- `CountNeeded` — 連續幾次偏離才派報

### 全域設定

```ini
[Monitor]
DynamicWindow = 24    # 回看歷史筆數
DynamicK = 3.0        # 預設 k 值
```

## 佈署為 Windows 服務（PyInstaller + WinSW）

由於 `asyncua` 套件僅支援特定版本的 Python，建議使用 PyInstaller 封裝成執行檔後，再透過 WinSW 註冊為 Windows Service。

### 1. 安裝 PyInstaller

```bash
pip install pyinstaller
```

### 2. 打包執行檔

```bash
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

產出檔案在 `dist/KepwareMonitor.exe`。

> **注意：** 若有其他動態 import（如 `asyncua` 子模組），可能需追加 `--hidden-import`。打包後先手動執行 `dist\KepwareMonitor.exe` 確認無 ModuleNotFoundError。

### 3. 佈署目錄結構

將以下檔案複製到目標主機（例如 `C:\KepwareMonitor\`）：

```
C:\KepwareMonitor\
├── KepwareMonitor.exe          # PyInstaller 產出
├── Config\
│   ├── settings.ini            # 設定檔
│   └── tags.csv                # 監控設備
├── data\                       # 自動產生（DB、排程、marker）
├── logs\                       # 自動產生
├── KepwareMonitor.xml          # WinSW 設定檔
└── WinSW.exe                   # WinSW 執行檔（重新命名）
```

### 4. 下載 WinSW

從 [WinSW Releases](https://github.com/winsw/winsw/releases) 下載 `WinSW-x64.exe`，重新命名為 `KepwareMonitor.exe` 同目錄下的 `KepwareMonitorSvc.exe`（或任意名稱，但 XML 檔名需對應）。

### 5. 建立 WinSW 設定檔

建立 `KepwareMonitorSvc.xml`（檔名需與 WinSW exe 同名）：

```xml
<service>
  <id>KepwareMonitor</id>
  <name>Kepware Monitor OPC</name>
  <description>Kepware OPC UA 監控系統 - 設備監控、事件記錄、專案備份</description>
  <executable>%BASE%\KepwareMonitor.exe</executable>
  <startmode>Automatic</startmode>
  <log mode="roll-by-size">
    <sizeThreshold>10240</sizeThreshold>
    <keepFiles>5</keepFiles>
  </log>
  <onfailure action="restart" delay="10 sec"/>
  <onfailure action="restart" delay="30 sec"/>
  <onfailure action="none"/>
</service>
```

### 6. 安裝與管理服務

以**系統管理員**身分開啟命令提示字元：

```cmd
cd C:\KepwareMonitor

:: 安裝服務
KepwareMonitorSvc.exe install

:: 啟動服務
KepwareMonitorSvc.exe start

:: 查看狀態
KepwareMonitorSvc.exe status

:: 停止服務
KepwareMonitorSvc.exe stop

:: 移除服務
KepwareMonitorSvc.exe uninstall
```

### 7. 驗證

1. 服務啟動後，瀏覽 `http://localhost:8080` 確認 Web UI 正常
2. 檢查 `logs\` 目錄下的日誌確認監控運作
3. 檢查 Windows 事件檢視器（應用程式日誌）確認服務狀態

## License

MIT
