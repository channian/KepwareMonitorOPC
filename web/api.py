import os
import csv
import json
import asyncio
import logging
import configparser
from datetime import datetime
from io import StringIO

from fastapi import FastAPI, Request, Form, Query
from fastapi.responses import (
    HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from web.auth import SessionManager, get_current_user, require_admin

WEB_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="Kepware Monitor", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=os.path.join(WEB_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(WEB_DIR, "templates"))

# 這些會在啟動時由 kepware_monitor.py 注入
session_mgr: SessionManager = None
db_service = None
monitor_manager = None
config: configparser.ConfigParser = None


def init_app(_session_mgr, _db_service, _monitor_manager, _config):
    """由主程式呼叫，注入共用元件"""
    global session_mgr, db_service, monitor_manager, config
    session_mgr = _session_mgr
    db_service = _db_service
    monitor_manager = _monitor_manager
    config = _config


# ===========================================
# 共用 helper
# ===========================================

def _user_or_redirect(request: Request):
    """取得當前使用者，未登入則回傳重導向"""
    user = get_current_user(request, session_mgr)
    if not user:
        return None, RedirectResponse("/login", status_code=302)
    return user, None


def _admin_or_403(request: Request):
    """要求 admin，否則回傳 403"""
    user = get_current_user(request, session_mgr)
    if not user:
        return None, RedirectResponse("/login", status_code=302)
    if user["role"] != "admin":
        return None, HTMLResponse("權限不足", status_code=403)
    return user, None


# ===========================================
# 登入 / 登出
# ===========================================

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = ""):
    return templates.TemplateResponse("login.html", {
        "request": request, "error": error,
    })


@app.post("/login")
async def login_submit(request: Request,
                        username: str = Form(...),
                        password: str = Form(...)):
    user_data = db_service.authenticate_user(username, password)
    if not user_data:
        return templates.TemplateResponse("login.html", {
            "request": request, "error": "帳號或密碼錯誤",
        })
    session_id = session_mgr.create_session(user_data)
    response = RedirectResponse("/", status_code=302)
    response.set_cookie("session_id", session_id, httponly=True, max_age=28800)
    return response


@app.get("/logout")
async def logout(request: Request):
    session_id = request.cookies.get("session_id")
    if session_id:
        session_mgr.destroy_session(session_id)
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("session_id")
    return response


# ===========================================
# 狀態看板（首頁）
# ===========================================

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    user, redir = _user_or_redirect(request)
    if redir:
        return redir
    return templates.TemplateResponse("dashboard.html", {
        "request": request, "user": user,
    })


@app.get("/api/dashboard/status")
async def api_dashboard_status(request: Request):
    """取得即時監控狀態（供看板 AJAX / SSE 使用）"""
    user, redir = _user_or_redirect(request)
    if redir:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    if not monitor_manager:
        return JSONResponse({"devices": [], "connections": {}})

    devices_data = []
    for d in monitor_manager.devices:
        diag_msg = ""
        if d.last_diagnostic:
            diag_msg = d.last_diagnostic.message
        devices_data.append({
            "name": d.name,
            "server_name": d.server_name,
            "nodeid": d.nodeid,
            "device_type": d.device_type,
            "condition": d.condition,
            "threshold": str(d.threshold) if d.threshold is not None else "",
            "counter": d.counter,
            "accumulate": d.accumulate,
            "enable": d.enable,
            "is_alert": d.counter >= d.accumulate if d.enable else False,
            "last_alert_time": d.last_alert_time,
            "diagnostic": diag_msg,
        })

    connections = {}
    for name, conn in monitor_manager.connections.items():
        connections[name] = {
            "url": conn.url,
            "connected": conn.connected,
        }

    return JSONResponse({
        "devices": devices_data,
        "connections": connections,
        "check_interval": monitor_manager.check_interval,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })


