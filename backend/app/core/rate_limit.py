"""IP-based rate limiting for auth endpoints — a basic defense against
credential stuffing / brute force. See docs/CONTRACT_CLM_BUILD_PLAN.md §6.8.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
