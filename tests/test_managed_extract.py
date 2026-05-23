"""Tests for diff extraction from Managed Agent responses."""

from __future__ import annotations

from gemcoder.managed import _extract_unified_diff, _normalize_workspace_paths


def test_empty_returns_empty() -> None:
    assert _extract_unified_diff("") == ""
    assert _extract_unified_diff("no diff here") == ""


def test_extracts_diff_from_yaml_block() -> None:
    text = """Here is the patch:

```yaml
patch: |
  --- a/workspace/repo/greet.py
  +++ b/workspace/repo/greet.py
  @@ -1,2 +1,2 @@
   def greet():
  -    return "hellow"
  +    return "hello"
changed_files:
  - workspace/repo/greet.py
```
"""
    out = _extract_unified_diff(text)
    assert "--- a/greet.py" in out
    assert "+++ b/greet.py" in out
    assert 'return "hello"' in out
    assert "workspace/repo" not in out


def test_extracts_diff_from_diff_fence() -> None:
    text = """Done.

```diff
--- a/foo.py
+++ b/foo.py
@@ -1 +1 @@
-x
+y
```
"""
    out = _extract_unified_diff(text)
    assert out.startswith("--- a/foo.py")
    assert "+y" in out


def test_extracts_raw_diff_git() -> None:
    text = "ok\ndiff --git a/foo.py b/foo.py\n--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-x\n+y\n"
    out = _extract_unified_diff(text)
    assert out.startswith("diff --git a/foo.py")


def test_extracts_raw_minus_a() -> None:
    text = "summary text\n\n--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-x\n+y\n"
    out = _extract_unified_diff(text)
    assert out.startswith("--- a/foo.py")


def test_normalize_workspace_paths() -> None:
    diff = "--- a/workspace/repo/foo.py\n+++ b/workspace/repo/foo.py\n@@ -1 +1 @@\n-x\n+y\n"
    out = _normalize_workspace_paths(diff)
    assert "workspace/repo" not in out
    assert "--- a/foo.py" in out
    assert "+++ b/foo.py" in out


def test_normalize_handles_diff_git_header() -> None:
    diff = "diff --git a/workspace/repo/foo.py b/workspace/repo/foo.py\n"
    out = _normalize_workspace_paths(diff)
    assert out == "diff --git a/foo.py b/foo.py\n"


def test_extracts_diff_without_ab_prefix() -> None:
    """Real-world case: Gemini sometimes emits `--- workspace/repo/X` (no a/b prefix)."""
    text = """```yaml
patch: |
  --- workspace/repo/greet.py
  +++ workspace/repo/greet.py
  @@ -1,2 +1,2 @@
   def greet():
  -    return "hellow"
  +    return "hello"
```
"""
    out = _extract_unified_diff(text)
    assert "--- a/greet.py" in out
    assert "+++ b/greet.py" in out
    assert "workspace/repo" not in out


def test_preserves_dev_null() -> None:
    diff = "--- /dev/null\n+++ b/new.py\n@@ -0,0 +1 @@\n+hi\n"
    out = _normalize_workspace_paths(diff)
    assert "--- /dev/null" in out
    assert "+++ b/new.py" in out


def test_no_yaml_patch_key_falls_through() -> None:
    """YAML without a 'patch:' key shouldn't crash; should try other fences."""
    text = """```yaml
not_patch: hello
```

```diff
--- a/foo.py
+++ b/foo.py
@@ -1 +1 @@
-x
+y
```
"""
    out = _extract_unified_diff(text)
    assert out.startswith("--- a/foo.py")
