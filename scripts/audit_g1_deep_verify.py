"""g1 deep mismatch B1 재검수."""
import json, re, subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT/"data"; OUT = DATA/"audit"

PROMPT = """너는 공인중개사 1차 시험 채점관이다. 본문과 선택지만 보고 신중히 판단.
법령 시점 의존 시 ambiguous=true.

[과목] {subject}
[문제] {question}
[선택지]
{choices}

JSON 만:
{{"answer": 1-{n}, "confidence": 0.0-1.0, "ambiguous": true|false, "reason": "100자"}}
"""

def call_claude(p, timeout=240):
    r = subprocess.run(["claude","-p",p], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0: raise RuntimeError(r.stderr)
    return r.stdout.strip()

def parse_json(out):
    m = re.search(r"\{.*\}", out, re.S)
    if not m: return None
    try: return json.loads(m.group(0))
    except: return None

def find_q(fl, num):
    doc = json.loads((DATA/"g1"/f"{fl}.json").read_text("utf-8"))
    for q in doc["questions"]:
        if q["number"]==num: return q

def main():
    rows = json.loads((OUT/"no_conclusion_sample_g1iz_deep.json").read_text("utf-8"))
    cands = [r for r in rows if r.get("verdict")=="mismatch" and r["exam"]=="g1"]
    results = []
    for i,c in enumerate(cands,1):
        fl,num = c["qid"].split("#")
        q = find_q(fl, int(num))
        if q is None or q.get("known_defect"):
            results.append({**c,"skip":"defect"}); continue
        choices = "\n".join(f"  ({k+1}) {ch.get('text','')}" for k,ch in enumerate(q["choices"]))
        prompt = PROMPT.format(subject=q.get("subject") or "", question=q.get("question") or "", choices=choices, n=len(q["choices"]))
        try:
            out = call_claude(prompt); parsed = parse_json(out) or {}
        except Exception as e:
            results.append({**c,"error":str(e)}); print(f"  [{i}] ERROR {e}"); continue
        sp = parsed.get("answer"); ambig = bool(parsed.get("ambiguous")); first = c.get("revalid")
        if ambig: v = "ambiguous"
        elif sp==first and sp!=q["answer"]: v = "confirmed"
        elif sp==q["answer"]: v = "first_pass_wrong"
        else: v = "disagreement"
        results.append({**c,"second":sp,"second_conf":parsed.get("confidence"),"second_ambig":ambig,"second_reason":parsed.get("reason"),"verdict_final":v})
        print(f"  [{i}/{len(cands)}] {c['qid']} answer={q['answer']} 1차={first} 2차={sp} → {v}")
    (OUT/"g1_deep_verified.json").write_text(json.dumps(results,ensure_ascii=False,indent=2),"utf-8")
    conf = [r for r in results if r.get("verdict_final")=="confirmed"]
    print(f"\n양차 합의: {len(conf)}")
    for r in conf:
        print(f"  - {r['qid']}: answer {r['answer_field']} → {r['revalid']} (conf2 {r.get('second_conf')})")
        print(f"    근거: {r.get('second_reason')}")

if __name__=="__main__":
    main()
