# Migration Guide: harness.schema → harness.contracts

**Target Audience:** Internal developers migrating legacy imports  
**Compatibility Period:** P5 phase (estimated 2-3 sprints)  
**Status:** Active migration

## Quick Reference

### Before (Legacy)
```python
from react_agent.harness import schema
from react_agent.harness.schema import (
    validate_trajectory,
    normalize_trajectory,
    assert_valid,
    load_and_validate,
    SCHEMA_VERSION,
)
```

### After (Canonical)
```python
from react_agent.harness import contracts
from react_agent.harness.contracts import (
    validate_trajectory,
    normalize_trajectory,
    parse_trajectory,  # Unified entry point
    assert_valid,
    load_and_validate,
    SCHEMA_VERSION,
)
```

## Migration Steps

### 1. Simple Import Replacement

Most files can be migrated with a straightforward find-replace:

```python
# OLD
from react_agent.harness import schema

# NEW
from react_agent.harness import contracts as schema  # Drop-in compatibility
```

Or fully migrate:

```python
# OLD
from react_agent.harness.schema import validate_trajectory

# NEW
from react_agent.harness.contracts import validate_trajectory
```

### 2. Use the Unified parse_trajectory()

The new `parse_trajectory()` accepts mappings, JSON strings, or file paths:

```python
from react_agent.harness.contracts import parse_trajectory

# From file path
trajectory = parse_trajectory("path/to/trajectory.json")

# From JSON string
trajectory = parse_trajectory(json_string)

# From dict
trajectory = parse_trajectory({"session_id": "...", "query": "...", "steps": [...]})
```

### 3. Test File Migration

For test files that explicitly test the legacy module, add this pattern:

```python
import warnings

# Suppress deprecation warnings in compatibility tests
with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from react_agent.harness import schema
```

### 4. Verify Your Changes

After migrating, verify:

```bash
# No syntax errors
python -m py_compile your_file.py

# Tests still pass
pytest tests/your_test.py

# No unintended deprecation warnings
pytest tests/ -W error::DeprecationWarning
```

## Common Patterns

### Pattern 1: Module-level import

```python
# Before
from react_agent.harness import schema
issues = schema.validate_trajectory(data)

# After
from react_agent.harness import contracts
issues = contracts.validate_trajectory(data)
```

### Pattern 2: Direct function import

```python
# Before
from react_agent.harness.schema import validate_trajectory, SCHEMA_VERSION

# After
from react_agent.harness.contracts import validate_trajectory, SCHEMA_VERSION
```

### Pattern 3: Load and validate file

```python
# Before
from react_agent.harness.schema import load_and_validate
trajectory = load_and_validate("trajectory.json")

# After - Option 1 (drop-in)
from react_agent.harness.contracts import load_and_validate
trajectory = load_and_validate("trajectory.json")

# After - Option 2 (preferred)
from react_agent.harness.contracts import parse_trajectory
trajectory = parse_trajectory("trajectory.json")
```

## Breaking Changes (Post-Compatibility Period)

After the compatibility period ends:
- ❌ `react_agent.harness.schema` module will be removed
- ❌ Direct imports from `schema.py` will fail

These will continue to work:
- ✅ All imports from `react_agent.harness.contracts`
- ✅ `parse_trajectory()` unified API
- ✅ All contract-based serializers and validators

## Automated Migration Script

For bulk migration of import statements:

```bash
# Dry run (shows what would change)
find src tests scripts -name "*.py" -exec sed -n \
  's/from react_agent\.harness import schema/from react_agent.harness import contracts/gp' {} +

# Apply changes
find src tests scripts -name "*.py" -exec sed -i \
  's/from react_agent\.harness import schema/from react_agent.harness import contracts/g' {} +

find src tests scripts -name "*.py" -exec sed -i \
  's/from react_agent\.harness\.schema import/from react_agent.harness.contracts import/g' {} +
```

## Support

- **Migration Inventory:** [Migration Inventory](inventory.md)
- **Spec Reference:** [Harness 主规格](../../spec.md) Phase 5
- **Questions:** Open an issue with label `migration/p5`

## Migration Checklist

For each file you migrate:
- [ ] Replace import statements
- [ ] Run file's tests
- [ ] Verify no deprecation warnings
- [ ] Update any inline documentation/comments
- [ ] Mark as migrated in tracking spreadsheet (if applicable)
