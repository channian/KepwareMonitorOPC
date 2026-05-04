import re
import hashlib
import logging
import threading
from datetime import datetime, timedelta

import requests


class KepwareLogService:
    """
    Kepware API Gateway Event/Transaction Log 監控服務：
      - JWT 認證 + 自動重新登入
      - 定期 polling events 和 transactions
      - 去重（timestamp + hash）
      - 異常判斷與派報觸發
      - 支援多台 Kepware（每台獨立 section: [KepwareLog.server_name]）
    """

    CHANNEL_DEVICE_RE = re.compile(r"^([A-Za-z0-9_\-]+)\.([A-Za-z0-9_\-]+)\s*\|")
    TAG_ADDRESS_RE = re.compile(r"Tag address\s*=\s*'([^']+)'")

    SEVERITY_LEVELS = ("Critical", "Warning", "Advisory", "Unclassified")

    DEFAULT_SEVERITY_CRITICAL = ["Device not responding"]
    DEFAULT_SEVERITY_WARNING = ["Timeout", "Add item failed"]
    DEFAULT_SEVERITY_ADVISORY = ["Failed to remove item"]

    def __init__(self, server_name, base_url, username, password,
                 db_service, email_service, webhook_service=None,
                 poll_interval=600,
                 channel_alert_window=3600, channel_alert_threshold=5,
                 tag_error_consecutive=6, retention_days=90,
                 critical_keywords=None,
                 severity_critical=None, severity_warning=None,
                 severity_advisory=None,
                 adaptive_baseline_days=7, adaptive_multiplier=3.0,
                 adaptive_min_threshold=3,
                 mail_to=None, mail_cc=None, event_subject=None):
        self.server_name = server_name
        self.db = db_service
        self.email_service = email_service
        self.webhook = webhook_service

        self.base_url = base_url.strip().rstrip("/")
        self.username = username
        self.password = password
        self.poll_interval = poll_interval

        self.channel_alert_window = channel_alert_window
        self.channel_alert_threshold = channel_alert_threshold
        self.tag_error_consecutive = tag_error_consecutive
        self.retention_days = retention_days

        self.critical_keywords = critical_keywords or [
            "Runtime stopped", "License error", "Server shutdown"
        ]

        self.severity_critical = severity_critical or self.DEFAULT_SEVERITY_CRITICAL
        self.severity_warning = severity_warning or self.DEFAULT_SEVERITY_WARNING
        self.severity_advisory = severity_advisory or self.DEFAULT_SEVERITY_ADVISORY

        self.adaptive_baseline_days = adaptive_baseline_days
        self.adaptive_multiplier = adaptive_multiplier
        self.adaptive_min_threshold = adaptive_min_threshold

        self.global_mail_to = mail_to or []
        self.global_mail_cc = mail_cc or []
        self.mail_subject = event_subject or "Kepware 事件監控通知"

        self._token = None
        self._headers = {}
        self._last_event_ts = None
        self._last_tx_ts = None
        self._alerted_channels = {}
        self._alerted_tags = {}
        self._channel_baselines = {}

        logging.info(f"KepwareLogService[{self.server_name}] 初始化: "
                     f"base_url={self.base_url}, poll={self.poll_interval}s, "
                     f"adaptive={self.adaptive_multiplier}x/{self.adaptive_baseline_days}d, "
                     f"tag_consecutive={self.tag_error_consecutive}")

    # ===========================================
    # JWT 認證
    # ===========================================

    def _login(self):
        try:
            resp = requests.post(
                f"{self.base_url}/api/auth/login",
                json={"username": self.username, "password": self.password},
                timeout=15,
            )
            resp.raise_for_status()
            self._token = resp.json()["access_token"]
            self._headers = {"Authorization": f"Bearer {self._token}"}
            logging.info(f"KepwareLogService[{self.server_name}]: JWT 登入成功")
        except Exception as ex:
            logging.error(f"KepwareLogService[{self.server_name}]: JWT 登入失敗: {ex}")
            raise

    def _api_get(self, path):
        if not self._token:
            self._login()

        url = f"{self.base_url}{path}"
        resp = requests.get(url, headers=self._headers, timeout=30)

        if resp.status_code == 401:
            logging.info(f"KepwareLogService[{self.server_name}]: Token 過期，重新登入")
            self._login()
            resp = requests.get(url, headers=self._headers, timeout=30)

        resp.raise_for_status()
        return resp.json()

    # ===========================================
    # Polling
    # ===========================================

    def poll(self):
        try:
            self._poll_events()
            self._poll_transactions()
        except Exception as ex:
            logging.error(f"KepwareLogService[{self.server_name}] polling 失敗: {ex}")

    def _poll_events(self):
        data = self._api_get("/api/monitor/events")
        events = data.get("data", [])

        new_count = 0
        for ev in events:
            ts = ev.get("timestamp", "")
            source = ev.get("source", "")
            message = ev.get("message", "")
            event_type = ev.get("event", "")

            dedup_hash = self._make_hash(ts, source, message)
            if self.db.kepware_event_exists(dedup_hash):
                continue

            channel, device = self._parse_channel_device(message)
            tag_address = self._parse_tag_address(message)
            severity = self._classify_severity(message)

            is_alert, alert_type = self._evaluate_event(
                event_type, message, channel, device, ts, severity
            )

            self.db.write_kepware_event(
                timestamp=ts, event=event_type, source=source,
                channel=channel, device=device, message=message,
                dedup_hash=dedup_hash, is_alert=is_alert, alert_type=alert_type,
                server_name=self.server_name, tag_address=tag_address,
                severity=severity,
            )
            new_count += 1

        if new_count > 0:
            logging.info(f"KepwareLogService[{self.server_name}]: 寫入 {new_count} 筆新事件")

    def _poll_transactions(self):
        data = self._api_get("/api/monitor/transactions")
        transactions = data.get("data", [])

        new_count = 0
        for tx in transactions:
            ts = tx.get("timestamp", "")
            user = tx.get("user", "")
            action = tx.get("action", "")
            endpoint = tx.get("endpoint", "")
            source_ip = tx.get("source", "")
            response = tx.get("response", 0)

            if self.db.kepware_transaction_exists(ts, user, action, endpoint):
                continue

            is_alert = action == "DELETE"

            self.db.write_kepware_transaction(
                timestamp=ts, user=user, action=action,
                endpoint=endpoint, source_ip=source_ip,
                response=response, is_alert=is_alert,
                server_name=self.server_name,
            )
            new_count += 1

            if is_alert:
                self._send_transaction_alert(tx)

        if new_count > 0:
            logging.info(f"KepwareLogService[{self.server_name}]: 寫入 {new_count} 筆新交易紀錄")

    # ===========================================
    # 解析 & 去重
    # ===========================================

    @staticmethod
    def _make_hash(timestamp, source, message):
        raw = f"{timestamp}|{source}|{message}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def _parse_channel_device(self, message):
        m = self.CHANNEL_DEVICE_RE.match(message)
        if m:
            return m.group(1), m.group(2)
        return "", ""

    def _parse_tag_address(self, message):
        m = self.TAG_ADDRESS_RE.search(message)
        return m.group(1) if m else ""

    # ===========================================
    # 事件分類 & 自適應閥值
    # ===========================================

    def _classify_severity(self, message):
        msg_lower = message.lower()
        for kw in self.severity_critical:
            if kw.lower() in msg_lower:
                return "Critical"
        for kw in self.severity_warning:
            if kw.lower() in msg_lower:
                return "Warning"
        for kw in self.severity_advisory:
            if kw.lower() in msg_lower:
                return "Advisory"
        return "Unclassified"

    def _get_adaptive_threshold(self, channel):
        baseline = self._channel_baselines.get(channel)
        now = datetime.now()
        if baseline and (now - baseline["ts"]).total_seconds() < 86400:
            return baseline["threshold"]

        avg_hourly = self.db.get_channel_hourly_error_rate(
            channel, days=self.adaptive_baseline_days
        )
        threshold = max(avg_hourly * self.adaptive_multiplier,
                        self.adaptive_min_threshold)
        self._channel_baselines[channel] = {"threshold": threshold, "ts": now}
        logging.info(f"KepwareLogService[{self.server_name}] "
                     f"Channel {channel} 自適應閥值: {threshold:.1f}/hr "
                     f"(基準 {avg_hourly:.2f}/hr × {self.adaptive_multiplier})")
        return threshold

    def _evaluate_event(self, event_type, message, channel, device,
                        timestamp, severity):
        if event_type not in ("Warning", "Error"):
            return False, None

        tag_address = self._parse_tag_address(message)

        if severity == "Critical":
            self._send_critical_alert(event_type, message, timestamp)
            return True, "critical_event"

        for kw in self.critical_keywords:
            if kw.lower() in message.lower():
                self._send_critical_alert(event_type, message, timestamp)
                return True, "critical_keyword"

        if severity == "Advisory":
            return False, None

        if channel:
            if severity == "Warning":
                threshold = self._get_adaptive_threshold(channel)
                threshold_label = f"自適應閥值 {threshold:.0f}"
            else:
                threshold = self.channel_alert_threshold
                threshold_label = f"固定閥值 {threshold}"

            window_start = (
                datetime.fromisoformat(timestamp) - timedelta(seconds=self.channel_alert_window)
            ).isoformat()
            count = self.db.count_channel_events_in_window(channel, window_start)
            count += 1

            if count >= threshold:
                alert_key = f"channel:{channel}"
                now = datetime.now()
                last_alerted = self._alerted_channels.get(alert_key)
                if not last_alerted or (now - last_alerted).total_seconds() > self.channel_alert_window:
                    self._alerted_channels[alert_key] = now
                    self._send_channel_alert(
                        channel, count, timestamp, severity,
                        threshold, threshold_label, message,
                    )
                return True, "channel_adaptive" if severity == "Warning" else "channel_threshold"

        if channel and device:
            consecutive = self.db.count_consecutive_tag_errors(channel, device)
            consecutive += 1

            if consecutive >= self.tag_error_consecutive:
                tag_key = f"tag:{channel}.{device}"
                now = datetime.now()
                last_alerted = self._alerted_tags.get(tag_key)
                if not last_alerted or (now - last_alerted).total_seconds() > self.channel_alert_window:
                    self._alerted_tags[tag_key] = now
                    self._send_tag_alert(channel, device, consecutive, timestamp, tag_address, message)
                return True, "tag_consecutive"

        return False, None

    # ===========================================
    # 派報
    # ===========================================

    _SEVERITY_COLORS = {
        "Critical": ("#dc3545", "#fdf2f2"),
        "Warning":  ("#f59e0b", "#fefce8"),
        "Advisory": ("#3b82f6", "#eff6ff"),
    }

    @staticmethod
    def _build_email_html(badge_color, badge_bg, badge_text, title,
                          rows, message="", footer=""):
        rows_html = ""
        for label, value in rows:
            rows_html += (
                f'<tr><td style="padding:6px 12px;font-weight:bold;'
                f'white-space:nowrap;vertical-align:top;">{label}</td>'
                f'<td style="padding:6px 12px;">{value}</td></tr>'
            )
        msg_html = ""
        if message:
            msg_html = (
                f'<div style="margin:16px 0;padding:12px 16px;'
                f'background:#f8f9fa;border-left:4px solid {badge_color};'
                f'font-family:monospace;font-size:13px;word-break:break-all;">'
                f'{message}</div>'
            )
        return f"""<html><body style="font-family:Arial,sans-serif;color:#333;margin:0;padding:0;">
<div style="max-width:640px;margin:20px auto;">
  <div style="padding:12px 20px;background:{badge_bg};border-left:5px solid {badge_color};margin-bottom:16px;">
    <span style="display:inline-block;padding:2px 10px;background:{badge_color};color:#fff;
          border-radius:3px;font-size:12px;font-weight:bold;letter-spacing:1px;">{badge_text}</span>
    <span style="margin-left:10px;font-size:16px;font-weight:bold;color:{badge_color};">{title}</span>
  </div>
  <table style="border-collapse:collapse;width:100%;font-size:14px;">
    {rows_html}
  </table>
  {msg_html}
  <hr style="border:none;border-top:1px solid #e0e0e0;margin:16px 0;">
  <p style="font-size:13px;color:#666;">{footer}</p>
</div>
</body></html>"""

    def _send_critical_alert(self, event_type, message, timestamp):
        subject = f"[緊急] {self.mail_subject} - [{self.server_name}] 關鍵事件"
        color, bg = self._SEVERITY_COLORS["Critical"]
        html_body = self._build_email_html(
            badge_color=color, badge_bg=bg,
            badge_text="CRITICAL", title="關鍵事件告警",
            rows=[
                ("Server", self.server_name),
                ("時間", timestamp),
                ("事件等級", event_type),
            ],
            message=message,
            footer="此事件符合關鍵字即時告警條件，請立即確認設備狀態。",
        )
        self._do_send_alert(subject, html_body, "kepware_critical", message)

    def _send_channel_alert(self, channel, count, timestamp, severity,
                            threshold, threshold_label, message=""):
        window_min = self.channel_alert_window // 60
        subject = f"[異常] {self.mail_subject} - [{self.server_name}] Channel {channel} 通訊異常"
        color, bg = self._SEVERITY_COLORS.get(severity, ("#6b7280", "#f3f4f6"))
        html_body = self._build_email_html(
            badge_color=color, badge_bg=bg,
            badge_text=severity.upper(), title=f"Channel {channel} 通訊異常",
            rows=[
                ("Server", self.server_name),
                ("時間", timestamp),
                ("Channel", channel),
                ("嚴重等級", severity),
                ("累積次數",
                 f'<span style="font-size:1.1em;font-weight:bold;color:{color};">'
                 f'{count} 次 / {window_min} 分鐘</span>'),
                ("告警門檻",
                 f'{threshold_label} — {threshold:.0f} 次 / {window_min} 分鐘'),
            ],
            message=message,
            footer="Channel 通訊錯誤累積已達門檻，請確認設備連線狀態。",
        )
        self._do_send_alert(subject, html_body, "kepware_channel", channel)

    def _send_tag_alert(self, channel, device, count, timestamp,
                        tag_address="", message=""):
        tag_name = f"{channel}.{device}"
        subject = f"[異常] {self.mail_subject} - [{self.server_name}] Tag {tag_name} 讀取異常"
        color, bg = self._SEVERITY_COLORS["Warning"]
        rows = [
            ("Server", self.server_name),
            ("時間", timestamp),
            ("Channel.Device", tag_name),
        ]
        if tag_address:
            rows.append(("Tag Address", f'<code>{tag_address}</code>'))
        rows += [
            ("連續失敗",
             f'<span style="font-size:1.1em;font-weight:bold;color:{color};">'
             f'{count} 次</span>'),
            ("告警門檻", f'{self.tag_error_consecutive} 次'),
        ]
        html_body = self._build_email_html(
            badge_color=color, badge_bg=bg,
            badge_text="TAG ERROR", title=f"Tag {tag_name} 讀取異常",
            rows=rows,
            message=message,
            footer="Tag 連續讀取失敗已達門檻，請確認點位設定或設備狀態。",
        )
        self._do_send_alert(subject, html_body, "kepware_tag", tag_name)

    def _send_transaction_alert(self, tx):
        subject = f"[操作] {self.mail_subject} - [{self.server_name}] DELETE 操作通知"
        html_body = self._build_email_html(
            badge_color="#f59e0b", badge_bg="#fefce8",
            badge_text="DELETE", title="設定刪除操作通知",
            rows=[
                ("Server", self.server_name),
                ("時間", tx.get("timestamp", "")),
                ("操作者", tx.get("user", "")),
                ("操作", "DELETE"),
                ("目標", f'<code>{tx.get("endpoint", "")}</code>'),
                ("來源 IP", tx.get("source", "")),
                ("回應碼", str(tx.get("response", ""))),
            ],
            footer="有人對 Kepware 執行了刪除操作，請確認是否為預期行為。",
        )
        self._do_send_alert(subject, html_body, "kepware_delete",
                            f"{tx.get('user')} DELETE {tx.get('endpoint')}")

    def _do_send_alert(self, subject, html_body, alert_type, diagnostic_msg):
        logging.info(f"KepwareLogService[{self.server_name}] 派報: {subject}")

        try:
            self.email_service.send_alert_email(
                to_addresses=self.global_mail_to,
                cc_addresses=self.global_mail_cc,
                subject=subject,
                html_body=html_body,
            )
        except Exception as ex:
            logging.exception(f"KepwareLogService[{self.server_name}] 寄信失敗: {ex}")

        try:
            self.db.write_alert_log(
                server_name=self.server_name,
                device_name="",
                alert_type=alert_type,
                diagnostic_level=alert_type,
                diagnostic_msg=diagnostic_msg,
                recipients_to=self.global_mail_to,
                recipients_cc=self.global_mail_cc,
                subject=subject,
            )
        except Exception as ex:
            logging.warning(f"KepwareLogService[{self.server_name}] 派報紀錄寫入失敗: {ex}")

        if self.webhook:
            self._fire_webhook(subject, diagnostic_msg, alert_type)

    def _fire_webhook(self, subject, diagnostic_msg, alert_type):
        def _do_send():
            try:
                variables = self.webhook.build_variables(
                    server_name=self.server_name,
                    device_name=alert_type,
                    value="",
                    threshold="",
                    condition="",
                    counter=0,
                    accumulate=0,
                    diagnostic_msg=diagnostic_msg,
                    is_recovery=False,
                )
                self.webhook.send(
                    variables,
                    db_service=self.db,
                    server_name=self.server_name,
                    device_name=alert_type,
                    is_recovery=False,
                )
            except Exception as ex:
                logging.warning(f"KepwareLogService[{self.server_name}] Webhook 推播失敗: {ex}")

        t = threading.Thread(target=_do_send, daemon=True)
        t.start()
