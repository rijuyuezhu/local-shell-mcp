"""Project-owned OAuth state, policy, URL helpers, and service operations.

Code in this package should stay independent of Starlette route handling. It can
use protocol adapters when that reduces OAuth-specific validation logic, but it
owns local-shell-mcp policy such as admin approval, resource binding, dynamic
client storage, and scope normalization.
"""
