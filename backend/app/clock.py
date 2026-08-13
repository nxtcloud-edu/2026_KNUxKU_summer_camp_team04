"""시간의 유일한 출처.

정책: **naive UTC로 저장하고, 출력할 때만 'Z'를 붙인다.**

이건 취향이 아니라 강제된 선택이다.
- SQLite에는 datetime 타입이 없다. SQLAlchemy의 DateTime은 ISO 문자열로 왕복하며
  **읽을 때 tzinfo를 버린다** (DateTime(timezone=True)도 SQLite에서는 마찬가지).
  aware를 쓰고 naive를 읽는 코드는 결국 `now_aware - stored_naive`를 하게 되고
  TypeError가 난다 -- 그것도 하필 seconds_without_progress 안에서, 테스트가 아니라 데모 중에.
- 반대편 함정: Pydantic은 naive datetime을 "2026-08-13T12:04:11"로 직렬화하고,
  JS의 new Date()는 그걸 **로컬 시간**으로 파싱한다. KST면 9시간이 조용히 밀린다.
  그래서 응답 스키마의 모든 datetime 필드는 schemas_common.UtcDatetime을 쓴다.

microsecond를 자르는 것은 의도적이다. 타임라인 출력이 읽기 좋아지고,
timestamp가 같은 이벤트의 순서 테스트가 재현 가능해진다
(애초에 순서는 timestamp가 아니라 seq가 결정한다).

datetime.utcnow()는 Python 3.12에서 deprecated다. 절대 쓰지 말고 여기 utcnow()를 쓴다.
"""
from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    """저장용 표준 시각. tz-naive UTC, microsecond 절삭."""
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def to_naive_utc(dt: datetime | None) -> datetime | None:
    """클라이언트가 보낸 시각을 naive UTC로 정규화. '...Z'와 '+09:00' 모두 처리."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(microsecond=0)  # 이미 naive면 UTC로 간주
    return dt.astimezone(timezone.utc).replace(tzinfo=None, microsecond=0)


def to_utc_iso(dt: datetime) -> str:
    """출력용. 반드시 'Z'를 붙인다."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def seconds_between(start: datetime, end: datetime) -> int:
    """두 naive UTC 시각의 차이(초). 음수는 0으로 clamp한다.

    clamp하는 이유: 클라이언트가 보낸 시각이 섞여 들어와 미래를 가리키면
    seconds_without_progress가 음수가 되어 규칙이 조용히 뒤집힌다.
    """
    return max(0, int((end - start).total_seconds()))
