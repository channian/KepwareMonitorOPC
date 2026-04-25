import sqlite3
import os
import json
import csv
import logging
import hashlib
import secrets
from datetime import datetime


class DatabaseService:
    """
    SQLite 資料庫服務：
      - monitor_history: 監控歷史紀錄
      - alert_log: 派報紀錄
      - users: 使用者帳號
      - webhook_log: Webhook 推播紀錄
      - kepware_events: Kepware 事件記錄
      - kepware_transactions: Kepware Config API 操作記錄
    """

    def __init__(self, db_path="data/monitor.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        conn = self._get_conn()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS monitor_history (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp   TEXT NOT NULL,
                    server_name TEXT,
                    device_name TEXT NOT NULL,
                    nodeid      TEXT,
                    value       TEXT,
                    threshold   TEXT,
                    condition   TEXT,
                    counter     INTEGER DEFAULT 0,
                    is_alert    INTEGER DEFAULT 0,
                    alert_type  TEXT DEFAULT 'value',
                    diagnostic  TEXT
                );

                CREATE TABLE IF NOT EXISTS alert_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp   TEXT NOT NULL,
                    server_name TEXT,
                    device_name TEXT,
                    alert_type  TEXT,
                    diagnostic_level TEXT,
                    diagnostic_msg   TEXT,
                    recipients_to    TEXT,
                    recipients_cc    TEXT,
                    subject     TEXT,
                    is_recovery INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS users (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    username    TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    salt        TEXT NOT NULL,
                    role        TEXT NOT NULL DEFAULT 'viewer',
                    display_name TEXT,
                    created_at  TEXT NOT NULL,
                    last_login  TEXT
                );

                CREATE TABLE IF NOT EXISTS webhook_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp   TEXT NOT NULL,
                    server_name TEXT,
                    device_name TEXT,
                    url         TEXT,
                    request_body TEXT,
                    response_code INTEGER,
                    response_body TEXT,
                    is_success  INTEGER DEFAULT 0,
                    is_recovery INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS kepware_events (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp   TEXT NOT NULL,
                    server_name TEXT,
                    event       TEXT,
                    source      TEXT,
                    channel     TEXT,
                    device      TEXT,
                    tag_address TEXT,
                    message     TEXT,
                    dedup_hash  TEXT,
                    is_alert    INTEGER DEFAULT 0,
                    alert_type  TEXT,
                    created_at  TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS kepware_transactions (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp   TEXT NOT NULL,
                    server_name TEXT,
                    user        TEXT,
                    action      TEXT,
                    endpoint    TEXT,
                    source_ip   TEXT,
                    response    INTEGER,
                    is_alert    INTEGER DEFAULT 0,
                    created_at  TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_history_ts
                    ON monitor_history(timestamp);
                CREATE INDEX IF NOT EXISTS idx_history_device
                    ON monitor_history(device_name);
                CREATE INDEX IF NOT EXISTS idx_alert_ts
                    ON alert_log(timestamp);
                CREATE INDEX IF NOT EXISTS idx_webhook_ts
                    ON webhook_log(timestamp);
                CREATE INDEX IF NOT EXISTS idx_kep_event_ts
                    ON kepware_events(timestamp);
                CREATE INDEX IF NOT EXISTS idx_kep_event_channel
                    ON kepware_events(channel);
                CREATE INDEX IF NOT EXISTS idx_kep_event_dedup
                    ON kepware_events(dedup_hash);
                CREATE INDEX IF NOT EXISTS idx_kep_tx_ts
                    ON kepware_transactions(timestamp);
            """)
            conn.commit()

            self._migrate_kepware_columns(conn)

            # 建立預設 admin 帳號（若不存在）
            self._ensure_default_admin(conn)
        finally:
            conn.close()
        logging.info(f"SQLite 資料庫初始化完成: {self.db_path}")

    # ===========================================
    # 密碼工具
    # ===========================================

    @staticmethod
    def _hash_password(password, salt=None):
        """使用 SHA-256 + salt 雜湊密碼"""
        if salt is None:
            salt = secrets.token_hex(16)
        hashed = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
        return hashed, salt

    @staticmethod
    def _migrate_kepware_columns(conn):
        """為既有 DB 補上新欄位（server_name, tag_address）"""
        cursor = conn.execute("PRAGMA table_info(kepware_events)")
        ev_cols = {row[1] for row in cursor.fetchall()}
        if "server_name" not in ev_cols:
            conn.execute("ALTER TABLE kepware_events ADD COLUMN server_name TEXT")
        if "tag_address" not in ev_cols:
            conn.execute("ALTER TABLE kepware_events ADD COLUMN tag_address TEXT")

        cursor = conn.execute("PRAGMA table_info(kepware_transactions)")
        tx_cols = {row[1] for row in cursor.fetchall()}
        if "server_name" not in tx_cols:
            conn.execute("ALTER TABLE kepware_transactions ADD COLUMN server_name TEXT")

        conn.commit()

    def _ensure_default_admin(self, conn):
        """確保預設 admin 帳號存在"""
        row = conn.execute(
            "SELECT id FROM users WHERE username = ?", ("admin",)
        ).fetchone()
        if row is None:
            pw_hash, salt = self._hash_password("admin")
            conn.execute(
                """INSERT INTO users (username, password_hash, salt, role, display_name, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                ("admin", pw_hash, salt, "admin", "Administrator",
                 datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )
            conn.commit()
            logging.info("已建立預設管理員帳號: admin / admin（請儘速修改密碼）")

    # ===========================================
    # 使用者管理
    # ===========================================

    def authenticate_user(self, username, password):
        """驗證帳密，成功回傳 user dict，失敗回傳 None"""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()
            if row is None:
                return None
            pw_hash, _ = self._hash_password(password, row["salt"])
            if pw_hash != row["password_hash"]:
                return None
            # 更新最後登入時間
            conn.execute(
                "UPDATE users SET last_login = ? WHERE id = ?",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), row["id"]),
            )
            conn.commit()
            return dict(row)
        finally:
            conn.close()

    def get_all_users(self):
        """取得所有使用者（不含密碼）"""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT id, username, role, display_name, created_at, last_login FROM users ORDER BY id"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def create_user(self, username, password, role="viewer", display_name=""):
        """建立使用者"""
        conn = self._get_conn()
        try:
            pw_hash, salt = self._hash_password(password)
            conn.execute(
                """INSERT INTO users (username, password_hash, salt, role, display_name, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (username, pw_hash, salt, role, display_name or username,
                 datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()

    def update_user(self, user_id, role=None, display_name=None, password=None):
        """更新使用者資訊"""
        conn = self._get_conn()
        try:
            if password:
                pw_hash, salt = self._hash_password(password)
                conn.execute(
                    "UPDATE users SET password_hash = ?, salt = ? WHERE id = ?",
                    (pw_hash, salt, user_id),
                )
            if role is not None:
                conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
            if display_name is not None:
                conn.execute("UPDATE users SET display_name = ? WHERE id = ?", (display_name, user_id))
            conn.commit()
            return True
        finally:
            conn.close()

    def delete_user(self, user_id):
        """刪除使用者"""
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM users WHERE id = ? AND username != 'admin'", (user_id,))
            conn.commit()
            return True
        finally:
            conn.close()

    # ===========================================
    # Webhook 紀錄
    # ===========================================

    def write_webhook_log(self, server_name, device_name, url,
                          request_body, response_code, response_body,
                          is_success, is_recovery=False):
        """寫入 Webhook 推播紀錄"""
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO webhook_log
                   (timestamp, server_name, device_name, url,
                    request_body, response_code, response_body,
                    is_success, is_recovery)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    server_name, device_name, url,
                    request_body, response_code, response_body,
                    int(is_success), int(is_recovery),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def query_webhook_logs(self, start_date=None, end_date=None, limit=200):
        """查詢 Webhook 推播紀錄"""
        conn = self._get_conn()
        try:
            sql = "SELECT * FROM webhook_log WHERE 1=1"
            params = []
            if start_date:
                sql += " AND timestamp >= ?"
                params.append(start_date)
            if end_date:
                sql += " AND timestamp <= ?"
                params.append(end_date + " 23:59:59")
            sql += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def write_history(self, server_name, device_name, nodeid, value,
                      threshold, condition, counter, is_alert,
                      alert_type="value", diagnostic=None):
        """寫入監控歷史紀錄"""
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO monitor_history
                   (timestamp, server_name, device_name, nodeid, value,
                    threshold, condition, counter, is_alert, alert_type, diagnostic)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    server_name,
                    device_name,
                    nodeid,
                    str(value) if value is not None else None,
                    str(threshold) if threshold is not None else None,
                    condition,
                    counter,
                    int(is_alert),
                    alert_type,
                    diagnostic,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def write_alert_log(self, server_name, device_name, alert_type,
                        diagnostic_level, diagnostic_msg,
                        recipients_to, recipients_cc, subject,
                        is_recovery=False):
        """寫入派報紀錄"""
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO alert_log
                   (timestamp, server_name, device_name, alert_type,
                    diagnostic_level, diagnostic_msg,
                    recipients_to, recipients_cc, subject, is_recovery)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    server_name,
                    device_name,
                    alert_type,
                    diagnostic_level,
                    diagnostic_msg,
                    json.dumps(recipients_to, ensure_ascii=False) if recipients_to else None,
                    json.dumps(recipients_cc, ensure_ascii=False) if recipients_cc else None,
                    subject,
                    int(is_recovery),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def query_history(self, start_date=None, end_date=None,
                      device_name=None, limit=500):
        """查詢監控歷史"""
        conn = self._get_conn()
        try:
            sql = "SELECT * FROM monitor_history WHERE 1=1"
            params = []
            if start_date:
                sql += " AND timestamp >= ?"
                params.append(start_date)
            if end_date:
                sql += " AND timestamp <= ?"
                params.append(end_date + " 23:59:59")
            if device_name:
                sql += " AND device_name = ?"
                params.append(device_name)
            sql += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def query_alerts(self, start_date=None, end_date=None, limit=200):
        """查詢派報紀錄"""
        conn = self._get_conn()
        try:
            sql = "SELECT * FROM alert_log WHERE 1=1"
            params = []
            if start_date:
                sql += " AND timestamp >= ?"
                params.append(start_date)
            if end_date:
                sql += " AND timestamp <= ?"
                params.append(end_date + " 23:59:59")
            sql += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def export_history_csv(self, output_path, start_date=None, end_date=None):
        """匯出歷史紀錄為 CSV"""
        rows = self.query_history(start_date=start_date, end_date=end_date, limit=100000)
        if not rows:
            return 0

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        return len(rows)

    # ===========================================
    # Kepware Events
    # ===========================================

    def kepware_event_exists(self, dedup_hash):
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT 1 FROM kepware_events WHERE dedup_hash = ?", (dedup_hash,)
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def write_kepware_event(self, timestamp, event, source, channel, device,
                            message, dedup_hash, is_alert=False, alert_type=None,
                            server_name=None, tag_address=None):
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO kepware_events
                   (timestamp, server_name, event, source, channel, device,
                    tag_address, message, dedup_hash, is_alert, alert_type, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (timestamp, server_name, event, source, channel, device,
                 tag_address, message, dedup_hash, int(is_alert), alert_type,
                 datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )
            conn.commit()
        finally:
            conn.close()

    def query_kepware_events(self, start_date=None, end_date=None,
                             channel=None, event_type=None,
                             server_name=None, limit=500):
        conn = self._get_conn()
        try:
            sql = "SELECT * FROM kepware_events WHERE 1=1"
            params = []
            if server_name:
                sql += " AND server_name = ?"
                params.append(server_name)
            if start_date:
                sql += " AND timestamp >= ?"
                params.append(start_date)
            if end_date:
                sql += " AND timestamp <= ?"
                params.append(end_date + " 23:59:59")
            if channel:
                sql += " AND channel = ?"
                params.append(channel)
            if event_type:
                sql += " AND event = ?"
                params.append(event_type)
            sql += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def count_channel_events_in_window(self, channel, window_start):
        conn = self._get_conn()
        try:
            row = conn.execute(
                """SELECT COUNT(*) as cnt FROM kepware_events
                   WHERE channel = ? AND timestamp >= ?
                   AND event IN ('Warning', 'Error')""",
                (channel, window_start),
            ).fetchone()
            return row["cnt"] if row else 0
        finally:
            conn.close()

    def count_consecutive_tag_errors(self, channel, device):
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """SELECT event FROM kepware_events
                   WHERE channel = ? AND device = ?
                   ORDER BY timestamp DESC LIMIT 100""",
                (channel, device),
            ).fetchall()
            count = 0
            for r in rows:
                if r["event"] in ("Warning", "Error"):
                    count += 1
                else:
                    break
            return count
        finally:
            conn.close()

    # ===========================================
    # Kepware Transactions
    # ===========================================

    def kepware_transaction_exists(self, timestamp, user, action, endpoint):
        conn = self._get_conn()
        try:
            row = conn.execute(
                """SELECT 1 FROM kepware_transactions
                   WHERE timestamp = ? AND user = ? AND action = ? AND endpoint = ?""",
                (timestamp, user, action, endpoint),
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def write_kepware_transaction(self, timestamp, user, action, endpoint,
                                  source_ip, response, is_alert=False,
                                  server_name=None):
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO kepware_transactions
                   (timestamp, server_name, user, action, endpoint, source_ip,
                    response, is_alert, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (timestamp, server_name, user, action, endpoint, source_ip,
                 response, int(is_alert),
                 datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )
            conn.commit()
        finally:
            conn.close()

    def query_kepware_transactions(self, start_date=None, end_date=None,
                                   action=None, server_name=None, limit=500):
        conn = self._get_conn()
        try:
            sql = "SELECT * FROM kepware_transactions WHERE 1=1"
            params = []
            if server_name:
                sql += " AND server_name = ?"
                params.append(server_name)
            if start_date:
                sql += " AND timestamp >= ?"
                params.append(start_date)
            if end_date:
                sql += " AND timestamp <= ?"
                params.append(end_date + " 23:59:59")
            if action:
                sql += " AND action = ?"
                params.append(action)
            sql += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def cleanup_old_records(self, days=90):
        """清理超過指定天數的舊紀錄"""
        conn = self._get_conn()
        try:
            cutoff = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            # 用 julianday 計算天數差
            sql_history = """
                DELETE FROM monitor_history
                WHERE julianday(?) - julianday(timestamp) > ?
            """
            sql_alerts = """
                DELETE FROM alert_log
                WHERE julianday(?) - julianday(timestamp) > ?
            """
            sql_webhook = """
                DELETE FROM webhook_log
                WHERE julianday(?) - julianday(timestamp) > ?
            """
            sql_kep_events = """
                DELETE FROM kepware_events
                WHERE julianday(?) - julianday(timestamp) > ?
            """
            sql_kep_tx = """
                DELETE FROM kepware_transactions
                WHERE julianday(?) - julianday(timestamp) > ?
            """
            cur1 = conn.execute(sql_history, (cutoff, days))
            cur2 = conn.execute(sql_alerts, (cutoff, days))
            cur3 = conn.execute(sql_webhook, (cutoff, days))
            cur4 = conn.execute(sql_kep_events, (cutoff, days))
            cur5 = conn.execute(sql_kep_tx, (cutoff, days))
            conn.commit()
            total = cur1.rowcount + cur2.rowcount + cur3.rowcount + cur4.rowcount + cur5.rowcount
            if total > 0:
                logging.info(f"清理舊紀錄: 刪除 {total} 筆 (超過 {days} 天)")
            return total
        finally:
            conn.close()
