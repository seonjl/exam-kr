"""감사 결과로 검증된 데이터 정정을 자격증 JSON 에 적용.

비파괴: 원본 값을 보존하고 정정 메타데이터를 함께 저장.

산출:
  data/audit/corrections.log.json — 적용된 정정 로그
"""
from __future__ import annotations
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "audit"
NOW = datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_q(exam: str, file_label: str, number: int) -> tuple[Path, dict, dict, int]:
    p = DATA / exam / f"{file_label}.json"
    doc = json.loads(p.read_text("utf-8"))
    for i, q in enumerate(doc["questions"]):
        if q["number"] == number:
            return p, doc, q, i
    raise ValueError(f"not found: {exam}/{file_label}#{number}")


def save(p: Path, doc: dict) -> None:
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), "utf-8")


def call_claude(prompt: str, *, timeout: int = 240) -> str:
    r = subprocess.run(
        ["claude", "-p", prompt], capture_output=True, text=True, timeout=timeout
    )
    if r.returncode != 0:
        raise RuntimeError(f"claude failed: {r.stderr.strip()}")
    out = r.stdout.strip()
    if not out:
        raise RuntimeError("claude returned empty output")
    return out


# ---- P1.1: answer 필드 정정 ----
ANSWER_FIXES = [
    # (exam, file_label, number, from_, to_, reason)
    # --- B1 1차 (학술적 명확) ---
    ("s2", "s2_20000920", 84, 2, 4,
     "주사위 1~6 기댓값 21/6=3.5 → 선택지 (4)"),
    ("s2", "s2_20020310", 82, 1, 2,
     "p<α 일 때 귀무가설 기각이 통계학 표준 (보기 ②)"),
    ("s2", "s2_20070805", 65, 2, 4,
     "실험설계 3원리는 임의화/반복/블록화. 평균화는 원리 아님 → ④"),
    ("s2", "s2_20070805", 68, 4, 3,
     "신뢰수준 95% ≠ 표본오차 ±5% (전형적 오개념). 보기 ③이 틀린 설명"),
    # --- P4/P4-ext 2단계 합의 (conf>=0.9 + 학술 명확) ---
    ("s2", "s2_20030316", 61, 3, 1,
     "정규분포 양쪽 꼬리는 점근적으로 0에 접근. '급격하게 내려간다'가 사실관계 오류"),
    ("s2", "s2_20000920", 68, 1, 3,
     "유한 모집단 표본조사에서 표본 단위가 중복 추출되지 않는 비복원추출이 일반적"),
    ("s2", "s2_20110821", 59, 4, 3,
     "서울 휴대폰 가입자 명부는 A병원 환자 모집단보다 훨씬 큰 집합 — 표집틀이 모집단보다 큼"),
    ("s2", "s2_20040808", 7, 2, 1,
     "여론주도층의 심층의견 청취에는 대면 면접조사가 가장 적합 (응답 깊이·심층성)"),
    ("g2", "g2_20050522", 16, 1, 4,
     "분사무소 이전은 이전한 날부터 10일 이내 이전지 시장·군수·구청장에게 신고"),
    # --- g2 deep B1 검증 (판례 기반/분류 오류만) ---
    ("g2", "g2_20050522", 32, 3, 1,
     "시효취득 분묘기지권도 판례상 지료 지급 의무 있음 (대판 2017다228007 전합, 2021.4.22)"),
    ("g2", "g2_20071028", 15, 3, 1,
     "신고 대상은 공인중개사법이 아닌 부동산거래신고법의 규정 (법령 분류 오류)"),
    # --- s2 deep B1 검증 (학술적으로 명확) ---
    ("s2", "s2_20000920", 91, 1, 4,
     "범위(range)는 최댓값-최솟값으로 산포도 측정치, 대표값 아님 (기하평균/중앙값/최빈수는 대표값)"),
    ("s2", "s2_20130602", 36, 2, 1,
     "보가더스 척도는 집단 간 사회적 거리(social distance)의 강도를 측정하는 척도"),
    ("s2", "s2_20010923", 69, 4, 2,
     "배반사상(P(A∩B)=0) 이면 P(A)P(B)>0 과 동일하지 않으므로 독립이 될 수 없음 (확률론 기본)"),
    ("s2", "s2_20160508", 57, 4, 3,
     "재검사법에서 간격이 짧으면 기억효과로 상관이 과대평가되어 신뢰도가 왜곡됨"),
    ("s2", "s2_20070805", 89, 1, 4,
     "Spearman-Brown 신뢰도 계산: 1-(1-0.4)(39/37) = 0.368"),
    # --- g1 deep B1 (판례 기반) ---
    ("g1", "g1_20071028", 77, 1, 4,
     "건물 일부 전세권자는 그 일부에 대해서만 우선변제권을 가지며 건물 전부에 대해 우선변제 못함 (판례)"),
    # --- g2 deep2 (측량 규칙) ---
    ("g2", "g2_20051030", 53, 2, 4,
     "지적확정측량지역은 1/500 축척으로 면적을 소수점 첫째자리(0.1m² 단위)까지 등록. 730.45 → 730.5m²"),
]


def apply_answer_fixes(log: list) -> None:
    for exam, file_label, num, frm, to, reason in ANSWER_FIXES:
        p, doc, q, _ = load_q(exam, file_label, num)
        if q["answer"] == to and q.get("answer_original") == frm:
            print(f"  skip (already corrected): {file_label}#{num}")
            continue
        if q["answer"] != frm:
            print(f"  WARN: {file_label}#{num} answer 가 예상값({frm}) 아님: 실제 {q['answer']}")
            continue
        q["answer_original"] = frm
        q["answer"] = to
        q["correction"] = {
            "kind": "answer_field",
            "from": frm,
            "to": to,
            "reason": reason,
            "source": "audit_a2_revalidate",
            "at": NOW,
        }
        save(p, doc)
        log.append({
            "qid": f"{file_label}#{num}",
            "kind": "answer_field",
            "from": frm,
            "to": to,
            "reason": reason,
        })
        print(f"  fixed: {file_label}#{num} {frm} → {to}")


