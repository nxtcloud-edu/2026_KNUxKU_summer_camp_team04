import { loadPyodide, type PyodideInterface } from 'pyodide'
import type { TestCase } from './problem'

export type TestResult = TestCase & {
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

export async function runPython(code: string, tests: TestCase[]): Promise<ExecutionResult> {
  const startedAt = performance.now()
  const stdout: string[] = []
  const pyodide = await preparePython()
  pyodide.setStdout({ batched: (message) => stdout.push(message) })
  pyodide.setStderr({ batched: (message) => stdout.push(message) })

  const serialized = JSON.stringify(tests)
  const script = `${code}\n\n${String.raw`
import json

__codetrace_cases = json.loads(r'''${serialized}''')
__codetrace_results = []

for __case in __codetrace_cases:
    try:
        __actual = sum_even(__case["input"])
        __codetrace_results.append({
            **__case,
            "passed": __actual == __case["expected"],
            "actual": __actual,
        })
    except Exception as __error:
        __codetrace_results.append({
            **__case,
            "passed": False,
            "error": f"{type(__error).__name__}: {__error}",
        })

json.dumps(__codetrace_results)
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

function cleanPythonError(message: string) {
  const lines = message.split('\n')
  const tracebackIndex = lines.findIndex((line) => line.includes('Traceback'))
  return (tracebackIndex >= 0 ? lines.slice(tracebackIndex) : lines).join('\n').trim()
}