@app.get("/api/dashboard/sse")
async def api_dashboard_sse(request: Request):
    """SSE 即時推送監控狀態，頻率同步監控間隔"""
    user = get_current_user(request, session_mgr)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    async def event_generator():
        while True:
            if await request.is_disconnected():
                break

            # 取得即時狀態
            devices_data = []
            connections = {}

            if monitor_manager:
                for d in monitor_manager.devices:
                    diag_msg = ""
                    if d.last_diagnostic:
                        diag_msg = d.last_diagnostic.message
                    devices_data.append({
                        "name": d.name,
                        "server_name": d.server_name,
                        "counter": d.counter,
                        "accumulate": d.accumulate,
                        "enable": d.enable,
                        "is_alert": d.counter >= d.accumulate if d.enable else False,
                        "last_alert_time": d.last_alert_time,
                        "diagnostic": diag_msg,
                    })

                for name, conn in monitor_manager.connections.items():
                    connections[name] = {
                        "connected": conn.connected,
                    }

            data = json.dumps({
                "devices": devices_data,
                "connections": connections,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }, ensure_ascii=False)

            yield f"data: {data}\n\n"

            # 等待間隔 = 監控間隔，最少 10 秒
            interval = 30
            if monitor_manager:
                interval = max(10, monitor_manager.check_interval)
            await asyncio.sleep(interval)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ===========================================
# 監控歷史
# ===========================================

@app.get("/history", response_class=HTMLResponse)
async def history_page(request: Request):
    user, redir = _user_or_redirect(request)
    if redir:
        return redir
    return templates.TemplateResponse("history.html", {
        "request": request, "user": user,
    })


@app.get("/api/history")
async def api_history(request: Request,
                      start_date: str = Query(""),
                      end_date: str = Query(""),
                      device_name: str = Query(""),
                      limit: int = Query(500)):
    user, redir = _user_or_redirect(request)
    if redir:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    rows = db_service.query_history(
        start_date=start_date or None,
        end_date=end_date or None,
        device_name=device_name or None,
        limit=min(limit, 5000),
    )
    return JSONResponse({"data": rows})


@app.get("/api/history/export")
async def api_history_export(request: Request,
                             start_date: str = Query(""),
                             end_date: str = Query("")):
    user, redir = _user_or_redirect(request)
    if redir:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    rows = db_service.query_history(
        start_date=start_date or None,
        end_date=end_date or None,
        limit=100000,
    )
    if not rows:
        return JSONResponse({"error": "no data"}, status_code=404)

    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=history_{datetime.now():%Y%m%d}.csv"},
    )


# ===========================================
# 派報紀錄
# ===========================================

@app.get("/alerts", response_class=HTMLResponse)
async def alerts_page(request: Request):
    user, redir = _user_or_redirect(request)
    if redir:
        return redir
    return templates.TemplateResponse("alerts.html", {
        "request": request, "user": user,
    })


@app.get("/api/alerts")
async def api_alerts(request: Request,
                     start_date: str = Query(""),
                     end_date: str = Query(""),
                     limit: int = Query(200)):
    user, redir = _user_or_redirect(request)
    if redir:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    rows = db_service.query_alerts(
        start_date=start_date or None,
        end_date=end_date or None,
        limit=min(limit, 2000),
    )
    return JSONResponse({"data": rows})


# ===========================================
# Tags 管理 (admin)
# ===========================================

@app.get("/tags", response_class=HTMLResponse)
async def tags_page(request: Request):
    user, err = _admin_or_403(request)
    if err:
        return err
    return templates.TemplateResponse("tags.html", {
        "request": request, "user": user,
    })


@app.get("/api/tags")
async def api_tags_get(request: Request):
    """讀取 tags CSV 內容"""
    user, err = _admin_or_403(request)
    if err:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    csv_path = config.get("Tags", "File", fallback="Config/tags.csv")
    if not os.path.exists(csv_path):
        return JSONResponse({"headers": [], "rows": []})

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        rows = [dict(r) for r in reader]

    return JSONResponse({"headers": headers, "rows": rows})


