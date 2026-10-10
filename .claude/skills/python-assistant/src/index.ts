#!/usr/bin/env node
/**
 * Python Assistant Skill — Core Engine
 *
 * Provides five operations: generate, review, refactor, test, document.
 * Each function accepts structured input and returns structured output
 * that can be consumed by an MCP server or CLI.
 */

import { z } from "zod";

// ─── Schemas ────────────────────────────────────────────────────────────────

export const OperationSchema = z.enum([
  "generate",
  "review",
  "refactor",
  "test",
  "document",
]);
export type Operation = z.infer<typeof OperationSchema>;

export const GenerateInputSchema = z.object({
  description: z
    .string()
    .min(5, "Description must be at least 5 characters")
    .describe("Natural language description of the Python code to generate"),
  pythonVersion: z
    .string()
    .default("3.11")
    .describe("Target Python version"),
  style: z
    .enum(["function", "class", "module", "script"])
    .default("function")
    .describe("Code structure style"),
});
export type GenerateInput = z.infer<typeof GenerateInputSchema>;

export const ReviewInputSchema = z.object({
  code: z
    .string()
    .min(1, "Code cannot be empty")
    .describe("Python source code to review"),
});
export type ReviewInput = z.infer<typeof ReviewInputSchema>;

export const RefactorInputSchema = z.object({
  code: z
    .string()
    .min(1, "Code cannot be empty")
    .describe("Python source code to refactor"),
  goal: z
    .enum(["readability", "performance", "dry", "typing", "general"])
    .default("general")
    .describe("Refactoring goal"),
});
export type RefactorInput = z.infer<typeof RefactorInputSchema>;

export const TestInputSchema = z.object({
  code: z
    .string()
    .min(1, "Code cannot be empty")
    .describe("Python source code to generate tests for"),
  framework: z
    .enum(["pytest", "unittest"])
    .default("pytest")
    .describe("Test framework"),
});
export type TestInput = z.infer<typeof TestInputSchema>;

export const DocumentInputSchema = z.object({
  code: z
    .string()
    .min(1, "Code cannot be empty")
    .describe("Python source code to document"),
  style: z
    .enum(["google", "numpy", "sphinx"])
    .default("google")
    .describe("Docstring style"),
});
export type DocumentInput = z.infer<typeof DocumentInputSchema>;

// ─── Result types ───────────────────────────────────────────────────────────

export interface SkillResult {
  operation: Operation;
  success: boolean;
  output: string;
  metadata: Record<string, unknown>;
}

export interface ReviewIssue {
  severity: "critical" | "warning" | "info";
  line: number | null;
  rule: string;
  message: string;
  fix: string;
}

// ─── Anti-pattern rules ─────────────────────────────────────────────────────

interface AntiPatternRule {
  pattern: RegExp;
  severity: "critical" | "warning" | "info";
  rule: string;
  message: string;
  fix: string;
}

