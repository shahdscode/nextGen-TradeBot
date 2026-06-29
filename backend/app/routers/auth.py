import uuid
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from datetime import timedelta
from app.services.auth_service import (
    authenticate_user, create_user, create_access_token,
    get_current_user, require_auth,
    verify_email_token, issue_verification_token,
    create_password_reset, reset_password_with_token,
)
from app.services.email_service import (
    send_verification_email, send_password_reset_email,
)
from app.config import settings
from app.utils.rate_limit import rate_limit

router = APIRouter(prefix="/auth", tags=["auth"])

# Throttles (per client IP, per route) to blunt brute-force / spam.
_rl_login = rate_limit(max_calls=10, window_seconds=60)
_rl_register = rate_limit(max_calls=5, window_seconds=300)
_rl_sensitive = rate_limit(max_calls=5, window_seconds=300)


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
def register(req: RegisterRequest, _rl=Depends(_rl_register)):
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
        if user.email and user.verification_token:
            send_verification_email(user.email, user.username, user.verification_token)
        return {
            "message": "User created",
            "username": user.username,
            "role": user.role,
            "email_verification_sent": bool(user.email and user.verification_token),
            "verification_required": settings.require_email_verification,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, _rl=Depends(_rl_login)):
    user = authenticate_user(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if (settings.require_email_verification and user.role != "admin"
            and user.email and not user.email_verified):
        raise HTTPException(status_code=403,
                            detail="Please verify your email before logging in.")
    token = create_access_token(
        data={"sub": user.username, "role": user.role},
        expires_delta=timedelta(minutes=settings.jwt_expire_minutes),
    )
    return TokenResponse(access_token=token, role=user.role, username=user.username)


class TokenOnly(BaseModel):
    token: str


class EmailOrUsername(BaseModel):
    identifier: str   # username or email


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


@router.post("/verify-email")
def verify_email(req: TokenOnly):
    user = verify_email_token(req.token)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired verification link")
    return {"ok": True, "message": "Email verified", "username": user.username}


@router.post("/resend-verification")
def resend_verification(req: EmailOrUsername, _rl=Depends(_rl_sensitive)):
    result = issue_verification_token(req.identifier)
    if result:
        user, token = result
        send_verification_email(user.email, user.username, token)
    # Always generic so we don't leak which accounts exist / are verified.
    return {"ok": True, "message": "If the account exists and is unverified, a new link was sent."}


@router.post("/forgot-password")
def forgot_password(req: EmailOrUsername, _rl=Depends(_rl_sensitive)):
    result = create_password_reset(req.identifier)
    if result:
        user, token = result
        send_password_reset_email(user.email, user.username, token)
    # Generic response — never reveal whether the account exists.
    return {"ok": True, "message": "If an account exists, a reset link has been sent."}


@router.post("/reset-password")
def reset_password(req: ResetPasswordRequest, _rl=Depends(_rl_sensitive)):
    if len(req.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    if not reset_password_with_token(req.token, req.new_password):
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")
    return {"ok": True, "message": "Password updated — you can now log in."}


@router.get("/me")
def me(user=Depends(require_auth)):
    created = user.created_at.isoformat() if getattr(user, "created_at", None) else None
    return {
        "username": user.username,
        "role": user.role,
        "email": user.email,
        "created_at": created,
        "is_active": getattr(user, "is_active", True),
        "email_verified": getattr(user, "email_verified", False),
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
