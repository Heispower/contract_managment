class BizError(Exception):
    def __init__(self, message: str, http: int = 400, code: int | None = None, data=None):
        super().__init__(message)
        self.message = message
        self.http = http
        self.code = code if code is not None else http
        self.data = data
