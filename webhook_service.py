import json
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

        # 診斷：記錄模板和變數
        logging.debug(f"Webhook 模板原始值: {self.body_template}")
        logging.debug(f"Webhook 變數 keys: {list(variables.keys())}")

        # 替換模板變數 {{$variable}}
        body_str = self._render_template(self.body_template, variables)
        raw_body = body_str  # 預設值，後面可能被覆寫

        logging.debug(f"Webhook 模板渲染後: {body_str[:300]}")

        # 發送 HTTP POST
        response_code = 0
        response_body = ""
        is_success = False

        try:
            # 將模板渲染結果解析為 dict
            try:
                post_data = json.loads(body_str)
            except json.JSONDecodeError as je:
                logging.warning(f"Webhook Body 模板解析失敗（非合法 JSON）: {je}")
                logging.warning(f"Body 內容: {body_str[:500]}")
                post_data = None

            headers = {
                "Content-Type": "application/json; charset=utf-8",
            }
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"

            # 用 data= + ensure_ascii=False 傳送原生 UTF-8
            # （某些 API 不接受 \uXXXX unicode escape，必須用原生中文）
            if post_data is not None:
                raw_body = json.dumps(post_data, ensure_ascii=False)
            else:
                raw_body = body_str

            # 診斷 log：顯示實際送出的內容
            logging.info(f"Webhook 送出 → URL: {self.url}")
            logging.info(f"Webhook 送出 → Headers: {headers}")
            logging.info(f"Webhook 送出 → Body: {raw_body[:500]}")

            resp = requests.post(
                self.url,
                data=raw_body.encode("utf-8"),
                headers=headers,
                verify=self.verify_ssl,
                proxies=self.proxies,
                timeout=(5, self.timeout),  # (連線逾時, 讀取逾時)
            )

            response_code = resp.status_code
            response_body = resp.text[:500]
            is_success = 200 <= response_code < 300

            # 詳細 log：無論成功失敗都記錄 response
            logging.info(
                f"Webhook 回應 ← {device_name} "
                f"HTTP {response_code} | Body: {response_body[:200]}"
            )

        except requests.exceptions.ConnectTimeout:
            response_body = "連線逾時（無法連到 API server）"
            logging.warning(f"Webhook 連線逾時: {device_name} - {self.url}")
        except requests.exceptions.ReadTimeout:
            response_body = "讀取逾時（API server 無回應）"
            logging.warning(f"Webhook 讀取逾時: {device_name} - {self.url}")
        except requests.exceptions.ConnectionError as ex:
            response_body = f"連線失敗: {ex}"
            logging.warning(f"Webhook 連線失敗: {device_name} - {ex}")
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
                    request_body=raw_body[:1000],
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

    def test_send(self):
        """
        測試 Webhook 推播（送一筆測試訊息），回傳 (success, detail) 。
        """
        variables = self.build_variables(
            server_name="測試Server",
            device_name="測試設備",
            value="999",
            threshold="100",
            condition=">",
            counter=3,
            accumulate=3,
            diagnostic_msg="這是一則測試推播",
            is_recovery=False,
        )
        body_str = self._render_template(self.body_template, variables)

        try:
            post_data = json.loads(body_str)
        except json.JSONDecodeError as je:
            return False, f"Body 模板解析失敗: {je}\n原始內容: {body_str[:300]}"

        headers = {
            "Content-Type": "application/json; charset=utf-8",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        raw_body = json.dumps(post_data, ensure_ascii=False)

        detail_lines = [
            f"URL: {self.url}",
            f"Headers: {headers}",
            f"Body: {raw_body}",
            f"verify_ssl: {self.verify_ssl}",
            f"proxies: {self.proxies}",
            "",
        ]

        try:
            resp = requests.post(
                self.url,
                data=raw_body.encode("utf-8"),
                headers=headers,
                verify=self.verify_ssl,
                proxies=self.proxies,
                timeout=(5, self.timeout),
            )
            detail_lines.append(f"HTTP {resp.status_code}")
            detail_lines.append(f"Response Headers: {dict(resp.headers)}")
            detail_lines.append(f"Response Body: {resp.text[:500]}")
            ok = 200 <= resp.status_code < 300
            return ok, "\n".join(detail_lines)

        except Exception as ex:
            detail_lines.append(f"Exception: {type(ex).__name__}: {ex}")
            return False, "\n".join(detail_lines)
