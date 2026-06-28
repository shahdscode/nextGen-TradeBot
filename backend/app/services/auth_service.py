import uuid
from datetime import datetime, timedelta
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.config import settings
from app.database import SessionLocal, User

try:
    import bcrypt
    from jose import JWTError, jwt
    AUTH_AVAILABLE = True
except ImportError:
    AUTH_AVAILABLE = False
    bcrypt = None

bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    if not AUTH_AVAILABLE:
        return f"plain:{password}"
    digest = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    return digest.decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    if not AUTH_AVAILABLE:
        return hashed == f"plain:{plain}"
    if hashed.startswith("plain:"):
        return hashed == f"plain:{plain}"
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    if not AUTH_AVAILABLE:
        import json, base64
        return base64.b64encode(json.dumps(data).encode()).decode()
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.jwt_expire_minutes))
    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> Optional[dict]:
    if not AUTH_AVAILABLE:
        import json, base64
        try:
            return json.loads(base64.b64decode(token.encode()).decode())
        except Exception:
            return None
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None


def get_user_by_username(username: str) -> Optional[User]:
    db = SessionLocal()
    try:
        return db.query(User).filter(User.username == username).first()
    finally:
        db.close()


def create_user(username: str, password: str, role: str = "user", email: str = "") -> User:
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == username).first()
        if existing:
            raise ValueError(f"Username '{username}' already exists")
        user = User(
            id=str(uuid.uuid4()),
            username=username,
            email=email or None,
            hashed_password=hash_password(password),
            role=role,
            is_active=True,
            created_at=datetime.utcnow(),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def authenticate_user(username: str, password: str) -> Optional[User]:
    user = get_user_by_username(username)
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user


def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme)) -> Optional[User]:
    if not credentials:
        return None
    payload = decode_token(credentials.credentials)
    if not payload:
        return None
    username = payload.get("sub")
    if not username:
        return None
    return get_user_by_username(username)


def require_auth(credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme)) -> User:
    user = get_current_user(credentials)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


def require_admin(credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme)) -> User:
    user = require_auth(credentials)
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


def get_user_id(user: User) -> str:
    """Stable user primary key for tenancy scoping."""
    return str(user.id)
