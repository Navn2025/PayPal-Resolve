"""HTTP authentication error redaction and private response headers."""

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from app.core.exceptions import StoreError


class PrivateAuthRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def private(request):
            try:
                response = await handler(request)
            except RequestValidationError:
                response = JSONResponse(
                    {"detail": "Enter a valid sign-in request"}, status_code=422
                )
            except StoreError as error:
                response = JSONResponse(
                    {"detail": error.detail}, status_code=error.status_code
                )
            response.headers.update(
                {
                    "Cache-Control": "private, no-store",
                    "Referrer-Policy": "no-referrer",
                    "X-Robots-Tag": "noindex, nofollow",
                }
            )
            return response

        return private
