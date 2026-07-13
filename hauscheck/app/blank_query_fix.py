from __future__ import annotations

from urllib.parse import parse_qsl, urlencode

from fastapi import FastAPI, Request


_BLANKABLE_NUMERIC_PARAMS = {
    "min_score",
    "max_price",
    "max_hwb",
}


def register_blank_query_fix(app: FastAPI) -> None:
    """Remove empty numeric GET parameters before FastAPI validates them.

    HTML number inputs are submitted as ``name=`` when left blank. Optional
    numeric FastAPI parameters still reject that empty string with HTTP 422.
    Treating a blank filter as an omitted filter matches the UI expectation.
    """

    @app.middleware("http")
    async def normalize_blank_numeric_query_params(request: Request, call_next):
        raw_query = request.scope.get("query_string", b"")
        if raw_query:
            pairs = parse_qsl(raw_query.decode("utf-8", errors="replace"), keep_blank_values=True)
            normalized = [
                (key, value)
                for key, value in pairs
                if not (key in _BLANKABLE_NUMERIC_PARAMS and not value.strip())
            ]
            if normalized != pairs:
                request.scope["query_string"] = urlencode(normalized, doseq=True).encode("utf-8")
        return await call_next(request)
