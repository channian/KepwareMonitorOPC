import asyncio
import logging
import platform


class DiagnosticResult:
    """三層診斷結果"""

    LEVEL_OK = "ok"
    LEVEL_HOST_DOWN = "host_down"              # Kepware 主機無法 Ping
    LEVEL_OPC_SERVICE_DOWN = "opc_service_down"  # 主機通但 OPC Port 不通
    LEVEL_DEVICE_DOWN = "device_down"            # iFIX/IGS 機台無法 Ping
    LEVEL_IGS_SERVICE_DOWN = "igs_service_down"  # 機台通但 IGS Port 不通
    LEVEL_VALUE_ABNORMAL = "value_abnormal"      # 連線正常但數值異常

    def __init__(self, level, message="", detail=None):
        self.level = level
        self.message = message
        self.detail = detail or {}

    @property
    def is_connection_issue(self):
        return self.level in (
            self.LEVEL_HOST_DOWN,
            self.LEVEL_OPC_SERVICE_DOWN,
            self.LEVEL_DEVICE_DOWN,
            self.LEVEL_IGS_SERVICE_DOWN,
        )

    def __repr__(self):
        return f"DiagnosticResult(level={self.level}, message={self.message})"


class DiagnosticService:
    """
    網路診斷服務：
      Layer 1 — Ping Kepware 主機
      Layer 2 — TCP 檢查 Kepware OPC Port
      Layer 3 — Ping iFIX/IGS 機台 + TCP 檢查 IGS Port
    """

    def __init__(self, ping_timeout=3, tcp_timeout=3):
        self.ping_timeout = ping_timeout
        self.tcp_timeout = tcp_timeout
        self._is_windows = platform.system().lower() == "windows"

    async def ping(self, host):
        """
        非同步 Ping 主機，回傳 True/False。
        """
        if not host:
            return False

        try:
            if self._is_windows:
                cmd = ["ping", "-n", "1", "-w", str(self.ping_timeout * 1000), host]
            else:
                cmd = ["ping", "-c", "1", "-W", str(self.ping_timeout), host]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            returncode = await asyncio.wait_for(proc.wait(), timeout=self.ping_timeout + 2)
            return returncode == 0

        except asyncio.TimeoutError:
            return False
        except Exception as ex:
            logging.warning(f"Ping {host} 發生例外: {ex}")
            return False

    async def check_tcp_port(self, host, port):
        """
        非同步檢查 TCP Port 是否可連線。
        """
        if not host or not port:
            return False

        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, int(port)),
                timeout=self.tcp_timeout,
            )
            writer.close()
            await writer.wait_closed()
            return True
        except (asyncio.TimeoutError, OSError, ConnectionRefusedError):
            return False
        except Exception as ex:
            logging.warning(f"TCP check {host}:{port} 發生例外: {ex}")
            return False

    async def diagnose_kepware_host(self, host, opc_port=49320):
        """
        Layer 1 + 2: 檢查 Kepware 主機與 OPC 服務。
        回傳 DiagnosticResult。
        """
        # Layer 1: Ping Kepware 主機
        ping_ok = await self.ping(host)
        if not ping_ok:
            return DiagnosticResult(
                level=DiagnosticResult.LEVEL_HOST_DOWN,
                message=f"Kepware 主機 {host} 無法連線 (Ping 失敗)",
                detail={"host": host},
            )

        # Layer 2: TCP 檢查 OPC Port
        tcp_ok = await self.check_tcp_port(host, opc_port)
        if not tcp_ok:
            return DiagnosticResult(
                level=DiagnosticResult.LEVEL_OPC_SERVICE_DOWN,
                message=f"Kepware 主機 {host} 正常但 OPC 服務 (Port {opc_port}) 無回應",
                detail={"host": host, "port": opc_port},
            )

        return DiagnosticResult(
            level=DiagnosticResult.LEVEL_OK,
            message=f"Kepware 主機 {host} 與 OPC 服務正常",
        )

    async def diagnose_device(self, device_ip, device_port=49310):
        """
        Layer 3: 檢查 iFIX/IGS 機台與 IGS 服務。
        只在 device_ip 有值時才執行。
        回傳 DiagnosticResult。
        """
        if not device_ip:
            # 沒有 IP 資訊，跳過設備層診斷
            return DiagnosticResult(
                level=DiagnosticResult.LEVEL_OK,
                message="無設備 IP，跳過設備層診斷",
            )

        # Ping iFIX/IGS 機台
        ping_ok = await self.ping(device_ip)
        if not ping_ok:
            return DiagnosticResult(
                level=DiagnosticResult.LEVEL_DEVICE_DOWN,
                message=f"iFIX/IGS 機台 {device_ip} 無法連線 (Ping 失敗，可能已關機)",
                detail={"device_ip": device_ip},
            )

        # TCP 檢查 IGS Port
        if device_port:
            tcp_ok = await self.check_tcp_port(device_ip, device_port)
            if not tcp_ok:
                return DiagnosticResult(
                    level=DiagnosticResult.LEVEL_IGS_SERVICE_DOWN,
                    message=f"iFIX/IGS 機台 {device_ip} 正常但 IGS 服務 (Port {device_port}) 無回應",
                    detail={"device_ip": device_ip, "device_port": device_port},
                )

        return DiagnosticResult(
            level=DiagnosticResult.LEVEL_OK,
            message=f"iFIX/IGS 機台 {device_ip} 與 IGS 服務正常",
        )

    async def full_diagnose(self, kepware_host, opc_port=49320,
                            device_ip=None, device_port=49310):
        """
        執行完整三層診斷，回傳最嚴重的 DiagnosticResult。
        """
        # Layer 1 + 2
        host_result = await self.diagnose_kepware_host(kepware_host, opc_port)
        if host_result.level != DiagnosticResult.LEVEL_OK:
            return host_result

        # Layer 3
        device_result = await self.diagnose_device(device_ip, device_port)
        return device_result