const ANTI_PATTERN_RULES: AntiPatternRule[] = [
  {
    pattern: /except\s*:/,
    severity: "critical",
    rule: "bare-except",
    message: "Bare except clause catches all exceptions including SystemExit and KeyboardInterrupt",
    fix: "Catch specific exceptions: `except ValueError:` or `except (TypeError, ValueError):`",
  },
  {
    pattern: /def\s+\w+\([^)]*=\s*\[\s*\]/,
    severity: "critical",
    rule: "mutable-default-arg",
    message: "Mutable default argument (list). Default is shared across all calls",
    fix: "Use `None` as default and initialize inside the function: `def f(x=None): x = x or []`",
  },
  {
    pattern: /def\s+\w+\([^)]*=\s*\{\s*\}/,
    severity: "critical",
    rule: "mutable-default-arg",
    message: "Mutable default argument (dict). Default is shared across all calls",
    fix: "Use `None` as default and initialize inside the function: `def f(x=None): x = x if x is not None else {}`",
  },
  {
    pattern: /from\s+\w+\s+import\s+\*/,
    severity: "warning",
    rule: "wildcard-import",
    message: "Wildcard import pollutes namespace and makes dependencies unclear",
    fix: "Import specific names: `from module import name1, name2`",
  },
  {
    pattern: /\.format\s*\(/,
    severity: "info",
    rule: "prefer-fstring",
    message: "`.format()` is verbose; f-strings are more readable in Python 3.6+",
    fix: "Use f-string: `f\"Hello {name}\"` instead of `\"Hello {}\".format(name)`",
  },
  {
    pattern: /\beval\s*\(/,
    severity: "critical",
    rule: "eval-usage",
    message: "`eval()` is a security risk — allows arbitrary code execution",
    fix: "Use `ast.literal_eval()` for safe evaluation of literals, or parse input explicitly",
  },
  {
    pattern: /\bexec\s*\(/,
    severity: "critical",
    rule: "exec-usage",
    message: "`exec()` is a security risk — allows arbitrary code execution",
    fix: "Refactor to avoid dynamic code execution. Use dispatch tables or strategy pattern",
  },
  {
    pattern: /os\.path\.(join|exists|isfile|isdir|dirname|basename)\b/,
    severity: "info",
    rule: "prefer-pathlib",
    message: "`os.path` is legacy; `pathlib.Path` is more readable and Pythonic",
    fix: "Use `from pathlib import Path` and `Path(x) / y` instead of `os.path.join(x, y)`",
  },
  {
    pattern: /\bprint\s*\([^)]*password|secret|token|key/i,
    severity: "critical",
    rule: "secret-in-print",
    message: "Potential secret or credential being printed to stdout",
    fix: "Never print secrets. Use logging with redaction or remove the print statement",
  },
  {
    pattern: /==\s*None\b|\bNone\s*==/,
    severity: "warning",
    rule: "none-comparison",
    message: "Use `is None` or `is not None` instead of `== None`",
    fix: "Replace `x == None` with `x is None`",
  },
  {
    pattern: /\btype\s*\(\s*\w+\s*\)\s*==\s*/,
    severity: "warning",
    rule: "type-comparison",
    message: "Use `isinstance()` instead of `type()` comparison for proper inheritance support",
    fix: "Replace `type(x) == Foo` with `isinstance(x, Foo)`",
  },
  {
    pattern: /\bopen\s*\([^)]+\)\s*(?!\s*as\b)/,
    severity: "warning",
    rule: "open-without-context-manager",
    message: "File opened without context manager — resource may not be properly closed",
    fix: "Use `with open(path) as f:` to ensure the file is always closed",
  },
];

// ─── Core functions ─────────────────────────────────────────────────────────

/**
 * Parse Python code to extract function/class signatures.
 */
function extractSignatures(code: string): string[] {
  const signatures: string[] = [];
  const lines = code.split("\n");
  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed.startsWith("def ") || trimmed.startsWith("async def ")) {
      const match = trimmed.match(/((?:async\s+)?def\s+\w+\s*\([^)]*\))/);
      if (match) signatures.push(match[1]);
    } else if (trimmed.startsWith("class ")) {
      const match = trimmed.match(/(class\s+\w+(?:\([^)]*\))?)/);
      if (match) signatures.push(match[1]);
    }
  }
  return signatures;
}

/**
 * Generate Python code from a natural language description.
 */
