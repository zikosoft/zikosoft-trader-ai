"""Petit utilitaire pour renvoyer une erreur API dans le format commun défini
en B01 (`shared.errors.APIError`) depuis une route, sans passer par le
`{"detail": ...}` par défaut de `HTTPException` (format FastAPI, pas celui du
contrat applicatif)."""

from __future__ import annotations

from fastapi.responses import JSONResponse

from shared.errors import APIError, ErrorCode


def api_error_response(
    status_code: int, code: ErrorCode, message: str, *, details: dict | None = None
) -> JSONResponse:
    error = APIError(code=code, message=message, details=details)
    return JSONResponse(status_code=status_code, content=error.to_response())
