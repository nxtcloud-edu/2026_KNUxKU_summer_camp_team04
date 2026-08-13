"""DMOJ류 문제 패키지(problem.md + init.yml + N.in/N.out)를
judge/problems/*.json (check_type: stdout_match)으로 변환하는 스크립트.

사용법:
    python scripts/convert_dmoj_package.py <소스폴더1> [<소스폴더2> ...]

각 소스폴더 밑의 "problem.md와 init.yml을 가진 하위 폴더"를 전부 찾아 변환한다.
(폴더 구조 예: problem_set_8_flat/01_bigger_number/{problem.md, init.yml, 1.in, ...})

Public/Hidden 분류 규칙:
    problem.md의 "## 예제 입력 N" / "## 예제 출력 N" 코드펜스 내용과 실제
    .in/.out 파일 내용이 (공백 제외) 일치하면 public(예제로 이미 공개된 것),
    아니면 hidden으로 분류한다. 즉 "학생에게 이미 보여준 예제인가"를 내용
    비교로 판별한다 — 파일 번호 순서에 의존하지 않는다.
"""
import json
import re
import sys
from pathlib import Path

import yaml

PROBLEMS_DIR = Path(__file__).parent.parent / "problems"

EXAMPLE_HEADER_RE = re.compile(r"^##\s*예제\s*(입력|출력)\s*(\d+)\s*$")
TITLE_RE = re.compile(r"^#\s+(.+)$", re.M)


def extract_examples(md_text: str) -> dict:
    """'## 예제 입력 N' / '## 예제 출력 N' 헤더 뒤 코드펜스 내용을 추출.

    반환: {번호: {"입력": str, "출력": str}}
    """
    lines = md_text.splitlines()
    examples: dict = {}
    i = 0
    while i < len(lines):
        m = EXAMPLE_HEADER_RE.match(lines[i].strip())
        if not m:
            i += 1
            continue
        kind, num = m.group(1), int(m.group(2))

        j = i + 1
        while j < len(lines) and not lines[j].strip().startswith("```"):
            j += 1
        content_lines = []
        k = j + 1
        while k < len(lines) and not lines[k].strip().startswith("```"):
            content_lines.append(lines[k])
            k += 1
        examples.setdefault(num, {})[kind] = "\n".join(content_lines)
        i = k + 1
    return examples


def convert_one(problem_dir: Path) -> dict:
    md_text = (problem_dir / "problem.md").read_text(encoding="utf-8")
    cfg = yaml.safe_load((problem_dir / "init.yml").read_text(encoding="utf-8"))

    title_match = TITLE_RE.search(md_text)
    title = title_match.group(1).strip() if title_match else problem_dir.name

    examples = extract_examples(md_text)

    public_cases, hidden_cases = [], []
    for tc in cfg["test_cases"]:
        stem = Path(tc["in"]).stem
        stdin = (problem_dir / tc["in"]).read_text(encoding="utf-8")
        expected_stdout = (problem_dir / tc["out"]).read_text(encoding="utf-8")

        matched_num = next(
            (
                num for num, ex in examples.items()
                if ex.get("입력", "").strip() == stdin.strip()
                and ex.get("출력", "").strip() == expected_stdout.strip()
            ),
            None,
        )
        if matched_num is not None:
            case = {"stdin": stdin, "expected_stdout": expected_stdout, "category": f"sample_{matched_num}"}
            public_cases.append(case)
        else:
            case = {"stdin": stdin, "expected_stdout": expected_stdout, "category": f"case_{stem}"}
            hidden_cases.append(case)

    problem_id = "stdout_" + re.sub(r"^\d+_", "", problem_dir.name)
    data = {
        "problem_id": problem_id,
        "title": title,
        "concept": [],
        "check_type": "stdout_match",
        "code_template": "# 여기에 코드를 작성하세요\n# 입력은 input()으로 받고, 출력은 print()로 출력하세요\n",
    }
    # init.yml의 time_limit(초)/memory_limit(KB)이 있으면 그대로 옮겨 담는다.
    # (time_limit_sec은 "테스트케이스 1개당" 제한시간 — judge_service.py 참고)
    if "time_limit" in cfg:
        data["time_limit_sec"] = cfg["time_limit"]
    if "memory_limit" in cfg:
        data["memory_limit_mb"] = round(cfg["memory_limit"] / 1024)
    data["public_test_cases"] = public_cases
    data["hidden_test_cases"] = hidden_cases
    return data


def main(source_dirs: list) -> None:
    PROBLEMS_DIR.mkdir(exist_ok=True)
    for source_dir in source_dirs:
        source_path = Path(source_dir)
        for problem_dir in sorted(source_path.iterdir()):
            if not problem_dir.is_dir():
                continue
            if not (problem_dir / "problem.md").exists() or not (problem_dir / "init.yml").exists():
                continue

            data = convert_one(problem_dir)
            out_path = PROBLEMS_DIR / f"{data['problem_id']}.json"
            out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(
                f"{data['problem_id']:35s} public={len(data['public_test_cases'])} "
                f"hidden={len(data['hidden_test_cases'])} <- {problem_dir}"
            )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: python scripts/convert_dmoj_package.py <소스폴더1> [<소스폴더2> ...]")
        sys.exit(1)
    main(sys.argv[1:])
