"""P3 split verdict 클러스터를 새 canonical 들로 분리.

비파괴:
  - data/concepts/iz/{index,aliases}.json 을 .backup 으로 백업 (없을 때만)
  - 자격증 question 파일의 concept_ids 갱신

자동 ID 생성: 기존 canonical ID + '-1', '-2', ... 접미사
"""
import json
import re
import glob
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CONCEPTS = DATA / "concepts" / "iz"
OUT = DATA / "audit"
NOW = datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_subgroup(raw: str) -> tuple[str, list[str]]:
    """'subgroup_name: m1, m2, m3' → (name, [m1, m2, m3])"""
    name, _, rest = raw.partition(":")
    members = [m.strip() for m in rest.split(",") if m.strip()]
    return name.strip(), members


def main():
    # 백업
    for fn in ("index.json", "aliases.json"):
        src = CONCEPTS / fn
        bk = CONCEPTS / (fn + ".pre_split.backup")
        if not bk.exists():
            bk.write_text(src.read_text("utf-8"), "utf-8")
            print(f"  backed up {fn}")

    idx = json.loads((CONCEPTS / "index.json").read_text("utf-8"))
    al = json.loads((CONCEPTS / "aliases.json").read_text("utf-8"))

    # split verdict 케이스 로드
    reviews = json.loads((OUT / "concepts_review.json").read_text("utf-8"))
    splits = [r for r in reviews if r["exam"] == "iz" and r.get("verdict") == "split"]
    print(f"split 대상: {len(splits)}")

    # 기록할 매핑: old_id → {member_text → new_id}
    member_to_newid: dict[tuple[str, str], str] = {}
    new_canonicals: dict[str, dict] = {}
    removed_old: list[str] = []

    for s in splits:
        old_id = s["id"]
        if old_id not in idx:
            print(f"  WARN: {old_id} 이미 제거됨")
            continue
        old_entry = idx[old_id]
        subgroups = s["subgroups"]
        # 새 ID 생성
        new_entries = []
        used_members = set()
        for i, sg in enumerate(subgroups, 1):
            name, members = parse_subgroup(sg)
            new_id = f"{old_id}-{i}"
            new_canonicals[new_id] = {
                "id": new_id,
                "name_ko": name,
                "name_en": old_entry.get("name_en", ""),
                "subjects": old_entry.get("subjects", []),
                "members": members,
                "split_from": old_id,
                "split_at": NOW,
            }
            for m in members:
                member_to_newid[(old_id, m)] = new_id
                used_members.add(m)
            new_entries.append(new_id)
        # 누락된 member 처리 (subgroups 에 안 들어간 것들) — 첫 subgroup 으로 fallback
        first_new = new_entries[0]
        for m in old_entry.get("members", []):
            if m not in used_members:
                # fallback subgroup 에 넣음
                new_canonicals[first_new]["members"].append(m)
                member_to_newid[(old_id, m)] = first_new
                print(f"  fallback assign {old_id}: {m!r} → {first_new}")
        removed_old.append(old_id)
        print(f"  {old_id} → {len(new_entries)} subgroups")

    # index 갱신: 제거 + 추가
    for oid in removed_old:
        idx.pop(oid, None)
    for nid, entry in new_canonicals.items():
        idx[nid] = entry

    # aliases 갱신: old canonical 가리키던 member → new canonical
    updated_aliases = 0
    for member_text, alias_id in list(al.items()):
        if alias_id in removed_old:
            new_id = member_to_newid.get((alias_id, member_text))
            if new_id:
                al[member_text] = new_id
                updated_aliases += 1
            else:
                # 못 찾으면 첫 sub 로
                for nid in new_canonicals:
                    if nid.startswith(alias_id + "-"):
                        al[member_text] = nid
                        updated_aliases += 1
                        break

    # question 파일 갱신
    q_updated = 0
    for f in glob.glob(str(DATA / "iz" / "iz_*.json")):
        doc = json.loads(Path(f).read_text("utf-8"))
        changed = False
        for q in doc["questions"]:
            concepts = q.get("concepts") or []
            ids = q.get("concept_ids") or []
            if len(concepts) != len(ids):
                continue
            new_ids = []
            for cn, ci in zip(concepts, ids):
                if ci in removed_old:
                    new_id = member_to_newid.get((ci, cn))
                    if new_id:
                        new_ids.append(new_id)
                        changed = True
                        continue
                    # fallback: first sub
                    for nid in new_canonicals:
                        if nid.startswith(ci + "-"):
                            new_ids.append(nid)
                            changed = True
                            break
                    else:
                        new_ids.append(ci)
                else:
                    new_ids.append(ci)
            if changed:
                q["concept_ids"] = new_ids
                q_updated += 1
        if changed:
            Path(f).write_text(json.dumps(doc, ensure_ascii=False, indent=2), "utf-8")

    # 저장
    (CONCEPTS / "index.json").write_text(json.dumps(idx, ensure_ascii=False, indent=2), "utf-8")
    (CONCEPTS / "aliases.json").write_text(json.dumps(al, ensure_ascii=False, indent=2), "utf-8")

    print(f"\n적용:")
    print(f"  분할된 canonical: {len(removed_old)}")
    print(f"  새 canonical 추가: {len(new_canonicals)}")
    print(f"  aliases 업데이트: {updated_aliases}")
    print(f"  questions 업데이트: {q_updated}")

    # 로그
    (OUT / "concept_split.log.json").write_text(json.dumps({
        "at": NOW,
        "removed": removed_old,
        "added": list(new_canonicals.keys()),
        "aliases_updated": updated_aliases,
        "questions_updated": q_updated,
    }, ensure_ascii=False, indent=2), "utf-8")


if __name__ == "__main__":
    main()
