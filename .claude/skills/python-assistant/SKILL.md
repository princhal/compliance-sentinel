---
name: python-assistant
description: |
  All-in-one Python coding assistant that generates, reviews, refactors, tests,
  and documents Python code. This skill should be used when users need help writing
  Python functions/classes, reviewing code for bugs and anti-patterns, refactoring
  for quality, generating pytest tests, or creating docstrings and documentation.
  Triggers on: "write python", "review python", "refactor", "generate tests",
  "add docstrings", "python help", "code quality".
---

# Python Assistant

Generate, review, refactor, test, and document Python code with production-grade quality.

## Scope

**Does**: Generate Python code from descriptions. Review code for bugs, anti-patterns, type issues. Refactor code for readability and performance. Generate pytest test suites. Create docstrings and documentation. Scaffold modules and packages.

**Does NOT**: Execute Python code at runtime. Manage virtual environments or dependencies. Deploy applications. Handle non-Python languages.

---

## Before Implementation

Gather context to ensure successful implementation:

| Source | Gather |
|--------|--------|
| **Codebase** | Existing structure, patterns, conventions to integrate with |
| **Conversation** | User's specific requirements, constraints, preferences |
| **Skill References** | Domain patterns from `references/` (Python best practices, style guides) |
| **User Guidelines** | Project-specific conventions, team standards |

Ensure all required context is gathered before implementing.
Only ask user for THEIR specific requirements (domain expertise is in this skill).

---

## Operations

### 1. Generate Python Code

Input: Natural language description of desired functionality.

Workflow:
1. Parse the requirement into components (inputs, outputs, side effects)
2. Determine appropriate patterns (function, class, module)
3. Generate typed Python 3.11+ code with type hints
4. Include error handling for edge cases
5. Add Google-style docstrings

Output: Complete Python code with type annotations, docstrings, error handling.

### 2. Review Python Code

Input: Python source code to review.

Checklist:
- [ ] Type hint coverage on all public functions
- [ ] No bare `except:` clauses — catch specific exceptions
- [ ] No mutable default arguments (`def f(x=[])`)
- [ ] No global mutable state without thread safety
- [ ] f-strings preferred over `.format()` or `%`
- [ ] Path handling uses `pathlib.Path`, not string concatenation
- [ ] No `import *` in non-`__init__` modules
- [ ] Resource cleanup uses context managers (`with`)
- [ ] No hardcoded secrets or credentials
- [ ] OWASP input validation at system boundaries

Output: Issue list with severity (Critical/Warning/Info), line references, fix suggestions.

### 3. Refactor Python Code

Input: Python code + refactoring goal (readability, performance, DRY, typing).

Strategies:
- Extract repeated logic into functions
- Replace nested conditionals with early returns/guard clauses
- Convert classes to dataclasses or NamedTuples where appropriate
- Use comprehensions over explicit loops where readable
- Apply single-responsibility principle to large functions
- Replace magic numbers/strings with named constants

Output: Refactored code + summary of changes with rationale.

### 4. Generate Tests

Input: Python code to test.

Workflow:
1. Identify testable units (functions, methods, classes)
2. Determine test categories: happy path, edge cases, error cases
3. Generate pytest tests with descriptive names (`test_<func>_<scenario>`)
4. Use `@pytest.fixture` for shared setup
5. Use `@pytest.mark.parametrize` for input variations
6. Mock external dependencies with `unittest.mock`
7. Assert specific exceptions with `pytest.raises`

Output: Complete pytest file with fixtures, parametrized tests, mocks.

### 5. Document Python Code

Input: Python code lacking documentation.

Generate:
- Module-level docstring (purpose, usage example)
- Class docstrings (purpose, attributes, example)
- Method/function docstrings (Google style: Args, Returns, Raises)
- Inline comments only where logic is non-obvious

Output: Documented code with Google-style docstrings.

---

## Decision Tree

```
User request
│
├─ "Write/create/generate [Python]" → Operation 1: Generate
├─ "Review/check/audit [code]"     → Operation 2: Review
├─ "Refactor/improve/clean [code]" → Operation 3: Refactor
├─ "Test/add tests [for code]"     → Operation 4: Generate Tests
├─ "Document/docstring [code]"     → Operation 5: Document
└─ Ambiguous                       → Ask: "Generate, review, refactor, test, or document?"
```

---

## Required Clarifications

1. **Operation** — Which operation? (if not obvious from request)
2. **Python version** — Target version? (default: 3.11+)
3. **Style guide** — PEP 8, Google, or project-specific? (default: PEP 8 + Google docstrings)

## Optional Clarifications

4. **Test framework** — pytest (default), unittest, or other?
5. **Type strictness** — Full typing or gradual? (default: full)

---

## Must Follow

- [ ] All generated code uses type hints (PEP 484/585)
- [ ] All public functions have Google-style docstrings
- [ ] Error handling catches specific exceptions, never bare `except:`
- [ ] Tests use pytest conventions and descriptive names
- [ ] No mutable default arguments
- [ ] f-strings for string formatting
- [ ] `pathlib.Path` for file paths
- [ ] Context managers for resource cleanup
- [ ] No hardcoded secrets

## Must Avoid

- Generating Python 2 syntax
- Using `type: ignore` without justification
- Overly abstract code (prefer explicit over clever)
- Tests that depend on execution order
- Docstrings that just repeat the function signature
- `from module import *` outside `__init__.py`

---

## Output Checklist

Before delivering any output:

- [ ] Code runs on Python 3.11+ without syntax errors
- [ ] All public APIs have type hints and docstrings
- [ ] No security vulnerabilities (OWASP top 10)
- [ ] Tests cover happy path + at least 2 edge cases
- [ ] Refactored code preserves original behavior
- [ ] Review findings include severity and fix suggestions

---

## Reference Files

| File | When to Read |
|------|--------------|
| `references/python-patterns.md` | Best practices, anti-patterns, style guide details |
