import asyncio
import csv
import os
import time
import logging
import threading
from datetime import datetime

from diagnostic_service import DiagnosticService, DiagnosticResult
from opc_connection import OPCConnection
from db_service import DatabaseService
from ase_email_service import EmailService
from webhook_service import WebhookService
from kepware_log_service import KepwareLogService


def log_and_print(msg):
    print(msg)
    logging.info(msg)


# 連線層重連失敗告警門檻：連續重連失敗達此次數時，額外發送一次升級告警
# （避免無限重試期間完全沒有二次提醒，但也不會每 30 秒就寄一封轟炸信箱）
RECONNECT_ALERT_THRESHOLD = 5

# 單次讀值失敗後，在同一輪迴圈內短間隔連續重試重連的次數與間隔。
# 原本重連只試一次，失敗就要等到下一個完整 check_interval（可能長達
# 數分鐘甚至十分鐘）才有機會再試，中間空窗期實際上比舊版「靠下一輪
# read_values() 自然重試」還長。改為短間隔連續重試數次，仍失敗才真正
# 放棄、留給下一輪。
RECONNECT_RETRY_ATTEMPTS = 3
RECONNECT_RETRY_DELAY = 20  # 秒


class DeviceConfig:
    """單一監控設備的設定與執行狀態"""

    def __init__(self, raw):
        # 基本設定（從 CSV 讀入）
        self.name = raw.get("name", "")
        self.nodeid = raw.get("nodeid", "")
        self.server_name = raw.get("server_name", "")
        self.device_type = raw.get("type", "number")
        self.condition = raw.get("condition", "greater")
        self.threshold = raw.get("threshold", None)
        self.accumulate = raw.get("accumulate", 1)
        self.enable = raw.get("enable", True)

        # 設備 IP 資訊（用於 Layer 3 診斷）
        self.device_ip = raw.get("device_ip", "")
        self.device_port = raw.get("device_port", 49310)

        # 派報對象
        self.mail_to = raw.get("mail_to", [])
        self.mail_cc = raw.get("mail_cc", [])

        # 執行狀態（運行時維護）
        self.counter = 0
        self.last_alert_time = 0  # timestamp，0 = 未發過
        self.last_diagnostic = None
        self.last_value = None  # 上一次讀取值（供 unchanged 條件使用）

    @property
    def key(self):
        return (self.name, self.nodeid)

    def inherit_state(self, old_device):
        """從舊設備繼承運行狀態"""
        if old_device and old_device.enable and self.enable:
            self.counter = old_device.counter
            self.last_alert_time = old_device.last_alert_time
            self.last_diagnostic = old_device.last_diagnostic
            self.last_value = old_device.last_value

    def reset_state(self):
        self.counter = 0
        self.last_alert_time = 0
        self.last_diagnostic = None


