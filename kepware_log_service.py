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
    """

    CHANNEL_DEVICE_RE = re.compile(r"^([A-Za-z0-9_\-]+)\.([A-Za-z0-9_\-]+)\s*\|")

    def __init__(self, config, db_service, email_service, webhook_service=None):
        self.config = config
        self.db = db_service
        self.email_service = email_service
        self.webhook = webhook_service

        self.base_url = config.get("KepwareLog", "ApiBaseUrl", fallback="").strip().rstrip("/")
        self.username = config.get("KepwareLog", "Username", fallback="")
        self.password = config.get("KepwareLog", "Password", fallback="")
        self.poll_interval = config.getint("KepwareLog", "PollInterval", fallback=600)

        self.channel_alert_window = config.getint("KepwareLog", "ChannelAlertWindow", fallback=3600)
        self.channel_alert_threshold = config.getint("KepwareLog", "ChannelAlertThreshold", fallback=5)
        self.tag_error_consecutive = config.getint("KepwareLog", "TagErrorConsecutive", fallback=6)
        self.retention_days = config.getint("KepwareLog", "RetentionDays", fallback=90)

        keywords_raw = config.get("KepwareLog", "CriticalKeywords",
                                  fallback="Runtime stopped,License error,Server shutdown")
        self.critical_keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]

        self.global_mail_to = [x.strip() for x in config.get("Mail", "To", fallback="").split(",") if x.strip()]
        self.global_mail_cc = [x.strip() for x in config.get("Mail", "Cc", fallback="").split(",") if x.strip()]
        self.mail_subject = config.get("Mail", "Subject", fallback="Kepware 設備監控通知")

        self._token = None
        self._headers = {}
        self._last_event_ts = None
        self._last_tx_ts = None
        self._alerted_channels = {}
        self._alerted_tags = set()

        logging.info(f"KepwareLogService 初始化: base_url={self.base_url}, "
                     f"poll={self.poll_interval}s, "
                     f"channel_threshold={self.channel_alert_threshold}/{self.channel_alert_window}s, "
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
            logging.info("KepwareLogService: JWT 登入成功")
        except Exception as ex:
            logging.error(f"KepwareLogService: JWT 登入失敗: {ex}")
            raise

    def _api_get(self, path):
        if not self._token:
            self._login()

        url = f"{self.base_url}{path}"
        resp = requests.get(url, headers=self._headers, timeout=30)

        if resp.status_code == 401:
            logging.info("KepwareLogService: Token 過期，重新登入")
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
            logging.error(f"KepwareLogService polling 失敗: {ex}")

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

            is_alert, alert_type = self._evaluate_event(
                event_type, message, channel, device, ts
            )

            self.db.write_kepware_event(
                timestamp=ts, event=event_type, source=source,
                channel=channel, device=device, message=message,
                dedup_hash=dedup_hash, is_alert=is_alert, alert_type=alert_type,
            )
            new_count += 1

        if new_count > 0:
            logging.info(f"KepwareLogService: 寫入 {new_count} 筆新事件")

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
            )
            new_count += 1

            if is_alert:
                self._send_transaction_alert(tx)

        if new_count > 0:
            logging.info(f"KepwareLogService: 寫入 {new_count} 筆新交易紀錄")

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

    # ===========================================
    # 異常判斷
    # ===========================================

    def _evaluate_event(self, event_type, message, channel, device, timestamp):
        if event_type not in ("Warning", "Error"):
            return False, None

        for kw in self.critical_keywords:
            if kw.lower() in message.lower():
                self._send_critical_alert(event_type, message, timestamp)
                return True, "critical_keyword"

        if channel:
            window_start = (
                datetime.fromisoformat(timestamp) - timedelta(seconds=self.channel_alert_window)
            ).isoformat()
            count = self.db.count_channel_events_in_window(channel, window_start)
            count += 1

            if count >= self.channel_alert_threshold:
                alert_key = f"channel:{channel}"
                now = datetime.now()
                last_alerted = self._alerted_channels.get(alert_key)
                if not last_alerted or (now - last_alerted).total_seconds() > self.channel_alert_window:
                    self._alerted_channels[alert_key] = now
                    self._send_channel_alert(channel, count, timestamp)
                return True, "channel_threshold"

        if channel and device:
            consecutive = self.db.count_consecutive_tag_errors(channel, device)
            consecutive += 1

            if consecutive >= self.tag_error_consecutive:
                tag_key = f"tag:{channel}.{device}"
                if tag_key not in self._alerted_tags:
                    self._alerted_tags.add(tag_key)
                    self._send_tag_alert(channel, device, consecutive, timestamp)
                return True, "tag_consecutive"

        return False, None

    # ===========================================
    # 派報
    # ===========================================

    def _send_critical_alert(self, event_type, message, timestamp):
        subject = f"[緊急] {self.mail_subject} - Kepware 關鍵事件"
        html_body = f"""
        <html><body>
            <h2 style="color: #dc3545;">Kepware 關鍵事件告警</h2>
            <p><strong>時間:</strong> {timestamp}</p>
            <p><strong>事件等級:</strong> {event_type}</p>
            <p><strong>訊息:</strong></p>
            <p style="font-size:1.1em;font-weight:bold;color:#dc3545;">{message}</p>
            <hr><p>此事件符合關鍵字即時告警條件，請立即確認。</p>
        </body></html>
        """
        self._do_send_alert(subject, html_body, "kepware_critical", message)

    def _send_channel_alert(self, channel, count, timestamp):
        window_min = self.channel_alert_window // 60
        subject = f"[異常] {self.mail_subject} - Channel {channel} 通訊異常"
        html_body = f"""
        <html><body>
            <h2 style="color: #dc3545;">Kepware Channel 通訊異常</h2>
            <p><strong>時間:</strong> {timestamp}</p>
            <p><strong>Channel:</strong> {channel}</p>
            <p><strong>累積次數:</strong>
               <span style="font-size:1.2em;font-weight:bold;color:#dc3545;">
               {count} 次 / {window_min} 分鐘</span></p>
            <p><strong>門檻:</strong> {self.channel_alert_threshold} 次 / {window_min} 分鐘</p>
            <hr><p>Channel 通訊錯誤累積已達門檻，請確認設備連線狀態。</p>
        </body></html>
        """
        self._do_send_alert(subject, html_body, "kepware_channel", channel)

    def _send_tag_alert(self, channel, device, count, timestamp):
        tag_name = f"{channel}.{device}"
        subject = f"[異常] {self.mail_subject} - Tag {tag_name} 讀取異常"
        html_body = f"""
        <html><body>
            <h2 style="color: #dc3545;">Kepware Tag 讀取異常</h2>
            <p><strong>時間:</strong> {timestamp}</p>
            <p><strong>Channel.Device:</strong> {tag_name}</p>
            <p><strong>連續失敗次數:</strong>
               <span style="font-size:1.2em;font-weight:bold;color:#dc3545;">
               {count} 次</span></p>
            <p><strong>門檻:</strong> {self.tag_error_consecutive} 次</p>
            <hr><p>Tag 連續讀取失敗已達門檻，請確認點位設定或設備狀態。</p>
        </body></html>
        """
        self._do_send_alert(subject, html_body, "kepware_tag", tag_name)

    def _send_transaction_alert(self, tx):
        subject = f"[操作] {self.mail_subject} - Kepware DELETE 操作通知"
        html_body = f"""
        <html><body>
            <h2 style="color: #f59e0b;">Kepware 設定刪除操作通知</h2>
            <p><strong>時間:</strong> {tx.get('timestamp')}</p>
            <p><strong>操作者:</strong> {tx.get('user')}</p>
            <p><strong>操作:</strong> DELETE</p>
            <p><strong>目標:</strong> {tx.get('endpoint')}</p>
            <p><strong>來源 IP:</strong> {tx.get('source')}</p>
            <p><strong>回應碼:</strong> {tx.get('response')}</p>
            <hr><p>有人對 Kepware 執行了刪除操作，請確認是否為預期行為。</p>
        </body></html>
        """
        self._do_send_alert(subject, html_body, "kepware_delete",
                            f"{tx.get('user')} DELETE {tx.get('endpoint')}")

    def _do_send_alert(self, subject, html_body, alert_type, diagnostic_msg):
        logging.info(f"KepwareLogService 派報: {subject}")

        try:
            self.email_service.send_alert_email(
                to_addresses=self.global_mail_to,
                cc_addresses=self.global_mail_cc,
                subject=subject,
                html_body=html_body,
            )
        except Exception as ex:
            logging.exception(f"KepwareLogService 寄信失敗: {ex}")

        try:
            self.db.write_alert_log(
                server_name="KepwareAPI",
                device_name="",
                alert_type=alert_type,
                diagnostic_level=alert_type,
                diagnostic_msg=diagnostic_msg,
                recipients_to=self.global_mail_to,
                recipients_cc=self.global_mail_cc,
                subject=subject,
            )
        except Exception as ex:
            logging.warning(f"KepwareLogService 派報紀錄寫入失敗: {ex}")

        if self.webhook:
            self._fire_webhook(subject, diagnostic_msg, alert_type)

    def _fire_webhook(self, subject, diagnostic_msg, alert_type):
        def _do_send():
            try:
                variables = self.webhook.build_variables(
                    server_name="KepwareAPI",
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
                    server_name="KepwareAPI",
                    device_name=alert_type,
                    is_recovery=False,
                )
            except Exception as ex:
                logging.warning(f"KepwareLogService Webhook 推播失敗: {ex}")

        t = threading.Thread(target=_do_send, daemon=True)
        t.start()
