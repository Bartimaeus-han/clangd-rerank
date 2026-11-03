"""Namer 문맥 보강: 커서 앞 40줄 바깥에 있는 '같은 파일의 앞선 선언들'을 한 줄 주석으로 요약해 프롬프트 앞에 붙인다.
표준 라이브러리만 쓴다(프록시·서버·평가 스크립트가 같이 쓴다). 커서 뒤 코드는 보지 않는다(top-down 가정).

build_prompt(full_before, ctx_lines=40, enrich=True) → 프롬프트 문자열
  full_before: 파일 시작부터 커서까지(친 글자 제외). 마지막 ctx_lines 줄은 그대로, 그 앞 부분은 선언 요약으로.
요약 예:  // earlier in this file: struct Config { std::string host; int port; }, int parse_port(const std::string& s), Config cfg, std::vector<std::string> args
"""
import re

_QUAL = r"(?:(?:static|const|constexpr|inline|extern|virtual|explicit|unsigned|signed|volatile|mutable|thread_local)\s+)*"
_TYPE = r"[A-Za-z_][\w:]*(?:\s*<[^<>;{}]*(?:<[^<>;{}]*>[^<>;{}]*)*>)?(?:\s*::\s*[A-Za-z_]\w*)*(?:\s*[*&]+)?"
_DECL = re.compile(r"^\s*" + _QUAL + r"(" + _TYPE + r")\s+[*&]*\s*([A-Za-z_]\w*)\s*(?:(\()|[=;,\[{:])", re.M)
_AGG = re.compile(r"^\s*(?:typedef\s+)?(struct|class|enum(?:\s+class)?|union|namespace)\s+([A-Za-z_]\w*)", re.M)
_NOT = {"return", "delete", "new", "throw", "case", "goto", "else", "do", "sizeof", "using", "namespace", "template", "typename",
        "if", "while", "for", "switch", "operator", "public", "private", "protected", "break", "continue", "typedef", "friend",
        "co_return", "co_await", "co_yield", "and", "or", "not", "define", "include", "pragma", "endif", "ifdef", "ifndef", "else"}


def _strip(code):
    """주석·문자열을 비워 가짜 선언을 줄인다 (줄 수는 유지)."""
    code = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), code, flags=re.S)
    code = re.sub(r"//[^\n]*", "", code)
    code = re.sub(r'"(?:\\.|[^"\\\n])*"', '""', code)
    return code


def decl_summary(code, max_items=40, max_chars=600):
    """code 안의 선언을 '타입 이름' 또는 '이름(' 꼴로 뽑아 최근 것부터 max_items 개."""
    items, seen = [], set()
    code = _strip(code)
    for m in _AGG.finditer(code):
        kw, name = m.group(1), m.group(2)
        if name not in seen:
            seen.add(name); items.append((m.start(), f"{kw} {name}"))
    for m in _DECL.finditer(code):
        typ, name, call = m.group(1).strip(), m.group(2), m.group(3)
        first = typ.split()[0].split("::")[0]
        if name in _NOT or first in _NOT or first.startswith("#") or name in seen:
            continue
        if typ in ("else", "return") or len(typ) > 40:
            continue
        seen.add(name)
        items.append((m.start(), f"{typ} {name}()" if call else f"{typ} {name}"))
    items.sort()
    picked = [t for _, t in items[-max_items:]]
    out = ", ".join(picked)
    while len(out) > max_chars and picked:
        picked.pop(0); out = ", ".join(picked)
    return out


def build_prompt(full_before, ctx_lines=40, enrich=True):
    lines = full_before.split("\n")
    tail = "\n".join(lines[-ctx_lines:])
    if not enrich or len(lines) <= ctx_lines:
        return tail
    summary = decl_summary("\n".join(lines[:-ctx_lines]))
    if not summary:
        return tail
    return f"// earlier in this file: {summary}\n" + tail


if __name__ == "__main__":
    import sys
    print(build_prompt(open(sys.argv[1]).read(), int(sys.argv[2]) if len(sys.argv) > 2 else 40)[:1500])
