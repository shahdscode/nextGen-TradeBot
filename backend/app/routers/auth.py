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
    if req.role != "admin" and not settings.allow_public_register:
        raise HTTPException(status_code=403, detail="Public registration is disabled")
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
    created = user.created_at.isoformat() if getattr(user, "created_at", None) else None
    return {
        "username": user.username,
        "role": user.role,
        "email": user.email,
        "created_at": created,
        "is_active": getattr(user, "is_active", True),
        "alpaca_configured": bool(user.alpaca_api_key and user.alpaca_api_secret),
    }


class AlpacaConfigRequest(BaseModel):
    api_key: str
    api_secret: str


@router.get("/alpaca-config")
def get_alpaca_config(user=Depends(require_auth)):
    """Whether the current user has Alpaca keys set (never returns the secret)."""
    configured = bool(user.alpaca_api_key and user.alpaca_api_secret)
    masked = (user.alpaca_api_key[:4] + "…" + user.alpaca_api_key[-4:]) \
        if configured and len(user.alpaca_api_key or "") >= 8 else None
    return {"configured": configured, "key_preview": masked}


@router.put("/alpaca-config")
def set_alpaca_config(req: AlpacaConfigRequest, user=Depends(require_auth)):
    """Save the current user's own Alpaca paper-trading keys."""
    from app.database import SessionLocal, User
    if not req.api_key.strip() or not req.api_secret.strip():
        raise HTTPException(status_code=400, detail="Both API key and secret are required")
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.id == user.id).first()
        if not u:
            raise HTTPException(status_code=404, detail="User not found")
        u.alpaca_api_key = req.api_key.strip()
        u.alpaca_api_secret = req.api_secret.strip()
        db.commit()
        return {"ok": True, "message": "Alpaca keys saved", "configured": True}
    finally:
        db.close()


@router.delete("/alpaca-config")
def clear_alpaca_config(user=Depends(require_auth)):
    """Remove the current user's Alpaca keys."""
    from app.database import SessionLocal, User
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.id == user.id).first()
        if u:
            u.alpaca_api_key = None
            u.alpaca_api_secret = None
            db.commit()
        return {"ok": True, "message": "Alpaca keys removed", "configured": False}
    finally:
        db.close()