@app.post("/api/tags")
async def api_tags_save(request: Request):
    """儲存 tags CSV"""
    user, err = _admin_or_403(request)
    if err:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    try:
        body = await request.json()
        headers = body.get("headers", [])
        rows = body.get("rows", [])

        if not headers:
            return JSONResponse({"error": "no headers"}, status_code=400)

        csv_path = config.get("Tags", "File", fallback="Config/tags.csv")
        os.makedirs(os.path.dirname(csv_path), exist_ok=True)

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            for row in rows:
                writer.writerow({h: row.get(h, "") for h in headers})

        logging.info(f"Tags CSV 已由 {user['username']} 更新 ({len(rows)} 筆)")
        return JSONResponse({"ok": True, "count": len(rows)})
    except Exception as ex:
        logging.exception(f"Tags 儲存失敗: {ex}")
        return JSONResponse({"error": str(ex)}, status_code=500)


# ===========================================
# 系統設定 (admin)
# ===========================================

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    user, err = _admin_or_403(request)
    if err:
        return err
    return templates.TemplateResponse("settings.html", {
        "request": request, "user": user,
    })


@app.get("/api/settings")
async def api_settings_get(request: Request):
    """讀取 settings.ini 內容（隱藏密碼類欄位）"""
    user, err = _admin_or_403(request)
    if err:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    sections = {}
    sensitive_keys = {"password", "token", "secret"}
    for section in config.sections():
        sections[section] = {}
        for key, value in config.items(section):
            # 隱藏敏感資訊
            if any(s in key.lower() for s in sensitive_keys):
                sections[section][key] = "********" if value else ""
            else:
                sections[section][key] = value

    return JSONResponse({"sections": sections})


@app.post("/api/settings")
async def api_settings_save(request: Request):
    """儲存 settings.ini"""
    user, err = _admin_or_403(request)
    if err:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    try:
        body = await request.json()
        sections = body.get("sections", {})

        sensitive_keys = {"password", "token", "secret"}

        # 記錄原始 key 大小寫（configparser 預設會轉小寫）
        config_path = "Config/settings.ini"
        original_lines = []
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8-sig") as f:
                original_lines = f.readlines()

        for section, kvs in sections.items():
            if not config.has_section(section):
                config.add_section(section)
            for key, value in kvs.items():
                if any(s in key.lower() for s in sensitive_keys) and value == "********":
                    continue
                config.set(section, key, value)

        # 用原始格式寫回，保留 key 大小寫與註解
        _write_config_preserve_format(config_path, config, original_lines)

        logging.info(f"設定檔已由 {user['username']} 更新")
        return JSONResponse({"ok": True, "message": "設定已儲存，部分設定需重啟程式才會生效"})
    except Exception as ex:
        logging.exception(f"設定儲存失敗: {ex}")
        return JSONResponse({"error": str(ex)}, status_code=500)


def _write_config_preserve_format(config_path, config_obj, original_lines):
    """
    寫入設定檔，盡量保留原始格式（註解、key 大小寫）。
    若原始檔案存在，以原始行為基礎更新值；否則用 configparser 預設寫入。
    """
    if not original_lines:
        with open(config_path, "w", encoding="utf-8") as f:
            config_obj.write(f)
        return

    output = []
    current_section = None

    for line in original_lines:
        stripped = line.strip()

        # 空行或註解：保留
        if not stripped or stripped.startswith("#") or stripped.startswith(";"):
            output.append(line)
            continue

        # Section header
        if stripped.startswith("[") and "]" in stripped:
            current_section = stripped[1:stripped.index("]")]
            output.append(line)
            continue

        # Key = Value
        if current_section and "=" in stripped:
            key_part = stripped.split("=", 1)[0].strip()
            key_lower = key_part.lower()
            if config_obj.has_option(current_section, key_lower):
                new_value = config_obj.get(current_section, key_lower)
                output.append(f"{key_part} = {new_value}\n")
            else:
                output.append(line)
            continue

        output.append(line)

    # 寫入新增的 section/key（原始檔案沒有的）
    existing_sections = set()
    for line in original_lines:
        s = line.strip()
        if s.startswith("[") and "]" in s:
            existing_sections.add(s[1:s.index("]")])

    for section in config_obj.sections():
        if section not in existing_sections:
            output.append(f"\n[{section}]\n")
            for key, value in config_obj.items(section):
                if key == "__name__":
                    continue
                output.append(f"{key} = {value}\n")

    with open(config_path, "w", encoding="utf-8") as f:
        f.writelines(output)


