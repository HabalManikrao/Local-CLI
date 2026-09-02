"""Build-system detection and failure parsing."""

from __future__ import annotations

from cle.tools.test_runner import (
    BuildSystem,
    detect_build_system,
    parse_failures,
)


def test_detect_maven(tmp_path):
    (tmp_path / "pom.xml").write_text("<project/>", encoding="utf-8")
    system, cmd = detect_build_system(tmp_path)
    assert system == BuildSystem.MAVEN
    assert cmd[0] == "mvn"


def test_detect_gradle_wrapper(tmp_path):
    (tmp_path / "build.gradle").write_text("", encoding="utf-8")
    (tmp_path / "gradlew.bat").write_text("", encoding="utf-8")
    system, cmd = detect_build_system(tmp_path)
    assert system == BuildSystem.GRADLE
    assert "gradlew.bat" in cmd


def test_detect_python(tmp_path):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    system, cmd = detect_build_system(tmp_path)
    assert system == BuildSystem.PYTHON
    assert cmd[-2:] == ["-m", "pytest"]


def test_detect_unknown(tmp_path):
    system, cmd = detect_build_system(tmp_path)
    assert system == BuildSystem.UNKNOWN
    assert cmd == []


def test_maven_takes_priority_over_python(tmp_path):
    (tmp_path / "pom.xml").write_text("<project/>", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    system, _ = detect_build_system(tmp_path)
    assert system == BuildSystem.MAVEN


PYTEST_OUTPUT = """\
tests/test_a.py::test_ok PASSED
tests/test_a.py::test_bad FAILED
=================================== FAILURES ===================================
tests/test_a.py:12: in test_bad
    assert 1 == 2
FAILED tests/test_a.py::test_bad - assert 1 == 2
=========================== 1 failed, 1 passed in 0.1s =========================
"""


def test_parse_pytest_failures():
    failures = parse_failures(PYTEST_OUTPUT, BuildSystem.PYTHON)
    assert len(failures) == 1
    f = failures[0]
    assert f.name == "tests/test_a.py::test_bad"
    assert f.file == "tests/test_a.py"
    assert "assert 1 == 2" in f.message


MAVEN_OUTPUT = """\
[ERROR] Tests run: 2, Failures: 1, Errors: 0, Skipped: 0
[ERROR] testLogin(com.example.LoginTest)  Time elapsed: 0.1 s  <<< FAILURE!
java.lang.AssertionError: expected true
    at com.example.LoginTest.testLogin(LoginTest.java:42)
"""


def test_parse_maven_failures():
    failures = parse_failures(MAVEN_OUTPUT, BuildSystem.MAVEN)
    assert len(failures) == 1
    f = failures[0]
    assert f.name == "com.example.LoginTest.testLogin"
    assert f.file == "LoginTest.java"
    assert f.line == 42


def test_parse_no_failures():
    assert parse_failures("all good", BuildSystem.PYTHON) == []
