# Kepware OPC UA 監控系統

透過 OPC UA 協定定期讀取 Kepware Server 的設備數值，當數值超出閾值時自動發送 Email 與 Webhook 推播通知，並提供 Web UI 管理介面。

## 功能特色

- **多台 Kepware Server** — 同時監控多台 OPC UA Server
- **彈性閾值設定** — 支援數值比較（大於/小於/等於）、布林判斷、純記錄模式
- **累積觸發機制** — 連續 N 次異常才派報，避免瞬間抖動誤報
- **復歸通知** — 設備恢復正常時自動發送復歸通知
- **三層式網路診斷** — Ping 主機、TCP Port 檢測、設備 IP 檢測，定位斷線層級
- **Email 派報** — HTML 格式，支援全域/設備獨立收件人
- **Webhook 推播** — 支援自訂 JSON Body 模板，Token 驗證，Proxy 設定
- **Web UI 管理介面** — 即時儀表板（SSE）、歷史紀錄查詢匯出、設定管理、帳號管理
- **CSV 熱載入** — 修改 tags.csv 後自動偵測並重新載入，無需重啟
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
| Condition | 比較條件：greater / less / equal / not_equal | greater |
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
| 設備管理 | 線上編輯 tags.csv |
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

## License

MIT
