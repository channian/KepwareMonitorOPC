import json
import re
import logging
import urllib.request
import urllib.error
from datetime import datetime


class WebhookService:
    """
    Webhook 推播服務：
      - 異常 / 復歸時呼叫外部 API（公司內部通訊軟體等）
      - 支援 {{$變數}} 模板替換
      - POST JSON + Bearer Token 認證
      - 支援 HTTP/HTTPS Proxy
    """

    def __init__(self, url, token, body_template, enable=True, timeout=10,
                 proxy_url=None):
        """
        Args:
            url: API endpoint URL
            token: Bearer Token
            body_template: JSON 字串模板，支援 {{$variable}} 變數替換
            enable: 是否啟用
            timeout: 請求逾時秒數
            proxy_url: Proxy URL，例如 http://proxy.company.com:8080
        """
        self.url = url
        self.token = token
        self.body_template = body_template
        self.enable = enable
        self.timeout = timeout

        # 建立 URL opener（支援 Proxy）
        if proxy_url:
            proxy_handler = urllib.request.ProxyHandler({
                "http": proxy_url,
                "https": proxy_url,
            })
            self._opener = urllib.request.build_opener(proxy_handler)
            logging.info(f"Webhook 使用 Proxy: {proxy_url}")
        else:
            # 使用系統預設（會讀取 Windows IE / 環境變數的 Proxy 設定）
            self._opener = urllib.request.build_opener()

    def send(self, variables, db_service=None, server_name="", device_name="",
             is_recovery=False):
        """
        發送 Webhook 推播。

        Args:
            variables: dict，可用的模板變數，例如:
                {
                    "server_name": "kepware_a",
                    "device_name": "K21GMS",
                    "value": "500",
                    "threshold": "300",
                    "condition": "greater",
                    "counter": "3",
                    "diagnostic": "設備正常但數值異常",
                    "message": "完整摘要訊息",
                    "timestamp": "2025-01-01 12:00:00",
                    "status": "異常",
                }
            db_service: DatabaseService instance（選填，用來寫入推播紀錄）
            server_name: OPC Server 名稱
            device_name: 設備名稱
            is_recovery: 是否為復歸通知
        """
        if not self.enable or not self.url:
            return

        # 替換模板變數 {{$variable}}
        body_str = self._render_template(self.body_template, variables)

        # 發送 HTTP POST
        response_code = 0
        response_body = ""
        is_success = False

        try:
            data = body_str.encode("utf-8")
            req = urllib.request.Request(
                self.url,
                data=data,
                method="POST",
            )
            req.add_header("Content-Type", "application/json; charset=utf-8")
            if self.token:
                req.add_header("Authorization", f"Bearer {self.token}")

            with self._opener.open(req, timeout=self.timeout) as resp:
                response_code = resp.status
                response_body = resp.read().decode("utf-8", errors="replace")[:500]
                is_success = 200 <= response_code < 300

            logging.info(f"Webhook 推播成功: {device_name} (HTTP {response_code})")

        except urllib.error.HTTPError as e:
            response_code = e.code
            response_body = e.read().decode("utf-8", errors="replace")[:500]
            logging.warning(f"Webhook 推播失敗: {device_name} (HTTP {response_code}) {response_body}")

        except Exception as ex:
            response_body = str(ex)[:500]
            logging.warning(f"Webhook 推播發生錯誤: {device_name} - {ex}")

        # 寫入推播紀錄
        if db_service:
            try:
                db_service.write_webhook_log(
                    server_name=server_name,
                    device_name=device_name,
                    url=self.url,
                    request_body=body_str[:1000],
                    response_code=response_code,
                    response_body=response_body,
                    is_success=is_success,
                    is_recovery=is_recovery,
                )
            except Exception as ex:
                logging.warning(f"Webhook 紀錄寫入失敗: {ex}")

        return is_success

    @staticmethod
    def _render_template(template, variables):
        """
        將模板中的 {{$variable}} 替換為實際值。
        例如: '{"content": "{{$message}}"}' → '{"content": "設備異常通知"}'
        """
        def replacer(match):
            var_name = match.group(1)
            value = variables.get(var_name, "")
            # 跳脫 JSON 特殊字元
            escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
            escaped = escaped.replace("\n", "\\n").replace("\r", "\\r")
            escaped = escaped.replace("\t", "\\t")
            return escaped

        return re.sub(r"\{\{\$(\w+)\}\}", replacer, template)

    def build_variables(self, server_name, device_name, value, threshold,
                        condition, counter, accumulate, diagnostic_msg,
                        is_recovery=False):
        """
        建立標準模板變數 dict。
        """
        status = "復歸" if is_recovery else "異常"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        message = (
            f"[{status}] {device_name}\n"
            f"Server: {server_name}\n"
            f"數值: {value} ({condition} {threshold})\n"
            f"累積: {counter}/{accumulate}"
        )
        if diagnostic_msg:
            message += f"\n診斷: {diagnostic_msg}"

        return {
            "server_name": server_name,
            "device_name": device_name,
            "value": str(value) if value is not None else "N/A",
            "threshold": str(threshold) if threshold is not None else "N/A",
            "condition": condition or "",
            "counter": str(counter),
            "accumulate": str(accumulate),
            "diagnostic": diagnostic_msg or "",
            "message": message,
            "timestamp": timestamp,
            "status": status,
        }
