import asyncio
import logging
from asyncua import Client
from urllib.parse import urlparse

from diagnostic_service import DiagnosticService, DiagnosticResult


class OPCConnection:
    """
    單一 Kepware OPC UA 連線管理：
      - 自動重連（含分層診斷）
      - 心跳檢測
      - 批次讀值
    """

    # OPC UA Server Status NodeId
    SERVER_STATUS_NODEID = "ns=0;i=2259"

    def __init__(self, name, url, diagnostic_service=None,
                 reconnect_delay=5, max_reconnect_delay=60):
        self.name = name
        self.url = url
        self.client = Client(url=url)
        self.connected = False
        self.diagnostic = diagnostic_service or DiagnosticService()
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_delay = max_reconnect_delay

        # 從 URL 解析 host 和 port，用於診斷
        parsed = urlparse(url)
        self.host = parsed.hostname
        self.opc_port = parsed.port or 49320

        self._last_diagnostic = DiagnosticResult(DiagnosticResult.LEVEL_OK)

    @property
    def last_diagnostic(self):
        return self._last_diagnostic

    async def connect(self):
        """連線到 OPC UA Server"""
        try:
            await self.client.connect()
            self.connected = True
            self._last_diagnostic = DiagnosticResult(DiagnosticResult.LEVEL_OK)
            logging.info(f"[{self.name}] OPC UA 連線成功: {self.url}")
            return True
        except Exception as ex:
            self.connected = False
            logging.error(f"[{self.name}] OPC UA 連線失敗: {ex}")
            return False

    async def disconnect(self):
        """斷開連線"""
        try:
            await self.client.disconnect()
        except Exception:
            pass
        self.connected = False

    async def heartbeat(self):
        """
        心跳檢測：讀取 Server Status 確認連線存活。
        回傳 True = 正常, False = 異常。
        """
        try:
            node = self.client.get_node(self.SERVER_STATUS_NODEID)
            await node.read_value()
            return True
        except Exception:
            self.connected = False
            return False

    async def read_values(self, devices):
        """
        批次讀取 device 列表中的點位值。
        回傳 list，順序對應 devices，讀取失敗的項目為 None。
        """
        if not devices:
            return []

        # 建立 node 物件
        nodes = []
        for d in devices:
            try:
                nodes.append(self.client.get_node(d["nodeid"]))
            except Exception as ex:
                logging.warning(f"[{self.name}] 無法建立 node {d.get('name')}: {ex}")
                nodes.append(None)

        # 分離有效與無效 nodes
        valid_indices = [i for i, n in enumerate(nodes) if n is not None]
        valid_nodes = [nodes[i] for i in valid_indices]

        if not valid_nodes:
            return [None] * len(devices)

        try:
            raw_values = await self.client.read_values(valid_nodes)
        except Exception as ex:
            self.connected = False
            raise ex

        # 映射回原始順序
        result = [None] * len(devices)
        for idx, val in zip(valid_indices, raw_values):
            result[idx] = val

        return result

    async def reconnect_with_diagnosis(self):
        """
        斷線後嘗試重連，先執行分層診斷再決定策略。
        回傳 (connected: bool, diagnostic: DiagnosticResult)
        """
        # 先斷開舊連線
        await self.disconnect()

        # 執行 Kepware 主機層診斷 (Layer 1 + 2)
        diag = await self.diagnostic.diagnose_kepware_host(
            self.host, self.opc_port
        )
        self._last_diagnostic = diag

        if diag.level == DiagnosticResult.LEVEL_HOST_DOWN:
            logging.warning(f"[{self.name}] {diag.message}")
            return False, diag

        if diag.level == DiagnosticResult.LEVEL_OPC_SERVICE_DOWN:
            logging.warning(f"[{self.name}] {diag.message}")
            return False, diag

        # Ping 和 Port 都通，嘗試 OPC 重連
        await asyncio.sleep(self.reconnect_delay)
        success = await self.connect()

        if not success:
            diag = DiagnosticResult(
                level=DiagnosticResult.LEVEL_OPC_SERVICE_DOWN,
                message=f"Kepware 主機 {self.host} 網路正常但 OPC UA 連線失敗 (可能授權或設定問題)",
                detail={"host": self.host, "port": self.opc_port},
            )
            self._last_diagnostic = diag

        return success, self._last_diagnostic

    async def connect_with_retry(self, max_retries=None):
        """
        啟動時持續重試連線，直到成功。
        max_retries=None 代表無限重試。
        """
        attempt = 0
        delay = self.reconnect_delay

        while max_retries is None or attempt < max_retries:
            attempt += 1
            logging.info(f"[{self.name}] 嘗試連線 (第 {attempt} 次)...")

            success = await self.connect()
            if success:
                return True

            # 診斷後等待
            diag = await self.diagnostic.diagnose_kepware_host(
                self.host, self.opc_port
            )
            self._last_diagnostic = diag
            logging.warning(f"[{self.name}] 連線失敗 - {diag.message}，{delay} 秒後重試...")

            await asyncio.sleep(delay)
            delay = min(delay * 1.5, self.max_reconnect_delay)

        return False