# ---- P1.2: g2#108 해설 재생성 ----
G2_108 = ("g2", "g2_20121028", 108)
G2_108_PROMPT = """너는 한국 공인중개사 2차 시험 채점관이다. 아래 문항의 해설을 생성하라.

[문제 배경]
주택법령상 분양가상한제 적용주택의 전매제한에 관한 문항. 이 문항은 "틀린 것"을 고르는 문제이며, **공식 정답은 ②번**이다(수도권 외 비투기과열지구 공공택지 대상주택의 전매제한기간을 3년으로 서술하여 틀림).

[규칙]
- 출력은 다음 3섹션 (정확히 이 헤더):
  핵심 개념
  정답 분석
  오답 분석
- 정답 분석은 **②번이 왜 틀린 지문인지** 명확히 설명할 것.
- 오답 분석은 ①, ③, ④이 왜 옳은 지문인지 각각 다룰 것.
- 한국어, 평이체, 군더더기 없는 톤. 250~600자 분량.

[문제]
甲은 주택법령상 분양가상한제 적용주택을 공급받아 소유하는 자로서 전매제한의 적용을 받고 있다. 이에 관한 설명으로 틀린 것은? (사업주체는 지방공사가 아니고, 세대원은 세대주가 포함된 세대의 구성원을 말하며, 수도권은 수도권정비계획법에 의한 것임)

[선택지]
(1) 甲에 대한 전매제한기간의 기산점은 대상주택의 입주자모집을 하여 최초로 주택공급계약 체결이 가능한 날이다.
(2) 대상주택이 수도권 외의 지역으로 비투기과열지구인 공공택지에 소재할 경우 甲에 대한 전매제한기간은 3년이다.  ← 정답(틀린 지문)
(3) 甲이 대상주택을 전매하는 경우 한국토지주택공사가 그 주택을 우선 매입할 수 있다.
(4) 甲이 상속에 의하여 주택을 취득하여 甲의 세대원 전원이 그 주택으로 이전하면서 한국토지주택공사의 동의를 받은 경우 甲은 대상주택을 전매할 수 있다.

해설만 출력. 다른 부가 텍스트 없이.
"""


def regenerate_g2_108(log: list) -> None:
    p, doc, q, _ = load_q(*G2_108)
    if (q.get("correction") or {}).get("kind_explanation") == "regenerated":
        print(f"  skip (already regenerated): {G2_108[1]}#{G2_108[2]}")
        return
    print(f"  regenerating {G2_108[1]}#{G2_108[2]} ...")
    new_explanation = call_claude(G2_108_PROMPT, timeout=240)
    # 섹션 헤더 검증
    if not all(h in new_explanation for h in ("핵심 개념", "정답 분석", "오답 분석")):
        raise RuntimeError("regen output missing required sections")
    q["explanation_detailed_original"] = q.get("explanation_detailed")
    q["explanation_detailed"] = new_explanation
    q["correction"] = {
        **q.get("correction", {}),
        "kind_explanation": "regenerated",
        "explanation_reason": "기존 해설이 ①을 틀린 지문으로 결론 → 재검수 결과 ②가 정답. 재생성.",
        "source": "audit_a2_revalidate",
        "at": NOW,
    }
    save(p, doc)
    log.append({
        "qid": f"{G2_108[1]}#{G2_108[2]}",
        "kind": "explanation_regenerated",
        "reason": "AI 결론이 answer 키와 다름 + 재검수가 answer 키 옳다 판정",
    })
    print(f"  regenerated: {G2_108[1]}#{G2_108[2]}")


# ---- P1.3: g2#2 누락 항목 → 데이터 결함 마킹 ----
G2_002 = ("g2", "g2_20071028", 2)


def mark_g2_002_defect(log: list) -> None:
    p, doc, q, _ = load_q(*G2_002)
    if q.get("known_defect"):
        print(f"  already marked: {G2_002[1]}#{G2_002[2]}")
        return
    q["known_defect"] = {
        "kind": "missing_question_body",
        "detail": "본문에 ㄱ/ㄴ/ㄷ 등 판단 대상 항목 목록 누락. 추출 단계 결함 의심.",
        "source": "audit_a2_revalidate",
        "at": NOW,
    }
    save(p, doc)
    log.append({
        "qid": f"{G2_002[1]}#{G2_002[2]}",
        "kind": "data_defect_marked",
        "reason": "문제 본문 누락 — 재추출 필요 (FETCH_BASE_URL 환경변수 미제공으로 본 단계에서는 마킹만)",
    })
    print(f"  marked defect: {G2_002[1]}#{G2_002[2]}")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    log_path = OUT / "corrections.log.json"
    log: list = []
    if log_path.exists():
        try:
            log = json.loads(log_path.read_text("utf-8"))
        except Exception:
            log = []

    print("[P1.1] answer 필드 정정 ...")
    apply_answer_fixes(log)
    print("[P1.2] g2#108 해설 재생성 ...")
    regenerate_g2_108(log)
    print("[P1.3] g2#2 결함 마킹 ...")
    mark_g2_002_defect(log)

    log_path.write_text(json.dumps(log, ensure_ascii=False, indent=2), "utf-8")
    print(f"\n→ {log_path}")


if __name__ == "__main__":
    main()
