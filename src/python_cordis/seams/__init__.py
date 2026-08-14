"""Capability seams: interface + provider + consumer triads.

- ``fs``  : filesystem seam (FileSystem / LocalFS / SandboxFS / tool-fs).
- ``llm`` : LLM seam (LlmAdapter / MockProvider / LlmStream).
- ``pipeline`` : tool execution pipeline (pre -> execute -> post).
"""