# ===========================================
# Webhook 測試
# ===========================================

@app.post("/api/webhook/test")
async def api_webhook_test(request: Request):
    """測試 Webhook 推播（發送一筆測試訊息）"""
    user, err = _admin_or_403(request)
    if err:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    if not monitor_manager or not monitor_manager.webhook:
        return JSONResponse({
            "ok": False,
            "detail": "Webhook 未啟用或未設定。請確認 settings.ini [Webhook] Enable = true",
        })

    # 在背景執行緒中執行（避免阻塞 event loop）
    import concurrent.futures
    loop = asyncio.get_running_loop()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        ok, detail = await loop.run_in_executor(
            pool, monitor_manager.webhook.test_send
        )

    return JSONResponse({"ok": ok, "detail": detail})


# ===========================================
# 帳號管理 (admin)
# ===========================================

@app.get("/users", response_class=HTMLResponse)
async def users_page(request: Request):
    user, err = _admin_or_403(request)
    if err:
        return err
    return templates.TemplateResponse("users.html", {
        "request": request, "user": user,
    })


@app.get("/api/users")
async def api_users_get(request: Request):
    user, err = _admin_or_403(request)
    if err:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    users = db_service.get_all_users()
    return JSONResponse({"data": users})


@app.post("/api/users")
async def api_users_create(request: Request):
    user, err = _admin_or_403(request)
    if err:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    body = await request.json()
    username = body.get("username", "").strip()
    password = body.get("password", "").strip()
    role = body.get("role", "viewer")
    display_name = body.get("display_name", "").strip()

    if not username or not password:
        return JSONResponse({"error": "帳號和密碼不可為空"}, status_code=400)
    if role not in ("viewer", "admin"):
        return JSONResponse({"error": "無效角色"}, status_code=400)

    ok = db_service.create_user(username, password, role, display_name)
    if not ok:
        return JSONResponse({"error": "帳號已存在"}, status_code=409)

    logging.info(f"使用者 {username} 已由 {user['username']} 建立")
    return JSONResponse({"ok": True})


@app.put("/api/users/{user_id}")
async def api_users_update(request: Request, user_id: int):
    user, err = _admin_or_403(request)
    if err:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    body = await request.json()
    db_service.update_user(
        user_id,
        role=body.get("role"),
        display_name=body.get("display_name"),
        password=body.get("password") or None,
    )
    logging.info(f"使用者 ID={user_id} 已由 {user['username']} 更新")
    return JSONResponse({"ok": True})


@app.delete("/api/users/{user_id}")
async def api_users_delete(request: Request, user_id: int):
    user, err = _admin_or_403(request)
    if err:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    db_service.delete_user(user_id)
    logging.info(f"使用者 ID={user_id} 已由 {user['username']} 刪除")
    return JSONResponse({"ok": True})


# ===========================================
# 修改自己的密碼
# ===========================================

@app.post("/api/change-password")
async def api_change_password(request: Request):
    user, redir = _user_or_redirect(request)
    if redir:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    body = await request.json()
    old_pw = body.get("old_password", "")
    new_pw = body.get("new_password", "")

    if not new_pw:
        return JSONResponse({"error": "新密碼不可為空"}, status_code=400)

    # 驗證舊密碼
    auth = db_service.authenticate_user(user["username"], old_pw)
    if not auth:
        return JSONResponse({"error": "舊密碼錯誤"}, status_code=400)

    db_service.update_user(user["user_id"], password=new_pw)
    return JSONResponse({"ok": True})
