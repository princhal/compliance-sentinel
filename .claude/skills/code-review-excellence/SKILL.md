---
name: code-review-excellence
description: Master effective code review practices to provide constructive feedback, catch bugs early, and foster knowledge sharing while maintaining team morale. Use when reviewing pull requests, establishing review standards, mentoring developers, or generating code review training content. Use PROACTIVELY when the user mentions code review, PR review, review standards, or feedback quality.
---

# Code Review Excellence

Provides guidelines and reusable practices for conducting high-quality code reviews that shift reviews from gatekeeping to collaborative learning.

## When to Use

- Reviewing pull requests
- Defining team review standards
- Mentoring developers on review practices
- Performing architecture reviews
- Generating realistic code review scenarios for training
- Creating code review rubrics and scoring templates

## Core Principles

### 1. Collaborative Over Gatekeeping

Code review should be a learning opportunity for both reviewer and author. The goal is shared understanding and code quality, not demonstrating superiority.

### 2. Specific, Actionable, Non-Judgmental Feedback

Every piece of feedback should follow the SAN framework:

- **Specific**: Point to exact lines/patterns, not vague concerns
- **Actionable**: Include a concrete suggestion or alternative
- **Non-judgmental**: Focus on the code, not the coder

**Bad feedback:**
> "This is wrong."
> "Why would you do it this way?"

**Good feedback:**
> "This loop could throw an IndexError when `items` is empty. Consider adding an early return: `if not items: return []`"

### 3. Prioritized Review Checklist

Review in this order of importance:

1. **Logic & Correctness** — Does it do what it claims?
2. **Security** — SQL injection, XSS, hardcoded secrets, unsafe deserialization
3. **Performance** — O(n²) where O(n) is possible, unnecessary DB queries, memory leaks
4. **Test Coverage** — Are edge cases tested? Are assertions meaningful?
5. **API Design** — Is the interface intuitive? Will it break existing consumers?
6. **Readability** — Naming, structure, comments (only for non-obvious logic)
7. **Style** — Leave to linters/formatters. Do NOT nitpick formatting.

### 4. What NOT to Review Manually

Delegate to automated tools:
- Formatting and indentation (Prettier, Black, gofmt)
- Import ordering
- Trailing whitespace
- Line length
- Unused variables (linters catch these)

## Review Process

### Phase 1: Context Gathering (Before Reading Code)

1. Read the PR description and linked issue
2. Understand the "why" — what problem is being solved?
3. Check the test plan
4. Note the scope — is this a focused change or a sprawling refactor?

### Phase 2: Focused Review

1. Start with the test files — they reveal intent
2. Review the main logic changes
3. Check edge cases and error handling
4. Verify naming and abstraction levels
5. Look for missing tests

### Phase 3: Writing Feedback

Use these feedback templates:

**Bug/Defect:**
> `[Bug]` Line 42: `user.name` can be `null` here because the API returns partial user objects for deleted accounts. This will throw a TypeError. Suggestion: `user.name ?? 'Unknown User'`

**Suggestion:**
> `[Suggestion]` This could be simplified using a dictionary comprehension: `{k: v for k, v in items.items() if v > threshold}`

**Question:**
> `[Question]` I'm not sure I understand the intent here — is this handling the case where the session expires mid-request? If so, a comment explaining the scenario would help future readers.

**Praise:**
> `[Praise]` Great use of the Strategy pattern here — it makes adding new payment providers much cleaner.

### Phase 4: Follow-Up

1. Re-review addressed comments promptly
2. Approve when concerns are resolved — don't block on preferences
3. Escalate design concerns to architecture discussions, not PR comments

## Review Scope Rules

| Change Type | Review Depth |
|---|---|
| Bug fix (< 50 lines) | Full review, focus on regression |
| Feature (50-300 lines) | Full review with architecture check |
| Large feature (300+ lines) | Request split if possible |
| Refactor (no behavior change) | Verify tests pass, spot-check logic |
| Config/dependency update | Verify versions, check changelogs |
| Documentation only | Light review for accuracy |

## Scoring Rubric for Code Quality

Use this rubric when scoring code (1-5 scale):

| Dimension | 1 (Poor) | 3 (Acceptable) | 5 (Excellent) |
|---|---|---|---|
| **Correctness** | Logic errors, crashes | Works for happy path | Handles all edge cases |
| **Readability** | Cryptic names, no structure | Readable with effort | Self-documenting |
| **Performance** | Obvious inefficiency | Adequate for use case | Optimized appropriately |
| **Security** | Known vulnerabilities | No obvious issues | Defense in depth |
| **Test Coverage** | No tests | Happy path tested | Edge cases + error paths |
| **Maintainability** | Tightly coupled | Modular with some coupling | Clean separation of concerns |

## Anti-Patterns to Flag

1. **God Functions** — Functions doing more than one thing (> 30 lines is a smell)
2. **Magic Numbers** — Unexplained numeric literals
3. **Swallowed Exceptions** — Empty catch blocks
4. **Copy-Paste Code** — Duplicated logic across files
5. **Premature Optimization** — Complexity without measured need
6. **Missing Input Validation** — Trusting external input
7. **Inconsistent Error Handling** — Mix of exceptions, error codes, and nulls
8. **Commented-Out Code** — Dead code that creates confusion

## Benefits of This Approach

- Earlier bug detection (shift-left)
- Faster review cycles (clear expectations)
- Stronger test coverage (test-first review)
- Improved maintainability (consistent standards)
- Richer knowledge sharing (learning-oriented feedback)
- Higher team morale (collaborative, not adversarial)
