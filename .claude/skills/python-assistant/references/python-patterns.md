# Python Best Practices Reference

## Type Hints (PEP 484 / 585 / 604)

### Modern syntax (Python 3.10+)
```python
def process(items: list[str], count: int | None = None) -> dict[str, int]:
    ...
```

### Legacy syntax (Python 3.9-)
```python
from typing import List, Optional, Dict
def process(items: List[str], count: Optional[int] = None) -> Dict[str, int]:
    ...
```

## Google-Style Docstrings

```python
def fetch_user(user_id: str, *, include_metadata: bool = False) -> dict[str, object]:
    """Fetch a user by ID from the data store.

    Args:
        user_id: The unique identifier of the user.
        include_metadata: If True, include audit metadata in the response.

    Returns:
        A dictionary containing user fields:
        - 'name': The user's display name
        - 'email': Primary email address
        - 'metadata': (optional) Audit metadata if requested

    Raises:
        ValueError: If user_id is empty.
        KeyError: If user is not found.

    Example:
        >>> fetch_user("u123")
        {'name': 'Alice', 'email': 'alice@example.com'}
    """
```

## Common Anti-Patterns

| Pattern | Problem | Fix |
|---------|---------|-----|
| `except:` | Catches SystemExit, KeyboardInterrupt | Catch specific: `except ValueError:` |
| `def f(x=[])` | Mutable default shared across calls | `def f(x=None): x = x or []` |
| `from x import *` | Namespace pollution | `from x import name1, name2` |
| `type(x) == Foo` | Breaks inheritance | `isinstance(x, Foo)` |
| `x == None` | Wrong semantics | `x is None` |
| `eval(user_input)` | Code injection | `ast.literal_eval()` or explicit parse |
| `open(f)` without `with` | Resource leak | `with open(f) as fh:` |
| `os.path.join()` | Legacy API | `pathlib.Path(a) / b` |

## Testing Patterns (pytest)

### Fixtures
```python
@pytest.fixture
def sample_user() -> dict[str, str]:
    return {"name": "Alice", "email": "alice@test.com"}
```

### Parametrize
```python
@pytest.mark.parametrize("input_val,expected", [
    ("hello", "HELLO"),
    ("world", "WORLD"),
    ("", pytest.raises(ValueError)),
])
def test_transform(input_val: str, expected: str) -> None:
    assert transform(input_val) == expected
```

### Mocking
```python
from unittest.mock import patch, AsyncMock

@patch("module.external_api", new_callable=AsyncMock)
async def test_fetch(mock_api: AsyncMock) -> None:
    mock_api.return_value = {"data": "value"}
    result = await fetch_data()
    assert result["data"] == "value"
    mock_api.assert_called_once()
```

## Security Checklist

- [ ] No `eval()` or `exec()` with user input
- [ ] No hardcoded secrets (use `.env` + `os.environ`)
- [ ] SQL queries use parameterized statements
- [ ] File paths validated against directory traversal
- [ ] HTTP inputs sanitized before processing
- [ ] Subprocess calls use `shlex.quote()` for arguments
