"""Java + Winium analyzer tests with realistic fixtures."""

from __future__ import annotations

import pytest

from cle.analysis.java import analyze_java
from cle.analysis.winium import analyze_winium

LOGIN_PAGE = """\
package com.example.pages;

import org.openqa.selenium.By;
import org.winium.WiniumDriver;

public class LoginPage {
    private WiniumDriver driver;

    public LoginPage() {
        driver = new WiniumDriver(/* ... */);
    }

    public void login(String user) {
        driver.findElement(By.xpath("//Window/Edit[1]")).sendKeys(user);
        Thread.sleep(2000);
        try {
            driver.findElement(By.id("submit")).click();
        } catch (Exception e) {
        }
        System.out.println("logged in");
    }

    public void logout() {
        driver.findElement(By.xpath("//Window/Edit[1]")).click();  // duplicate locator
    }
}
"""


@pytest.fixture
def java_project(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "LoginPage.java").write_text(LOGIN_PAGE, encoding="utf-8")
    return tmp_path


@pytest.mark.integration
def test_winium_flags_sleep_high(java_project):
    findings = analyze_winium(java_project)
    sleeps = [f for f in findings if f.category == "brittle-wait"]
    assert sleeps and sleeps[0].severity == "HIGH"
    assert sleeps[0].line == 15  # Thread.sleep line


@pytest.mark.integration
def test_winium_flags_missing_teardown(java_project):
    findings = analyze_winium(java_project)
    lifecycle = [f for f in findings if f.category == "driver-lifecycle"]
    assert lifecycle and lifecycle[0].severity == "MEDIUM"


@pytest.mark.integration
def test_winium_flags_absolute_xpath(java_project):
    findings = analyze_winium(java_project)
    assert any(f.category == "brittle-locator" for f in findings)


@pytest.mark.integration
def test_winium_flags_duplicated_locator(java_project):
    findings = analyze_winium(java_project)
    dups = [f for f in findings if f.category == "duplicated-locator"]
    assert dups
    assert "//Window/Edit[1]" in dups[0].title


@pytest.mark.integration
def test_winium_teardown_present_is_info(tmp_path):
    src = (
        "public class T {\n"
        "  void a() { d = new WiniumDriver(); }\n"
        "  void z() { d.quit(); }\n"
        "}\n"
    )
    (tmp_path / "T.java").write_text(src, encoding="utf-8")
    findings = analyze_winium(tmp_path)
    lifecycle = [f for f in findings if f.category == "driver-lifecycle"]
    assert lifecycle and lifecycle[0].severity == "INFO"


@pytest.mark.integration
def test_java_flags_empty_catch_and_sysout(java_project):
    findings = analyze_java(java_project)
    cats = {f.category for f in findings}
    assert "exception-handling" in cats  # empty catch
    assert "logging" in cats             # System.out
    assert "unnecessary-sleep" in cats   # Thread.sleep


@pytest.mark.integration
def test_java_ignores_commented_code(tmp_path):
    src = (
        "public class C {\n"
        "  void a() {\n"
        "    // Thread.sleep(999);\n"
        "  }\n"
        "}\n"
    )
    (tmp_path / "C.java").write_text(src, encoding="utf-8")
    findings = analyze_java(tmp_path)
    assert not any(f.category == "unnecessary-sleep" for f in findings)


@pytest.mark.integration
def test_no_java_returns_empty(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    assert analyze_java(tmp_path) == []
    assert analyze_winium(tmp_path) == []