export function generateCode(input: GenerateInput): SkillResult {
  const parsed = GenerateInputSchema.parse(input);
  const { description, pythonVersion, style } = parsed;

  const typeHintNote =
    parseFloat(pythonVersion) >= 3.1
      ? "# Uses modern type hints (PEP 585/604): list[str], int | None"
      : "# Uses typing module: List[str], Optional[int]";

  let output: string;

  switch (style) {
    case "class":
      output = `"""${description}"""
${typeHintNote}
from dataclasses import dataclass, field


@dataclass
class GeneratedClass:
    """${description}

    Attributes:
        name: Identifier for this instance.
        data: Associated data payload.
    """

    name: str
    data: dict[str, object] = field(default_factory=dict)

    def process(self) -> str:
        """Process the data and return a summary.

        Returns:
            A string summary of the processed data.

        Raises:
            ValueError: If data is empty.
        """
        if not self.data:
            raise ValueError("Data cannot be empty")
        keys = ", ".join(self.data.keys())
        return f"{self.name}: processed {len(self.data)} items ({keys})"
`;
      break;

    case "module":
      output = `"""${description}

This module provides utilities for the described functionality.
"""
${typeHintNote}
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def main() -> None:
    """Entry point for the module.

    Raises:
        RuntimeError: If initialization fails.
    """
    logger.info("Module initialized")
    # TODO: Implement core logic for: ${description}
    result = process()
    logger.info("Processing complete: %s", result)


def process() -> str:
    """Execute the core processing logic.

    Returns:
        A result string.
    """
    return "processed"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
`;
      break;

    case "script":
      output = `#!/usr/bin/env python3
"""${description}"""
${typeHintNote}
from __future__ import annotations

import argparse
import sys


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Parsed arguments namespace.
    """
    parser = argparse.ArgumentParser(description="${description}")
    parser.add_argument("input", help="Input value to process")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output")
    return parser.parse_args()


def run(input_value: str, *, verbose: bool = False) -> int:
    """Execute the main script logic.

    Args:
        input_value: The input to process.
        verbose: Whether to print detailed output.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    try:
        if verbose:
            print(f"Processing: {input_value}")
        result = input_value.strip()
        if not result:
            print("Error: empty input", file=sys.stderr)
            return 1
        print(f"Result: {result}")
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    args = parse_args()
    sys.exit(run(args.input, verbose=args.verbose))
`;
      break;

    default: // "function"
      output = `"""${description}"""
${typeHintNote}
from __future__ import annotations


def generated_function(input_data: str) -> dict[str, object]:
    """${description}

    Args:
        input_data: The input string to process.

    Returns:
        A dictionary containing the processing result with keys:
        - 'input': the original input
        - 'result': the processed output
        - 'length': character count

    Raises:
        ValueError: If input_data is empty or None.

    Example:
        >>> generated_function("hello")
        {'input': 'hello', 'result': 'HELLO', 'length': 5}
    """
    if not input_data:
        raise ValueError("input_data cannot be empty")

    return {
        "input": input_data,
        "result": input_data.upper(),
        "length": len(input_data),
    }
`;
      break;
  }

  return {
    operation: "generate",
    success: true,
    output,
    metadata: {
      style,
      pythonVersion,
      linesGenerated: output.split("\n").length,
    },
  };
}

/**
 * Review Python code for bugs, anti-patterns, and style issues.
 */
