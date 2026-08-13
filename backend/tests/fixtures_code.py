"""시나리오 테스트가 쓰는 코드 버전들.

V2~V4는 **같은 loop 영역만** 반복 수정한다 -- backend_plan §22 시나리오 2가
same_region_edit_count >= 2를 요구하기 때문.
"""

TEMPLATE = "def sum_list(arr):\n    # 여기에 코드를 작성하세요\n    pass"

# loop 영역을 반복 수정하는 버전들 (range의 경계만 바뀐다)
LOOP_V2 = (
    "def sum_list(arr):\n"
    "    total = 0\n"
    "    for i in range(len(arr) - 1):\n"
    "        total += arr[i]\n"
    "    return total"
)
LOOP_V3 = (
    "def sum_list(arr):\n"
    "    total = 0\n"
    "    for i in range(1, len(arr)):\n"
    "        total += arr[i]\n"
    "    return total"
)
LOOP_V4 = (
    "def sum_list(arr):\n"
    "    total = 0\n"
    "    for i in range(0, len(arr) - 1):\n"
    "        total += arr[i]\n"
    "    return total"
)
LOOP_V5_CORRECT = (
    "def sum_list(arr):\n"
    "    total = 0\n"
    "    for i in range(len(arr)):\n"
    "        total += arr[i]\n"
    "    return total"
)

# LOOP_V3에서 **return 줄만** 바뀐 버전.
# "서로 다른 영역을 편집하면 same_region_edit_count가 누적되지 않는다" 테스트용이므로
# 반드시 LOOP_V3에서 파생되어야 한다 (LOOP_V2에서 파생하면 for 줄도 함께 바뀐다).
RETURN_EDIT = (
    "def sum_list(arr):\n"
    "    total = 0\n"
    "    for i in range(1, len(arr)):\n"
    "        total += arr[i]\n"
    "    return total + 1"
)

# 편집 중이라 문법이 깨진 코드. diff 태거가 예외 없이 loop로 태깅해야 한다.
BROKEN_MID_EDIT = (
    "def sum_list(arr):\n"
    "    total = 0\n"
    "    for i in range(len(arr) -\n"
    "        total += arr[i]\n"
    "    return total"
)

# 대규모 재작성 (시나리오 C용). 위 버전들과 거의 모든 줄이 다르다.
BIG_REWRITE = (
    "def sum_list(arr):\n"
    "    result = 0\n"
    "    index = 0\n"
    "    while index < len(arr):\n"
    "        result = result + arr[index]\n"
    "        index = index + 1\n"
    "    return result"
)

# BIG_REWRITE에서 **한 줄만** 바뀐 버전.
# "대규모 변경 직후의 작은 변경"을 만들어야 하는 테스트용.
BIG_REWRITE_TWEAK = (
    "def sum_list(arr):\n"
    "    result = 0\n"
    "    index = 0\n"
    "    while index <= len(arr):\n"
    "        result = result + arr[index]\n"
    "        index = index + 1\n"
    "    return result"
)
