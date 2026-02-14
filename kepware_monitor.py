import asyncio
from asyncua import Client
import datetime
import logging
import configparser
import csv
import os
import time
from ase_email_service import EmailService
from logging.handlers import TimedRotatingFileHandler

# =========================
# 設定檔讀取
# =========================
config = configparser.ConfigParser()
with open("Config/settings.ini", "r", encoding="utf-8-sig") as f:
    config.read_file(f)

# OPC
OPC_URL = config.get("OPC", "ServerUrl")

# Mail
SMTP_SERVER = config.get("Mail", "SmtpServer")
SMTP_PORT = config.getint("Mail", "Port", fallback=25)
MAIL_FROM = config.get("Mail", "From")
MAIL_TO = [x.strip() for x in config.get("Mail", "To").split(",") if x.strip()]
MAIL_CC = [x.strip() for x in config.get("Mail", "Cc").split(",") if x.strip()]
MAIL_SUBJECT = config.get("Mail", "Subject")
ALERT_RESEND_INTERVAL = config.getint("Monitor", "alertResendInterval", fallback=1800)

# Log
LOG_PATH = config.get("Log", "LogPath", fallback="logs")
DEBUG = config.getboolean("Log", "Debug", fallback=True)
os.makedirs(LOG_PATH, exist_ok=True)

log_basename = os.path.join(LOG_PATH, 'kepware_device_monitor.log')
handler = TimedRotatingFileHandler(
    log_basename,
    when='midnight',
    interval=1,
    backupCount=7,
    encoding='utf-8'
)
formatter = logging.Formatter('%(asctime)s - %(message)s')
handler.setFormatter(formatter)
logger = logging.getLogger()
logger.setLevel(logging.DEBUG if DEBUG else logging.INFO)
logger.addHandler(handler)
logger.info("📡 Kepware 監控程式啟動中...")


def log_and_print(msg):
    print(msg)
    logging.info(msg)


# =========================
# 全域與設定
# =========================
TAGS_CSV = config.get("Tags", "File")
CHECK_INTERVAL_SECONDS = config.getint("Monitor", "intervalSeconds", fallback=600)
CSV_RELOAD_SECONDS = config.getint("Monitor", "csvReloadSeconds", fallback=30)

# global monitor list and mtime
MONITOR_LIST = []
TAGS_CSV_MTIME = None


# =========================
# 刪除舊的 log 檔案
# =========================
def clean_old_logs(log_dir, days=7):
    now = time.time()
    cutoff = now - (days * 86400)  # 86400 = 一天的秒數

    for filename in os.listdir(log_dir):
        file_path = os.path.join(log_dir, filename)
        if os.path.isfile(file_path):
            file_mtime = os.path.getmtime(file_path)
            if file_mtime < cutoff:
                try:
                    os.remove(file_path)
                    print(f"刪除舊 log 檔案: {filename}")
                except Exception as e:
                    print(f"刪除失敗 {filename}: {e}")


