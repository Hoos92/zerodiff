"""Security & quality gate for rewritten code (zero dependencies, stdlib ast).

Catches the vulnerability classes and quality rot that AI-written code
most often introduces, and blocks the loop until they're gone. Findings
have severities: **error** findings block (the loop won't go green);
**warn** findings are reported and handed to the agent but don't block.

Honesty note (same rules as the rest of Retrace): static analysis proves
the absence of *these specific patterns*, not the absence of all
vulnerabilities. The gate complements behavioral verification; neither
replaces security review for high-stakes code.
"""

import ast
import re
from typing import Any, Dict, List, Optional

DEFAULT_BUDGETS = {
    "max_function_lines": 60,
    "max_complexity": 10,
    "max_nesting": 5,
}

_SECRET_ASSIGN_RE = re.compile(
    r"(?i)\b(password|passwd|secret|api_key|apikey|auth_token|access_key)"
    r"\s*=\s*[\"'][^\"']{4,}[\"']")
_TOKEN_LITERAL_RE = re.compile(
    r"(AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{22,}|"
    r"sk-[A-Za-z0-9]{24,}|xox[baprs]-[A-Za-z0-9-]{10,})")
_SQL_RE = re.compile(r"(?i)\b(select\s+.+\s+from|insert\s+into|"
                     r"update\s+\w+\s+set|delete\s+from)\b")


class Finding:
    def __init__(self, rule: str, severity: str, file: str, line: int,
                 message: str, hint: str) -> None:
        self.rule = rule
        self.severity = severity  # "error" | "warn"
        self.file = file
        self.line = line
        self.message = message
        self.hint = hint

    def to_dict(self) -> Dict[str, Any]:
        return {"rule": self.rule, "severity": self.severity,
                "file": self.file, "line": self.line,
                "message": self.message, "hint": self.hint}


def _call_name(node: ast.Call) -> str:
    func = node.func
    parts = []
    while isinstance(func, ast.Attribute):
        parts.append(func.attr)
        func = func.value
    if isinstance(func, ast.Name):
        parts.append(func.id)
    return ".".join(reversed(parts))


def _kw(node: ast.Call, name: str):
    for keyword in node.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _is_true(node) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def _is_false(node) -> bool:
    return isinstance(node, ast.Constant) and node.value is False