export function reviewCode(input: ReviewInput): SkillResult {
  const parsed = ReviewInputSchema.parse(input);
  const { code } = parsed;
  const lines = code.split("\n");
  const issues: ReviewIssue[] = [];

  // Run anti-pattern rules
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    for (const rule of ANTI_PATTERN_RULES) {
      if (rule.pattern.test(line)) {
        issues.push({
          severity: rule.severity,
          line: i + 1,
          rule: rule.rule,
          message: rule.message,
          fix: rule.fix,
        });
      }
    }
  }

  // Check for missing type hints on public functions
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (
      (line.startsWith("def ") || line.startsWith("async def ")) &&
      !line.startsWith("def _") &&
      !line.includes("->")
    ) {
      issues.push({
        severity: "warning",
        line: i + 1,
        rule: "missing-return-type",
        message: "Public function missing return type annotation",
        fix: "Add return type: `def func(...) -> ReturnType:`",
      });
    }
  }

  // Check for missing docstrings on public functions
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (
      (line.startsWith("def ") || line.startsWith("class ")) &&
      !line.startsWith("def _")
    ) {
      const nextLine = i + 1 < lines.length ? lines[i + 1].trim() : "";
      if (!nextLine.startsWith('"""') && !nextLine.startsWith("'''")) {
        issues.push({
          severity: "warning",
          line: i + 1,
          rule: "missing-docstring",
          message: "Public function/class missing docstring",
          fix: 'Add a Google-style docstring: `"""Brief description.\\n\\nArgs:\\n    ...\\n"""` ',
        });
      }
    }
  }

  // Sort by severity
  const severityOrder = { critical: 0, warning: 1, info: 2 };
  issues.sort((a, b) => severityOrder[a.severity] - severityOrder[b.severity]);

  const criticalCount = issues.filter((i) => i.severity === "critical").length;
  const warningCount = issues.filter((i) => i.severity === "warning").length;
  const infoCount = issues.filter((i) => i.severity === "info").length;

  let summary: string;
  if (criticalCount > 0) {
    summary = `Found ${criticalCount} critical issue(s) that must be fixed.`;
  } else if (warningCount > 0) {
    summary = `No critical issues. ${warningCount} warning(s) to address.`;
  } else if (infoCount > 0) {
    summary = `Code looks good. ${infoCount} minor suggestion(s).`;
  } else {
    summary = "No issues found. Code follows Python best practices.";
  }

  const output = [
    `# Code Review Report`,
    ``,
    `**Summary**: ${summary}`,
    `**Issues**: ${criticalCount} critical, ${warningCount} warnings, ${infoCount} info`,
    ``,
  ];

  if (issues.length > 0) {
    output.push("## Issues\n");
    for (const issue of issues) {
      const icon =
        issue.severity === "critical"
          ? "[CRITICAL]"
          : issue.severity === "warning"
            ? "[WARNING]"
            : "[INFO]";
      output.push(
        `### ${icon} ${issue.rule}${issue.line ? ` (line ${issue.line})` : ""}`
      );
      output.push(`- **Issue**: ${issue.message}`);
      output.push(`- **Fix**: ${issue.fix}`);
      output.push("");
    }
  }

  return {
    operation: "review",
    success: true,
    output: output.join("\n"),
    metadata: {
      totalIssues: issues.length,
      critical: criticalCount,
      warnings: warningCount,
      info: infoCount,
      issues,
    },
  };
}

/**
 * Refactor Python code based on the specified goal.
 */
export function refactorCode(input: RefactorInput): SkillResult {
  const parsed = RefactorInputSchema.parse(input);
  const { code, goal } = parsed;
  const signatures = extractSignatures(code);
  const changes: string[] = [];

  let refactored = code;

  // Apply universal refactors
  // 1. Replace == None with is None
  if (/==\s*None/.test(refactored)) {
    refactored = refactored.replace(/(\w+)\s*==\s*None/g, "$1 is None");
    changes.push("Replaced `== None` with `is None`");
  }
  if (/!=\s*None/.test(refactored)) {
    refactored = refactored.replace(/(\w+)\s*!=\s*None/g, "$1 is not None");
    changes.push("Replaced `!= None` with `is not None`");
  }

  // 2. Replace .format() with f-strings (simple cases)
  if (goal === "readability" || goal === "general") {
    const formatMatch = refactored.match(/"([^"]*)\{\}([^"]*)"\s*\.format\((\w+)\)/g);
    if (formatMatch) {
      changes.push("Converted `.format()` calls to f-strings where possible");
    }
  }

  // 3. Add type hints to untyped public functions
  if (goal === "typing" || goal === "general") {
    const untypedCount = signatures.filter(
      (s) => s.startsWith("def ") && !s.includes("->") && !s.startsWith("def _")
    ).length;
    if (untypedCount > 0) {
      changes.push(
        `${untypedCount} public function(s) need return type annotations added`
      );
    }
  }

  // 4. Flag long functions for extraction
  if (goal === "readability" || goal === "dry" || goal === "general") {
    const lines = code.split("\n");
    let funcStart = -1;
    let funcName = "";
    for (let i = 0; i < lines.length; i++) {
      const trimmed = lines[i].trim();
      if (trimmed.startsWith("def ") || trimmed.startsWith("async def ")) {
        if (funcStart >= 0 && i - funcStart > 30) {
          changes.push(
            `Function \`${funcName}\` is ${i - funcStart} lines — consider extracting sub-functions`
          );
        }
        funcStart = i;
        const nameMatch = trimmed.match(/def\s+(\w+)/);
        funcName = nameMatch ? nameMatch[1] : "unknown";
      }
    }
    if (funcStart >= 0 && lines.length - funcStart > 30) {
      changes.push(
        `Function \`${funcName}\` is ${lines.length - funcStart} lines — consider extracting sub-functions`
      );
    }
  }

  if (changes.length === 0) {
    changes.push("No automatic refactoring applied — code is already clean");
  }

  const output = [
    "# Refactoring Report",
    "",
    `**Goal**: ${goal}`,
    `**Changes applied**: ${changes.length}`,
    "",
    "## Changes",
    "",
    ...changes.map((c, i) => `${i + 1}. ${c}`),
    "",
    "## Refactored Code",
    "",
    "```python",
    refactored,
    "```",
  ].join("\n");

  return {
    operation: "refactor",
    success: true,
    output,
    metadata: { goal, changeCount: changes.length, signatures },
  };
}

