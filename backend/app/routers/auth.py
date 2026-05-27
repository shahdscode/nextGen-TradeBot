import uuid
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from datetime import timedelta
from app.services.auth_service import (
    authenticate_user, create_user, create_access_token,
    get_current_user, require_auth,
)
from app.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    username: str
    password: str
    email: Optional[str] = None
    role: str = "user"
    admin_secret: Optional[str] = None  # required to create admin accounts


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    username: str


@router.post("/register")
def register(req: RegisterRequest):
    if req.role == "admin":
        if req.admin_secret != settings.jwt_secret_key[:16]:
            raise HTTPException(status_code=403, detail="Invalid admin secret")
    try:
        user = create_user(
            username=req.username,
            password=req.password,
            role=req.role,
            email=req.email or "",
        )
        return {"message": "User created", "username": user.username, "role": user.role}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest):
    user = authenticate_user(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = create_access_token(
        data={"sub": user.username, "role": user.role},
        expires_delta=timedelta(minutes=settings.jwt_expire_minutes),
    )
    return TokenResponse(access_token=token, role=user.role, username=user.username)


@router.get("/me")
def me(user=Depends(require_auth)):
    return {"username": user.username, "role": user.role, "email": user.email}