class _Analyzer(ast.NodeVisitor):
    def __init__(self, path: str, budgets: Dict[str, int],
                 disabled: List[str]) -> None:
        self.path = path
        self.budgets = budgets
        self.disabled = set(disabled)
        self.findings = []  # type: List[Finding]

    def add(self, rule: str, severity: str, line: int, message: str,
            hint: str) -> None:
        if rule in self.disabled:
            return
        self.findings.append(Finding(rule, severity, self.path, line,
                                     message, hint))

    # -- dangerous calls ---------------------------------------------------
    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node)
        line = node.lineno

        if name in ("eval", "exec") or name.endswith(("builtins.eval",
                                                      "builtins.exec")):
            self.add("eval-exec", "error", line,
                     "use of %s()" % name,
                     "eval/exec on any input is code injection waiting to "
                     "happen; replace with explicit parsing or dispatch.")
        if name in ("os.system", "os.popen"):
            self.add("shell-injection", "error", line,
                     "use of %s" % name,
                     "shell command built from strings; use subprocess "
                     "with a list argv and shell=False.")
        if name.startswith("subprocess.") and _is_true(_kw(node, "shell")):
            self.add("shell-injection", "error", line,
                     "%s with shell=True" % name,
                     "shell=True enables injection via any interpolated "
                     "value; pass a list argv with shell=False.")
        if name in ("pickle.load", "pickle.loads", "marshal.load",
                    "marshal.loads", "shelve.open"):
            self.add("unsafe-deserialization", "error", line,
                     "use of %s" % name,
                     "deserializing untrusted data executes arbitrary "
                     "code; use json or a schema-validated format.")
        if name in ("yaml.load",) and _kw(node, "Loader") is None:
            self.add("unsafe-deserialization", "error", line,
                     "yaml.load without an explicit safe Loader",
                     "use yaml.safe_load (or Loader=yaml.SafeLoader).")
        if name == "tempfile.mktemp":
            self.add("insecure-tempfile", "error", line,
                     "tempfile.mktemp is race-condition-prone",
                     "use tempfile.mkstemp or NamedTemporaryFile.")
        if name == "ssl._create_unverified_context":
            self.add("tls-verification-disabled", "error", line,
                     "TLS certificate verification disabled",
                     "never disable certificate verification; fix the "
                     "certificate chain instead.")
        if name.startswith("requests.") and _is_false(_kw(node, "verify")):
            self.add("tls-verification-disabled", "error", line,
                     "%s with verify=False" % name,
                     "never disable certificate verification; fix the "
                     "certificate chain instead.")
        if name in ("hashlib.md5", "hashlib.sha1"):
            self.add("weak-hash", "warn", line,
                     "use of %s" % name,
                     "fine for checksums, broken for security; use "
                     "sha256+ (or hmac) for anything security-relevant.")
        self.generic_visit(node)

    # -- exception hygiene -------------------------------------------------
    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.type is None:
            self.add("bare-except", "warn", node.lineno,
                     "bare `except:` catches SystemExit/KeyboardInterrupt",
                     "catch specific exceptions, or at minimum "
                     "`except Exception:`.")
        if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
            self.add("silent-except", "warn", node.lineno,
                     "exception silently swallowed (except: pass)",
                     "swallowed errors hide real failures; log, re-raise, "
                     "or handle explicitly.")
        self.generic_visit(node)

    # -- function budgets & footguns ----------------------------------------
    def _check_function(self, node) -> None:
        end = getattr(node, "end_lineno", node.lineno)
        length = end - node.lineno + 1
        if length > self.budgets["max_function_lines"]:
            self.add("function-length", "warn", node.lineno,
                     "%s is %d lines (budget %d)" % (
                         node.name, length,
                         self.budgets["max_function_lines"]),
                     "long functions hide bugs; extract helpers.")
        complexity = _complexity(node)
        if complexity > self.budgets["max_complexity"]:
            self.add("complexity", "warn", node.lineno,
                     "%s has cyclomatic complexity %d (budget %d)" % (
                         node.name, complexity,
                         self.budgets["max_complexity"]),
                     "split branches into smaller functions.")
        depth = _max_nesting(node)
        if depth > self.budgets["max_nesting"]:
            self.add("nesting", "warn", node.lineno,
                     "%s nests %d levels deep (budget %d)" % (
                         node.name, depth, self.budgets["max_nesting"]),
                     "use guard clauses / early returns to flatten.")
        for default in list(node.args.defaults) + \
                [d for d in node.args.kw_defaults if d is not None]:
            if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                self.add("mutable-default", "warn", default.lineno,
                         "mutable default argument in %s" % node.name,
                         "shared across calls; default to None and create "
                         "inside the function.")

    def visit_FunctionDef(self, node) -> None:
        self._check_function(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node) -> None:
        self._check_function(node)
        self.generic_visit(node)

    # -- string-built SQL ----------------------------------------------------
    def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
        literal = "".join(v.value for v in node.values
                          if isinstance(v, ast.Constant)
                          and isinstance(v.value, str))
        has_interp = any(isinstance(v, ast.FormattedValue)
                         for v in node.values)
        if has_interp and _SQL_RE.search(literal):
            self.add("sql-injection", "error", node.lineno,
                     "SQL statement built with an f-string",
                     "interpolating values into SQL is injection; use "
                     "parameterized queries (cursor.execute(sql, params)).")
        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        if isinstance(node.op, ast.Mod) and \
                isinstance(node.left, ast.Constant) and \
                isinstance(node.left.value, str) and \
                _SQL_RE.search(node.left.value):
            self.add("sql-injection", "error", node.lineno,
                     "SQL statement built with %-formatting",
                     "interpolating values into SQL is injection; use "
                     "parameterized queries (cursor.execute(sql, params)).")
        self.generic_visit(node)


