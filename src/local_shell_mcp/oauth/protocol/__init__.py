"""Protocol-library adapters for local OAuth behavior.

This package is the boundary around Authlib and token codec details. It should
translate local-shell-mcp data structures into library-facing request, client,
bearer-token, and credential objects without owning HTTP routes or project
approval policy.
"""
