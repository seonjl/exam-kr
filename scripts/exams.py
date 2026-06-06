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
    "c1": {
        "name": "컴퓨터활용능력 1급",
        "hack": 0,
        "parts": {"part1": 20, "part2": 20, "part3": 20,
                  "part4": "false", "part5": "false", "part6": "false", "part7": "false"},
        "subjects": [
            "컴퓨터 일반",
            "스프레드시트 일반",
            "데이터베이스 일반",
        ],
    },
    "sa": {
        "name": "산업안전기사",
        "hack": 0,
        "dbname": "ku",
        "parts": {"part1": 20, "part2": 20, "part3": 20, "part4": 20, "part5": 20,
                  "part6": 20, "part7": "false"},
        "subjects": [
            "안전관리론",
            "인간공학 및 시스템안전공학",
            "기계위험방지기술",
            "전기위험방지기술",
            "화학설비위험방지기술",
            "건설안전기술",
        ],
    },
    "kt": {
        "name": "전기기사",
        "hack": 0,
        "parts": {"part1": 20, "part2": 20, "part3": 20, "part4": 20, "part5": 20,
                  "part6": "false", "part7": "false"},
        "subjects": [
            "전기자기학",
            "전력공학",
            "전기기기",
            "회로이론 및 제어공학",
            "전기설비기술기준 및 판단기준",
        ],
    },
    "nd": {
        "name": "소방설비기사(기계분야)",
        "hack": 0,
        "parts": {"part1": 20, "part2": 20, "part3": 20, "part4": 20,
                  "part5": "false", "part6": "false", "part7": "false"},
        "subjects": [
            "소방원론",
            "소방유체역학",
            "소방관계법규",
            "소방기계시설의 구조 및 원리",
        ],
    },
    "k1": {
        "name": "한국사능력검정시험 심화",
        "hack": 0,
        "parts": {"part1": 50,
                  "part2": "false", "part3": "false", "part4": "false",
                  "part5": "false", "part6": "false", "part7": "false"},
        "subjects": [
            "한국사",
        ],
    },
    # cbtbank.kr 출처 (fetch_cbtbank.py 로 수집). parts/hack 은 comcbt fetch.py 전용이라 미포함.
    "sw": {
        "name": "사회복지사 1급",
        "source": "cbtbank",
        "subjects": [
            "인간행동과사회환경",
            "사회복지조사론",
            "사회복지실천론",
            "사회복지실천기술론",
            "지역사회복지론",
            "사회복지정책론",
            "사회복지행정론",
            "사회복지법제론",
        ],
    },
    "jc": {
        "name": "직업상담사 2급",
        "source": "cbtbank",
        "subjects": ["직업상담학", "직업심리학", "직업정보론", "노동시장론", "노동관계법규"],
    },
    "j1": {
        "name": "주택관리사보 1차",
        "source": "cbtbank",
        "subjects": ["회계원리", "공동주택시설개론", "민법"],
    },
    "j2": {
        "name": "주택관리사보 2차",
        "source": "cbtbank",
        "subjects": ["주택관리관계법규", "공동주택관리실무",
                     "주택관리관계법규(주관식)", "공동주택관리실무(주관식)"],
    },
}
