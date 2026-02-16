import re
import logging
from datetime import datetime

import requests
import urllib3

# 停用 InsecureRequestWarning（公司內部 API 使用自簽憑證時）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class WebhookService:
    """
    Webhook 推播服務：
      - 異常 / 復歸時呼叫外部 API（公司內部通訊軟體等）
      - 支援 {{$變數}} 模板替換
      - POST JSON + Bearer Token 認證
      - 支援 Proxy 繞過（公司內網 API 直連）
    """

    def __init__(self, url, token, body_template, enable=True, timeout=10,
                 verify_ssl=False, use_proxy=False, proxy_url=None):
        """
        Args:
            url: API endpoint URL
            token: Bearer Token
            body_template: JSON 字串模板，支援 {{$variable}} 變數替換
            enable: 是否啟用
            timeout: 請求逾時秒數
            verify_ssl: 是否驗證 SSL 憑證（內網 API 通常設 False）
            use_proxy: 是否使用 Proxy（False = 直連，不走系統 Proxy）
            proxy_url: 指定 Proxy URL（use_proxy=True 時有效）
        """
        self.url = url
        self.token = token
        self.body_template = body_template
        self.enable = enable
        self.timeout = timeout
        self.verify_ssl = verify_ssl

        # Proxy 設定
        if use_proxy and proxy_url:
            self.proxies = {"http": proxy_url, "https": proxy_url}
            logging.info(f"Webhook 使用 Proxy: {proxy_url}")
        elif use_proxy:
            self.proxies = None  # 使用系統預設 Proxy
            logging.info("Webhook 使用系統預設 Proxy")
        else:
            # 強制不走 Proxy（直連），適用於公司內網 API
            self.proxies = {"http": None, "https": None}
            logging.info("Webhook 直連模式（不走 Proxy）")

    def send(self, variables, db_service=None, server_name="", device_name="",
             is_recovery=False):
        """
        發送 Webhook 推播。
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
            headers = {"Content-Type": "application/json; charset=utf-8"}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"

            resp = requests.post(
                self.url,
                data=body_str.encode("utf-8"),
                headers=headers,
                verify=self.verify_ssl,
                proxies=self.proxies,
                timeout=self.timeout,
            )

            response_code = resp.status_code
            response_body = resp.text[:500]
            is_success = 200 <= response_code < 300

            if is_success:
                logging.info(f"Webhook 推播成功: {device_name} (HTTP {response_code})")
            else:
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
