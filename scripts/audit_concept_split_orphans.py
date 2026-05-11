"""concept_split 후 남은 orphan concept_ids 정리 — 길이 불일치 케이스 fallback 매핑."""
import json
import glob
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OLD_IDS = {"ui-design-principles", "requirements-process", "dfd"}


def main():
    idx = json.loads((DATA / "concepts" / "iz" / "index.json").read_text("utf-8"))
    al = json.loads((DATA / "concepts" / "iz" / "aliases.json").read_text("utf-8"))

    # 각 old_id 의 새 sub IDs 찾기
    new_subs: dict[str, list[str]] = {oid: [] for oid in OLD_IDS}
    for nid, e in idx.items():
        for oid in OLD_IDS:
            if nid.startswith(oid + "-"):
                new_subs[oid].append(nid)

    fixed = 0
    for f in glob.glob(str(DATA / "iz" / "iz_*.json")):
        doc = json.loads(Path(f).read_text("utf-8"))
        changed = False
        for q in doc["questions"]:
            ids = q.get("concept_ids") or []
            cs = q.get("concepts") or []
            new_ids = []
            for i, cid in enumerate(ids):
                if cid not in OLD_IDS:
                    new_ids.append(cid)
                    continue
                # 텍스트 매칭 시도 — concepts[i] 와 aliases 둘 다 확인
                text = cs[i] if i < len(cs) else None
                if text and text in al and al[text] in new_subs[cid]:
                    new_ids.append(al[text])
                else:
                    # fallback: 첫 sub
                    new_ids.append(new_subs[cid][0])
                changed = True
                fixed += 1
            if changed:
                q["concept_ids"] = new_ids
        if changed:
            Path(f).write_text(json.dumps(doc, ensure_ascii=False, indent=2), "utf-8")

    print(f"orphan concept_ids 수정: {fixed}")


if __name__ == "__main__":
    main()
