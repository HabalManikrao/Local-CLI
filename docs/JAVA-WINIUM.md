# Java & Winium Intelligence

Static, evidence-backed analysis of Java and Winium automation code. **Analysis
never changes code** — it reports findings you act on (or feed to `cle code`).

```bash
cle java analyze      # general Java quality
cle winium analyze    # Winium/automation smells
```

## Finding format

```
HIGH  Thread.sleep() detected  (brittle-wait)
  File: src/pages/LoginPage.java
  Line: 143
  Code: Thread.sleep(2000);
  Recommendation: Replace fixed sleep with an explicit wait (WebDriverWait/until).
```

Severities: `HIGH` > `MEDIUM` > `LOW` > `INFO`. Findings are comment-safe (the
source is comment/string-stripped before matching, preserving line numbers).

## Java rules (`cle java analyze`)

| Category            | Severity | Trigger                                  |
|---------------------|----------|------------------------------------------|
| exception-handling  | MEDIUM   | empty `catch (...) {}`                    |
| exception-handling  | LOW      | `printStackTrace()`                       |
| logging             | LOW      | `System.out/err.print...`                 |
| unnecessary-sleep   | MEDIUM   | `Thread.sleep(...)`                        |
| long-method         | LOW      | method/constructor > 80 lines (from index)|
| todo                | INFO     | `TODO`/`FIXME`                            |

## Winium rules (`cle winium analyze`)

| Category           | Severity     | Trigger                                          |
|--------------------|--------------|--------------------------------------------------|
| brittle-wait       | HIGH         | `Thread.sleep(...)`                               |
| driver-lifecycle   | MEDIUM/INFO  | `new WiniumDriver(...)` — MEDIUM if no `.quit()/.close()` anywhere, else INFO |
| brittle-locator    | MEDIUM       | absolute/near-absolute `By.xpath("/...")`         |
| duplicated-locator | MEDIUM       | same locator string used in >1 place              |
| accessibility-id   | INFO         | `By.accessibilityId` / `findElementByAccessibilityId` (good practice) |
| screenshot         | INFO         | `getScreenshotAs(...)`                             |

Detected Winium/automation signals include: WiniumDriver, driver
initialization & lifecycle, element lookup, XPath, accessibility IDs, waits,
`Thread.sleep()`, page objects, screenshots, logging, and JUnit/TestNG usage.

## Workflow

1. `cle winium analyze` → review findings.
2. Fix manually, or drive a change with `cle code "replace the Thread.sleep in
   LoginPage.login with an explicit wait"` (which plans, previews, and asks
   before editing).
3. `cle test` to verify.