# =========================
# 寫入監控資料 log 檔案（每日一檔）
# =========================
def write_history(device, value, is_alert, count):
    """
    寫入 daily history CSV。
    若 device 被停用則不會呼叫（呼叫方應先判斷 enable）。
    """
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    folder = os.path.join(LOG_PATH, "history")
    os.makedirs(folder, exist_ok=True)

    filename = os.path.join(folder, f"{today}.csv")
    new_file = not os.path.exists(filename)

    with open(filename, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(["timestamp", "name", "tag_nodeid", "value",
                             "threshold", "condition",
                             "counter", "alert"])
        writer.writerow([
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            device.get("name", ""),
            device.get("nodeid", ""),
            value,
            device.get("threshold", ""),
            device.get("condition", ""),
            count,
            int(is_alert)
        ])


# =========================
# 讀取並解析 CSV（回傳 list of device dicts）
# =========================
def load_monitor_list_from_csv(csv_path):
    lst = []
    with open(csv_path, newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            # 基本欄位
            name = row.get("Name", "").strip()
            nodeid = row.get("NodeId", "").strip()
            device_type = row.get("Type", "number").strip().lower()
            condition = row.get("Condition", "greater").strip().lower()
            threshold_raw = row.get("Threshold", "").strip()
            accumulate_raw = str(row.get("CountNeeded", "1") or "1").strip()
            enable_raw = row.get("Enable", "True").strip()

            # parse accumulate safely
            try:
                accumulate = int(accumulate_raw)
                if accumulate <= 0:
                    accumulate = 1
            except Exception:
                accumulate = 1

            # parse threshold by type
            threshold = None
            if device_type == "number":
                try:
                    threshold = float(threshold_raw) if threshold_raw != "" else None
                except Exception:
                    threshold = None
            elif device_type == "bool":
                thr = threshold_raw.strip().lower()
                threshold = True if thr in ("1", "true", "yes") else False if thr in ("0", "false", "no") else None
            # for 'log' type threshold remains None

            # parse enable (B: True/False; accept cases)
            enable = True if enable_raw.strip().lower() == "true" else False

            # mail merge
            mail_to_csv = [x.strip() for x in row.get("MailTo", "").split(",") if x.strip()]
            mail_cc_csv = [x.strip() for x in row.get("MailCc", "").split(",") if x.strip()]
            merged_to = list(dict.fromkeys(MAIL_TO + mail_to_csv))  # preserve order, unique
            merged_cc = list(dict.fromkeys(MAIL_CC + mail_cc_csv))

            device = {
                "name": name,
                "nodeid": nodeid,
                "type": device_type,      # 'number' / 'bool' / 'log'
                "condition": condition,
                "threshold": threshold,
                "accumulate": accumulate,
                "counter": 0,
                "mail_to": merged_to,
                "mail_cc": merged_cc,
                "enable": enable
            }
            lst.append(device)
    return lst


# =========================
# 合併新載入的 list 與現有 MONITOR_LIST（保留 counter 與處理 enable 變化）
# =========================
def merge_monitor_lists(old_list, new_list):
    """
    合併新舊清單，保留 counter 與 alert_sent (是否已發報) 狀態
    """
    old_map = {(d.get("name"), d.get("nodeid")): d for d in old_list}
    merged = []
    for nd in new_list:
        key = (nd.get("name"), nd.get("nodeid"))
        od = old_map.get(key)

        # 預設狀態初始化
        nd["counter"] = 0
        nd["last_alert_time"] = 0  # 改為記錄時間戳記，0 代表沒發過

        if od:
            # 如果舊有該設備，且兩邊都啟用，則繼承計數器與警報狀態
            if od.get("enable", True) and nd.get("enable", True):
                nd["counter"] = od.get("counter", 0)
                nd["last_alert_time"] = od.get("last_alert_time", 0)  # 關鍵：繼承時間
            # 若狀態改變(如從停用變啟用)，則使用預設值(重置)

        merged.append(nd)
    return merged


# =========================
# CSV 自動重載（比較 mtime）
# =========================
def reload_csv_if_needed():
    global TAGS_CSV_MTIME, MONITOR_LIST
    try:
        current_mtime = os.path.getmtime(TAGS_CSV)
    except Exception:
        # CSV not found or inaccessible
        return

    if TAGS_CSV_MTIME is None or current_mtime != TAGS_CSV_MTIME:
        # load new list then merge with existing counters
        try:
            new_list = load_monitor_list_from_csv(TAGS_CSV)
        except Exception as ex:
            logging.exception(f"Failed to parse CSV: {ex}")
            return
        MONITOR_LIST = merge_monitor_lists(MONITOR_LIST, new_list)
        TAGS_CSV_MTIME = current_mtime
        logging.info("🔄 CSV 重載成功，監控項目已更新")


# 初始載入（程式啟動時）
try:
    MONITOR_LIST = load_monitor_list_from_csv(TAGS_CSV)
    TAGS_CSV_MTIME = os.path.getmtime(TAGS_CSV)
    logging.info("✅ 初始載入 CSV 成功")
except Exception as e:
    logging.exception(f"無法載入 TAGS CSV: {e}")
    MONITOR_LIST = []
    TAGS_CSV_MTIME = None


# =========================
# 判斷是否觸發（單一 device, single value）
# 回傳 (is_alert:bool, write_history_flag:bool)
# =========================
def evaluate_device_and_handle(device, raw_value):
    """
    根據 device 設定與 raw_value，回傳 (is_alert, parsed_value, counter_delta_flag)
    - For type 'log': always is_alert=False but should write history if enabled.
    - For 'number' / 'bool': returns is_alert depending on threshold/condition.
    """
    dtype = device.get("type", "number")
    condition = device.get("condition", "greater")
    threshold = device.get("threshold", None)

    # If device disabled, caller should skip entirely (we protect caller too)
    if not device.get("enable", True):
        return False, None  # not alert, no parsed value

    # Handle None early
    if raw_value is None:
        # treat None as non-parsed; for 'log' we still record raw None as value
        return False, None

    # log-only -> record and skip any alert logic
    if dtype == "log":
        return False, raw_value

    # number type
    if dtype == "number":
        try:
            val = float(raw_value)
        except Exception:
            # can't parse number -> treat as non-alert but return None to avoid writing false info
            logging.warning(f"[{device.get('name')}] number parse failed for raw_value={raw_value}")
            return False, None
        # if threshold not set, cannot evaluate
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

    # bool type
    if dtype == "bool":
        # robust conversion
        if isinstance(raw_value, bool):
            val = raw_value
        else:
            s = str(raw_value).strip().lower()
            if s in ("1", "true", "t", "yes", "on"):
                val = True
            elif s in ("0", "false", "f", "no", "off"):
                val = False
            else:
                # try numeric convert
                try:
                    val = bool(int(raw_value))
                except Exception:
                    logging.warning(f"[{device.get('name')}] bool parse failed for raw_value={raw_value}; treating as False")
                    val = False
        # threshold may be None or True/False
        if threshold is None:
            return False, val
        # condition handling for bool: support 'true'/'false' as shortcuts
        if condition in ("true", "1"):
            return (val is True), val
        if condition in ("false", "0"):
            return (val is False), val
        if condition in ("equal", "=="):
            return (val == threshold), val
        if condition in ("not_equal", "!="):
            return (val != threshold), val
        return False, val

    # unknown type fallback: do nothing
    return False, None


# =========================
# 警報函式（保留你現有呼叫介面）
# =========================
def send_alert(email_service, to_addresses, cc_addresses, device_name, value, is_recovery=False):
    """
    發送通知信
    :param is_recovery: False=異常通知(紅色), True=復歸通知(綠色)
    """

    # 1. 決定標題與樣式
    if is_recovery:
        status_tag = "[復歸]"
        title_text = "Kepware 設備恢復正常通知"
        color_hex = "#28a745"  # 綠色
        msg_context = "設備已恢復正常通訊。"
    else:
        status_tag = "[異常]"
        title_text = "Kepware 設備通訊異常通知"
        color_hex = "#dc3545"  # 紅色
        msg_context = "設備通訊異常，請儘速確認。"

    # 2. 組合信件主旨 (保留原本設定檔中的 MAIL_SUBJECT 前綴)
    subject = f"{status_tag} {MAIL_SUBJECT} - {device_name}"

    # 3. 組合 HTML 內容 (加入顏色樣式)
    html_body = f"""
    <html>
    <body>
        <h2 style="color: {color_hex};">{title_text}</h2>
        <p><strong>通知時間:</strong> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        <p><strong>設備名稱:</strong> {device_name}</p>
        <p><strong>持續持間:</strong> <span style="font-size: 1.2em; font-weight: bold; color: {color_hex};">{value}</span></p>
        <hr>
        <p>{msg_context}</p>
    </body>
    </html>
    """

    log_and_print(f"    >>> 寄送信件: {subject}")

    email_service.send_alert_email(
        to_addresses=to_addresses,
        cc_addresses=cc_addresses,
        subject=subject,
        html_body=html_body
    )


# =========================
# 監控主程式 (含 CSV reload、node list rebuild)
# =========================
async def monitor_kepware_devices(client, email_service):
    # 用來追蹤上次 reload 時間
    last_csv_check = 0

    while True:
        # ==========================================
        # 1. 迴圈開頭：CSV 檢查與 Node 建立
        # ==========================================
        now_time = time.time()
        if (now_time - last_csv_check) >= CSV_RELOAD_SECONDS:
            reload_csv_if_needed()
            last_csv_check = now_time

        devices = [d for d in MONITOR_LIST if d.get("nodeid")]
        if not devices:
            log_and_print("⚠️ 找不到任何監控項目，請檢查 CSV")
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)
            continue

        nodes = []
        # 建立 Node 物件 (每次迴圈確保 Session ID 正確)
        for d in devices:
            try:
                nodes.append(client.get_node(d["nodeid"]))
            except Exception as ex:
                logging.warning(f"無法建立 node for {d.get('name')}: {ex}")
                nodes.append(None)

        # ==========================================
        # 2. 讀值與重連機制 (斷線立即重試邏輯)
        # ==========================================
        try:
            read_nodes = [n for n in nodes]
            valid_nodes = [n for n in read_nodes if n is not None]

            if valid_nodes:
                raw_values_list = await client.read_values(valid_nodes)
            else:
                raw_values_list = []

            # 將結果映射回原始列表
            vals_iter = iter(raw_values_list)
            values = []
            for n in read_nodes:
                if n is None:
                    values.append(None)
                else:
                    values.append(next(vals_iter))

        except Exception as ex:
            log_and_print(f"⚠️ 讀取失敗或連線斷掉: {ex}")

            # --- 自動重連邏輯 ---
            try:
                log_and_print("嘗試重新連線 OPC UA 伺服器...")
                try:
                    await client.disconnect()
                except Exception:
                    pass

                await asyncio.sleep(5)  # 稍微緩衝

                await client.connect()
                log_and_print("✅ 重新連線成功！立即重試讀取...")

                # 【功能 1】連線成功後，直接 continue 跳回 while 開頭，立即讀取數據
                continue

            except Exception as e2:
                log_and_print(f"⚠️ 重新連線失敗: {e2}")
                log_and_print(f"將等待 30 秒後再次嘗試...")
                await asyncio.sleep(30)
                continue

        # ==========================================
        # 3. 數據處理與警報 (持續提醒)
        # ==========================================
        current_ts = time.time()  # 取得現在時間戳記

        for device, raw_value in zip(devices, values):
            device_name = device.get("name", "")

            # 若停用，重置所有狀態
            if not device.get("enable", True):
                device["counter"] = 0
                device["last_alert_time"] = 0
                continue

            # 判斷數值
            is_alert, parsed_value = evaluate_device_and_handle(device, raw_value)

            # 處理 LOG 類型
            if device.get("type") == "log":
                device["counter"] = 0
                write_val = parsed_value if parsed_value is not None else raw_value
                write_history(device, write_val, False, 0)
                log_and_print(f"紀錄: {device_name} = {write_val}")
                continue

            write_val = parsed_value if parsed_value is not None else raw_value

            # 計算 Counter
            if is_alert:
                device["counter"] = device.get("counter", 0) + 1
            else:
                device["counter"] = 0  # 正常時清零

            # 寫入歷史紀錄
            write_history(device, write_val, is_alert, device["counter"])

            # 取得設定參數
            alert_threshold = device.get("accumulate", 1)
            is_triggered = device["counter"] >= alert_threshold

            # 取得上次發送時間 (若沒發過則為 0)
            last_sent_ts = device.get("last_alert_time", 0)
            time_since_last = current_ts - last_sent_ts

            # 【核心修改】持續派報邏輯
            if is_triggered:
                # 判斷條件：(從未發送過) 或者 (距離上次發送已超過設定間隔)
                if last_sent_ts == 0 or time_since_last >= ALERT_RESEND_INTERVAL:

                    if last_sent_ts == 0:
                        log_msg = f"🚨 [首次觸發] {device_name} 異常值: {write_val}"
                    else:
                        log_msg = f"⏰ [持續異常/重發] {device_name} 仍異常: {write_val} (已過 {int(time_since_last)} 秒)"

                    log_and_print(log_msg)

                    try:
                        # === 修改點 A: 發送異常信 (is_recovery=False) ===
                        send_alert(
                            email_service,
                            device.get("mail_to", MAIL_TO),
                            device.get("mail_cc", MAIL_CC),
                            device_name,
                            write_val,
                            is_recovery=False
                        )
                        device["last_alert_time"] = current_ts

                    except Exception as e:
                        logging.exception(f"寄信失敗: {e}")

            elif not is_alert and last_sent_ts > 0:
                # 狀況：數值恢復正常，且之前有發過警報 -> 解除鎖定 & 發送復歸信
                log_and_print(f"✅ [恢復] {device_name} 已恢復正常值: {write_val} (發送復歸通知)")

                try:
                    # === 修改點 B: 發送復歸信 (is_recovery=True) ===
                    send_alert(
                        email_service,
                        device.get("mail_to", MAIL_TO),
                        device.get("mail_cc", MAIL_CC),
                        device_name,
                        write_val,
                        is_recovery=True
                    )
                except Exception as e:
                    logging.exception(f"復歸信寄送失敗: {e}")

                device["last_alert_time"] = 0
                device["counter"] = 0

            else:
                # 正常狀態
                pass

        # ==========================================
        # 4. 正常週期的等待
        # ==========================================
        log_and_print(f"等待 {CHECK_INTERVAL_SECONDS} 秒後更新...")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


# =========================
# 主程式
# =========================
async def main():
    clean_old_logs(LOG_PATH, days=7)

    email_service = EmailService(
        smtp_server=SMTP_SERVER,
        smtp_port=SMTP_PORT,
        sender_email=MAIL_FROM
    )

    client = Client(url=OPC_URL)
    try:
        await client.connect()
        log_and_print("已成功連接到 Kepware OPC UA 伺服器")
        await monitor_kepware_devices(client, email_service)
    except Exception as e:
        log_and_print(f"發生嚴重錯誤: {e}")
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass
        log_and_print("已斷開連接")


if __name__ == "__main__":
    asyncio.run(main())
