class AppError(Exception):
    def __init__(self, code, message, status=400, retryable=False, details=None):
        self.code, self.message, self.status = code, message, status
        self.retryable, self.details = retryable, details or {}
        super().__init__(message)