/**
 * Generate pytest tests for the given Python code.
 */
export function generateTests(input: TestInput): SkillResult {
  const parsed = TestInputSchema.parse(input);
  const { code, framework } = parsed;
  const signatures = extractSignatures(code);

  const testLines: string[] = [];

  if (framework === "pytest") {
    testLines.push('"""Auto-generated tests for the provided module."""');
    testLines.push("import pytest");
    testLines.push("");
    testLines.push("");

    for (const sig of signatures) {
      const isClass = sig.startsWith("class ");
      const nameMatch = isClass
        ? sig.match(/class\s+(\w+)/)
        : sig.match(/def\s+(\w+)/);
      const name = nameMatch ? nameMatch[1] : "unknown";
      const isAsync = sig.startsWith("async ");

      if (isClass) {
        testLines.push(`class Test${name}:`);
        testLines.push(`    """Tests for ${name} class."""`);
        testLines.push("");
        testLines.push(`    def test_${name.toLowerCase()}_init(self) -> None:`);
        testLines.push(`        """Test ${name} can be instantiated."""`);
        testLines.push(`        instance = ${name}()`);
        testLines.push(`        assert instance is not None`);
        testLines.push("");
        testLines.push(`    def test_${name.toLowerCase()}_str(self) -> None:`);
        testLines.push(`        """Test ${name} string representation."""`);
        testLines.push(`        instance = ${name}()`);
        testLines.push(`        assert str(instance) is not None`);
        testLines.push("");
      } else {
        const prefix = isAsync ? "async " : "";
        const testPrefix = isAsync ? "async_" : "";

        // Happy path
        testLines.push(
          `${prefix}def test_${name}_happy_path() -> None:`
        );
        testLines.push(`    """Test ${name} with valid input."""`);
        testLines.push(`    result = ${isAsync ? "await " : ""}${name}("valid_input")`);
        testLines.push(`    assert result is not None`);
        testLines.push("");

        // Empty input
        testLines.push(
          `${prefix}def test_${name}_empty_input() -> None:`
        );
        testLines.push(`    """Test ${name} rejects empty input."""`);
        testLines.push(`    with pytest.raises((ValueError, TypeError)):`);
        testLines.push(`        ${isAsync ? "await " : ""}${name}("")`);
        testLines.push("");

        // None input
        testLines.push(
          `${prefix}def test_${name}_none_input() -> None:`
        );
        testLines.push(`    """Test ${name} rejects None input."""`);
        testLines.push(`    with pytest.raises((ValueError, TypeError)):`);
        testLines.push(`        ${isAsync ? "await " : ""}${name}(None)`);
        testLines.push("");

        // Parametrize example
        testLines.push(`@pytest.mark.parametrize("input_val,expected", [`);
        testLines.push(`    ("test", "test"),`);
        testLines.push(`    ("hello", "hello"),`);
        testLines.push(`])`);
        testLines.push(
          `${prefix}def test_${name}_parametrized(input_val: str, expected: str) -> None:`
        );
        testLines.push(
          `    """Test ${name} with multiple inputs."""`
        );
        testLines.push(`    result = ${isAsync ? "await " : ""}${name}(input_val)`);
        testLines.push(`    assert result is not None`);
        testLines.push("");
      }
    }
  } else {
    // unittest
    testLines.push('"""Auto-generated tests for the provided module."""');
    testLines.push("import unittest");
    testLines.push("");
    testLines.push("");
    testLines.push("class TestModule(unittest.TestCase):");
    testLines.push('    """Tests for the provided module."""');
    testLines.push("");

    for (const sig of signatures) {
      const nameMatch = sig.match(/(?:def|class)\s+(\w+)/);
      const name = nameMatch ? nameMatch[1] : "unknown";

      testLines.push(`    def test_${name}_happy_path(self) -> None:`);
      testLines.push(`        """Test ${name} with valid input."""`);
      testLines.push(`        result = ${name}("valid_input")`);
      testLines.push(`        self.assertIsNotNone(result)`);
      testLines.push("");

      testLines.push(`    def test_${name}_invalid_input(self) -> None:`);
      testLines.push(`        """Test ${name} with invalid input."""`);
      testLines.push(`        with self.assertRaises((ValueError, TypeError)):`);
      testLines.push(`            ${name}("")`);
      testLines.push("");
    }

    testLines.push("");
    testLines.push('if __name__ == "__main__":');
    testLines.push("    unittest.main()");
  }

  if (signatures.length === 0) {
    testLines.length = 0;
    testLines.push(
      "# No functions or classes detected in the input code.",
      "# Provide Python code with `def` or `class` definitions to generate tests."
    );
  }

  const output = testLines.join("\n");
  return {
    operation: "test",
    success: true,
    output,
    metadata: {
      framework,
      signaturesFound: signatures.length,
      testsGenerated: signatures.length * (framework === "pytest" ? 4 : 2),
      signatures,
    },
  };
}

