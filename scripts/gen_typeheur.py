#!/usr/bin/env python3
"""식별자 생성의 '진짜' 기준선: 선언 자리의 타입에서 규칙으로 이름을 만든다 (JetBrains 식, 모델 없음, 0ms).
사용: gen_typeheur.py <dir>  →  <dir>/typeheur-gen.jsonl ({"i","k","guesses","type"}) → gen_report.py 로 채점.

규칙: 커서 앞 줄에서 타입 토큰을 읽어
  - 사용자 타입 `adm_scene_stream_t*` → stream, scene_stream, adm_scene_stream ... (접두어 제거, 뒤 단어부터)
  - `ApRecord` → record, apRecord / ap_record (주변 코드의 표기법을 따라 camel/snake 선택)
  - 템플릿 `std::vector<Item>` → items, vec / `unique_ptr<Foo>` → foo
  - 기본형 `int`, `size_t`, `const char*` 등은 고정 표(i, n, count ... / size, len, n ... / name, str, s ...)
  - 함수 선언(`void `, `bool ` 뒤 함수 이름)은 타입만으로는 못 만든다 → 기본형 표
접두어가 있으면(k=1,2) 그에 맞는 것만 남긴다. 타입을 못 읽은 자리는 빈 추측(no_type 로 센다)."""
import json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eval_rerank as er  # noqa: E402

QUAL = {"const", "static", "volatile", "constexpr", "inline", "extern", "mutable", "register", "unsigned", "signed",
        "struct", "class", "enum", "union", "typename", "thread_local", "virtual", "explicit", "friend", "override", "final"}
FUND = {
    "int": ["i", "n", "count", "result", "ret"], "long": ["n", "value", "count", "l", "result"], "short": ["n", "s", "value", "count", "idx"],
    "unsigned": ["n", "i", "count", "u", "value"], "char": ["c", "ch", "buf", "name", "s"],
    "bool": ["ok", "result", "found", "enabled", "done"], "float": ["value", "x", "f", "t", "scale"], "double": ["value", "x", "d", "t", "scale"],
    "void": ["init", "update", "run", "reset", "process"], "auto": ["it", "result", "value", "x", "n"],
    "size_t": ["size", "len", "n", "count", "i"], "ssize_t": ["n", "len", "ret", "size", "r"],
    "uint8_t": ["len", "data", "b", "value", "buf"], "uint16_t": ["len", "value", "port", "n", "id"], "uint32_t": ["len", "value", "id", "n", "count"],
    "uint64_t": ["value", "id", "n", "count", "ts"], "int8_t": ["value", "v", "n", "i", "rssi"], "int16_t": ["value", "v", "n", "x", "y"],
    "int32_t": ["value", "n", "i", "ret", "id"], "int64_t": ["value", "n", "ts", "id", "count"], "uintptr_t": ["addr", "ptr", "p", "base", "value"],
    "string": ["name", "s", "str", "path", "text"], "string_view": ["name", "s", "str", "sv", "text"], "vector": ["items", "vec", "v", "list", "values"],
    "map": ["map", "m", "table", "lookup", "entries"], "unordered_map": ["map", "m", "table", "lookup", "cache"], "set": ["set", "s", "seen", "ids", "keys"],
    "array": ["arr", "a", "data", "buf", "values"], "pair": ["p", "pair", "kv", "entry", "item"], "function": ["fn", "f", "cb", "callback", "func"],
    "optional": ["result", "opt", "value", "v", "maybe"], "ostream": ["os", "out", "stream", "o", "s"], "istream": ["is", "in", "stream", "i", "s"],
    "ofstream": ["out", "ofs", "file", "f", "stream"], "ifstream": ["in", "ifs", "file", "f", "stream"], "FILE": ["fp", "f", "file", "out", "in"],
    "mutex": ["mutex", "mtx", "m", "lock", "mu"], "thread": ["thread", "t", "worker", "th", "tid"],
}
SMART = {"unique_ptr", "shared_ptr", "weak_ptr", "optional", "span", "reference_wrapper", "atomic", "basic_string"}
IDENT = re.compile(r"[A-Za-z_]\w*")
_SUB = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")


def words(ident):
    return [w.lower() for w in _SUB.findall(ident.replace("_", " "))]


