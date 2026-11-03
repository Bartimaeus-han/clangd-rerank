#!/usr/bin/env python3
"""Namer(이름 생성 모델) 학습 데이터: 소스에서 '새 이름을 선언하는 자리'를 tree-sitter 로 뽑는다 (clangd 불필요).
사용: jevenv/bin/python -I scripts/collect_decl.py <소스 루트> <저장소 목록 파일> <출력 jsonl> [--per-repo 800] [--per-name 5] [--per-file 40]
  저장소 목록: 한 줄에 하나(train_v4_sources.txt 처럼 '<루트>/<저장소>' 또는 '<저장소>'). codecontests 등은 목록에서 빼면 된다.
뽑는 자리: 지역·전역 변수, 매개변수, 멤버(필드), range-for 변수의 이름. 함수 이름·타입 이름·매크로는 뺀다.
한 줄: {"src","file","line","col","gold","kind","type","prefix"(커서 앞 최대 60줄, 친 글자 없음),"after"(뒤 40자)}
편향 상한: 저장소당 per-repo, 저장소 안 같은 이름 per-name, 파일당 per-file (i/it/result 같은 이름이 데이터를 덮지 않게)."""
import argparse, collections, hashlib, json, os, random, re, sys

import tree_sitter_c, tree_sitter_cpp
from tree_sitter import Language, Parser

