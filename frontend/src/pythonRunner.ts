import { loadPyodide, type PyodideInterface } from 'pyodide'
import type { ProblemDetail, PublicTestCase } from './problemService'

export type TestResult = PublicTestCase & {
  passed: boolean
  actual?: unknown
  error?: string
}

export type ExecutionResult = {
  stdout: string
  tests: TestResult[]
  error?: { type: 'syntax' | 'runtime'; message: string }
  duration: number
}

export type TraceStep = {
  iteration: number
  line: number
  locals: Record<string, string | number | boolean | null>
}

let runtimePromise: Promise<PyodideInterface> | null = null

export function preparePython() {
  if (!runtimePromise) {
    runtimePromise = loadPyodide({
      indexURL: 'https://cdn.jsdelivr.net/pyodide/v0.27.2/full/',
    })
  }
  return runtimePromise
}

export async function runPython(code: string, problem: ProblemDetail): Promise<ExecutionResult> {
  return problem.check_type === 'stdout_match'
    ? runStdoutProblem(code, problem.public_test_cases)
    : runFunctionProblem(code, problem.function_name, problem.public_test_cases)
}

async function runFunctionProblem(code: string, functionName: string | undefined, tests: PublicTestCase[]): Promise<ExecutionResult> {
  const startedAt = performance.now()
  const stdout: string[] = []
  const pyodide = await preparePython()
  pyodide.setStdout({ batched: (message) => stdout.push(message) })
  pyodide.setStderr({ batched: (message) => stdout.push(message) })

  if (!functionName) {
    return {
      stdout: '',
      tests: [],
      error: { type: 'runtime', message: '문제의 function_name이 없습니다.' },
      duration: performance.now() - startedAt,
    }
  }

  const serialized = JSON.stringify(tests)
  const script = `${code}\n\n${String.raw`
import json

__codetrace_cases = json.loads(r'''${serialized}''')
__codetrace_results = []
__codetrace_fn = globals().get('${functionName}')

if not callable(__codetrace_fn):
    raise NameError('함수 ${functionName}를 찾을 수 없습니다.')

for __case in __codetrace_cases:
    try:
        __args = __case.get("input", [])
        if not isinstance(__args, list):
            __args = [__args]
        __actual = __codetrace_fn(*__args)
        __codetrace_results.append({
            **__case,
            "passed": __actual == __case.get("expected"),
            "actual": __actual,
        })
    except Exception as __error:
        __codetrace_results.append({
            **__case,
            "passed": False,
            "error": f"{type(__error).__name__}: {__error}",
        })

json.dumps(__codetrace_results, ensure_ascii=False)
`}`

  try {
    const value = await pyodide.runPythonAsync(script)
    const testResults = JSON.parse(String(value)) as TestResult[]
    return {
      stdout: stdout.join('\n'),
      tests: testResults,
      duration: performance.now() - startedAt,
    }
  } catch (caught) {
    return pythonErrorResult(caught, stdout, startedAt)
  }
}

async function runStdoutProblem(code: string, tests: PublicTestCase[]): Promise<ExecutionResult> {
  const startedAt = performance.now()
  const stdout: string[] = []
  const pyodide = await preparePython()
  pyodide.setStdout({ batched: (message) => stdout.push(message) })
  pyodide.setStderr({ batched: (message) => stdout.push(message) })

  const serializedCode = JSON.stringify(code)
  const serializedTests = JSON.stringify(tests)
  const script = `
import contextlib
import io
import json
import sys

__codetrace_code = ${serializedCode}
__codetrace_cases = json.loads(r'''${serializedTests}''')
__codetrace_results = []

for __case in __codetrace_cases:
    __stdin = io.StringIO(__case.get("stdin", ""))
    __stdout = io.StringIO()
    __old_stdin = sys.stdin
    try:
        sys.stdin = __stdin
        with contextlib.redirect_stdout(__stdout):
            exec(compile(__codetrace_code, "<solution>", "exec"), {})
        __actual = __stdout.getvalue()
        __expected = __case.get("expected_stdout", "")
        __codetrace_results.append({
            **__case,
            "passed": __actual.strip() == str(__expected).strip(),
            "actual": __actual,
        })
    except Exception as __error:
        __codetrace_results.append({
            **__case,
            "passed": False,
            "error": f"{type(__error).__name__}: {__error}",
        })
    finally:
        sys.stdin = __old_stdin

json.dumps(__codetrace_results, ensure_ascii=False)
`

  try {
    const value = await pyodide.runPythonAsync(script)
    const testResults = JSON.parse(String(value)) as TestResult[]
    return {
      stdout: stdout.join('\n'),
      tests: testResults,
      duration: performance.now() - startedAt,
    }
  } catch (caught) {
    return pythonErrorResult(caught, stdout, startedAt)
  }
}

export async function runTrace(code: string): Promise<TraceStep[]> {
  const pyodide = await preparePython()
  const serializedCode = JSON.stringify(code)
  const script = `
import json

__trace_steps = []
__trace_iteration = 0

def __trace(frame, event, arg):
    global __trace_iteration
    if frame.f_code.co_filename != "<trace-activity>" or event != "line":
        return __trace
    # The loop header is reached again after the body has updated total.
    if frame.f_lineno == 3 and "i" in frame.f_locals:
        __trace_iteration += 1
        __trace_steps.append({
            "iteration": __trace_iteration,
            "line": 4,
            "locals": {
                "i": frame.f_locals.get("i"),
                "total": frame.f_locals.get("total"),
            },
        })
    return __trace

import sys
sys.settrace(__trace)
try:
    exec(compile(${serializedCode}, "<trace-activity>", "exec"), {})
finally:
    sys.settrace(None)

json.dumps(__trace_steps)
`
  const value = await pyodide.runPythonAsync(script)
  return JSON.parse(String(value)) as TraceStep[]
}

function pythonErrorResult(caught: unknown, stdout: string[], startedAt: number): ExecutionResult {
  const message = caught instanceof Error ? caught.message : String(caught)
  return {
    stdout: stdout.join('\n'),
    tests: [],
    error: {
      type: /SyntaxError|IndentationError|TabError/.test(message) ? 'syntax' : 'runtime',
      message: cleanPythonError(message),
    },
    duration: performance.now() - startedAt,
  }
}

function cleanPythonError(message: string) {
  const lines = message.split('\n')
  const tracebackIndex = lines.findIndex((line) => line.includes('Traceback'))
  return (tracebackIndex >= 0 ? lines.slice(tracebackIndex) : lines).join('\n').trim()
}
