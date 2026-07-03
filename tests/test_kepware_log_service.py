"""
針對 kepware_log_service.py 中純函式邏輯的單元測試。

涵蓋範圍：
  - _normalize_timestamp：9 種支援格式 + 空字串 fallback + 無法解析字串的 fallback
  - _classify_severity：大小寫不敏感關鍵字比對、Critical/Warning/Advisory 優先順序
  - _parse_channel_device：CHANNEL_DEVICE_RE 匹配 / 不匹配
  - _parse_tag_address：TAG_ADDRESS_RE 匹配 / 不匹配
  - _make_hash：相同輸入 -> 相同 hash，不同輸入 -> 不同 hash

測試資料盡量使用中文情境（設備名稱、告警訊息），符合本系統實際資料型態。
"""
import os
import sys
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kepware_log_service import KepwareLogService


@pytest.fixture
def log_service(tmp_path, monkeypatch):
    """建立最小可用的 KepwareLogService 實例。

    db_service / email_service 用 MagicMock 頂替（建構子不需要它們做任何 I/O）。
    cwd 切到 tmp_path，避免建構子的 Path("data").mkdir() 在專案根目錄留下側寫檔案。
    """
    monkeypatch.chdir(tmp_path)
    svc = KepwareLogService(
        server_name="測試站台",
        base_url="http://10.10.51.81:8000",
        username="admin",
        password="pass",
        db_service=MagicMock(),
        email_service=MagicMock(),
    )
    return svc


# ============================================================
# _normalize_timestamp
# ============================================================

class TestNormalizeTimestamp:
    def test_format_iso_with_micro_and_z(self):
        assert (KepwareLogService._normalize_timestamp("2026-07-03T10:15:30.123456Z")
                == "2026-07-03 10:15:30")

    def test_format_iso_with_z(self):
        assert (KepwareLogService._normalize_timestamp("2026-07-03T10:15:30Z")
                == "2026-07-03 10:15:30")

    def test_format_iso_with_micro_no_z(self):
        assert (KepwareLogService._normalize_timestamp("2026-07-03T10:15:30.123456")
                == "2026-07-03 10:15:30")

    def test_format_iso_no_micro_no_z(self):
        assert (KepwareLogService._normalize_timestamp("2026-07-03T10:15:30")
                == "2026-07-03 10:15:30")

    def test_format_space_separated(self):
        assert (KepwareLogService._normalize_timestamp("2026-07-03 10:15:30")
                == "2026-07-03 10:15:30")

    def test_format_us_12hour_am_pm(self):
        assert (KepwareLogService._normalize_timestamp("07/03/2026 10:15:30 AM")
                == "2026-07-03 10:15:30")
        assert (KepwareLogService._normalize_timestamp("07/03/2026 02:15:30 PM")
                == "2026-07-03 14:15:30")

    def test_format_us_24hour(self):
        # 沒有 AM/PM，必須跳過 "%I...%p" 格式，改用 "%m/%d/%Y %H:%M:%S"
        assert (KepwareLogService._normalize_timestamp("07/03/2026 14:15:30")
                == "2026-07-03 14:15:30")

    def test_format_day_month_year(self):
        # day=25 超過月份合法範圍(1-12)，會讓 m/d/Y 系列格式解析失敗，
        # 進而落到 "%d/%m/%Y %H:%M:%S" 才能命中
        assert (KepwareLogService._normalize_timestamp("25/12/2026 10:15:30")
                == "2026-12-25 10:15:30")

    def test_format_year_month_day_slash(self):
        assert (KepwareLogService._normalize_timestamp("2026/07/03 10:15:30")
                == "2026-07-03 10:15:30")

    def test_empty_string_fallback_uses_now(self):
        before = datetime.now()
        result = KepwareLogService._normalize_timestamp("")
        after = datetime.now()
        parsed = datetime.strptime(result, "%Y-%m-%d %H:%M:%S")
        # 允許 1 秒誤差（現在時間與呼叫時間可能跨秒）
        assert before - timedelta(seconds=2) <= parsed <= after + timedelta(seconds=2)

    def test_none_fallback_uses_now(self):
        result = KepwareLogService._normalize_timestamp(None)
        # 不應拋例外，且格式正確可被解析
        datetime.strptime(result, "%Y-%m-%d %H:%M:%S")

    def test_unparseable_but_length_and_dash_positions_match_truncates(self):
        # 長度 >= 19，且第 4、7 個字元為 '-'（符合日期部分格式），但分隔符不是 T 或空白
        # -> 落入 "len(ts) >= 19 and ts[4]=='-' and ts[7]=='-'" 的 fallback，回傳前 19 碼
        raw = "2026-07-03X10:15:30額外文字"
        result = KepwareLogService._normalize_timestamp(raw)
        assert result == raw[:19]
        assert len(result) == 19

    def test_completely_unparseable_short_string_returned_as_is(self):
        raw = "garbage"
        assert KepwareLogService._normalize_timestamp(raw) == raw

    def test_unparseable_long_string_without_dash_positions_returned_as_is(self):
        # 長度 >= 19，但第 4、7 個字元不是 '-' -> 不觸發 truncate fallback，整串原樣回傳
        raw = "這是一段完全無法解析的中文時間字串內容"
        assert len(raw) >= 19
        assert raw[4] != "-" and raw[7] != "-"
        assert KepwareLogService._normalize_timestamp(raw) == raw