class MonitorManager:
    """
    核心監控管理器：
      - 多 Kepware Server 支援
      - CSV 設定載入與熱重載
      - 三層診斷整合
      - 派報分流（連線層 → IT / 數值層 → 設備人員）
    """

    def __init__(self, config):
        """
        config: configparser 物件
        """
        self.config = config

        # 基礎設定
        self.check_interval = config.getint("Monitor", "intervalSeconds", fallback=600)
        self.csv_reload_seconds = config.getint("Monitor", "csvReloadSeconds", fallback=30)
        self.alert_resend_interval = config.getint("Monitor", "alertResendInterval", fallback=1800)
        self.dynamic_window = config.getint("Monitor", "DynamicWindow", fallback=24)
        self.dynamic_k = config.getfloat("Monitor", "DynamicK", fallback=3.0)

        # 全域派報設定
        self.global_mail_to = [x.strip() for x in config.get("Mail", "To", fallback="").split(",") if x.strip()]
        self.global_mail_cc = [x.strip() for x in config.get("Mail", "Cc", fallback="").split(",") if x.strip()]
        self.mail_subject = config.get("Mail", "Subject", fallback="Kepware 設備監控通知")

        # Tags CSV
        self.tags_csv = config.get("Tags", "File", fallback="Config/tags.csv")
        self._csv_mtime = None

        # 服務元件
        self.diagnostic = DiagnosticService()
        self.db = DatabaseService(
            db_path=config.get("Database", "Path", fallback="data/monitor.db")
        )
        self.email_service = EmailService(
            smtp_server=config.get("Mail", "SmtpServer"),
            smtp_port=config.getint("Mail", "Port", fallback=25),
            sender_email=config.get("Mail", "From"),
        )

        # Webhook 推播
        self.webhook = self._init_webhook()

        # 備份排程
        self.backup_schedule = self._load_backup_schedule()

        # OPC 連線（多 Server）
        self.connections = {}  # name -> OPCConnection
        self._parse_servers()

        # Kepware Log 監控（多台）
        self.kepware_logs = self._init_kepware_logs()

        # 監控設備清單
        self.devices = []  # list of DeviceConfig

        # 連線層重連失敗次數追蹤（斷線告警降噪與升級用）
        # key: 連線名稱, value: 連續重連失敗次數（成功後歸零）
        self.connection_fail_counts = {}

        # 記錄哪些連線已經警告過「缺少 is_alive() 方法」，避免每輪重複洗版
        self._is_alive_missing_warned = set()

        logging.info(f"MonitorManager 設定: 檢查間隔={self.check_interval}s, "
                     f"CSV={self.tags_csv}, Server 數={len(self.connections)}")

    @staticmethod
    def _load_backup_schedule():
        import json
        try:
            with open("data/backup_schedule.json", "r") as f:
                return json.load(f)
        except (FileNotFoundError, ValueError):
            return {"day_of_week": 6, "time": "02:00"}

    def _init_webhook(self):
        """初始化 Webhook 推播服務"""
        enable = self.config.getboolean("Webhook", "Enable", fallback=False)
        if not enable:
            logging.info("Webhook 推播未啟用")
            return None

        url = self.config.get("Webhook", "Url", fallback="").strip().strip('"').strip("'")
        token = self.config.get("Webhook", "Token", fallback="").strip().strip('"').strip("'")
        body_template = self.config.get("Webhook", "BodyTemplate", fallback="").strip()
        timeout = self.config.getint("Webhook", "Timeout", fallback=10)
        verify_ssl = self.config.getboolean("Webhook", "VerifySSL", fallback=False)
        use_proxy = self.config.getboolean("Webhook", "UseProxy", fallback=False)
        proxy_url = self.config.get("Webhook", "ProxyUrl", fallback="").strip()

        if not url or not body_template:
            logging.warning("Webhook 設定不完整（缺少 Url 或 BodyTemplate），已停用")
            return None

        # 診斷：顯示讀取到的原始值，方便確認模板是否正確
        logging.info(f"Webhook 推播已啟用: {url}")
        logging.info(f"Webhook BodyTemplate: {body_template}")

        return WebhookService(
            url=url, token=token, body_template=body_template,
            enable=True, timeout=timeout,
            verify_ssl=verify_ssl,
            use_proxy=use_proxy,
            proxy_url=proxy_url or None,
        )

    def _init_kepware_logs(self):
        """初始化 Kepware Log 監控服務（支援多台）

        支援兩種設定格式：
        - 單台（向下相容）：[KepwareLog] + ServerName
        - 多台：[KepwareLog.kepware_a], [KepwareLog.kepware_b], ...
        """
        instances = []
        mail_to = self.global_mail_to
        mail_cc = self.global_mail_cc

        sections = [s for s in self.config.sections() if s.startswith("KepwareLog")]

        for section in sections:
            enable = self.config.getboolean(section, "Enable", fallback=False)
            if not enable:
                continue

            base_url = self.config.get(section, "ApiBaseUrl", fallback="").strip()
            if not base_url:
                logging.warning(f"[{section}] 設定不完整（缺少 ApiBaseUrl），已跳過")
                continue

            if "." in section:
                server_name = section.split(".", 1)[1]
            else:
                server_name = self.config.get(section, "ServerName", fallback="KepwareAPI").strip()

            def _parse_kw(key, fallback):
                raw = self.config.get(section, key, fallback=fallback)
                return [k.strip() for k in raw.split(",") if k.strip()]

            svc = KepwareLogService(
                server_name=server_name,
                base_url=base_url,
                username=self.config.get(section, "Username", fallback=""),
                password=self.config.get(section, "Password", fallback=""),
                db_service=self.db,
                email_service=self.email_service,
                webhook_service=self.webhook,
                poll_interval=self.config.getint(section, "PollInterval", fallback=600),
                retention_days=self.config.getint(section, "RetentionDays", fallback=90),
                critical_keywords=_parse_kw("CriticalKeywords",
                                            "Runtime stopped,License error,Server shutdown"),
                severity_critical=_parse_kw("SeverityCritical",
                                            "Device not responding"),
                severity_warning=_parse_kw("SeverityWarning",
                                           "Timeout,Add item failed"),
                severity_advisory=_parse_kw("SeverityAdvisory",
                                            "Failed to remove item"),
                mail_to=mail_to,
                mail_cc=mail_cc,
                event_subject=self.config.get(section, "EventSubject",
                                              fallback="Kepware 事件監控通知"),
            )
            instances.append(svc)

        if not instances:
            logging.info("Kepware Log 監控未啟用")

        return instances

    def _parse_servers(self):
        """解析設定檔中的多 Kepware Server"""
        # 讀取全域安全設定
        security_policy = self.config.get("OPC", "SecurityPolicy", fallback="None").strip()
        security_mode = self.config.get("OPC", "SecurityMode", fallback="None").strip()
        authentication = self.config.get("OPC", "Authentication", fallback="anonymous").strip()
        username = self.config.get("OPC", "Username", fallback="").strip() or None
        password = self.config.get("OPC", "Password", fallback="").strip() or None

        security_kwargs = dict(
            security_policy=security_policy,
            security_mode=security_mode,
            authentication=authentication,
            username=username,
            password=password,
        )

        servers_raw = self.config.get("OPC", "Servers", fallback="")
        if servers_raw.strip():
            for entry in servers_raw.split(","):
                entry = entry.strip()
                if not entry:
                    continue
                if "|" in entry:
                    name, url = entry.split("|", 1)
                else:
                    name = entry
                    url = entry
                name = name.strip()
                url = url.strip()
                self.connections[name] = OPCConnection(
                    name=name, url=url, diagnostic_service=self.diagnostic,
                    **security_kwargs,
                )
        else:
            # 向下相容：單一 ServerUrl
            url = self.config.get("OPC", "ServerUrl", fallback="")
            if url:
                self.connections["default"] = OPCConnection(
                    name="default", url=url, diagnostic_service=self.diagnostic,
                    **security_kwargs,
                )

    # ===========================================
    # CSV 設定載入
    # ===========================================

    def load_devices_from_csv(self):
        """讀取 CSV 並回傳 DeviceConfig 列表"""
        devices = []
        with open(self.tags_csv, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                raw = self._parse_csv_row(row)
                devices.append(DeviceConfig(raw))
        return devices

    def _parse_csv_row(self, row):
        """解析 CSV 單一列"""
        name = row.get("Name", "").strip()
        nodeid = row.get("NodeId", "").strip()
        server_name = row.get("Server", "default").strip()
        device_type = row.get("Type", "number").strip().lower()
        condition = row.get("Condition", "greater").strip().lower()
        threshold_raw = row.get("Threshold", "").strip()
        accumulate_raw = str(row.get("CountNeeded", "1") or "1").strip()
        enable_raw = row.get("Enable", "True").strip()

        # device network info
        device_ip = row.get("DeviceIP", "").strip()
        device_port_raw = row.get("DevicePort", "49310").strip()

        # parse accumulate
        try:
            accumulate = max(1, int(accumulate_raw))
        except Exception:
            accumulate = 1

        # parse device port
        try:
            device_port = int(device_port_raw) if device_port_raw else 49310
        except Exception:
            device_port = 49310

        # parse threshold
        threshold = None
        if device_type == "number":
            try:
                threshold = float(threshold_raw) if threshold_raw else None
            except Exception:
                threshold = None
        elif device_type == "bool":
            thr = threshold_raw.lower()
            if thr in ("1", "true", "yes"):
                threshold = True
            elif thr in ("0", "false", "no"):
                threshold = False

        # parse enable
        enable = enable_raw.lower() == "true"

        # mail merge（全域 + 設備專屬，去重保序）
        mail_to_csv = [x.strip() for x in row.get("MailTo", "").split(",") if x.strip()]
        mail_cc_csv = [x.strip() for x in row.get("MailCc", "").split(",") if x.strip()]
        merged_to = list(dict.fromkeys(self.global_mail_to + mail_to_csv))
        merged_cc = list(dict.fromkeys(self.global_mail_cc + mail_cc_csv))

        return {
            "name": name,
            "nodeid": nodeid,
            "server_name": server_name,
            "type": device_type,
            "condition": condition,
            "threshold": threshold,
            "accumulate": accumulate,
            "enable": enable,
            "device_ip": device_ip,
            "device_port": device_port,
            "mail_to": merged_to,
            "mail_cc": merged_cc,
        }

    def reload_csv_if_needed(self):
        """檢查 CSV 變更並重載，保留既有設備的運行狀態"""
        try:
            mtime = os.path.getmtime(self.tags_csv)
        except Exception:
            logging.warning(f"CSV 檔案不存在或無法存取: {self.tags_csv}")
            return

        if self._csv_mtime is not None and mtime == self._csv_mtime:
            return

        try:
            new_devices = self.load_devices_from_csv()
        except Exception as ex:
            logging.exception(f"CSV 載入失敗: {ex}")
            return

        # 建立舊設備查找表
        old_map = {d.key: d for d in self.devices}

        # 繼承狀態
        for nd in new_devices:
            od = old_map.get(nd.key)
            nd.inherit_state(od)

        self.devices = new_devices
        self._csv_mtime = mtime
        logging.info(f"CSV 重載成功，共 {len(self.devices)} 個監控項目")

    # ===========================================
    # 數值判斷邏輯
    # ===========================================

    @staticmethod
    def evaluate(device, raw_value):
        """
        判斷設備數值是否觸發警報。
        回傳 (is_alert: bool, parsed_value)
        """
        dtype = device.device_type
        condition = device.condition
        threshold = device.threshold

        if not device.enable:
            return False, None

        if raw_value is None:
            return False, None

        if dtype == "log":
            return False, raw_value

        if dtype == "number":
            try:
                val = float(raw_value)
            except Exception:
                logging.warning(f"[{device.name}] 數值解析失敗: {raw_value}")
                return False, None
            # unchanged 不需要 threshold，優先判斷
            if condition == "unchanged":
                if val == 0:
                    return True, val
                if device.last_value is None:
                    return False, val
                return (val == device.last_value), val
            if threshold is None:
                return False, val
            if condition == "greater":
                return (val > threshold), val
            if condition == "less":
                return (val < threshold), val
            if condition in ("equal", "=="):
                return (val == threshold), val
            if condition in ("not_equal", "!="):
                return (val != threshold), val
            return False, val

        if dtype == "bool":
            if isinstance(raw_value, bool):
                val = raw_value
            else:
                s = str(raw_value).strip().lower()
                if s in ("1", "true", "t", "yes", "on"):
                    val = True
                elif s in ("0", "false", "f", "no", "off"):
                    val = False
                else:
                    try:
                        val = bool(int(raw_value))
                    except Exception:
                        val = False
            # unchanged 不需要 threshold，優先判斷
            if condition == "unchanged":
                if device.last_value is None:
                    return False, val
                return (val == device.last_value), val
            if threshold is None:
                return False, val
            if condition in ("true", "1"):
                return (val is True), val
            if condition in ("false", "0"):
                return (val is False), val
            if condition in ("equal", "=="):
                return (val == threshold), val
            if condition in ("not_equal", "!="):
                return (val != threshold), val
            return False, val

        return False, None

    def _evaluate_dynamic(self, device, raw_value, conn_name):
        import statistics as _stats
        try:
            val = float(raw_value)
        except (TypeError, ValueError):
            return False, None

        server_name = conn_name if len(self.connections) > 1 else None
        history = self.db.get_recent_device_values(
            device_name=device.name, server_name=server_name,
            limit=self.dynamic_window,
        )

        if len(history) < 3:
            return False, val

        mean = _stats.mean(history)
        stdev = _stats.stdev(history)

        k = float(device.threshold) if device.threshold is not None else self.dynamic_k

        if stdev == 0:
            is_alert = val != mean
        else:
            is_alert = abs(val - mean) > k * stdev

        if is_alert:
            logging.info(f"[{conn_name}] {device.name} 動態閥值觸發: "
                         f"val={val}, mean={mean:.2f}, σ={stdev:.2f}, "
                         f"k={k}, 偏離={abs(val - mean) / stdev:.1f}σ"
                         if stdev > 0 else
                         f"[{conn_name}] {device.name} 動態閥值觸發: "
                         f"val={val}, mean={mean}, 值已變化")

        return is_alert, val

    # ===========================================
    # 派報
    # ===========================================

    def send_device_alert(self, device, value, is_recovery=False,
                          diagnostic_result=None):
        """
        發送設備派報（異常或復歸），同時寫入 DB。
        """
        if is_recovery:
            status_tag = "[復歸]"
            title_text = "Kepware 設備恢復正常通知"
            color_hex = "#28a745"
            msg_context = "設備已恢復正常通訊。"
        else:
            status_tag = "[異常]"
            title_text = "Kepware 設備通訊異常通知"
            color_hex = "#dc3545"
            msg_context = "設備通訊異常，請儘速確認。"

        # 若有診斷結果，加入信件內容
        diag_html = ""
        diag_level = ""
        diag_msg = ""
        if diagnostic_result and diagnostic_result.level != DiagnosticResult.LEVEL_OK:
            diag_level = diagnostic_result.level
            diag_msg = diagnostic_result.message
            diag_html = f"""
            <p><strong>診斷結果:</strong>
               <span style="color: {color_hex};">{diagnostic_result.message}</span></p>
            """

        subject = f"{status_tag} {self.mail_subject} - {device.name}"
        html_body = f"""
        <html>
        <body>
            <h2 style="color: {color_hex};">{title_text}</h2>
            <p><strong>通知時間:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <p><strong>Kepware Server:</strong> {device.server_name}</p>
            <p><strong>設備名稱:</strong> {device.name}</p>
            <p><strong>目前數值:</strong>
               <span style="font-size: 1.2em; font-weight: bold; color: {color_hex};">{value}</span></p>
            <p><strong>閾值設定:</strong> {device.condition} {device.threshold}</p>
            <p><strong>累積次數:</strong> {device.counter} / {device.accumulate}</p>
            {diag_html}
            <hr>
            <p>{msg_context}</p>
        </body>
        </html>
        """

        log_and_print(f"    >>> 寄送信件: {subject}")

        try:
            self.email_service.send_alert_email(
                to_addresses=device.mail_to,
                cc_addresses=device.mail_cc,
                subject=subject,
                html_body=html_body,
            )
        except Exception as ex:
            logging.exception(f"寄信失敗: {ex}")

        # 寫入派報紀錄
        try:
            self.db.write_alert_log(
                server_name=device.server_name,
                device_name=device.name,
                alert_type="value" if not diagnostic_result else diag_level,
                diagnostic_level=diag_level,
                diagnostic_msg=diag_msg,
                recipients_to=device.mail_to,
                recipients_cc=device.mail_cc,
                subject=subject,
                is_recovery=is_recovery,
            )
        except Exception as ex:
            logging.warning(f"派報紀錄寫入失敗: {ex}")

        # Webhook 推播（daemon thread，不阻塞主程式）
        if self.webhook:
            try:
                variables = self.webhook.build_variables(
                    server_name=device.server_name,
                    device_name=device.name,
                    value=value,
                    threshold=device.threshold,
                    condition=device.condition,
                    counter=device.counter,
                    accumulate=device.accumulate,
                    diagnostic_msg=diag_msg,
                    is_recovery=is_recovery,
                )
                self._fire_webhook(variables, device.server_name, device.name, is_recovery)
            except Exception as ex:
                logging.warning(f"Webhook 推播失敗: {ex}")

    def _fire_webhook(self, variables, server_name, device_name, is_recovery):
        """在 daemon thread 中發送 Webhook，不阻塞任何流程"""
        def _do_send():
            try:
                self.webhook.send(
                    variables,
                    db_service=self.db,
                    server_name=server_name,
                    device_name=device_name,
                    is_recovery=is_recovery,
                )
            except Exception as ex:
                logging.warning(f"Webhook 背景推播失敗: {ex}")

        t = threading.Thread(target=_do_send, daemon=True)
        t.start()

    def send_connection_alert(self, conn_name, diagnostic_result, is_recovery=False):
        """
        發送連線層派報（Kepware 主機斷線 / 恢復），通知 IT 基礎人員。
        使用全域收件人。
        """
        level_labels = {
            DiagnosticResult.LEVEL_HOST_DOWN: "主機離線",
            DiagnosticResult.LEVEL_OPC_SERVICE_DOWN: "OPC 服務異常",
        }
        label = level_labels.get(diagnostic_result.level, "連線異常")

        if is_recovery:
            status_tag = "[連線復歸]"
            title_text = "Kepware 連線恢復正常通知"
            color_hex = "#28a745"
            msg_context = "連線已恢復正常，若持續穩定可忽略此通知。"
        else:
            status_tag = "[連線異常]"
            title_text = "Kepware 連線異常通知"
            color_hex = "#dc3545"
            msg_context = "請 IT 人員儘速確認。"

        subject = f"{status_tag} {self.mail_subject} - {conn_name} {label}"

        html_body = f"""
        <html>
        <body>
            <h2 style="color: {color_hex};">{title_text}</h2>
            <p><strong>通知時間:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <p><strong>Server:</strong> {conn_name}</p>
            <p><strong>診斷結果:</strong>
               <span style="font-size: 1.2em; font-weight: bold; color: {color_hex};">
               {diagnostic_result.message}</span></p>
            <hr>
            <p>{msg_context}</p>
        </body>
        </html>
        """

        log_and_print(f"    >>> 寄送連線{'復歸' if is_recovery else '異常'}通知: {subject}")

        try:
            self.email_service.send_alert_email(
                to_addresses=self.global_mail_to,
                cc_addresses=self.global_mail_cc,
                subject=subject,
                html_body=html_body,
            )
        except Exception as ex:
            logging.exception(f"連線{'復歸' if is_recovery else '異常'}通知寄送失敗: {ex}")

        try:
            self.db.write_alert_log(
                server_name=conn_name,
                device_name="",
                alert_type="connection",
                diagnostic_level=diagnostic_result.level,
                diagnostic_msg=diagnostic_result.message,
                recipients_to=self.global_mail_to,
                recipients_cc=self.global_mail_cc,
                subject=subject,
                is_recovery=is_recovery,
            )
        except Exception as ex:
            logging.warning(f"連線派報紀錄寫入失敗: {ex}")

        # Webhook 推播
        if self.webhook:
            try:
                variables = self.webhook.build_variables(
                    server_name=conn_name,
                    device_name="(連線層)",
                    value=label,
                    threshold="",
                    condition="",
                    counter=0,
                    accumulate=0,
                    diagnostic_msg=diagnostic_result.message,
                    is_recovery=is_recovery,
                )
                self._fire_webhook(variables, conn_name, "", is_recovery)
            except Exception as ex:
                logging.warning(f"連線 Webhook 推播失敗: {ex}")

    # ===========================================
    # 主監控迴圈
    # ===========================================

    async def start(self):
        """
        啟動所有 OPC 連線並開始監控。
        連線方式與舊版完全一致：直接 connect，失敗就拋出例外。
        """
        # 初始載入 CSV
        logging.info("載入監控設備 CSV...")
        self.reload_csv_if_needed()
        logging.info(f"已載入 {len(self.devices)} 個監控項目")

        # 檢查 CSV 中的 Server 名稱是否與連線設定匹配
        conn_names = set(self.connections.keys())
        csv_server_names = set(d.server_name for d in self.devices if d.enable)
        unmatched = csv_server_names - conn_names
        if unmatched and len(self.connections) == 1:
            the_conn = list(conn_names)[0]
            logging.info(f"單台模式：CSV 中的 Server 名稱 {unmatched} 將自動對應到 '{the_conn}'")
        elif unmatched:
            logging.warning(f"CSV 中有未匹配的 Server 名稱: {unmatched}，"
                            f"可用連線: {conn_names}，這些設備將不會被監控！")

        # 逐一連線（與舊版一樣，直接 connect，失敗會拋出例外）
        for name, conn in self.connections.items():
            log_and_print(f"[{name}] 正在連線到 {conn.url} ...")
            await conn.connect()

        # 進入主迴圈（DB 舊紀錄清理改為在迴圈中每日執行一次，見 _monitor_loop）
        logging.info("進入主監控迴圈...")
        await self._monitor_loop()

    async def _monitor_loop(self):
        """
        主監控迴圈 — 讀值與重連邏輯與舊版一致。
        """
        last_csv_check = 0
        last_kepware_log_poll = {}
        last_cleanup_date = None  # 每日清理舊紀錄追蹤（服務長駐執行，避免資料庫無限增長）

        while True:
            now = time.time()

            # CSV 熱重載
            if (now - last_csv_check) >= self.csv_reload_seconds:
                self.reload_csv_if_needed()
                last_csv_check = now

            # 依 Server 分組處理
            is_single_server = len(self.connections) == 1
            for conn_name, conn in self.connections.items():
                # 篩選此 Server 的設備
                # 單台模式：CSV 中 Server 名稱不論填什麼都歸到這台
                if is_single_server:
                    server_devices = [
                        d for d in self.devices
                        if d.nodeid and d.enable
                    ]
                else:
                    server_devices = [
                        d for d in self.devices
                        if d.server_name == conn_name and d.nodeid and d.enable
                    ]
                if not server_devices:
                    logging.debug(f"[{conn_name}] 無匹配的監控設備 "
                                  f"(總設備數={len(self.devices)}, "
                                  f"連線名稱='{conn_name}')")
                    continue

                logging.info(f"[{conn_name}] 開始讀取 {len(server_devices)} 個設備...")

                # ==========================================
                # 讀值與重連
                # ==========================================
                try:
                    # 讀值前先做一次輕量健康檢查：asyncua 背景 watchdog
                    # 偵測到斷線時只會印 log，不會讓下一次 read_values()
                    # 立刻失敗，這裡讓斷線可以提早被主迴圈感知，不用等到
                    # 真正讀值失敗才觸發重連。
                    #
                    # is_alive() 若不存在（例如部署時漏更新 opc_connection.py，
                    # 舊版 OPCConnection 沒有這個方法）不能直接讓 AttributeError
                    # 被下面的 except 當成「連線斷掉」處理——那樣會導致每一輪
                    # 都誤判斷線、觸發不必要的重連，反而比沒有健康檢查更不穩定。
                    # 只在每個連線第一次遇到時警告一次，之後靜默略過健康檢查，
                    # 行為等同退回舊版（只靠 read_values() 例外判斷斷線）。
                    is_alive_fn = getattr(conn, "is_alive", None)
                    if is_alive_fn is None:
                        if conn_name not in self._is_alive_missing_warned:
                            logging.warning(
                                f"[{conn_name}] OPCConnection 缺少 is_alive() 方法"
                                f"（部署檔案可能未同步更新 opc_connection.py），"
                                f"本次執行將略過連線健康檢查，僅依讀值例外判斷斷線"
                            )
                            self._is_alive_missing_warned.add(conn_name)
                    elif not await is_alive_fn():
                        raise ConnectionError(
                            f"[{conn_name}] 連線健康檢查失敗（背景 watchdog 已偵測到斷線）"
                        )
                    values = await conn.read_values(
                        [{"nodeid": d.nodeid, "name": d.name} for d in server_devices]
                    )
                except Exception as ex:
                    log_and_print(f"[{conn_name}] 讀取失敗或連線斷掉: {ex}")

                    # --- 重連邏輯：短間隔連續重試數次，避免只試一次就要
                    # 等到下一個完整 check_interval 才有機會再試 ---
                    success = False
                    for attempt in range(1, RECONNECT_RETRY_ATTEMPTS + 1):
                        success = await conn.reconnect()
                        if success:
                            break
                        if attempt < RECONNECT_RETRY_ATTEMPTS:
                            log_and_print(f"[{conn_name}] 第 {attempt}/{RECONNECT_RETRY_ATTEMPTS} "
                                          f"次重連失敗，{RECONNECT_RETRY_DELAY} 秒後再試...")
                            await asyncio.sleep(RECONNECT_RETRY_DELAY)

                    if success:
                        log_and_print(f"[{conn_name}] 重新連線成功！立即重試讀取...")
                        if self.connection_fail_counts.get(conn_name, 0) > 0:
                            # 曾經連續失敗過（已寄過斷線告警），寄送復歸通知
                            try:
                                diag_result = await conn.diagnose_kepware()
                            except Exception:
                                diag_result = DiagnosticResult(
                                    DiagnosticResult.LEVEL_OK,
                                    f"[{conn_name}] 已恢復連線",
                                )
                            self.send_connection_alert(conn_name, diag_result, is_recovery=True)
                        self.connection_fail_counts[conn_name] = 0

                        # 立即重試讀值（原本這裡的 continue 只會跳到 for 迴圈
                        # 的下一台 Server，多台部署時剛重連成功的這台要等到
                        # 下一輪整體迴圈才會真正重試，與上面的 log 訊息不符）
                        try:
                            values = await conn.read_values(
                                [{"nodeid": d.nodeid, "name": d.name} for d in server_devices]
                            )
                        except Exception as ex2:
                            log_and_print(f"[{conn_name}] 重連後立即重試讀取仍失敗: {ex2}，"
                                          f"將於下一輪重試")
                            continue
                        # 不 continue，直接往下走到「數據處理與警報」區塊
                    else:
                        fail_count = self.connection_fail_counts.get(conn_name, 0) + 1
                        self.connection_fail_counts[conn_name] = fail_count
                        log_and_print(f"[{conn_name}] 連續重試 {RECONNECT_RETRY_ATTEMPTS} 次仍無法"
                                      f"重新連線，將留待下一輪 ({self.check_interval} 秒後) 再試..."
                                      f"(連續失敗週期 {fail_count} 次)")

                        # 降噪：首次失敗寄送一次告警，之後不再重複，
                        # 直到連續失敗次數達到升級門檻才再寄一次
                        if fail_count == 1 or fail_count == RECONNECT_ALERT_THRESHOLD:
                            try:
                                diag_result = await conn.diagnose_kepware()
                            except Exception:
                                diag_result = DiagnosticResult(
                                    DiagnosticResult.LEVEL_HOST_DOWN,
                                    f"[{conn_name}] 連線異常: {ex}",
                                )
                            if fail_count == RECONNECT_ALERT_THRESHOLD:
                                diag_result.message = (
                                    f"{diag_result.message}"
                                    f"（已連續重連失敗 {fail_count} 次，請儘速確認）"
                                )
                            self.send_connection_alert(conn_name, diag_result)

                        continue

                # ==========================================
                # 數據處理與警報
                # ==========================================
                current_ts = time.time()
                for device, raw_value in zip(server_devices, values):
                    try:
                        await self._process_device(device, raw_value, conn_name, current_ts)
                    except Exception as ex:
                        logging.exception(f"[{conn_name}] 處理設備 {device.name} 發生錯誤: {ex}")

            # Kepware Log polling（多台）
            for kl in self.kepware_logs:
                last_t = last_kepware_log_poll.get(kl.server_name, 0)
                if (now - last_t) >= kl.poll_interval:
                    try:
                        await asyncio.get_running_loop().run_in_executor(
                            None, kl.poll
                        )
                    except Exception as ex:
                        logging.error(f"Kepware Log[{kl.server_name}] polling 錯誤: {ex}")
                    last_kepware_log_poll[kl.server_name] = time.time()

            # Kepware 排程備份檢查
            if hasattr(self, 'backup_schedule') and self.backup_schedule:
                for kl in self.kepware_logs:
                    try:
                        await asyncio.get_running_loop().run_in_executor(
                            None, kl.check_weekly_backup, self.backup_schedule
                        )
                    except Exception as ex:
                        logging.error(f"Kepware Backup[{kl.server_name}] 檢查錯誤: {ex}")

            # 每日清理舊 DB 紀錄（服務長駐執行，可能數月不重啟，
            # 不能只在 start() 執行一次，否則資料會無限增長）
            today_str = datetime.now().strftime("%Y-%m-%d")
            if today_str != last_cleanup_date:
                if self.kepware_logs:
                    retention = max(kl.retention_days for kl in self.kepware_logs)
                else:
                    retention = 90
                try:
                    await asyncio.get_running_loop().run_in_executor(
                        None, self.db.cleanup_old_records, retention
                    )
                except Exception as ex:
                    logging.error(f"每日清理舊紀錄失敗: {ex}")
                last_cleanup_date = today_str

            # 等待下一輪
            log_and_print(f"等待 {self.check_interval} 秒後更新...")
            await asyncio.sleep(self.check_interval)

    async def _process_device(self, device, raw_value, conn_name, current_ts):
        """處理單一設備的數值判斷與派報"""
        # 檢查讀值是否為 None（Tag 不存在或讀取失敗）
        if raw_value is None and device.device_type != "log":
            device.counter += 1
            logging.warning(f"[{conn_name}] {device.name} 讀取值為 None "
                            f"(NodeId={device.nodeid})，Tag 可能不存在或讀取失敗 "
                            f"(counter={device.counter}/{device.accumulate})")

            self.db.write_history(
                server_name=conn_name,
                device_name=device.name,
                nodeid=device.nodeid,
                value=None,
                threshold=device.threshold,
                condition=device.condition,
                counter=device.counter,
                is_alert=True,
                alert_type="read_error",
            )

            # None 也要計入派報邏輯
            is_triggered = device.counter >= device.accumulate
            last_sent_ts = device.last_alert_time
            time_since_last = current_ts - last_sent_ts

            if is_triggered:
                if last_sent_ts == 0 or time_since_last >= self.alert_resend_interval:
                    log_and_print(
                        f"[{conn_name}] [讀取異常] {device.name} 連續 {device.counter} 次讀取為 None"
                    )
                    self.send_device_alert(
                        device, "None (Tag 不存在或讀取失敗)",
                        is_recovery=False,
                    )
                    device.last_alert_time = current_ts
            return

        if device.condition == "dynamic":
            is_alert, parsed_value = self._evaluate_dynamic(device, raw_value, conn_name)
        else:
            is_alert, parsed_value = self.evaluate(device, raw_value)
        write_val = parsed_value if parsed_value is not None else raw_value

        # 更新上一次讀取值（供 unchanged 條件使用）
        if parsed_value is not None:
            device.last_value = parsed_value

        # LOG 類型：只記錄不判斷
        if device.device_type == "log":
            device.counter = 0
            self.db.write_history(
                server_name=conn_name,
                device_name=device.name,
                nodeid=device.nodeid,
                value=write_val,
                threshold=device.threshold,
                condition=device.condition,
                counter=0,
                is_alert=False,
                alert_type="log",
            )
            log_and_print(f"[{conn_name}] 紀錄: {device.name} = {write_val}")
            return

        # 計算 counter
        if is_alert:
            device.counter += 1
        else:
            device.counter = 0

        # 數值異常時，做設備層診斷 (Layer 3)
        diag_result = None
        if is_alert and device.device_ip:
            diag_result = await self.diagnostic.diagnose_device(
                device.device_ip, device.device_port
            )
            device.last_diagnostic = diag_result

        # 寫入歷史
        self.db.write_history(
            server_name=conn_name,
            device_name=device.name,
            nodeid=device.nodeid,
            value=write_val,
            threshold=device.threshold,
            condition=device.condition,
            counter=device.counter,
            is_alert=is_alert,
            alert_type=diag_result.level if diag_result else "value",
            diagnostic=diag_result.message if diag_result else None,
        )

        status = "異常" if is_alert else "正常"
        log_and_print(f"[{conn_name}] {device.name} = {write_val} [{status}] "
                      f"(counter={device.counter}/{device.accumulate})")

        # 派報邏輯
        is_triggered = device.counter >= device.accumulate
        last_sent_ts = device.last_alert_time
        time_since_last = current_ts - last_sent_ts

        if is_triggered:
            if last_sent_ts == 0 or time_since_last >= self.alert_resend_interval:
                if last_sent_ts == 0:
                    log_and_print(
                        f"[{conn_name}] [首次觸發] {device.name} 異常值: {write_val}"
                    )
                else:
                    log_and_print(
                        f"[{conn_name}] [持續異常] {device.name} 仍異常: {write_val} "
                        f"(已過 {int(time_since_last)} 秒)"
                    )

                self.send_device_alert(
                    device, write_val,
                    is_recovery=False,
                    diagnostic_result=diag_result,
                )
                device.last_alert_time = current_ts

        elif not is_alert and last_sent_ts > 0:
            # 復歸
            log_and_print(
                f"[{conn_name}] [恢復] {device.name} 已恢復正常: {write_val}"
            )
            self.send_device_alert(
                device, write_val,
                is_recovery=True,
            )
            device.last_alert_time = 0
            device.counter = 0
