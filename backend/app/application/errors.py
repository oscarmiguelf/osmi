class AppError(Exception):
    status = 400

    def __init__(self, detail: str | dict):
        super().__init__(detail)
        self.detail = detail


class NotFound(AppError):
    status = 404


class Forbidden(AppError):
    status = 403


class Conflict(AppError):
    status = 409


class Invalid(AppError):
    status = 422


class TooManyRequests(AppError):
    status = 429
