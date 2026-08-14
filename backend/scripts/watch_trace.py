"""데모용 trace 실시간 뷰어. `codetrace.db`를 **읽기 전용으로 tail** 한다.

발표 중에 "지금 무슨 일이 벌어지고 있는지"를 한 터미널에서 보여주기 위한 도구다.
학생이 코드를 고치고 실행하는 것부터, Monitor가 개입 시점이라고 판단하는 순간,
그리고 튜터가 실제로 뭐라고 말했는지까지 **하나의 스트림**으로 흐른다.

    python scripts/watch_trace.py                 # 모든 세션을 지금부터 따라간다
    python scripts/watch_trace.py --replay 30     # 최근 30개를 먼저 보여주고 이어서 따라간다
    python scripts/watch_trace.py --session f222  # 세션 id 접두어로 필터
    python scripts/watch_trace.py --only AGENT    # agent 관련 이벤트만
    python scripts/watch_trace.py --verbose       # features/payload 원본까지 전부

왜 API가 아니라 DB를 직접 읽는가
--------------------------------
`GET /sessions/{id}/events`는 인증(`get_current_user`)과 소유권 검사를 통과해야
하고, 세션 하나로 범위가 고정된다. 발표용 뷰어는 (a) 로그인 없이 즉시 떠야 하고
(b) 어떤 세션이 시작되든 자동으로 주워야 하므로, 읽기 전용 SQLite 연결이 훨씬
단순하다. **쓰기는 절대 하지 않는다** -- `mode=ro`로 연다.

`AGENT_TRIGGER`(Monitor의 규칙 판단)와 `AGENT_INTERVENTION`(LLM 파이프라인의
최종 산출물)이 이미 payload에 근거/이유/메시지를 통째로 담고 있어
(`app/trace/service.py`), 뷰어는 그걸 읽기 좋게 펴놓기만 하면 된다.

**LLM 파이프라인 내부**(state -> guided_action -> tutor_message 각 단계에서 무슨
판단을 했는지, 어떤 모델이 몇 초 걸렸는지)는 DB에 남지 않는다. 그건 agent
프로세스의 stdout에 찍히므로 터미널을 하나 더 띄워서 나란히 보면 된다:

    cd agent && uvicorn tutor_agent.service:app --port 8100
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

#: backend/scripts/watch_trace.py -> backend/codetrace.db
DEFAULT_DB = Path(__file__).resolve().parent.parent / "codetrace.db"

POLL_INTERVAL_SECONDS = 0.5


# --------------------------------------------------------------------- 색상

class C:
    """ANSI 색상. `--no-color`나 파이프 출력이면 전부 빈 문자열로 바뀐다."""

    RESET = "\033[0m"
    DIM = "\033[2m"
    BOLD = "\033[1m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    GRAY = "\033[90m"
    BG_MAGENTA = "\033[45m\033[97m"

    @classmethod
    def disable(cls) -> None:
        for name in dir(cls):
            if name.isupper():
                setattr(cls, name, "")


# --------------------------------------------------------------------- 폭 계산

def _width(text: str) -> int:
    """한글/이모지를 2칸으로 세는 표시 폭.

    `len()`으로 정렬하면 한글이 섞인 순간 컬럼이 어긋난다 -- 발표 화면에서
    제일 먼저 눈에 띄는 종류의 지저분함이라 여기서만큼은 제대로 센다.
    """
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _width(text))


def _wrap(text: str, width: int) -> list[str]:
    """표시 폭 기준 줄바꿈. 공백이 없는 한글 문장도 잘라야 하므로 문자 단위로 센다."""
    lines: list[str] = []
    current = ""
    current_width = 0
    for word in text.split(" "):
        w = _width(word)
        if current and current_width + 1 + w > width:
            lines.append(current)
            current, current_width = "", 0
        if w > width:  # 단어 하나가 폭보다 길다 (긴 한글 문장 등) -> 문자 단위로 쪼갠다
            if current:
                lines.append(current)
                current, current_width = "", 0
            for ch in word:
                cw = _width(ch)
                if current_width + cw > width:
                    lines.append(current)
                    current, current_width = "", 0
                current += ch
                current_width += cw
            continue
        if current:
            current += " "
            current_width += 1
        current += word
        current_width += w
    if current:
        lines.append(current)
    return lines or [""]


def _term_width() -> int:
    return max(60, shutil.get_terminal_size((120, 30)).columns)


# --------------------------------------------------------------------- DB

def open_db(path: Path) -> sqlite3.Connection:
    """읽기 전용으로 연다.

    WAL 모드 DB를 `mode=ro`로 열면, 복구가 필요한 상태(백엔드가 죽어 있고 -wal이
    남아 있는 경우)에서 "attempt to write a readonly database"가 날 수 있다.
    그때만 일반 연결로 물러난다 -- 이 스크립트는 어느 경로로도 INSERT/UPDATE를
    하지 않으므로 안전하다.
    """
    if not path.exists():
        sys.exit(f"DB를 찾을 수 없습니다: {path}\n(backend를 한 번 실행해 DB를 만들어 주세요)")

    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
        conn.execute("select 1 from events limit 1")
    except sqlite3.OperationalError:
        conn = sqlite3.connect(str(path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def _payload(row: sqlite3.Row) -> dict[str, Any]:
    raw = row["payload"]
    if not raw:
        return {}
    try:
        return json.loads(raw) if isinstance(raw, (str, bytes)) else dict(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}


def fetch_events(conn: sqlite3.Connection, after_rowid: int, limit: int = 200) -> list[sqlite3.Row]:
    """rowid 순서로 새 이벤트를 읽는다.

    `seq`가 아니라 `rowid`를 커서로 쓰는 이유: seq는 세션 안에서만 단조 증가라
    여러 세션을 동시에 따라갈 때 전역 순서가 되지 못한다. rowid는 삽입 순서다.
    """
    return list(
        conn.execute(
            "select rowid as rid, * from events where rowid > ? order by rowid limit ?",
            (after_rowid, limit),
        )
    )


def last_rowid(conn: sqlite3.Connection) -> int:
    row = conn.execute("select coalesce(max(rowid), 0) from events").fetchone()
    return int(row[0])


def rowid_before_last(conn: sqlite3.Connection, n: int) -> int:
    """최근 n개를 재생하기 위한 시작 커서."""
    row = conn.execute(
        "select rowid from events order by rowid desc limit 1 offset ?", (n - 1,)
    ).fetchone()
    return int(row[0]) - 1 if row else 0


def session_info(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        select s.id, s.problem_id, s.status, s.started_at,
               u.nickname, u.name, u.email
          from sessions s left join users u on u.id = s.user_id
         where s.id = ?
        """,
        (session_id,),
    ).fetchone()
    return dict(row) if row else {}


