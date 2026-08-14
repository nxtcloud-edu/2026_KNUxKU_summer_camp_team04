"""Settings -> MonitorConfig 배선 테스트.

이 파일이 존재하는 이유는 두 번 물린 적이 있기 때문이다:

1. `Settings.monitor` 프로퍼티를 아무도 호출하지 않아서 MONITOR_* 환경변수가
   통째로 무시됐다 (monitor.evaluate*()의 호출자들이 cfg를 생략해 코드에 박힌
   DEFAULT_MONITOR_CONFIG로 떨어졌다).
2. 기본값이 MonitorConfig와 Settings 두 곳에 적혀 있어서, MonitorConfig에서만
   낮춘 값이 Settings의 옛 값에 덮여 아무 변화가 없었다.

둘 다 "고쳤는데 아무 일도 안 일어난다"로 나타나서 원인 찾기가 오래 걸린다.
"""
from __future__ import annotations

import dataclasses

from app.config import DEFAULT_MONITOR_CONFIG, MonitorConfig, Settings


def test_settings_monitor_defaults_match_monitor_config():
    """Settings의 monitor_* 기본값은 MonitorConfig 기본값과 **같아야** 한다.

    두 곳에 숫자를 따로 적으면 조용히 어긋난다. Settings는 MonitorConfig의
    기본값을 참조하도록 되어 있으므로, 이 테스트는 누가 다시 숫자를 하드코딩하면
    깨진다.
    """
    built = Settings(_env_file=None).monitor
    assert built == DEFAULT_MONITOR_CONFIG


def test_every_monitor_config_field_is_reachable_from_env():
    """MonitorConfig의 모든 필드가 MONITOR_* 환경변수로 조절 가능해야 한다.

    필드를 추가하고 Settings에 대응 필드를 안 만들면 .env에 적어도 안 먹는다 --
    조용한 실패라서 테스트로 잡는다.
    """
    missing = [
        f.name
        for f in dataclasses.fields(MonitorConfig)
        if f"monitor_{f.name}" not in Settings.model_fields
    ]
    assert not missing, f"Settings에 대응 필드가 없다: {missing}"


def test_monitor_env_var_actually_changes_the_config():
    """MONITOR_* 값이 실제로 MonitorConfig까지 전달되는지."""
    s = Settings(_env_file=None, monitor_paste_settle_seconds=99)
    assert s.monitor.paste_settle_seconds == 99