# ============================================================
# _classify_severity
# ============================================================

class TestClassifySeverity(object):
    def test_default_critical_keyword(self, log_service):
        msg = "Channel1.Device1 | Device not responding"
        assert log_service._classify_severity(msg) == "Critical"

    def test_critical_case_insensitive(self, log_service):
        msg = "channel1.device1 | DEVICE NOT RESPONDING to poll request"
        assert log_service._classify_severity(msg) == "Critical"

    def test_default_warning_keyword_timeout(self, log_service):
        msg = "Channel1.Device1 | Timeout waiting for response from 設備一"
        assert log_service._classify_severity(msg) == "Warning"

    def test_default_warning_keyword_add_item_failed(self, log_service):
        msg = "Channel1.Device1 | Add item failed for tag 'D100'"
        assert log_service._classify_severity(msg) == "Warning"

    def test_default_advisory_keyword(self, log_service):
        msg = "Channel1.Device1 | Failed to remove item 'ns=2;s=D100' from group"
        assert log_service._classify_severity(msg) == "Advisory"

    def test_unclassified_when_no_keyword_matches(self, log_service):
        msg = "系統已啟動，Channel1.Device1 連線正常"
        assert log_service._classify_severity(msg) == "Unclassified"

    def test_critical_takes_priority_over_warning(self, log_service):
        # 同時包含 critical 與 warning 關鍵字時，critical 應優先命中
        msg = "Device not responding, previous Timeout also occurred"
        assert log_service._classify_severity(msg) == "Critical"

    def test_custom_severity_keywords_are_used(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        svc = KepwareLogService(
            server_name="自訂關鍵字站台",
            base_url="http://10.10.51.81:8000",
            username="admin",
            password="pass",
            db_service=MagicMock(),
            email_service=MagicMock(),
            severity_critical=["設備斷線"],
            severity_warning=["逾時"],
            severity_advisory=["移除項目失敗"],
        )
        assert svc._classify_severity("Channel1.Device1 | 設備斷線警告") == "Critical"
        assert svc._classify_severity("Channel1.Device1 | 讀取逾時") == "Warning"
        assert svc._classify_severity("Channel1.Device1 | 移除項目失敗") == "Advisory"
        assert svc._classify_severity("Channel1.Device1 | 一般訊息") == "Unclassified"


# ============================================================
# _parse_channel_device
# ============================================================

class TestParseChannelDevice:
    def test_matches_standard_message(self, log_service):
        msg = "Channel1.Device1 | Tag address = 'D100' failed to add item"
        assert log_service._parse_channel_device(msg) == ("Channel1", "Device1")

    def test_matches_with_underscore_and_hyphen(self, log_service):
        msg = "PLC_Line-1.Device_02 | Device not responding"
        assert log_service._parse_channel_device(msg) == ("PLC_Line-1", "Device_02")

    def test_no_match_without_pipe_separator(self, log_service):
        msg = "Channel1.Device1 Device not responding"
        assert log_service._parse_channel_device(msg) == ("", "")

    def test_no_match_when_channel_device_use_chinese_chars(self, log_service):
        # regex 字元類別只允許 [A-Za-z0-9_\-]，中文站名/設備名不會匹配
        msg = "一號通道.一號設備 | Device not responding"
        assert log_service._parse_channel_device(msg) == ("", "")

    def test_no_match_empty_message(self, log_service):
        assert log_service._parse_channel_device("") == ("", "")


# ============================================================
# _parse_tag_address
# ============================================================

class TestParseTagAddress:
    def test_matches_tag_address(self, log_service):
        msg = "Channel1.Device1 | Tag address = 'D100' failed to add item"
        assert log_service._parse_tag_address(msg) == "D100"

    def test_matches_with_extra_spaces(self, log_service):
        msg = "Channel1.Device1 | Tag address='400001' invalid"
        assert log_service._parse_tag_address(msg) == "400001"

    def test_no_match_returns_empty_string(self, log_service):
        msg = "Channel1.Device1 | Device not responding"
        assert log_service._parse_tag_address(msg) == ""

    def test_no_match_empty_message(self, log_service):
        assert log_service._parse_tag_address("") == ""


# ============================================================
# _make_hash
# ============================================================

class TestMakeHash:
    def test_same_input_same_hash(self):
        h1 = KepwareLogService._make_hash("2026-07-03 10:15:30", "Channel1.Device1",
                                          "Device not responding")
        h2 = KepwareLogService._make_hash("2026-07-03 10:15:30", "Channel1.Device1",
                                          "Device not responding")
        assert h1 == h2

    def test_different_message_different_hash(self):
        h1 = KepwareLogService._make_hash("2026-07-03 10:15:30", "Channel1.Device1", "訊息A")
        h2 = KepwareLogService._make_hash("2026-07-03 10:15:30", "Channel1.Device1", "訊息B")
        assert h1 != h2

    def test_different_timestamp_different_hash(self):
        h1 = KepwareLogService._make_hash("2026-07-03 10:15:30", "Channel1.Device1", "訊息A")
        h2 = KepwareLogService._make_hash("2026-07-03 10:15:31", "Channel1.Device1", "訊息A")
        assert h1 != h2

    def test_hash_length_is_16(self):
        h = KepwareLogService._make_hash("ts", "src", "msg")
        assert len(h) == 16