def snapshot_info(conn: sqlite3.Connection, session_id: str, version: int | None) -> dict[str, Any]:
    if version is None:
        return {}
    row = conn.execute(
        """
        select added_line_count, deleted_line_count, change_size, seconds_since_parent
          from code_snapshots where session_id = ? and version = ?
        """,
        (session_id, version),
    ).fetchone()
    return dict(row) if row else {}


# --------------------------------------------------------------------- 렌더링

#: 이벤트 타입 -> (아이콘, 색). 아이콘은 폭 2를 차지하는 문자만 쓴다.
STYLE: dict[str, tuple[str, str]] = {
    "SESSION_START": ("🟢", C.GREEN),
    "SESSION_END": ("⬛", C.GRAY),
    "CODE_SNAPSHOT": ("✏️ ", C.GRAY),
    "RUN": ("▶️ ", C.BLUE),
    "SUBMIT": ("📤", C.BLUE),
    "TEST_RESULT": ("🎯", C.YELLOW),
    "UNDO": ("↩️ ", C.GRAY),
    "RESET": ("🔄", C.GRAY),
    "HINT_REQUEST": ("🙋", C.CYAN),
    "ACTIVITY_OPENED": ("📂", C.CYAN),
    "ACTIVITY_RESPONSE": ("💬", C.CYAN),
    "AGENT_TRIGGER": ("⚡", C.YELLOW),
    "AGENT_INTERVENTION": ("🤖", C.MAGENTA),
}

