"""Generate docs/TOOLS.md from the @tool() functions in MCP_Server/server.py.

Usage: python scripts/gen_tools_doc.py          # rewrite docs/TOOLS.md
       python scripts/gen_tools_doc.py --check  # exit 1 if it is out of date

Parses the source with ast, so it needs neither the mcp package nor Live.
tests/unit/test_tools_doc.py runs the --check logic so the reference cannot
drift from the code.
"""
import ast
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(REPO_ROOT, "MCP_Server", "server.py")
OUTPUT = os.path.join(REPO_ROOT, "docs", "TOOLS.md")


def _is_tool(fn: ast.FunctionDef) -> bool:
    for dec in fn.decorator_list:
        if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name) and dec.func.id == "tool":
            return True
    return False


def _summary(doc: str) -> str:
    doc = (doc or "").strip()
    first_para = doc.split("\n\n")[0]
    return " ".join(line.strip() for line in first_para.splitlines())


def _params(fn: ast.FunctionDef):
    args = fn.args.args
    defaults = [None] * (len(args) - len(fn.args.defaults)) + list(fn.args.defaults)
    out = []
    for arg, default in zip(args, defaults):
        if arg.arg == "ctx":
            continue
        out.append(arg.arg if default is None else f"{arg.arg}={ast.unparse(default)}")
    return out


def tools():
    with open(SERVER) as f:
        tree = ast.parse(f.read())
    return [n for n in tree.body if isinstance(n, ast.FunctionDef) and _is_tool(n)]


def render() -> str:
    found = tools()
    lines = [
        "# Tool reference",
        "",
        "Generated from `MCP_Server/server.py` by `python scripts/gen_tools_doc.py`;",
        "do not edit by hand. Each tool's full parameter documentation is its",
        "docstring, which MCP clients show.",
        "",
        "Conventions: track, clip slot, scene, device and parameter numbers are",
        "1-based. Bar ranges are inclusive (bars 1-4 is four bars). Tools that",
        "act on mixer or devices take `track_type` = `track` / `return` / `master`.",
        "",
        f"{len(found)} tools.",
        "",
        "| Tool | Parameters | What it does |",
        "| --- | --- | --- |",
    ]
    for fn in found:
        params = ", ".join(f"`{p}`" for p in _params(fn)) or "-"
        summary = _summary(ast.get_docstring(fn)).replace("|", "\\|")
        lines.append(f"| `{fn.name}` | {params} | {summary} |")
    return "\n".join(lines) + "\n"


def main():
    content = render()
    if "--check" in sys.argv:
        current = open(OUTPUT).read() if os.path.exists(OUTPUT) else ""
        if current != content:
            print("docs/TOOLS.md is out of date; run: python scripts/gen_tools_doc.py")
            sys.exit(1)
        print("docs/TOOLS.md is up to date")
        return
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w") as f:
        f.write(content)
    print(f"Wrote {OUTPUT} ({len(tools())} tools)")


if __name__ == "__main__":
    main()
