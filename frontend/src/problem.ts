export type TestCase = {
  id: number
  input: number[]
  expected: number
  hidden?: boolean
}

export const STARTER_CODE = `def sum_even(numbers):
    """리스트에서 짝수만 더해 반환해 보세요."""
    # 여기에 코드를 작성하세요.
    pass
`

export const TESTS: TestCase[] = [
  { id: 1, input: [1, 2, 3, 4], expected: 6 },
  { id: 2, input: [2, 2, 2], expected: 6 },
  { id: 3, input: [], expected: 0 },
  { id: 4, input: [-4, -1, 3, 8], expected: 4, hidden: true },
  { id: 5, input: [1, 3, 5, 7], expected: 0, hidden: true },
]