#: TEST_RESULT status -> 색. 학생 코드 실패(빨강)와 오답(노랑)을 구분한다.
JUDGE_COLOR = {
    "ACCEPTED": C.GREEN,
    "WRONG_ANSWER": C.YELLOW,
    "SYNTAX_ERROR": C.RED,
    "RUNTIME_ERROR": C.RED,
    "TIME_LIMIT": C.RED,
    "INTERNAL_ERROR": C.BG_MAGENTA,
}

#: 시각(8) + seq(5) + 아이콘/타입(21) 만큼 들여쓴 상세 줄의 왼쪽 여백.
DETAIL_INDENT = " " * 36


def _local_time(raw: str | None) -> str:
    """저장은 naive UTC (`app/clock.py`). 발표 화면에는 로컬 시각으로 보여준다."""
    if not raw:
        return "--:--:--"
    try:
        dt = datetime.fromisoformat(str(raw)).replace(tzinfo=timezone.utc)
    except ValueError:
        return str(raw)[:8]
    return dt.astimezone().strftime("%H:%M:%S")


def _detail(text: str, *, color: str = "", bullet: str = "└") -> str:
    """상세 한 항목을 들여쓴 여러 줄로 만든다.

    튜터 메시지에는 코드 블록(```)이 통째로 들어오는 일이 흔해서 원본 줄바꿈을
    먼저 살린 뒤 각 줄을 폭에 맞춰 접는다. 이걸 안 하면 개행이 그대로 흘러
    들여쓰기가 무너진다.
    """
    width = _term_width() - len(DETAIL_INDENT) - 2
    lines: list[str] = []
    for raw_line in str(text).splitlines() or [""]:
        lines.extend(_wrap(raw_line, width))

    out = [f"{DETAIL_INDENT}{C.GRAY}{bullet}{C.RESET} {color}{lines[0]}{C.RESET}"]
    out += [f"{DETAIL_INDENT}  {color}{line}{C.RESET}" for line in lines[1:]]
    return "\n".join(out)


def render_session_banner(info: dict[str, Any], session_id: str) -> str:
    who = info.get("nickname") or info.get("name") or info.get("email") or "?"
    problem = info.get("problem_id", "?")
    status = info.get("status", "?")
    line = (
        f"{C.BOLD}{C.CYAN}▸ session {session_id[:13]}…{C.RESET}"
        f"  {C.DIM}학생{C.RESET} {who}"
        f"  {C.DIM}문제{C.RESET} {problem}"
        f"  {C.DIM}상태{C.RESET} {status}"
    )
    rule = f"{C.GRAY}{'─' * min(_term_width(), 100)}{C.RESET}"
    return f"\n{rule}\n {line}\n{rule}"


def render_event(conn: sqlite3.Connection, row: sqlite3.Row, *, verbose: bool) -> str:
    etype = str(row["type"])
    payload = _payload(row)
    icon, color = STYLE.get(etype, ("  ", C.RESET))

    head = (
        f"{C.GRAY}{_local_time(row['server_timestamp'])}{C.RESET} "
        f"{C.GRAY}#{str(row['seq']):<4}{C.RESET}"
        f"{icon} {color}{_pad(etype, 19)}{C.RESET}"
    )

    lines: list[str] = []
    summary, details = _describe(conn, row, etype, payload)
    lines.append(head + summary)
    lines.extend(details)

    if verbose and payload:
        dump = json.dumps(payload, ensure_ascii=False, indent=2)
        for line in dump.splitlines():
            lines.append(f"{DETAIL_INDENT}{C.GRAY}{line}{C.RESET}")

    return "\n".join(lines)