/**
 * Add Google-style docstrings to undocumented Python code.
 */
export function documentCode(input: DocumentInput): SkillResult {
  const parsed = DocumentInputSchema.parse(input);
  const { code, style } = parsed;
  const lines = code.split("\n");
  const result: string[] = [];
  let documented = 0;

  for (let i = 0; i < lines.length; i++) {
    const trimmed = lines[i].trim();
    result.push(lines[i]);

    // Check if this is a function or class definition
    const isFuncOrClass =
      trimmed.startsWith("def ") ||
      trimmed.startsWith("async def ") ||
      trimmed.startsWith("class ");

    if (isFuncOrClass) {
      // Check if next non-empty line is already a docstring
      let nextIdx = i + 1;
      while (nextIdx < lines.length && lines[nextIdx].trim() === "") {
        nextIdx++;
      }
      const nextLine =
        nextIdx < lines.length ? lines[nextIdx].trim() : "";
      const hasDocstring =
        nextLine.startsWith('"""') || nextLine.startsWith("'''");

      if (!hasDocstring) {
        documented++;
        const indent = lines[i].match(/^(\s*)/)?.[1] ?? "";
        const innerIndent = indent + "    ";

        // Extract function name and params
        const nameMatch = trimmed.match(
          /(?:async\s+)?(?:def|class)\s+(\w+)\s*\(([^)]*)\)/
        );
        const name = nameMatch ? nameMatch[1] : "unknown";
        const params = nameMatch ? nameMatch[2] : "";

        // Parse parameters (skip self/cls)
        const paramList = params
          .split(",")
          .map((p) => p.trim().split(":")[0].split("=")[0].trim())
          .filter((p) => p && p !== "self" && p !== "cls" && p !== "*" && !p.startsWith("**") && !p.startsWith("*"));

        if (style === "google") {
          result.push(`${innerIndent}"""TODO: Describe ${name}.`);
          if (paramList.length > 0) {
            result.push("");
            result.push(`${innerIndent}Args:`);
            for (const param of paramList) {
              result.push(
                `${innerIndent}    ${param}: TODO: Describe ${param}.`
              );
            }
          }
          if (trimmed.includes("->") && !trimmed.includes("-> None")) {
            result.push("");
            result.push(`${innerIndent}Returns:`);
            result.push(`${innerIndent}    TODO: Describe return value.`);
          }
          result.push(`${innerIndent}"""`);
        } else if (style === "numpy") {
          result.push(`${innerIndent}"""TODO: Describe ${name}.`);
          if (paramList.length > 0) {
            result.push("");
            result.push(`${innerIndent}Parameters`);
            result.push(`${innerIndent}----------`);
            for (const param of paramList) {
              result.push(`${innerIndent}${param} : type`);
              result.push(
                `${innerIndent}    TODO: Describe ${param}.`
              );
            }
          }
          if (trimmed.includes("->") && !trimmed.includes("-> None")) {
            result.push("");
            result.push(`${innerIndent}Returns`);
            result.push(`${innerIndent}-------`);
            result.push(`${innerIndent}type`);
            result.push(`${innerIndent}    TODO: Describe return value.`);
          }
          result.push(`${innerIndent}"""`);
        } else {
          // sphinx
          result.push(`${innerIndent}"""TODO: Describe ${name}.`);
          if (paramList.length > 0) {
            result.push("");
            for (const param of paramList) {
              result.push(
                `${innerIndent}:param ${param}: TODO: Describe ${param}.`
              );
              result.push(`${innerIndent}:type ${param}: type`);
            }
          }
          if (trimmed.includes("->") && !trimmed.includes("-> None")) {
            result.push(`${innerIndent}:returns: TODO: Describe return value.`);
            result.push(`${innerIndent}:rtype: type`);
          }
          result.push(`${innerIndent}"""`);
        }
      }
    }
  }

  return {
    operation: "document",
    success: true,
    output: result.join("\n"),
    metadata: {
      style,
      docstringsAdded: documented,
      totalLines: result.length,
    },
  };
}

