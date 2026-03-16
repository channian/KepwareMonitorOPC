import sqlite3
import os
import json
import csv
import logging
from datetime import datetime


class DatabaseService:
    """
    SQLite 資料庫服務：
      - monitor_history: 監控歷史紀錄
      - alert_log: 派報紀錄
    """

    def __init__(self, db_path="data/monitor.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")  # 啟用 WAL 模式，提升並發寫入安全性
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

                CREATE INDEX IF NOT EXISTS idx_history_ts
                    ON monitor_history(timestamp);
                CREATE INDEX IF NOT EXISTS idx_history_device
                    ON monitor_history(device_name);
                CREATE INDEX IF NOT EXISTS idx_alert_ts
                    ON alert_log(timestamp);

                CREATE TABLE IF NOT EXISTS kepware_event_log (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    fetched_at    TEXT NOT NULL,
                    event_time    TEXT,
                    server_name   TEXT NOT NULL,
                    channel_name  TEXT,
                    device_name   TEXT,
                    event_source  TEXT,
                    event_message TEXT,
                    severity      TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_event_fetched
                    ON kepware_event_log(fetched_at DESC);

                CREATE INDEX IF NOT EXISTS idx_event_severity
                    ON kepware_event_log(severity, fetched_at DESC);

                CREATE INDEX IF NOT EXISTS idx_event_channel
                    ON kepware_event_log(channel_name, fetched_at DESC);
            """)
            conn.commit()
        finally:
            conn.close()
        logging.info(f"SQLite 資料庫初始化完成: {self.db_path}")

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

    def write_event_logs(self, events: list[dict]) -> int:
        """批次寫入 Kepware 事件日誌"""
        if not events:
            return 0
        with self._get_conn() as conn:
            conn.executemany("""
                INSERT INTO kepware_event_log
                    (fetched_at, event_time, server_name, channel_name,
                     device_name, event_source, event_message, severity)
                VALUES
                    (:fetched_at, :event_time, :server_name, :channel_name,
                     :device_name, :event_source, :event_message, :severity)
            """, events)
        return len(events)

    def get_last_event_time(self, server_name: str) -> str | None:
        """取得指定 server 最新的事件時間"""
        with self._get_conn() as conn:
            row = conn.execute("""
                SELECT event_time FROM kepware_event_log
                WHERE server_name = ?
                ORDER BY event_time DESC
                LIMIT 1
            """, (server_name,)).fetchone()
        return row["event_time"] if row else None

    def query_event_logs(
        self,
        severity: str | None = None,
        channel_name: str | None = None,
        hours: int = 24,
        limit: int = 200
    ) -> list[dict]:
        """查詢事件日誌"""
        conditions = ["fetched_at >= datetime('now', ? || ' hours')"]
        params: list = [f"-{hours}"]
        if severity:
            conditions.append("severity = ?")
            params.append(severity)
        if channel_name:
            conditions.append("channel_name = ?")
            params.append(channel_name)
        where = " AND ".join(conditions)
        with self._get_conn() as conn:
            rows = conn.execute(f"""
                SELECT * FROM kepware_event_log
                WHERE {where}
                ORDER BY fetched_at DESC
                LIMIT ?
            """, params + [limit]).fetchall()
        return [dict(r) for r in rows]

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
            sql_events = """
                DELETE FROM kepware_event_log
                WHERE fetched_at < datetime('now', ? || ' days')
            """
            cur1 = conn.execute(sql_history, (cutoff, days))
            cur2 = conn.execute(sql_alerts, (cutoff, days))
            cur3 = conn.execute(sql_events, (f"-{days}",))
            conn.commit()
            total = cur1.rowcount + cur2.rowcount + cur3.rowcount
            if total > 0:
                logging.info(f"清理舊紀錄: 刪除 {total} 筆 (超過 {days} 天)")
            return total
        finally:
            conn.close()
