from fastapi import HTTPException


class APIError(HTTPException):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(status_code=status)
        self.code = code
        self.message = message
