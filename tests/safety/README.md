# Safety Tests

Tests for safety mechanisms including permissions, approvals, and network guards.

## Structure

- `test_permissions_gate.py` - Permission gate functionality
- `test_net_guard.py` - Network SSRF protection
- `test_approvals.py` - Approval workflow

## Permission Levels

Tests verify the DENY → ASK → ALLOW permission hierarchy:
- DENY - Blocked operations
- CONFIRM - Requires approval (async/HITL)
- CONFIRM_READ - Sensitive read-only (auto-allowed)
- NOTIFY - Logged and allowed
- SAFE - Auto-allowed
