"""자격증별 설정 테이블.

fetch.py가 이 테이블을 참조하여 범용으로 동작한다.
새 자격증을 추가하려면 아래 EXAMS에 한 항목을 추가하기만 하면 된다.
"""

EXAMS = {
    "s2": {
        "name": "사회조사분석사 2급",
        "hack": 29,
        "parts": {"part1": 30, "part2": 30, "part3": 40,
                  "part4": "false", "part5": "false", "part6": "false", "part7": "false"},
        "subjects": [
            "조사방법론 I",
            "조사방법론 II",
            "사회통계",
        ],
    },
    "g1": {
        "name": "공인중개사 1차",
        "hack": 0,
        "parts": {"part1": 40, "part2": 40,
                  "part3": "false", "part4": "false", "part5": "false", "part6": "false", "part7": "false"},
        "subjects": [
            "부동산학개론",
            "민법 및 민사특별법",
        ],
    },
    "g2": {
        "name": "공인중개사 2차",
        "hack": 0,
        "parts": {"part1": 40, "part2": 40, "part3": 40,
                  "part4": "false", "part5": "false", "part6": "false", "part7": "false"},
        "subjects": [
            "공인중개사법령 및 실무",
            "부동산공법",
            "부동산공시법 및 세법",
        ],
    },
    "iz": {
        "name": "정보처리기사",
        "hack": 0,
        "parts": {"part1": 20, "part2": 20, "part3": 20, "part4": 20, "part5": 20,
                  "part6": "false", "part7": "false"},
        "subjects": [
            "소프트웨어 설계",
            "소프트웨어 개발",
            "데이터베이스 구축",
            "프로그래밍 언어 활용",
            "정보시스템 구축관리",
        ],
    },
}
