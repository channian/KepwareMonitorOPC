import os
import re
import hashlib
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path

import requests


class KepwareLogService:
    """
    Kepware API Gateway Event/Transaction Log 監控服務：
      - JWT 認證 + 自動重新登入
      - 定期 polling events 和 transactions
      - 去重（timestamp + hash）
      - CriticalKeywords / Critical severity → 立即派報
      - 其餘事件僅記錄，每日 23:50 彙整報告
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
                 poll_interval=600, retention_days=90,
                 critical_keywords=None,
                 severity_critical=None, severity_warning=None,
                 severity_advisory=None,
                 mail_to=None, mail_cc=None, event_subject=None,
                 **_ignored):
        self.server_name = server_name
        self.db = db_service
        self.email_service = email_service
        self.webhook = webhook_service

        self.base_url = base_url.strip().rstrip("/")
        self.username = username
        self.password = password
        self.poll_interval = poll_interval
        self.retention_days = retention_days

        self.critical_keywords = critical_keywords or [
            "Runtime stopped", "License error", "Server shutdown"
        ]

        self.severity_critical = severity_critical or self.DEFAULT_SEVERITY_CRITICAL
        self.severity_warning = severity_warning or self.DEFAULT_SEVERITY_WARNING
        self.severity_advisory = severity_advisory or self.DEFAULT_SEVERITY_ADVISORY

        self.global_mail_to = mail_to or []
        self.global_mail_cc = mail_cc or []
        self.mail_subject = event_subject or "Kepware 事件監控通知"

        self._token = None
        self._headers = {}
        self._last_event_ts = None
        self._last_tx_ts = None

        self._summary_marker_dir = Path("data")
        self._summary_marker_dir.mkdir(parents=True, exist_ok=True)
        self._summary_marker_path = (
            self._summary_marker_dir / f".daily_summary_sent_{self.server_name}"
        )
        self._daily_summary_sent = self._load_summary_marker()

        logging.info(f"KepwareLogService[{self.server_name}] 初始化: "
                     f"base_url={self.base_url}, poll={self.poll_interval}s")

    def _load_summary_marker(self):
        try:
            return self._summary_marker_path.read_text().strip()
        except FileNotFoundError:
            return None

    def _save_summary_marker(self, date_str):
        self._summary_marker_path.write_text(date_str)
        self._daily_summary_sent = date_str

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
            self._check_daily_summary()
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
                event_type, message, severity
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
    # 事件分類
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

    def _evaluate_event(self, event_type, message, severity):
        if event_type not in ("Warning", "Error"):
            return False, None

        if severity == "Critical":
            self._send_critical_alert(event_type, message,
                                      datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            return True, "critical_event"

        for kw in self.critical_keywords:
            if kw.lower() in message.lower():
                self._send_critical_alert(event_type, message,
                                          datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                return True, "critical_keyword"

        return False, None

    # ===========================================
    # 每日彙整報告（22:00 後首次 poll 觸發）
    # ===========================================

    def _check_daily_summary(self):
        now = datetime.now()
        if now.hour < 22:
            return
        today_str = now.strftime("%Y-%m-%d")
        if self._daily_summary_sent == today_str:
            return
        try:
            self._send_daily_summary(today_str)
            self._save_summary_marker(today_str)
        except Exception as ex:
            logging.error(f"KepwareLogService[{self.server_name}] "
                          f"每日彙整失敗: {ex}")

    def _send_daily_summary(self, date_str):
        summary = self.db.get_daily_event_summary(date_str, self.server_name)
        today = summary["today_total"]

        subject = f"[日報] {self.mail_subject} - [{self.server_name}] {date_str}"

        if today == 0:
            html_body = f"""<html><body style="font-family:Arial,sans-serif;color:#333;margin:0;padding:0;">
<div style="max-width:700px;margin:20px auto;">
  <div style="padding:12px 20px;background:#f0fdf4;border-left:5px solid #22c55e;margin-bottom:16px;">
    <span style="font-size:16px;font-weight:bold;color:#16a34a;">
      Kepware 事件日報 — {self.server_name}</span>
    <span style="float:right;color:#666;">{date_str}</span>
  </div>
  <p style="font-size:15px;padding:8px 12px;">今日無異常事件，系統運作正常。</p>
  <hr style="border:none;border-top:1px solid #e0e0e0;margin:20px 0;">
  <p style="font-size:12px;color:#999;">
    此為每日自動彙整報告，詳細紀錄請至 Web UI 查詢。</p>
