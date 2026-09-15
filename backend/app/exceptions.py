class BusinessError(Exception):
    def __init__(self, message: str, code: str = "business_error") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class NotFoundError(BusinessError):
    def __init__(self, message: str = "资源不存在") -> None:
        super().__init__(message, "not_found")


class ValidationError(BusinessError):
    def __init__(self, message: str) -> None:
        super().__init__(message, "validation_error")