def _complexity(fn_node) -> int:
    score = 1
    for node in ast.walk(fn_node):
        if isinstance(node, (ast.If, ast.For, ast.While, ast.IfExp,
                             ast.ExceptHandler, ast.Assert)):
            score += 1
        elif isinstance(node, ast.BoolOp):
            score += len(node.values) - 1
        elif isinstance(node, ast.comprehension):
            score += 1 + len(node.ifs)
    return score


def _max_nesting(fn_node) -> int:
    def depth(node, current):
        deepest = current
        for child in ast.iter_child_nodes(node):
            bump = 1 if isinstance(child, (ast.If, ast.For, ast.While,
                                           ast.With, ast.Try)) else 0
            deepest = max(deepest, depth(child, current + bump))
        return deepest

    return depth(fn_node, 0)


_INLINE_IGNORE_RE = re.compile(
    r"#\s*retrace-quality:\s*ignore\[([a-z\-, ]+)\]")


def _inline_ignores(source: str) -> Dict[int, set]:
    """`# retrace-quality: ignore[rule]` suppresses that rule on that line
    -- visible in the diff, reviewable, unlike a global disable."""
    ignores = {}
    for lineno, line in enumerate(source.splitlines(), 1):
        match = _INLINE_IGNORE_RE.search(line)
        if match:
            ignores[lineno] = {r.strip() for r in match.group(1).split(",")}
    return ignores


def check_source(source: str, path: str,
                 budgets: Optional[Dict[str, int]] = None,
                 disabled: Optional[List[str]] = None) -> List[Finding]:
    merged = dict(DEFAULT_BUDGETS)
    merged.update(budgets or {})
    analyzer = _Analyzer(path, merged, disabled or [])
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        analyzer.add("syntax-error", "error", exc.lineno or 0,
                     "file does not parse: %s" % exc.msg,
                     "fix the syntax error first.")
        return analyzer.findings
    analyzer.visit(tree)

    # raw-source secret scanning (catches strings the AST walk skips)
    for match in _SECRET_ASSIGN_RE.finditer(source):
        line = source[:match.start()].count("\n") + 1
        analyzer.add("hardcoded-secret", "error", line,
                     "hardcoded credential assigned to %r"
                     % match.group(1),
                     "read secrets from the environment or a secret "
                     "manager; never commit them in source.")
    for match in _TOKEN_LITERAL_RE.finditer(source):
        line = source[:match.start()].count("\n") + 1
        analyzer.add("hardcoded-secret", "error", line,
                     "credential-shaped literal in source",
                     "this looks like a real API token; revoke it and "
                     "load it from the environment instead.")

    ignores = _inline_ignores(source)
    if ignores:
        return [f for f in analyzer.findings
                if f.rule not in ignores.get(f.line, ())]
    return analyzer.findings


def check_files(paths: List[str], budgets: Optional[Dict[str, int]] = None,
                disabled: Optional[List[str]] = None) -> List[Finding]:
    findings = []
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8") as f:
                source = f.read()
        except (OSError, UnicodeDecodeError) as exc:
            findings.append(Finding(
                "unreadable", "error", path, 0,
                "cannot read file: %s" % exc,
                "the gate cannot vouch for code it cannot read; fix the "
                "path or encoding."))
            continue
        findings.extend(check_source(source, path, budgets, disabled))
    return findings


def error_count(findings: List[Finding]) -> int:
    return sum(1 for f in findings if f.severity == "error")


def render_text(findings: List[Finding]) -> str:
    lines = []
    for f in sorted(findings, key=lambda x: (x.severity != "error",
                                             x.file, x.line)):
        lines.append("%s:%d: [%s/%s] %s" % (f.file, f.line, f.severity,
                                            f.rule, f.message))
        lines.append("    hint: %s" % f.hint)
    return "\n".join(lines)