</div>
</body></html>"""
            self._do_send_alert(subject, html_body, "kepware_daily_summary",
                                f"{date_str} total=0 (無異常)")
            logging.info(f"KepwareLogService[{self.server_name}] "
                         f"每日彙整已發送: {date_str}, 今日無異常")
            return

        sc = summary["severity_counts"]
        avg = summary["avg_daily_7d"]

        if avg > 0:
            pct = ((today - avg) / avg) * 100
            if pct > 0:
                trend = f"↑ {pct:.0f}% (7日均值 {avg:.0f})"
            elif pct < 0:
                trend = f"↓ {abs(pct):.0f}% (7日均值 {avg:.0f})"
            else:
                trend = f"— 持平 (7日均值 {avg:.0f})"
        else:
            trend = "無歷史資料"

        sev_html = ""
        sev_colors = {"Critical": "#dc3545", "Warning": "#f59e0b",
                      "Advisory": "#3b82f6", "Unclassified": "#6b7280"}
        for sev in ("Critical", "Warning", "Advisory", "Unclassified"):
            cnt = sc.get(sev, 0)
            if cnt == 0:
                continue
            color = sev_colors[sev]
            sev_html += (
                f'<span style="display:inline-block;margin:2px 6px 2px 0;'
                f'padding:3px 10px;background:{color};color:#fff;'
                f'border-radius:3px;font-size:13px;">'
                f'{sev} {cnt}</span>'
            )

        ch_html = ""
        if summary["top_channels"]:
            ch_html = ('<table style="border-collapse:collapse;width:100%;'
                       'font-size:13px;margin-top:8px;">'
                       '<tr style="background:#f3f4f6;">'
                       '<th style="padding:6px 10px;text-align:left;">Channel</th>'
                       '<th style="padding:6px 10px;text-align:right;">Critical</th>'
                       '<th style="padding:6px 10px;text-align:right;">Warning</th>'
                       '<th style="padding:6px 10px;text-align:right;">Advisory</th>'
                       '<th style="padding:6px 10px;text-align:right;">Other</th>'
                       '<th style="padding:6px 10px;text-align:right;">Total</th></tr>')
            for ch in summary["top_channels"]:
                ch_html += (
                    f'<tr><td style="padding:4px 10px;">{ch["channel"]}</td>'
                    f'<td style="padding:4px 10px;text-align:right;">{ch["Critical"]}</td>'
                    f'<td style="padding:4px 10px;text-align:right;">{ch["Warning"]}</td>'
                    f'<td style="padding:4px 10px;text-align:right;">{ch["Advisory"]}</td>'
                    f'<td style="padding:4px 10px;text-align:right;">{ch["Unclassified"]}</td>'
                    f'<td style="padding:4px 10px;text-align:right;font-weight:bold;">'
                    f'{ch["total"]}</td></tr>'
                )
            ch_html += "</table>"

        tag_html = ""
        if summary["top_tags"]:
            tag_html = ('<table style="border-collapse:collapse;width:100%;'
                        'font-size:13px;margin-top:8px;">'
                        '<tr style="background:#f3f4f6;">'
                        '<th style="padding:6px 10px;text-align:left;">Channel.Device</th>'
                        '<th style="padding:6px 10px;text-align:left;">Tag Address</th>'
                        '<th style="padding:6px 10px;text-align:right;">次數</th></tr>')
            for t in summary["top_tags"]:
                tag_html += (
                    f'<tr><td style="padding:4px 10px;">'
                    f'{t["channel"]}.{t["device"]}</td>'
                    f'<td style="padding:4px 10px;font-family:monospace;font-size:12px;">'
                    f'{t["tag_address"]}</td>'
                    f'<td style="padding:4px 10px;text-align:right;">{t["cnt"]}</td></tr>'
                )
            tag_html += "</table>"

        html_body = f"""<html><body style="font-family:Arial,sans-serif;color:#333;margin:0;padding:0;">
<div style="max-width:700px;margin:20px auto;">
  <div style="padding:12px 20px;background:#f0f9ff;border-left:5px solid #2563eb;margin-bottom:16px;">
    <span style="font-size:16px;font-weight:bold;color:#2563eb;">
      Kepware 事件日報 — {self.server_name}</span>
    <span style="float:right;color:#666;">{date_str}</span>
  </div>

  <table style="border-collapse:collapse;width:100%;font-size:14px;">
    <tr><td style="padding:6px 12px;font-weight:bold;">總異常事件</td>
        <td style="padding:6px 12px;">
          <span style="font-size:1.2em;font-weight:bold;">{today}</span> 筆</td></tr>
    <tr><td style="padding:6px 12px;font-weight:bold;">趨勢</td>
        <td style="padding:6px 12px;">{trend}</td></tr>
    <tr><td style="padding:6px 12px;font-weight:bold;">嚴重等級分佈</td>
        <td style="padding:6px 12px;">{sev_html}</td></tr>
  </table>

  <h3 style="font-size:14px;color:#333;margin:20px 0 8px;">Channel 異常排行</h3>
  {ch_html if ch_html else '<p style="color:#999;font-size:13px;">無 Channel 異常</p>'}

  <h3 style="font-size:14px;color:#333;margin:20px 0 8px;">Tag 讀取異常</h3>
  {tag_html if tag_html else '<p style="color:#999;font-size:13px;">無 Tag 讀取異常</p>'}

  <hr style="border:none;border-top:1px solid #e0e0e0;margin:20px 0;">
  <p style="font-size:12px;color:#999;">
    此為每日自動彙整報告，詳細紀錄請至 Web UI 查詢。</p>
</div>
</body></html>"""

        self._do_send_alert(subject, html_body, "kepware_daily_summary",
                            f"{date_str} total={today}")
        logging.info(f"KepwareLogService[{self.server_name}] "
                     f"每日彙整已發送: {date_str}, 事件={today}")

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
