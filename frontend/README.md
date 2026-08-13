# CodeTrace Frontend

학생이 부담 없이 문제를 읽고 Python 코드를 실행·제출할 수 있는 Coding MVP입니다.

## 실행

```bash
npm install
npm run dev
```

## 구현 범위

- Monaco 기반 Python 에디터 (Undo/Redo 포함)
- Pyodide 기반 브라우저 Python 실행
- 공개 테스트를 확인하는 `실행`
- 공개/비공개 테스트를 모두 평가하는 `제출하기`
- stdout, Syntax Error, Runtime Error, 테스트 통과/실패 표시
- 기본 코드 초기화 및 반응형 레이아웃

현재 문제와 테스트 데이터는 `src/problem.ts`에 있습니다. 실제 서비스에서는 문제와 테스트를 API로 받아오고, 비공개 테스트는 보안을 위해 백엔드에서 실행해야 합니다.
## Problem list API

The problem list works with the repository's `judge/problems-index.json` by default.
To connect a backend, copy `.env.example` to `.env` and set `VITE_API_BASE_URL`.

The frontend requests:

```http
GET {VITE_API_BASE_URL}/problems
Accept: application/json
```

Both response shapes below are accepted:

```json
[
  {
    "problem_id": "func_sum_list",
    "title": "리스트 합 구하기",
    "concept": ["loop", "function"]
  }
]
```

```json
{ "problems": [/* same items */] }
```

Required fields are `problem_id` and `title`. `concept` is optional. If the API
is unavailable, the UI falls back to the local index so frontend development can
continue independently.
