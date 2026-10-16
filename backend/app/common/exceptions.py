import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from app.common.responses import ErrorDetail, ErrorResponse

logger = logging.getLogger(__name__)


class AppError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def error_response(
    request: Request, status: int, code: str, message: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    payload = ErrorResponse(error=ErrorDetail(code=code, message=message), request_id=request_id)
    response_headers = dict(headers or {})
    if request_id:
        response_headers["X-Request-ID"] = request_id
    return JSONResponse(payload.model_dump(), status_code=status, headers=response_headers)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return error_response(request, exc.status_code, exc.code, exc.message)

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "请求失败"
        return error_response(request, exc.status_code, "http_error", message, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = exc.errors()
        # 只返回代码中明确标记的用户提示，避免回显校验输入、密钥或原始异常。
        message = next(
            (str(error["msg"]) for error in errors if error["type"] == "user_input"),
            "请求参数格式错误，请检查请求内容",
        )
        logger.info(
            "请求参数校验失败 count=%s types=%s request_id=%s",
            len(errors),
            ",".join(sorted({str(error["type"]) for error in errors})),
            getattr(request.state, "request_id", None),
        )
        return error_response(request, 422, "validation_error", message)

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "未处理异常 type=%s request_id=%s",
            type(exc).__name__,
            getattr(request.state, "request_id", None),
        )
        return error_response(request, 500, "internal_error", "服务暂时不可用，请稍后重试")
