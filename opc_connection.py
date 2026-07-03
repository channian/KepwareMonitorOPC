import asyncio
import logging
from asyncua import Client
from asyncua.crypto.security_policies import SecurityPolicyBasic256Sha256, SecurityPolicyBasic256
from asyncua.ua import MessageSecurityMode
from urllib.parse import urlparse

from diagnostic_service import DiagnosticService, DiagnosticResult


class OPCConnection:
    """
    OPC UA 連線管理 — 支援安全策略、安全模式與認證設定。
    """

    def __init__(self, name, url, diagnostic_service=None,
                 security_policy="None", security_mode="None",
                 authentication="anonymous", username=None, password=None):
        self.name = name
        self.url = url
        self.security_policy = security_policy
        self.security_mode = security_mode
        self.authentication = authentication
        self.username = username
        self.password = password

        self.client = Client(url=url)
        self.connected = False

        # 設定安全模式
        self._apply_security_settings()

        # 診斷服務（選用）
        self.diagnostic = diagnostic_service or DiagnosticService()
        parsed = urlparse(url)
        self.host = parsed.hostname
        self.opc_port = parsed.port or 49320

    def _apply_security_settings(self):
        """套用 OPC UA 安全與認證設定"""
        # 設定安全模式
        mode_str = self.security_mode.strip().lower()
        if mode_str in ("none", ""):
            self.client.security_mode = MessageSecurityMode.None_
        elif mode_str == "sign":
            self.client.security_mode = MessageSecurityMode.Sign
        elif mode_str in ("signandencrypt", "sign_and_encrypt"):
            self.client.security_mode = MessageSecurityMode.SignAndEncrypt
        else:
            self.client.security_mode = MessageSecurityMode.None_
            logging.warning(f"[{self.name}] 未知的 SecurityMode '{self.security_mode}'，使用 None")

        # 設定認證方式
        auth_str = self.authentication.strip().lower()
        if auth_str == "username" and self.username:
            self.client.set_user(self.username)
            self.client.set_password(self.password or "")
            logging.info(f"[{self.name}] 使用帳號密碼認證 (user={self.username})")
        else:
            logging.info(f"[{self.name}] 使用匿名認證")

        logging.info(f"[{self.name}] 安全設定: Policy={self.security_policy}, "
                     f"Mode={self.security_mode}, Auth={self.authentication}")

    async def connect(self):
        """連線到 OPC UA Server"""
        await self.client.connect()
        self.connected = True
        logging.info(f"[{self.name}] 已成功連接到 Kepware OPC UA 伺服器")

    async def disconnect(self):
        """斷開連線"""
        try:
            await self.client.disconnect()
        except Exception:
            pass
        self.connected = False

    async def reconnect(self):
        """
        與舊版重連邏輯完全一致：
        disconnect → sleep 5 → connect → 成功則 continue，失敗等 30 秒
        """
        try:
            logging.info(f"[{self.name}] 嘗試重新連線 OPC UA 伺服器...")
            try:
                await self.client.disconnect()
            except Exception:
                pass

            await asyncio.sleep(5)

            await self.client.connect()
            self.connected = True
            logging.info(f"[{self.name}] 重新連線成功！")
            return True

        except Exception as ex:
            self.connected = False
            logging.warning(f"[{self.name}] 重新連線失敗: {ex}")
            return False

    async def read_values(self, nodes_info):
        """
        批次讀取點位值。
        nodes_info: list of dict with 'nodeid' and 'name'
        回傳值列表，順序對應 nodes_info。
        """
        nodes = []
        for d in nodes_info:
            try:
                nodes.append(self.client.get_node(d["nodeid"]))
            except Exception as ex:
                logging.warning(f"[{self.name}] 無法建立 node {d.get('name')}: {ex}")
                nodes.append(None)

        valid_nodes = [n for n in nodes if n is not None]
        if not valid_nodes:
            return [None] * len(nodes_info)

        raw_values = await self.client.read_values(valid_nodes)

        # 映射回原始順序
        vals_iter = iter(raw_values)
        values = []
        for n in nodes:
            if n is None:
                values.append(None)
            else:
                values.append(next(vals_iter))

        return values

    async def is_alive(self):
        """
        輕量連線健康檢查。

        asyncua 的背景 watchdog task 偵測到連線異常時只會印 log（"Error in
        watchdog loop"），不會讓下一次 read_values() 立刻失敗，主迴圈要等到
        下一輪真正讀值失敗才會發現斷線，中間會有監控空窗。這裡在每輪讀值前
        先做一次便宜的狀態檢查，讓斷線可以更快被主迴圈感知。

        舊版 asyncua（約 1.x）提供 client.check_connection()，若背景 task
        已掛掉會在這裡重新拋出例外；新版（2.x）改用 client.uaclient.state
        表示連線狀態。兩種 API 都嘗試相容，其他情況一律視為存活，交由
        read_values() 的例外處理去判斷。
        """
        if not self.connected:
            return False
        try:
            check_fn = getattr(self.client, "check_connection", None)
            if check_fn is not None:
                await check_fn()
                return True

            state = getattr(getattr(self.client, "uaclient", None), "state", None)
            if state is not None:
                return getattr(state, "value", state) == "connected"

            return True
        except Exception as ex:
            logging.warning(f"[{self.name}] 連線健康檢查偵測到異常: {ex}")
            self.connected = False
            return False

    async def diagnose_kepware(self):
        """執行 Kepware 主機層診斷 (Layer 1 + 2)"""
        return await self.diagnostic.diagnose_kepware_host(
            self.host, self.opc_port
        )
