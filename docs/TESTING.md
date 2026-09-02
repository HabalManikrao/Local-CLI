# Testing & Debugging

CLE both **runs** the project's tests (test/debug agents) and **is tested**
itself (its own suite). This page covers both.

## Test / debug / fix-tests commands

```bash
cle test          # detect build system, run tests, report failures
cle debug         # run tests; if failing, diagnose root cause (no changes)
cle fix-tests     # bounded loop: run → propose fix → approve → apply → re-run
```

### Build-system detection

| Marker                         | System | Command                         |
|--------------------------------|--------|----------------------------------|
| `pom.xml`                      | Maven  | `mvn -B test`                    |
| `build.gradle[.kts]` / wrapper | Gradle | `gradlew test` / `gradle test`   |
| `pyproject.toml` / `tests/`    | Python | `<python> -m pytest`             |

Override with a stored command: `cle memory set test_command "mvn -q test"`.
Java runners (JUnit/TestNG) are exercised through Maven/Gradle.

### Failure parsing

- **pytest** — `FAILED path::test - message` + `path:line: in test`.
- **Maven/Gradle (surefire)** — `method(pkg.ClassTest) ... <<< FAILURE!` +
  `at pkg.ClassTest.method(ClassTest.java:line)`.

Parsed failures carry test name, file, line, and message.

### `cle fix-tests` (bounded)

```
loop up to agent.max_iterations (default 5, --max-iter to override):
  run tests
    pass? -> done (exit 0)
  build a fix request from the failures (debug agent)
  coding agent plans a fix (JSON edit plan)
  show plan + diff -> approval (--yes to skip)
  git checkpoint -> apply -> re-run
exhausted -> exit 1 (never loops forever)
```

The debug agent frames the failures; the coding agent proposes source changes
(it is told **not** to weaken tests unless they are clearly wrong). Every fix
goes through the same approval + checkpoint path as `cle code`.

## CLE's own test suite

```bash
pytest                 # full suite — fully offline, no Ollama daemon needed
pytest tests/unit      # fast unit tests
pytest -m integration  # integration (temp git repos, sqlite, ripgrep)
pytest -m e2e          # end-to-end (CLI + a real pytest subprocess)
```

- All model interaction is faked (`FakeProvider`) or mocked
  (`httpx.MockTransport`), so the suite runs without a daemon.
- The `fix-tests` e2e test creates a real failing pytest project, runs the
  loop, and asserts the source was fixed and tests pass.