EXTS = {".c": "c", ".h": "cpp", ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp", ".hxx": "cpp", ".inl": "cpp"}
SKIP_DIRS = {"third_party", "thirdparty", "third-party", "external", "extern", "vendor", "deps", "dependencies", "3rdparty", "lib", "libs",
             "node_modules", "build", "cmake-build-debug", "cmake-build-release", ".git", "test_data", "testdata"}
PARSERS = {"c": Parser(Language(tree_sitter_c.language())), "cpp": Parser(Language(tree_sitter_cpp.language()))}
CTX_LINES = 60
DECL_PARENTS = {"declaration": "local", "field_declaration": "field", "parameter_declaration": "param",
                "optional_parameter_declaration": "param", "condition_clause": "local", "for_range_loop": "local"}
IDENT_KINDS = {"identifier", "field_identifier"}


def declared_name(node):
    """선언자 노드에서 이름 식별자 노드를 찾는다. 함수 선언자(이름 뒤 괄호)면 None."""
    cur = node
    while cur is not None:
        t = cur.type
        if t in IDENT_KINDS:
            return cur
        if t == "function_declarator":
            return None
        if t in ("init_declarator", "pointer_declarator", "reference_declarator", "array_declarator", "parenthesized_declarator",
                 "attributed_declarator"):
            d = cur.child_by_field_name("declarator") or next((c for c in cur.children if c.is_named and c.type != "attribute_declaration"), None)
            cur = d
            continue
        return None
    return None


def walk(root, src, out, stats):
    stack = [root]
    while stack:
        n = stack.pop()
        kind = DECL_PARENTS.get(n.type)
        if kind:
            if n.type == "declaration" and any(c.type == "storage_class_specifier" and src[c.start_byte:c.end_byte] == b"typedef" for c in n.children):
                stats["skip_typedef"] += 1
            else:
                scope_kind = kind
                if kind == "local":
                    p = n.parent
                    while p is not None and p.type not in ("function_definition", "lambda_expression", "translation_unit", "class_specifier",
                                                           "struct_specifier", "namespace_definition"):
                        p = p.parent
                    if p is None or p.type in ("translation_unit", "namespace_definition"):
                        scope_kind = "global"
                type_node = n.child_by_field_name("type")
                for c in n.children:
                    if c.type in ("init_declarator", "identifier", "field_identifier", "pointer_declarator", "reference_declarator",
                                  "array_declarator", "parenthesized_declarator", "attributed_declarator"):
                        if n.type == "for_range_loop" and c is not n.child_by_field_name("declarator"):
                            continue
                        if n.type == "condition_clause" and c is not n.child_by_field_name("value"):
                            continue
                        name = declared_name(c)
                        if name is None:
                            stats["skip_func"] += 1
                            continue
                        out.append((name, scope_kind, src[type_node.start_byte:type_node.end_byte].decode("utf8", "ignore") if type_node else ""))
        stack.extend(n.children)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root"); ap.add_argument("repos"); ap.add_argument("out")
    ap.add_argument("--per-repo", type=int, default=800); ap.add_argument("--per-name", type=int, default=5)
    ap.add_argument("--per-file", type=int, default=40); ap.add_argument("--max-kb", type=int, default=300)
    a = ap.parse_args()
    repos = [l.strip().rstrip("/") for l in open(a.repos) if l.strip() and not l.startswith("#")]  # 루트 기준 상대 경로
    rng = random.Random(0)
    total = collections.Counter(); kinds = collections.Counter(); names = collections.Counter(); per_repo_n = {}
    with open(a.out, "w") as fo:
        for rel_repo in repos:
            rdir = os.path.join(a.root, rel_repo)
            repo = os.path.basename(rel_repo)
            if not os.path.isdir(rdir):
                print(f"없음: {rdir}", file=sys.stderr); continue
            files = []
            for dp, dns, fns in os.walk(rdir):
                dns[:] = [d for d in dns if d.lower() not in SKIP_DIRS]
                for fn in fns:
                    ext = os.path.splitext(fn)[1].lower()
                    if ext in EXTS:
                        p = os.path.join(dp, fn)
                        if os.path.getsize(p) <= a.max_kb * 1024:
                            files.append(p)
            rng.shuffle(files)
            cands = []
            stats = collections.Counter()
            for p in files:
                src = open(p, "rb").read()
                if b"\0" in src:
                    continue
                tree = PARSERS[EXTS[os.path.splitext(p)[1].lower()]].parse(src)
                found = []
                walk(tree.root_node, src, found, stats)
                rng.shuffle(found)
                rel = os.path.relpath(p, rdir)
                taken = 0
                for name_node, kind, typ in found:
                    if taken >= a.per_file:
                        break
                    gold = src[name_node.start_byte:name_node.end_byte].decode("utf8", "ignore")
                    if not re.fullmatch(r"[A-Za-z_]\w*", gold) or gold in ("this",):
                        continue
                    before = src[:name_node.start_byte].decode("utf8", "ignore")
                    line_text = before.split("\n")[-1]
                    if not line_text or not line_text[-1].isspace() and line_text[-1] not in "*&(":
                        stats["skip_nospace"] += 1  # `int(x)` 같은 캐스트·매크로 꼴
                        continue
                    lines = before.split("\n")
                    prefix = "\n".join(lines[-CTX_LINES:])
                    after = src[name_node.end_byte:name_node.end_byte + 40].decode("utf8", "ignore")
                    cands.append({"src": repo, "file": rel, "line": name_node.start_point[0], "col": name_node.start_point[1], "gold": gold,
                                  "kind": kind, "type": typ[:80], "prefix": prefix, "after": after})
                    taken += 1
            rng.shuffle(cands)
            per_name = collections.Counter(); kept = 0
            for c in cands:
                if kept >= a.per_repo:
                    break
                if per_name[c["gold"]] >= a.per_name:
                    continue
                per_name[c["gold"]] += 1
                fo.write(json.dumps(c, ensure_ascii=False) + "\n")
                kept += 1; kinds[c["kind"]] += 1; names[c["gold"]] += 1
            per_repo_n[repo] = kept
            total["files"] += len(files); total["found"] += len(cands); total["kept"] += kept
            total["skip_func"] += stats["skip_func"]; total["skip_nospace"] += stats["skip_nospace"]
            print(f"{repo}: 파일 {len(files)}, 자리 {len(cands)}, 채택 {kept}", flush=True)
    print("\n== 합계", dict(total))
    print("종류별", dict(kinds))
    print("고유 이름", len(names), "/ 상위 20:", names.most_common(20))
    lens = collections.Counter(min(len(n), 20) for n in names.elements())
    print("이름 길이 분포", sorted(lens.items()))
    print("저장소당 채택(중앙값)", sorted(per_repo_n.values())[len(per_repo_n) // 2], "최소", min(per_repo_n.values()), "최대", max(per_repo_n.values()))


if __name__ == "__main__":
    main()
