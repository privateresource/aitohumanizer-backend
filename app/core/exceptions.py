from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppException(Exception):
    def __init__(self, message: str, status_code: int = 400, detail: dict = None):
        self.message = message
        self.status_code = status_code
        self.detail = detail or {}
        super().__init__(self.message)


class NotFoundException(AppException):
    def __init__(self, message: str = "Resource not found", detail: dict = None):
        super().__init__(message=message, status_code=404, detail=detail)


class ForbiddenException(AppException):
    def __init__(self, message: str = "Forbidden", detail: dict = None):
        super().__init__(message=message, status_code=403, detail=detail)


class UnauthorizedException(AppException):
    def __init__(self, message: str = "Unauthorized", detail: dict = None):
        super().__init__(message=message, status_code=401, detail=detail)


class ServiceUnavailableException(AppException):
    def __init__(self, message: str = "Service unavailable", detail: dict = None):
        super().__init__(message=message, status_code=503, detail=detail)


class BadRequestException(AppException):
    def __init__(self, message: str = "Bad request", detail: dict = None):
        super().__init__(message=message, status_code=400, detail=detail)


class QuotaExceededException(AppException):
    def __init__(self, message: str = "Quota exceeded", detail: dict = None):
        super().__init__(message=message, status_code=429, detail=detail)


class RateLimitException(AppException):
    def __init__(self, message: str = "Rate limit exceeded", detail: dict = None):
        super().__init__(message=message, status_code=429, detail=detail)


def add_exception_handlers(app: FastAPI):
    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.__class__.__name__,
                "message": exc.message,
                "detail": exc.detail,
            },
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content={
                "error": "InternalServerError",
                "message": "An unexpected error occurred",
            },
        )
