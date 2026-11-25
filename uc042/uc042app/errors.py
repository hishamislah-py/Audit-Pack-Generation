"""Application errors. Services raise AppError with a stable code; the API turns it into an RFC 7807 problem-details
response {type, title, status, detail, code}. Messages are written for the analyst and never carry paths or traces."""


class AppError(Exception):
    status = 400
    code = "BAD_REQUEST"
    title = "Bad request"

    def __init__(self, detail="", code=None, status=None, extra=None):
        self.detail = str(detail)[:1000]
        self.code = code or self.code
        self.status = status or self.status
        self.extra = dict(extra or {})
        super().__init__(f"{self.code}: {self.detail}")


class NotFound(AppError):
    status, code, title = 404, "NOT_FOUND", "Not found"


class InvalidInput(AppError):
    status, code, title = 422, "VALIDATION_ERROR", "Invalid request"


class Conflict(AppError):
    status, code, title = 409, "CONFLICT", "Conflict"


class ServiceUnavailable(AppError):
    status, code, title = 503, "SERVICE_UNAVAILABLE", "Service unavailable"


class IntegrityFailure(AppError):
    status, code, title = 409, "INTEGRITY_FAILURE", "Integrity verification failed"
