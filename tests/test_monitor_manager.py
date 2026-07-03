"""
針對 monitor_manager.py 中純函式邏輯的單元測試。

涵蓋範圍：
  - DeviceConfig.__init__：CSV 欄位缺漏時的預設值、key 屬性
  - MonitorManager._parse_csv_row：CSV 原始字串欄位轉型（Enable 布林轉換等）
  - MonitorManager.evaluate（staticmethod）：number / bool / log 三種 device_type
    的閾值判斷邏輯，涵蓋所有支援的 condition

測試資料盡量使用中文情境（設備名稱），符合本系統實際資料型態。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from monitor_manager import DeviceConfig, MonitorManager


def _make_row_parser():
    """建立一個不經過完整 __init__（不需要 config/DB/OPC 連線）的 MonitorManager，
    僅具備 _parse_csv_row 所需的 global_mail_to / global_mail_cc 屬性。"""
    mm = MonitorManager.__new__(MonitorManager)
    mm.global_mail_to = ["it@example.com"]
    mm.global_mail_cc = []
    return mm


def _make_device(**overrides):
    """建立一個 DeviceConfig，預設值可透過 overrides 覆寫（給 evaluate() 測試用）。"""
    raw = {
        "name": "水塔液位計",
        "nodeid": "ns=2;s=Channel1.Device1.Tag1",
        "server_name": "default",
        "type": "number",
        "condition": "greater",
        "threshold": 50.0,
        "accumulate": 1,
        "enable": True,
    }
    raw.update(overrides)
    return DeviceConfig(raw)


# ============================================================
# DeviceConfig.__init__ / key
# ============================================================

class TestDeviceConfigInit:
    def test_defaults_when_fields_missing(self):
        dc = DeviceConfig({})
        assert dc.name == ""
        assert dc.nodeid == ""
        assert dc.server_name == ""
        assert dc.device_type == "number"
        assert dc.condition == "greater"
        assert dc.threshold is None
        assert dc.accumulate == 1
        assert dc.enable is True
        assert dc.device_ip == ""
        assert dc.device_port == 49310
        assert dc.mail_to == []
        assert dc.mail_cc == []
        # 執行狀態初始值
        assert dc.counter == 0
        assert dc.last_alert_time == 0
        assert dc.last_diagnostic is None
        assert dc.last_value is None

    def test_full_fields_populated(self):
        raw = {
            "name": "冷凍主機溫度",
            "nodeid": "ns=2;s=Channel1.Device2.Temp",
            "server_name": "kepware_a",
            "type": "number",
            "condition": "greater",
            "threshold": 80.0,
            "accumulate": 3,
            "enable": True,
            "device_ip": "10.10.51.100",
            "device_port": 502,
            "mail_to": ["ops@example.com"],
            "mail_cc": ["mgr@example.com"],
        }
        dc = DeviceConfig(raw)
        assert dc.name == "冷凍主機溫度"
        assert dc.nodeid == "ns=2;s=Channel1.Device2.Temp"
        assert dc.server_name == "kepware_a"
        assert dc.threshold == 80.0
        assert dc.accumulate == 3
        assert dc.device_ip == "10.10.51.100"
        assert dc.device_port == 502
        assert dc.mail_to == ["ops@example.com"]
        assert dc.mail_cc == ["mgr@example.com"]

    def test_key_property_reflects_name_and_nodeid(self):
        dc = DeviceConfig({"name": "水塔液位計", "nodeid": "ns=2;s=Tag1"})
        assert dc.key == ("水塔液位計", "ns=2;s=Tag1")

    def test_key_property_empty_when_missing(self):
        dc = DeviceConfig({})
        assert dc.key == ("", "")

    def test_inherit_state_copies_runtime_state_when_both_enabled(self):
        old = DeviceConfig({"name": "A", "nodeid": "n1", "enable": True})
        old.counter = 3
        old.last_alert_time = 123456.0
        old.last_value = 99.5

        new = DeviceConfig({"name": "A", "nodeid": "n1", "enable": True})
        new.inherit_state(old)

        assert new.counter == 3
        assert new.last_alert_time == 123456.0
        assert new.last_value == 99.5

    def test_inherit_state_skipped_when_new_device_disabled(self):
        old = DeviceConfig({"name": "A", "nodeid": "n1", "enable": True})
        old.counter = 3

        new = DeviceConfig({"name": "A", "nodeid": "n1", "enable": False})
        new.inherit_state(old)

        assert new.counter == 0  # 未繼承，維持初始值

    def test_inherit_state_skipped_when_no_old_device(self):
        new = DeviceConfig({"name": "A", "nodeid": "n1", "enable": True})
        new.inherit_state(None)
        assert new.counter == 0


# ============================================================
# MonitorManager._parse_csv_row（CSV 字串 -> 型別轉換，含 Enable 布林邏輯）
# ============================================================

class TestParseCsvRow:
    def test_enable_true_string_variants(self):
        mm = _make_row_parser()
        for val in ("True", "TRUE", "true", "TrUe"):
            row = {"Name": "設備A", "NodeId": "n1", "Enable": val}
            parsed = mm._parse_csv_row(row)
            assert parsed["enable"] is True, f"Enable={val!r} 應轉換為 True"

    def test_enable_false_string(self):
        mm = _make_row_parser()
        row = {"Name": "設備A", "NodeId": "n1", "Enable": "False"}
        parsed = mm._parse_csv_row(row)
        assert parsed["enable"] is False

    def test_enable_non_true_string_is_false(self):
        # 目前實作只認可字串 "true"（不分大小寫）視為 True，
        # 其餘任何字串（含 "1"、"yes"）皆視為 False。
        # 這與 bool 型別 threshold 解析（接受 1/true/yes）不對稱，記錄為既有行為。
        mm = _make_row_parser()
        for val in ("1", "yes", "on", "", "無效值"):
            row = {"Name": "設備A", "NodeId": "n1", "Enable": val}
            parsed = mm._parse_csv_row(row)
            assert parsed["enable"] is False, f"Enable={val!r} 應轉換為 False"

    def test_enable_missing_defaults_true(self):
        mm = _make_row_parser()
        row = {"Name": "設備A", "NodeId": "n1"}
        parsed = mm._parse_csv_row(row)
        assert parsed["enable"] is True

    def test_missing_optional_fields_get_defaults(self):
        mm = _make_row_parser()
        row = {"Name": "設備A", "NodeId": "n1"}
        parsed = mm._parse_csv_row(row)
        assert parsed["server_name"] == "default"
        assert parsed["type"] == "number"
        assert parsed["condition"] == "greater"
        assert parsed["threshold"] is None
        assert parsed["accumulate"] == 1
        assert parsed["device_ip"] == ""
        assert parsed["device_port"] == 49310

    def test_number_threshold_parses_float(self):
        mm = _make_row_parser()
        row = {"Name": "水塔液位計", "NodeId": "n1", "Type": "Number", "Threshold": "75.5"}
        parsed = mm._parse_csv_row(row)
        assert parsed["threshold"] == 75.5

    def test_number_threshold_invalid_falls_back_to_none(self):
        mm = _make_row_parser()
        row = {"Name": "水塔液位計", "NodeId": "n1", "Type": "number", "Threshold": "not_a_number"}
        parsed = mm._parse_csv_row(row)
        assert parsed["threshold"] is None

    def test_bool_threshold_true_variants(self):
        mm = _make_row_parser()
        for val in ("1", "true", "yes", "TRUE", "Yes"):
            row = {"Name": "泵浦運轉狀態", "NodeId": "n1", "Type": "bool", "Threshold": val}
            parsed = mm._parse_csv_row(row)
            assert parsed["threshold"] is True, f"Threshold={val!r} 應為 True"

    def test_bool_threshold_false_variants(self):
        mm = _make_row_parser()
        for val in ("0", "false", "no", "FALSE", "No"):
            row = {"Name": "泵浦運轉狀態", "NodeId": "n1", "Type": "bool", "Threshold": val}
            parsed = mm._parse_csv_row(row)
            assert parsed["threshold"] is False

    def test_accumulate_invalid_defaults_to_1(self):
        mm = _make_row_parser()
        row = {"Name": "設備A", "NodeId": "n1", "CountNeeded": "abc"}
        parsed = mm._parse_csv_row(row)
        assert parsed["accumulate"] == 1

    def test_accumulate_below_1_clamped_to_1(self):
        mm = _make_row_parser()
        row = {"Name": "設備A", "NodeId": "n1", "CountNeeded": "0"}
        parsed = mm._parse_csv_row(row)
        assert parsed["accumulate"] == 1

    def test_mail_merge_global_and_csv_deduplicated(self):
        mm = _make_row_parser()
        row = {"Name": "設備A", "NodeId": "n1", "MailTo": "it@example.com, ops@example.com"}
        parsed = mm._parse_csv_row(row)
        # global_mail_to 已含 it@example.com，CSV 又填一次，應去重保序
        assert parsed["mail_to"] == ["it@example.com", "ops@example.com"]


# ============================================================
# MonitorManager.evaluate — number 型別
# ============================================================

class TestEvaluateNumber:
    def test_greater_triggers_alert(self):
        d = _make_device(type="number", condition="greater", threshold=50.0)
        is_alert, val = MonitorManager.evaluate(d, 60)
        assert is_alert is True
        assert val == 60.0

    def test_greater_no_alert(self):
        d = _make_device(type="number", condition="greater", threshold=50.0)
        is_alert, val = MonitorManager.evaluate(d, 40)
        assert is_alert is False
        assert val == 40.0

    def test_less_triggers_alert(self):
        d = _make_device(type="number", condition="less", threshold=10.0)
        is_alert, val = MonitorManager.evaluate(d, 5)
        assert is_alert is True
        assert val == 5.0

    def test_less_no_alert(self):
        d = _make_device(type="number", condition="less", threshold=10.0)
        is_alert, val = MonitorManager.evaluate(d, 20)
        assert is_alert is False

    @pytest.mark.parametrize("condition", ["equal", "=="])
    def test_equal_triggers_alert(self, condition):
        d = _make_device(type="number", condition=condition, threshold=100.0)
        is_alert, val = MonitorManager.evaluate(d, 100)
        assert is_alert is True
        assert val == 100.0

    @pytest.mark.parametrize("condition", ["equal", "=="])
    def test_equal_no_alert(self, condition):
        d = _make_device(type="number", condition=condition, threshold=100.0)
        is_alert, val = MonitorManager.evaluate(d, 99)
        assert is_alert is False

    @pytest.mark.parametrize("condition", ["not_equal", "!="])
    def test_not_equal_triggers_alert(self, condition):
        d = _make_device(type="number", condition=condition, threshold=100.0)
        is_alert, val = MonitorManager.evaluate(d, 99)
        assert is_alert is True

    @pytest.mark.parametrize("condition", ["not_equal", "!="])
    def test_not_equal_no_alert(self, condition):
        d = _make_device(type="number", condition=condition, threshold=100.0)
        is_alert, val = MonitorManager.evaluate(d, 100)
        assert is_alert is False

    def test_unsupported_condition_returns_no_alert(self):
        d = _make_device(type="number", condition="foo", threshold=50.0)
        is_alert, val = MonitorManager.evaluate(d, 999)
        assert is_alert is False
        assert val == 999.0

    def test_threshold_none_never_alerts_but_still_parses_value(self):
        d = _make_device(type="number", condition="greater", threshold=None)
        is_alert, val = MonitorManager.evaluate(d, 60)
        assert is_alert is False
        assert val == 60.0

    def test_unparseable_value_returns_none(self):
        d = _make_device(type="number", condition="greater", threshold=50.0)
        is_alert, val = MonitorManager.evaluate(d, "非數值字串")
        assert is_alert is False
        assert val is None

    def test_unchanged_zero_value_always_alerts(self):
        d = _make_device(type="number", condition="unchanged", threshold=None)
        d.last_value = 0.0
        is_alert, val = MonitorManager.evaluate(d, 0)
        assert is_alert is True
        assert val == 0.0

    def test_unchanged_no_history_no_alert(self):
        d = _make_device(type="number", condition="unchanged", threshold=None)
        d.last_value = None
        is_alert, val = MonitorManager.evaluate(d, 5)
        assert is_alert is False
        assert val == 5.0

    def test_unchanged_same_as_last_value_alerts(self):
        d = _make_device(type="number", condition="unchanged", threshold=None)
        d.last_value = 5.0
        is_alert, val = MonitorManager.evaluate(d, 5)
        assert is_alert is True

    def test_unchanged_different_from_last_value_no_alert(self):
        d = _make_device(type="number", condition="unchanged", threshold=None)
        d.last_value = 5.0
        is_alert, val = MonitorManager.evaluate(d, 7)
        assert is_alert is False


# ============================================================
# MonitorManager.evaluate — bool 型別
# ============================================================

class TestEvaluateBool:
    def test_string_true_variants_parse_true(self):
        for s in ("1", "true", "T", "yes", "on", "TRUE", "Yes"):
            d = _make_device(type="bool", condition="true", threshold=True)
            is_alert, val = MonitorManager.evaluate(d, s)
            assert val is True, f"{s!r} 應解析為 True"

    def test_string_false_variants_parse_false(self):
        for s in ("0", "false", "f", "no", "off", "FALSE", "No"):
            d = _make_device(type="bool", condition="false", threshold=False)
            is_alert, val = MonitorManager.evaluate(d, s)
            assert val is False, f"{s!r} 應解析為 False"

    def test_native_bool_passthrough(self):
        d = _make_device(type="bool", condition="true", threshold=True)
        is_alert, val = MonitorManager.evaluate(d, True)
        assert val is True

    def test_numeric_string_fallback_uses_int_bool(self):
        # "2" 不在 true/false 字串清單中，落到 bool(int(raw_value)) -> bool(2) -> True
        d = _make_device(type="bool", condition="true", threshold=True)
        is_alert, val = MonitorManager.evaluate(d, "2")
        assert val is True

    def test_unparseable_string_fallback_to_false(self):
        d = _make_device(type="bool", condition="false", threshold=True)
        is_alert, val = MonitorManager.evaluate(d, "設備狀態異常字串")
        assert val is False

    def test_condition_true_triggers_when_value_true(self):
        d = _make_device(type="bool", condition="true", threshold=True)
        is_alert, val = MonitorManager.evaluate(d, True)
        assert is_alert is True

    def test_condition_true_no_alert_when_value_false(self):
        d = _make_device(type="bool", condition="true", threshold=True)
        is_alert, val = MonitorManager.evaluate(d, False)
        assert is_alert is False

    def test_condition_false_triggers_when_value_false(self):
        d = _make_device(type="bool", condition="false", threshold=True)
        is_alert, val = MonitorManager.evaluate(d, False)
        assert is_alert is True

    def test_condition_1_alias_for_true(self):
        d = _make_device(type="bool", condition="1", threshold=True)
        is_alert, val = MonitorManager.evaluate(d, True)
        assert is_alert is True

    def test_condition_0_alias_for_false(self):
        d = _make_device(type="bool", condition="0", threshold=True)
        is_alert, val = MonitorManager.evaluate(d, False)
        assert is_alert is True

    @pytest.mark.parametrize("condition", ["equal", "=="])
    def test_equal_condition(self, condition):
        d = _make_device(type="bool", condition=condition, threshold=True)
        is_alert, val = MonitorManager.evaluate(d, True)
        assert is_alert is True
        is_alert2, _ = MonitorManager.evaluate(d, False)
        assert is_alert2 is False

    @pytest.mark.parametrize("condition", ["not_equal", "!="])
    def test_not_equal_condition(self, condition):
        d = _make_device(type="bool", condition=condition, threshold=True)
        is_alert, val = MonitorManager.evaluate(d, False)
        assert is_alert is True

    def test_threshold_none_never_alerts(self):
        d = _make_device(type="bool", condition="true", threshold=None)
        is_alert, val = MonitorManager.evaluate(d, True)
        assert is_alert is False
        assert val is True  # 仍會回傳解析後的值

    def test_unchanged_no_history_no_alert(self):
        d = _make_device(type="bool", condition="unchanged", threshold=None)
        d.last_value = None
        is_alert, val = MonitorManager.evaluate(d, True)
        assert is_alert is False

    def test_unchanged_same_as_last_value_alerts(self):
        d = _make_device(type="bool", condition="unchanged", threshold=None)
        d.last_value = True
        is_alert, val = MonitorManager.evaluate(d, True)
        assert is_alert is True

    def test_unchanged_different_from_last_value_no_alert(self):
        d = _make_device(type="bool", condition="unchanged", threshold=None)
        d.last_value = True
        is_alert, val = MonitorManager.evaluate(d, False)
        assert is_alert is False


# ============================================================
# MonitorManager.evaluate — log 型別 / enable=False / 其他邊界
# ============================================================

class TestEvaluateLogAndEdgeCases:
    def test_log_type_never_alerts_and_passes_value_through(self):
        d = _make_device(type="log", condition="greater", threshold=None)
        is_alert, val = MonitorManager.evaluate(d, "Channel1.Device1 設備已啟動")
        assert is_alert is False
        assert val == "Channel1.Device1 設備已啟動"

    def test_log_type_with_none_value_no_alert(self):
        # 頂層 "raw_value is None" 檢查先於 dtype == 'log' 分支執行，
        # 但兩者對 None 輸入的結果一致：(False, None)
        d = _make_device(type="log", condition="greater", threshold=None)
        is_alert, val = MonitorManager.evaluate(d, None)
        assert is_alert is False
        assert val is None

    def test_disabled_device_never_alerts_regardless_of_value(self):
        d = _make_device(type="number", condition="greater", threshold=1.0, enable=False)
        is_alert, val = MonitorManager.evaluate(d, 999)
        assert is_alert is False
        assert val is None

    def test_none_raw_value_no_alert_for_number_type(self):
        d = _make_device(type="number", condition="greater", threshold=50.0)
        is_alert, val = MonitorManager.evaluate(d, None)
        assert is_alert is False
        assert val is None

    def test_unsupported_device_type_returns_no_alert(self):
        d = _make_device(type="string", condition="greater", threshold=50.0)
        is_alert, val = MonitorManager.evaluate(d, "任意值")
        assert is_alert is False
        assert val is None
