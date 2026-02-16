import asyncio
import os
import time
import logging
import configparser
from logging.handlers import TimedRotatingFileHandler

from monitor_manager import MonitorManager


# =========================
# 設定檔讀取
# =========================
CONFIG_PATH = "Config/settings.ini"

config = configparser.ConfigParser()
with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
    config.read_file(f)


# =========================
# Log 設定
# =========================
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
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)

# Console handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)

logger = logging.getLogger()
logger.setLevel(logging.DEBUG if DEBUG else logging.INFO)
logger.addHandler(handler)
logger.addHandler(console_handler)


# =========================
# 清理舊 log
# =========================
def clean_old_logs(log_dir, days=7):
    now = time.time()
    cutoff = now - (days * 86400)

    for filename in os.listdir(log_dir):
        file_path = os.path.join(log_dir, filename)
        if os.path.isfile(file_path):
            file_mtime = os.path.getmtime(file_path)
            if file_mtime < cutoff:
                try:
                    os.remove(file_path)
                    logging.info(f"刪除舊 log: {filename}")
                except Exception as e:
                    logging.warning(f"刪除失敗 {filename}: {e}")


# =========================
# Web UI 啟動
# =========================
async def start_webui(manager):
    """啟動 FastAPI Web UI（在背景 Task 中執行）"""
    try:
        import uvicorn
        from web.api import app, init_app
        from web.auth import SessionManager

        host = config.get("WebUI", "Host", fallback="0.0.0.0")
        port = config.getint("WebUI", "Port", fallback=8080)

        session_mgr = SessionManager()
        init_app(session_mgr, manager.db, manager, config)

        webui_config = uvicorn.Config(
            app, host=host, port=port,
            log_level="warning",
            access_log=False,
        )
        server = uvicorn.Server(webui_config)
        logging.info(f"Web UI 啟動於 http://{host}:{port}")
        await server.serve()

    except ImportError as e:
        logging.warning(f"Web UI 啟動失敗（缺少套件）: {e}")
        logging.warning("請安裝: pip install fastapi uvicorn jinja2 python-multipart")
    except Exception as e:
        logging.exception(f"Web UI 發生錯誤: {e}")


# =========================
# 主程式
# =========================
async def main():
    logging.info("Kepware 監控程式啟動中...")

    # 清理舊 log
    clean_old_logs(LOG_PATH, days=7)

    manager = None
    webui_task = None

    try:
        # 建立 MonitorManager
        logging.info("初始化 MonitorManager...")
        manager = MonitorManager(config)
        logging.info("MonitorManager 初始化完成")

        # 啟動 Web UI（若啟用）
        webui_enabled = config.getboolean("WebUI", "Enable", fallback=False)
        if webui_enabled:
            webui_task = asyncio.create_task(start_webui(manager))
            logging.info("Web UI 背景啟動中...")
        else:
            logging.info("Web UI 未啟用（WebUI.Enable = false）")

        # 啟動監控
        await manager.start()

    except KeyboardInterrupt:
        logging.info("收到中斷信號，正在停止...")
    except Exception as e:
        logging.exception(f"發生嚴重錯誤: {e}")
    finally:
        # 取消 Web UI
        if webui_task and not webui_task.done():
            webui_task.cancel()
            try:
                await webui_task
            except asyncio.CancelledError:
                pass

        # 斷開所有 OPC 連線
        if manager and manager.connections:
            for name, conn in manager.connections.items():
                try:
                    await conn.disconnect()
                    logging.info(f"[{name}] 已斷開連接")
                except Exception:
                    pass
        logging.info("監控程式已停止")


if __name__ == "__main__":
    asyncio.run(main())