def style(before):
    """주변 코드의 변수 표기: snake_case 가 많으면 'snake', 아니면 'camel'."""
    ids = IDENT.findall(before[-3000:])
    snake = sum("_" in x.strip("_") for x in ids)
    camel = sum(re.search(r"[a-z][A-Z]", x) is not None for x in ids)
    return "snake" if snake >= camel else "camel"


def join(ws, st):
    if not ws:
        return ""
    return "_".join(ws) if st == "snake" else ws[0] + "".join(w.capitalize() for w in ws[1:])


def type_before(line):
    """커서 앞 한 줄에서 선언 타입을 읽는다. (바깥 타입 이름, 템플릿 인자 안쪽 타입 이름 or None, 포인터/참조 여부) 또는 None."""
    s = line.rstrip()
    if not s or not s.endswith(("*", "&", ">", ")", "]")) and not re.search(r"[A-Za-z0-9_]$", s):
        return None  # 타입 뒤가 아니다 (예: `(&`, `&& `)
    if s.endswith("&&"):
        s = s[:-2].rstrip()
    while s.endswith(("*", "&")):
        s = s[:-1].rstrip()
    inner = None
    if s.endswith(">"):  # 템플릿 인자: 짝 맞춰 벗긴다
        depth, j = 0, len(s) - 1
        while j >= 0:
            depth += s[j] == ">"
            depth -= s[j] == "<"
            if depth == 0:
                break
            j -= 1
        if j <= 0:
            return None
        args = s[j + 1:-1]
        m = list(IDENT.finditer(args))
        inner = m[-1].group(0) if m else None
        s = s[:j].rstrip()
    m = re.search(r"([A-Za-z_][\w:]*)$", s)
    if not m:
        return None
    name = m.group(1).split("::")[-1]
    if name in QUAL or name in er.KEYWORDS and name not in FUND:
        return None
    return name, inner


def guesses_for(line, before):
    t = type_before(line)
    if t is None:
        return [], None
    name, inner = t
    st = style(before)
    out = []
    if name in FUND and name not in ("vector", "array", "set", "map", "unordered_map"):
        out += FUND[name]
    elif name in ("vector", "array", "set", "map", "unordered_map") and inner:
        ws = words(inner)
        if ws:
            ws = [w for w in ws if w not in ("t", "s")] or ws
            out += [join(ws[:-1] + [ws[-1] + "s"], st), join([ws[-1] + "s"], st), join(ws, st)]
        out += FUND[name]
    elif name in SMART and inner:
        ws = [w for w in words(inner) if w not in ("t",)] or words(inner)
        out += [join([ws[-1]], st), join(ws, st), "ptr", "p"]
    else:
        ws = words(name)
        # 흔한 꼬리·머리 제거: adm_scene_stream_t → scene stream, ApRecord → ap record, FooImpl → foo
        if ws and ws[-1] in ("t", "type", "impl", "s", "ptr", "ref", "cls", "class", "struct"):
            ws = ws[:-1]
        if len(ws) > 1 and len(ws[0]) <= 3:  # 프로젝트 접두어(adm_, sf, gl ...)
            core = ws[1:]
        else:
            core = ws
        if core:
            out += [join([core[-1]], st), join(core, st), join(core[-2:], st) if len(core) >= 2 else join(ws, st)]
            out += [core[-1][0]]  # 첫 글자 하나 (f, s ...)
        out += ["value", "item", "result"]
    seen, g = set(), []
    for x in out:
        if x and x not in seen and x not in er.KEYWORDS:
            seen.add(x); g.append(x)
    return g, name


def main():
    d = sys.argv[1]
    samples = [json.loads(l) for l in open(os.path.join(d, "samples.jsonl"))]
    n_no = 0
    with open(os.path.join(d, "typeheur-gen.jsonl"), "w") as f:
        for i, s in enumerate(samples):
            for k, lv in s["levels"].items():
                typed = s["gold"][:int(k)]
                before = lv["state"].split("<CURSOR>")[0]
                if typed:
                    before = before[:-len(typed)]
                g, tname = guesses_for(before.split("\n")[-1], before)
                if tname is None and s.get("cls") == "decl" and k == "0":
                    n_no += 1
                g = [x for x in g if x.startswith(typed)][:5]
                f.write(json.dumps({"i": i, "k": k, "guesses": g, "type": tname}) + "\n")
    print(f"typeheur-gen.jsonl 저장: {len(samples)}곳, decl 중 타입 못 읽음 {n_no}")


if __name__ == "__main__":
    main()
