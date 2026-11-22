"""Request dependencies. There is no authentication in this local single-analyst POC (see api/main.py: loopback only)."""
from fastapi import Request


def services(request: Request):
    return request.app.state.services
