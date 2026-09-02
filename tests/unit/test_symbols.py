"""Symbol extraction tests (Java heuristic + Python ast)."""

from __future__ import annotations

from pathlib import Path

from cle.indexing.symbols import detect_language, parse_source

JAVA = """\
package com.example.login;

import java.util.List;
import static org.junit.Assert.assertTrue;

@Service
public class LoginPage extends BasePage implements Clickable {

    private final WiniumDriver driver;
    public static final String URL = "app://login";

    public LoginPage(WiniumDriver driver) {
        this.driver = driver;
    }

    @Override
    public void login(String user, String pass) {
        driver.findElement(By.name("user")).sendKeys(user);
        if (user != null) {
            Thread.sleep(1000);
        }
    }

    private boolean isLoaded() {
        return true;
    }
}
"""


def _by_kind(parse, kind):
    return [s for s in parse.symbols if s.kind == kind]


def test_detect_language():
    assert detect_language(Path("A.java")) == "java"
    assert detect_language(Path("a.py")) == "python"
    assert detect_language(Path("a.unknown")) is None


def test_java_package_and_imports():
    p = parse_source(Path("LoginPage.java"), JAVA)
    pkgs = _by_kind(p, "package")
    assert pkgs and pkgs[0].name == "com.example.login"
    targets = {imp.target for imp in p.imports}
    assert "java.util.List" in targets
    assert "org.junit.Assert.assertTrue" in targets


def test_java_class_with_inheritance():
    p = parse_source(Path("LoginPage.java"), JAVA)
    classes = _by_kind(p, "class")
    assert len(classes) == 1
    cls = classes[0]
    assert cls.name == "LoginPage"
    assert cls.extra.get("extends") == ["BasePage"]
    assert cls.extra.get("implements") == ["Clickable"]
    assert "Service" in cls.extra.get("annotations", [])
    assert cls.line_end and cls.line_end > cls.line_start


def test_java_methods_and_constructor():
    p = parse_source(Path("LoginPage.java"), JAVA)
    methods = {s.name for s in _by_kind(p, "method")}
    assert "login" in methods
    assert "isLoaded" in methods
    ctors = _by_kind(p, "constructor")
    assert ctors and ctors[0].name == "LoginPage"
    # Control-flow keywords must not be captured as methods.
    assert "if" not in methods


def test_java_fields():
    p = parse_source(Path("LoginPage.java"), JAVA)
    fields = {s.name for s in _by_kind(p, "field")}
    assert "driver" in fields
    assert "URL" in fields


def test_java_method_parent_is_class():
    p = parse_source(Path("LoginPage.java"), JAVA)
    login = next(s for s in p.symbols if s.name == "login" and s.kind == "method")
    assert login.parent == "LoginPage"


def test_java_ignores_commented_code():
    src = (
        "public class C {\n"
        "  // public void ghost() {}\n"
        "  /* public void ghost2() {} */\n"
        "  public void real() {}\n"
        "}\n"
    )
    p = parse_source(Path("C.java"), src)
    names = {s.name for s in p.symbols if s.kind == "method"}
    assert names == {"real"}


PY = """\
import os
from pathlib import Path

class Widget:
    def __init__(self):
        pass

    def render(self):
        return 1

def helper():
    return 2
"""


def test_python_symbols():
    p = parse_source(Path("m.py"), PY)
    classes = _by_kind(p, "class")
    assert classes and classes[0].name == "Widget"
    methods = {s.name for s in _by_kind(p, "method")}
    assert {"__init__", "render"} <= methods
    funcs = {s.name for s in _by_kind(p, "function")}
    assert "helper" in funcs
    targets = {imp.target for imp in p.imports}
    assert "os" in targets and "pathlib" in targets