def _describe(
    conn: sqlite3.Connection, row: sqlite3.Row, etype: str, p: dict[str, Any]
) -> tuple[str, list[str]]:
    """이벤트 한 건을 (한 줄 요약, 상세 줄들)로 편다."""
    details: list[str] = []

    if etype == "CODE_SNAPSHOT":
        snap = snapshot_info(conn, str(row["session_id"]), row["code_version"])
        added, deleted = snap.get("added_line_count", 0), snap.get("deleted_line_count", 0)
        churn = f"{C.GREEN}+{added}{C.RESET}/{C.RED}-{deleted}{C.RESET}" if snap else ""
        region = p.get("primary_region", "")
        summary = (
            f"v{row['code_version']}  {churn}  {C.DIM}{region}  "
            f"{p.get('line_count', '?')}줄{C.RESET}"
        )
        if p.get("deduplicated"):
            summary += f"  {C.GRAY}(동일 코드){C.RESET}"
        if p.get("summary"):
            details.append(_detail(str(p["summary"]), color=C.DIM))
        return summary, details

    if etype == "TEST_RESULT":
        status = str(p.get("status", "?"))
        c = JUDGE_COLOR.get(status, C.RESET)
        meta = [str(p.get("mode", "")), str(p.get("judge", ""))]
        if p.get("runtime_ms"):
            meta.append(f"{p['runtime_ms']}ms")
        summary = (
            f"{c}{C.BOLD}{status}{C.RESET}  {p.get('passed', 0)}/{p.get('total', 0)}"
            f"  {C.DIM}{' · '.join(x for x in meta if x)}{C.RESET}"
        )
        if p.get("message"):
            details.append(_detail(str(p["message"]).strip().splitlines()[-1], color=c))
        return summary, details

    if etype == "AGENT_TRIGGER":
        summary = (
            f"{C.BOLD}{C.YELLOW}{p.get('trigger', '?')}{C.RESET}"
            f"  {C.DIM}→ status={p.get('status', '?')}{C.RESET}"
        )
        if p.get("reason"):
            details.append(_detail(str(p["reason"]), color=C.YELLOW))
        for ev in p.get("evidence") or []:
            details.append(_detail(str(ev), color=C.DIM, bullet="·"))
        return summary, details

    if etype == "AGENT_INTERVENTION":
        activity = p.get("activity") or {}
        action = str(p.get("action", "?"))
        meta = [f"state={p.get('state', '?')}"]
        if p.get("concept"):
            meta.append(f"concept={p['concept']}")
        if p.get("trigger"):
            meta.append(f"trigger={p['trigger']}")
        summary = (
            f"{C.BOLD}{C.MAGENTA}{action}{C.RESET}  {C.DIM}{'  '.join(meta)}{C.RESET}"
        )
        # 학생이 먼저 말을 건 경우(=/agent/respond 경로)는 그 말부터 보여준다.
        if activity.get("student_answer"):
            details.append(
                _detail(f"학생: {activity['student_answer']}", color=C.CYAN, bullet="🙋")
            )
        if p.get("reason"):
            details.append(_detail(str(p["reason"]), color=C.DIM))
        if activity.get("message"):
            details.append(_detail(str(activity["message"]), color=C.MAGENTA, bullet="💬"))
        # 내부 판단. 학생 화면에는 안 가지만 발표에서는 이게 핵심이다.
        judged = [
            f"{k}={activity[k]}"
            for k in ("understanding", "is_correct", "follow_up_needed", "next_focus")
            if activity.get(k) not in (None, "", [])
        ]
        if judged:
            details.append(_detail("  ".join(judged), color=C.GRAY, bullet="·"))
        for m in activity.get("misconceptions") or []:
            details.append(_detail(f"오개념: {m}", color=C.RED, bullet="·"))
        if activity.get("expects_reply"):
            details.append(_detail("학생 답변 대기 중", color=C.GRAY, bullet="·"))
        return summary, details

    if etype == "SESSION_START":
        return f"{C.DIM}{p.get('problem_id', '')}{C.RESET}", details

    if etype in ("RUN", "SUBMIT"):
        return f"{C.DIM}{p.get('mode', '')}{C.RESET}", details

    if etype == "ACTIVITY_RESPONSE":
        if p.get("answer"):
            details.append(_detail(str(p["answer"]), color=C.CYAN))
        return "", details

    # 남은 타입은 payload를 짧게 한 줄로.
    if p:
        compact = json.dumps(p, ensure_ascii=False)
        return f"{C.DIM}{compact[:100]}{C.RESET}", details
    return "", details


