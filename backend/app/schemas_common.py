"""응답 스키마 공용 타입."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import PlainSerializer

from app.clock import to_utc_iso

# 응답 스키마의 **모든** datetime 필드에 이 타입을 쓴다.
# 그냥 datetime을 쓰면 Pydantic이 'Z' 없이 직렬화하고 JS가 로컬 시간으로 파싱한다.
UtcDatetime = Annotated[datetime, PlainSerializer(to_utc_iso, return_type=str)]
