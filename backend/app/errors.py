from fastapi import Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    """Rendered as {"error": {"code", "message", "details"}} (PRD § Internal REST API conventions)."""

    def __init__(self, status: int, code: str, message: str, details: dict | None = None):
        self.status, self.code, self.message, self.details = status, code, message, details or {}


def bad(code: str, message: str, **details):
    return ApiError(400, code, message, details)


def conflict(code: str, message: str, **details):
    return ApiError(409, code, message, details)


def not_found(what: str = "resource"):
    return ApiError(404, "not_found", f"{what} not found")


def forbidden(message: str = "not allowed"):
    return ApiError(403, "forbidden", message)


async def api_error_handler(_: Request, exc: ApiError):
    return JSONResponse(status_code=exc.status,
                        content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}})
