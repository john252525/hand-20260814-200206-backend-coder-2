class AppError(Exception):
    def __init__(self, code: str = "INTERNAL_ERROR", message: str = "Internal error", details: dict | None = None):
        self.code = code
        self.message = message
        self.details = details
        super().__init__(self.message)


class NotFoundError(AppError):
    def __init__(self, message: str = "Not found", details: dict | None = None):
        super().__init__("NOT_FOUND", message, details)


class ConflictError(AppError):
    def __init__(self, message: str = "Conflict", details: dict | None = None):
        super().__init__("CONFLICT", message, details)


class ValidationError(AppError):
    def __init__(self, message: str = "Validation error", details: dict | None = None):
        super().__init__("VALIDATION_ERROR", message, details)


class UnauthorizedError(AppError):
    def __init__(self, message: str = "Unauthorized", details: dict | None = None):
        super().__init__("UNAUTHORIZED", message, details)
