"""Schémas Pydantic — B05 (authentification locale)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    # `str` plutôt que `pydantic.EmailStr` : évite une dépendance
    # supplémentaire (`email-validator`) pour un format qui n'a de toute
    # façon aucune valeur de sécurité ici — la seule vérification qui compte
    # est la correspondance en base, faite par `authenticate_user`.
    email: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=512)


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str

    model_config = {"from_attributes": True}


class MeResponse(BaseModel):
    user: UserOut


class DemoCredentialsResponse(BaseModel):
    email: str
    password: str
