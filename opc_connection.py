import asyncio
import logging
from asyncua import Client
from urllib.parse import urlparse

from diagnostic_service import DiagnosticService, DiagnosticResult


class OPCConnection:
    """
    OPC UA 連線管理 — 保留與舊版完全相同的連線模式。
    只做薄包裝，不改變 asyncua Client 的使用方式。
    """

    def __init__(self, name, url, diagnostic_service=None):
        self.name = name
        self.url = url
        # 與舊版一樣：建立 Client 後直接 connect
        self.client = Client(url=url)
        self.connected = False

        # 診斷服務（選用）
        self.diagnostic = diagnostic_service or DiagnosticService()
        parsed = urlparse(url)
        self.host = parsed.hostname
        self.opc_port = parsed.port or 49320

    async def connect(self):
        """
        連線到 OPC UA Server。
        與舊版 `await client.connect()` 完全相同。
        """
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

    async def diagnose_kepware(self):
        """執行 Kepware 主機層診斷 (Layer 1 + 2)"""
        return await self.diagnostic.diagnose_kepware_host(
            self.host, self.opc_port
        )