# --------------------------------------------------------------------- 메인 루프

def _matches(row: sqlite3.Row, session_filter: str | None, only: list[str] | None) -> bool:
    """세션/타입 필터. 둘 다 **부분 일치**다 -- 발표 중에 전체 id를 타이핑할 수는 없다.

    `--session f222`는 `sess_f222518a...`에 걸리고, `--only AGENT`는
    `AGENT_TRIGGER`와 `AGENT_INTERVENTION` 둘 다에 걸린다.
    """
    if session_filter and session_filter not in str(row["session_id"]):
        return False
    if only and not any(str(row["type"]).startswith(prefix) for prefix in only):
        return False
    return True


def watch(args: argparse.Namespace) -> None:
    conn = open_db(args.db)
    only = [t.strip().upper() for t in args.only.split(",")] if args.only else None

    cursor = rowid_before_last(conn, args.replay) if args.replay else last_rowid(conn)
    current_session: str | None = None

    print(f"{C.BOLD}CodeTrace 실시간 뷰어{C.RESET}  {C.GRAY}{args.db}{C.RESET}")
    filters = []
    if args.session:
        filters.append(f"session~{args.session}")
    if only:
        filters.append(f"type~{','.join(only)}")
    print(
        f"{C.GRAY}{'  '.join(filters) if filters else '전체 세션'}"
        f"  ·  {'최근 ' + str(args.replay) + '건 재생 후 ' if args.replay else ''}"
        f"실시간 추적 중 (Ctrl+C 종료){C.RESET}"
    )

    try:
        while True:
            rows = fetch_events(conn, cursor)
            for row in rows:
                cursor = int(row["rid"])
                if not _matches(row, args.session, only):
                    continue
                session_id = str(row["session_id"])
                if session_id != current_session:
                    print(render_session_banner(session_info(conn, session_id), session_id))
                    current_session = session_id
                print(render_event(conn, row, verbose=args.verbose))
                sys.stdout.flush()

            if not args.follow and not rows:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print(f"\n{C.GRAY}종료했습니다.{C.RESET}")
    finally:
        conn.close()


def main(argv: Iterable[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="codetrace.db를 읽기 전용으로 tail 하는 발표용 trace 뷰어",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"기본값: {DEFAULT_DB}")
    parser.add_argument("--session", help="세션 id 또는 그 일부 (예: f222)")
    parser.add_argument(
        "--only",
        help="이 접두어로 시작하는 이벤트 타입만 (쉼표 구분). 예: --only AGENT",
    )
    parser.add_argument(
        "--replay", type=int, default=0, metavar="N", help="시작할 때 최근 N건을 먼저 보여준다"
    )
    parser.add_argument(
        "--interval", type=float, default=POLL_INTERVAL_SECONDS, help="폴링 간격(초)"
    )
    parser.add_argument("--verbose", action="store_true", help="payload 원본까지 전부 출력")
    parser.add_argument(
        "--no-follow", dest="follow", action="store_false", help="현재까지만 출력하고 종료"
    )
    parser.add_argument("--no-color", dest="color", action="store_false", help="ANSI 색상 끄기")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if not args.color or not sys.stdout.isatty() or os.getenv("NO_COLOR"):
        C.disable()
        # 색을 끄면 STYLE 안에 캡처된 색 문자열도 같이 비워야 한다.
        for key, (icon, _) in STYLE.items():
            STYLE[key] = (icon, "")
        for key in JUDGE_COLOR:
            JUDGE_COLOR[key] = ""

    watch(args)


if __name__ == "__main__":
    main()
