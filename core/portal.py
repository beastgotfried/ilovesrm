"""Portal access layer — pure HTTP (no browser, no WebBridge).

This module is the canonical portal client; it re-exports core.portal_http.
The previous WebBridge/DOM implementation is kept in core/portal_webbridge.py
for reference only.
"""
from .portal_http import (  # noqa: F401
    Portal, PortalError,
    up, login_with_token, login_with_password, detect_identity,
    list_courses, open_course, read_slot, submit_links, session_code,
    mcq_scores, submit_mcq,
)
