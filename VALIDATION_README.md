# Syntax Validation System

This project includes automatic syntax validation to check for balanced brackets, braces, and parentheses before updates.

## Quick Start

**Validate all project files:**
```bash
python3 pre_update_validation.py
```

**Validate specific files:**
```bash
python3 validate_syntax.py app.py templates/index.html
```

**Use in Python code:**
```python
from validate_before_update import validate_before_update

# Validate before making updates
try:
    validate_before_update(fail_on_error=True)
    # Proceed with updates...
except SyntaxError as e:
    print(f"Validation failed: {e}")
    # Don't proceed with updates
```

## Integration into Update Workflow

### Option 1: Manual Validation Before Updates

Before making code changes, run:
```bash
python3 pre_update_validation.py
```

If validation passes, proceed with your updates.

### Option 2: Git Pre-commit Hook

Install the pre-commit hook to automatically validate before commits:

```bash
# Make hook executable
chmod +x .pre-commit-hook.sh

# Install as git hook (if using git)
ln -s ../../.pre-commit-hook.sh .git/hooks/pre-commit
```

Now every `git commit` will automatically validate syntax first.

### Option 3: Programmatic Integration

Add validation to your update functions:

```python
from validate_before_update import validate_before_update

def update_order_function():
    # Validate before updating
    validate_before_update(['app.py'], fail_on_error=True)
    
    # Proceed with update logic...
    pass
```

## What Gets Validated

- **Python files (.py)**: All parentheses `()`, brackets `[]`, and braces `{}`
- **HTML files (.html)**: 
  - JavaScript code in `<script>` tags
  - Jinja2 template expressions `{{ ... }}`
  - JavaScript template literals `${ ... }`

## Validation Results

- ✅ **Valid**: All brackets, braces, and parentheses are balanced
- ❌ **Invalid**: Shows specific errors with line numbers and positions

## Notes

- Complex nested template literals in JavaScript may occasionally show false positives
- The validator focuses on syntax balance, not semantic correctness
- Always review validation errors carefully before fixing

## Files

- `validate_syntax.py` - Core validation functions
- `pre_update_validation.py` - Standalone validation script for all project files
- `validate_before_update.py` - Programmatic validation function for integration
- `.pre-commit-hook.sh` - Git pre-commit hook script