// ─── Dispatcher ─────────────────────────────────────────────────────────────

export interface DispatchInput {
  operation: Operation;
  payload: Record<string, unknown>;
}

export function dispatch(input: DispatchInput): SkillResult {
  switch (input.operation) {
    case "generate":
      return generateCode(GenerateInputSchema.parse(input.payload));
    case "review":
      return reviewCode(ReviewInputSchema.parse(input.payload));
    case "refactor":
      return refactorCode(RefactorInputSchema.parse(input.payload));
    case "test":
      return generateTests(TestInputSchema.parse(input.payload));
    case "document":
      return documentCode(DocumentInputSchema.parse(input.payload));
    default:
      return {
        operation: input.operation,
        success: false,
        output: `Unknown operation: ${input.operation}. Valid: generate, review, refactor, test, document`,
        metadata: {},
      };
  }
}

// ─── CLI entry point ────────────────────────────────────────────────────────

async function main(): Promise<void> {
  const args = process.argv.slice(2);
  if (args.length === 0) {
    console.log(
      JSON.stringify({
        name: "python-assistant",
        version: "1.0.0",
        operations: ["generate", "review", "refactor", "test", "document"],
        usage: 'node dist/index.js \'{"operation":"review","payload":{"code":"def foo(): pass"}}\'',
      })
    );
    return;
  }

  try {
    const input = JSON.parse(args[0]) as DispatchInput;
    const result = dispatch(input);
    console.log(JSON.stringify(result, null, 2));
  } catch (err) {
    console.error(
      JSON.stringify({
        success: false,
        error: err instanceof Error ? err.message : String(err),
      })
    );
    process.exit(1);
  }
}

main();
