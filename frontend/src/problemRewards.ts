export type ProblemReward = { points: number; acorns: number }

// KUICS 문제 목록의 포인트를 10:1로 환산한다. 직접 대응 항목이 없는 함수형
// 연습 3개와 정수 뒤집기는 기초 문제 기본값(30p)을 쓴다.
const POINTS_BY_PROBLEM_ID: Record<string, number> = {
  func_count_positive: 30, func_find_max: 30, func_sum_list: 30,
  stdout_bigger_number: 30, stdout_bit_is_on: 80, stdout_classify_three_numbers: 50,
  stdout_countdown: 30, stdout_digitcount: 50, stdout_discount_shop: 80,
  stdout_divisorcount: 50, stdout_evenoddstripe: 50, stdout_flip_kth_bit: 50,
  stdout_leap_year: 50, stdout_multiplicationtable: 30, stdout_odd_detector: 30,
  stdout_perfectnumber: 50, stdout_prefixthreshold: 30, stdout_primecount: 50,
  stdout_primelist: 50, stdout_printevens: 30, stdout_reverseinteger: 30,
  stdout_skipmultiples: 30, stdout_sort_three_numbers: 80, stdout_sumton: 30,
  stdout_sumuntilzero: 50, stdout_threesixninecount: 80,
}

export function getProblemReward(problemId: string): ProblemReward {
  const points = POINTS_BY_PROBLEM_ID[problemId] ?? 30
  return { points, acorns: Math.max(1, Math.round(points / 10)) }
}

const LOCAL_REWARD_KEY = 'tutory:rewarded-problems'
const PROFILE_KEY = 'tutory:profile'

/** API 없는 로컬 학습 모드에서만 최초 풀이 보상을 반영한다. */
export function awardLocalProblemReward(problemId: string, acorns: number): number {
  let rewardedIds: string[] = []
  try { rewardedIds = JSON.parse(localStorage.getItem(LOCAL_REWARD_KEY) ?? '[]') as string[] } catch { rewardedIds = [] }
  const rewarded = new Set(rewardedIds)
  if (rewarded.has(problemId)) return 0

  let profile: Record<string, unknown> = {}
  try { profile = JSON.parse(localStorage.getItem(PROFILE_KEY) ?? '{}') as Record<string, unknown> } catch { profile = {} }
  const balance = typeof profile.acorns === 'number' ? profile.acorns : 135
  const total = typeof profile.totalAcorns === 'number' ? profile.totalAcorns : 260
  localStorage.setItem(PROFILE_KEY, JSON.stringify({ ...profile, acorns: balance + acorns, totalAcorns: total + acorns }))
  rewarded.add(problemId)
  localStorage.setItem(LOCAL_REWARD_KEY, JSON.stringify([...rewarded]))
  return acorns
}
