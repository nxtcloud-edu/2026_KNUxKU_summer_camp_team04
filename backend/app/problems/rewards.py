"""KUICS 포인트 기반 문제 보상 정책."""

POINTS_BY_PROBLEM_ID: dict[str, int] = {
    "func_count_positive": 30, "func_find_max": 30, "func_sum_list": 30,
    "stdout_bigger_number": 30, "stdout_bit_is_on": 80,
    "stdout_classify_three_numbers": 50, "stdout_countdown": 30,
    "stdout_digitcount": 50, "stdout_discount_shop": 80,
    "stdout_divisorcount": 50, "stdout_evenoddstripe": 50,
    "stdout_flip_kth_bit": 50, "stdout_leap_year": 50,
    "stdout_multiplicationtable": 30, "stdout_odd_detector": 30,
    "stdout_perfectnumber": 50, "stdout_prefixthreshold": 30,
    "stdout_primecount": 50, "stdout_primelist": 50,
    "stdout_printevens": 30, "stdout_reverseinteger": 30,
    "stdout_skipmultiples": 30, "stdout_sort_three_numbers": 80,
    "stdout_sumton": 30, "stdout_sumuntilzero": 50,
    "stdout_threesixninecount": 80,
}


def points_for(problem_id: str) -> int:
    return POINTS_BY_PROBLEM_ID.get(problem_id, 30)


def acorns_for(problem_id: str) -> int:
    return max(1, round(points_for(problem_id) / 10))
