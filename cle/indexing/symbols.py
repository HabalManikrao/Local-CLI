"""Symbol extraction.

Produces a language-tagged :class:`FileParse` (symbols + imports) for a source
file. Java uses a brace-depth-aware heuristic scanner (tree-sitter is an
optional future upgrade; see the audit). Python uses the stdlib ``ast``. Other
languages are indexed at file level only.

The Java scanner is deliberately heuristic: it favors useful recall over
perfect precision, and is documented as such. It handles package/imports,
class/interface/enum/record declarations with extends/implements, methods,
constructors, fields, and annotations.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

# Extension → language name.
LANGUAGE_BY_EXT = {
    ".java": "java",
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".kt": "kotlin",
    ".go": "go",
    ".rb": "ruby",
    ".cs": "csharp",
    ".xml": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".md": "markdown",
    ".json": "json",
}


@dataclass
class ExtractedSymbol:
    kind: str          # package|class|interface|enum|record|method|constructor|function|field|annotation
    name: str
    parent: str | None
    line_start: int
    line_end: int | None = None
    signature: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class ExtractedImport:
    target: str
    line: int


@dataclass
class FileParse:
    language: str
    symbols: list[ExtractedSymbol] = field(default_factory=list)
    imports: list[ExtractedImport] = field(default_factory=list)


def detect_language(path: Path) -> str | None:
    return LANGUAGE_BY_EXT.get(path.suffix.lower())


def parse_source(path: Path, text: str) -> FileParse:
    """Parse *text* for *path*, dispatching on detected language."""
    language = detect_language(path)
    if language == "java":
        return _parse_java(text)
    if language == "python":
        return _parse_python(text)
    return FileParse(language=language or "unknown")


# ---------------------------------------------------------------------------
# Java (heuristic, brace-depth aware)
# ---------------------------------------------------------------------------

_CONTROL_KEYWORDS = {
    "if", "for", "while", "switch", "catch", "return", "new", "synchronized",
    "else", "do", "try", "throw", "assert", "super", "this",
}

_PACKAGE_RE = re.compile(r"^\s*package\s+([\w.]+)\s*;")
_IMPORT_RE = re.compile(r"^\s*import\s+(?:static\s+)?([\w.*]+)\s*;")
_TYPE_RE = re.compile(
    r"^\s*(?P<mods>(?:public|private|protected|abstract|final|static|sealed|"
    r"non-sealed|strictfp|\s)*)"
    r"\b(?P<kind>class|interface|enum|record)\s+(?P<name>\w+)"
    r"(?P<rest>[^{]*)"
)
_EXTENDS_RE = re.compile(r"\bextends\s+([\w.<>,\s]+?)(?:\bimplements\b|\{|$)")
_IMPLEMENTS_RE = re.compile(r"\bimplements\s+([\w.<>,\s]+?)(?:\{|$)")
_METHOD_RE = re.compile(
    r"^\s*(?P<mods>(?:public|private|protected|static|final|abstract|"
    r"synchronized|native|default|strictfp|\s)*)"
    r"(?P<ret>[\w<>\[\],.?\s]+?)\s+"
    r"(?P<name>\w+)\s*\((?P<params>[^)]*)\)"
)
_CTOR_RE = re.compile(
    r"^\s*(?:public|private|protected|\s)*(?P<name>\w+)\s*\((?P<params>[^)]*)\)"
)
_FIELD_RE = re.compile(
    r"^\s*(?P<mods>(?:public|private|protected|static|final|volatile|transient|\s)+)"
    r"(?P<type>[\w<>\[\],.?]+)\s+(?P<name>\w+)\s*(?:=[^;]*)?;"
)
_ANNOTATION_USE_RE = re.compile(r"^\s*@(\w+)")


def _strip_comments(text: str) -> str:
    """Replace comment content with spaces, preserving line count/offsets."""
    out = []
    i, n = 0, len(text)
    in_line = in_block = in_str = in_char = False
    while i < n:
        c = text[i]
        two = text[i : i + 2]
        if in_line:
            if c == "\n":
                in_line = False
                out.append(c)
            else:
                out.append(" ")
            i += 1
        elif in_block:
            if two == "*/":
                in_block = False
                out.append("  ")
                i += 2
            else:
                out.append("\n" if c == "\n" else " ")
                i += 1
        elif in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
        elif in_char:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == "'":
                in_char = False
            i += 1
        elif two == "//":
            in_line = True
            out.append("  ")
            i += 2
        elif two == "/*":
            in_block = True
            out.append("  ")
            i += 2
        elif c == '"':
            in_str = True
            out.append(c)
            i += 1
        elif c == "'":
            in_char = True
            out.append(c)
            i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _parse_java(text: str) -> FileParse:
    parse = FileParse(language="java")
    raw_lines = text.splitlines()
    clean_lines = _strip_comments(text).splitlines()

    # package + imports from raw lines.
    for idx, line in enumerate(raw_lines, start=1):
        m = _PACKAGE_RE.match(line)
        if m:
            parse.symbols.append(ExtractedSymbol("package", m.group(1), None, idx))
        mi = _IMPORT_RE.match(line)
        if mi:
            parse.imports.append(ExtractedImport(mi.group(1), idx))

    # Brace-depth scan for types/methods/fields.
    depth = 0
    stack: list[dict] = []          # entries: {name, kind, open_depth, symbol}
    pending_annotations: list[str] = []

    for idx, cline in enumerate(clean_lines, start=1):
        stripped = cline.strip()
        enclosing = stack[-1] if stack else None
        parent_name = enclosing["name"] if enclosing else None

        # Annotation usage on its own — remember it for the next declaration.
        am = _ANNOTATION_USE_RE.match(cline)
        if am:
            ann = am.group(1)
            parse.symbols.append(ExtractedSymbol("annotation", ann, parent_name, idx))
            pending_annotations.append(ann)
            continue  # annotations don't change brace depth meaningfully here

        # Type declaration?
        tm = _TYPE_RE.match(cline)
        if tm:
            extra: dict = {}
            rest = tm.group("rest") or ""
            em = _EXTENDS_RE.search(rest)
            if em:
                extra["extends"] = [s.strip() for s in em.group(1).split(",") if s.strip()]
            im = _IMPLEMENTS_RE.search(rest)
            if im:
                extra["implements"] = [s.strip() for s in im.group(1).split(",") if s.strip()]
            if pending_annotations:
                extra["annotations"] = list(pending_annotations)
            sym = ExtractedSymbol(
                tm.group("kind"), tm.group("name"), parent_name, idx,
                signature=stripped.split("{")[0].strip(), extra=extra,
            )
            parse.symbols.append(sym)
            open_at = depth
            depth += cline.count("{") - cline.count("}")
            stack.append({
                "name": tm.group("name"), "kind": tm.group("kind"),
                "open_depth": open_at, "symbol": sym,
            })
            pending_annotations.clear()
            continue

        # Member directly inside a type body (one level below the type's brace)?
        in_type_body = enclosing is not None and depth == enclosing["open_depth"] + 1
        if in_type_body and stripped:
            member = _match_member(cline, idx, enclosing["name"])
            if member is not None:
                if pending_annotations:
                    member.extra["annotations"] = list(pending_annotations)
                parse.symbols.append(member)

        # Any substantive line consumes pending annotations.
        if stripped:
            pending_annotations.clear()

        # Update depth and close any scopes that ended on this line.
        depth += cline.count("{") - cline.count("}")
        while stack and depth <= stack[-1]["open_depth"]:
            stack.pop()["symbol"].line_end = idx

    return parse


def _match_member(cline: str, line: int, parent: str) -> ExtractedSymbol | None:
    stripped = cline.strip()

    # Constructors first: a bare `Name(` with no return type would otherwise be
    # mis-read by the method regex (which can treat the access modifier as the
    # return type). A constructor's name equals the enclosing type.
    cm = _CTOR_RE.match(cline)
    if cm and cm.group("name") == parent:
        return ExtractedSymbol(
            "constructor", cm.group("name"), parent, line,
            signature=stripped.split("{")[0].strip().rstrip(";"),
            extra={"params": cm.group("params").strip()},
        )

    mm = _METHOD_RE.match(cline)
    if mm and "(" in cline:
        name = mm.group("name")
        ret = mm.group("ret").strip()
        if name not in _CONTROL_KEYWORDS and ret not in _CONTROL_KEYWORDS and ret:
            return ExtractedSymbol(
                "method", name, parent, line,
                signature=stripped.split("{")[0].strip().rstrip(";"),
                extra={"returns": ret, "params": mm.group("params").strip()},
            )

    fm = _FIELD_RE.match(cline)
    if fm and fm.group("name") not in _CONTROL_KEYWORDS:
        return ExtractedSymbol(
            "field", fm.group("name"), parent, line,
            signature=stripped.rstrip(";"),
            extra={"type": fm.group("type")},
        )
    return None


# ---------------------------------------------------------------------------
# Python (ast-based, precise)
# ---------------------------------------------------------------------------

def _parse_python(text: str) -> FileParse:
    parse = FileParse(language="python")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return parse  # unparseable file → file-level only

    def visit(node: ast.AST, parent: str | None) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                parse.symbols.append(ExtractedSymbol(
                    "class", child.name, parent, child.lineno,
                    getattr(child, "end_lineno", None),
                    signature=f"class {child.name}",
                    extra={"bases": [ast.unparse(b) for b in child.bases]},
                ))
                visit(child, child.name)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                kind = "method" if parent else "function"
                parse.symbols.append(ExtractedSymbol(
                    kind, child.name, parent, child.lineno,
                    getattr(child, "end_lineno", None),
                    signature=f"def {child.name}(...)",
                ))
            elif isinstance(child, (ast.Import, ast.ImportFrom)):
                if isinstance(child, ast.Import):
                    for alias in child.names:
                        parse.imports.append(ExtractedImport(alias.name, child.lineno))
                else:
                    mod = child.module or ""
                    parse.imports.append(ExtractedImport(mod, child.lineno))

    visit(tree, None)
    return parse
