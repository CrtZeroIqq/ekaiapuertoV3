"""
EKAIA Puerto - Authentication API
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole
from app.services.auth_service import AuthService
from app.services import get_db_session

router = APIRouter(prefix="/api/auth", tags=["authentication"])
security = HTTPBearer(auto_error=False)


# Request/Response Models
class LoginRequest(BaseModel):
    username: str = Field(..., min_length=3)
    password: str = Field(..., min_length=6)


class LoginResponse(BaseModel):
    success: bool
    message: str
    token: Optional[str] = None
    user: Optional[dict] = None


class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=6)
    full_name: str = Field(..., min_length=2)
    role: str = Field(default="viewer")


class UpdateUserRequest(BaseModel):
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=6)


# Dependencies
async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db_session)
) -> User:
    token = None
    if credentials:
        token = credentials.credentials
    if not token:
        token = request.cookies.get("session_token")
    if not token:
        raise HTTPException(status_code=401, detail="No autenticado")
    
    auth_service = AuthService(db)
    user = await auth_service.validate_session(token)
    if not user:
        raise HTTPException(status_code=401, detail="Sesion invalida")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Se requiere rol admin")
    return user


# Endpoints
@router.post("/login", response_model=LoginResponse)
async def login(
    request: Request,
    response: Response,
    data: LoginRequest,
    db: AsyncSession = Depends(get_db_session)
):
    auth_service = AuthService(db)
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    
    success, user, token, message = await auth_service.authenticate(data.username, data.password, ip, ua)
    
    if success and token:
        response.set_cookie(
            key="session_token",
            value=token,
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=86400
        )
        return LoginResponse(success=True, message=message, token=token, user=user.to_dict())
    
    return LoginResponse(success=False, message=message)


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db_session)
):
    token = credentials.credentials if credentials else request.cookies.get("session_token")
    if token:
        auth_service = AuthService(db)
        await auth_service.logout(token)
    response.delete_cookie("session_token")
    return {"success": True, "message": "Sesion cerrada"}


@router.get("/me")
async def get_me(user: User = Depends(get_current_user)):
    return user.to_dict()


@router.get("/validate")
async def validate(user: User = Depends(get_current_user)):
    return {"valid": True, "user": user.to_dict()}


# Admin endpoints
@router.get("/users")
async def list_users(
    include_inactive: bool = False,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session)
):
    auth_service = AuthService(db)
    users = await auth_service.get_all_users(include_inactive)
    return [u.to_dict() for u in users]


@router.post("/users")
async def create_user(
    data: CreateUserRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session)
):
    auth_service = AuthService(db)
    try:
        role = UserRole(data.role)
    except ValueError:
        raise HTTPException(status_code=400, detail="Rol invalido")
    
    success, user, message = await auth_service.create_user(
        data.username, data.email, data.password, data.full_name, role, admin.id
    )
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return user.to_dict()


@router.put("/users/{user_id}")
async def update_user(
    user_id: int,
    data: UpdateUserRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session)
):
    auth_service = AuthService(db)
    role = UserRole(data.role) if data.role else None
    success, user, message = await auth_service.update_user(
        user_id, data.email, data.full_name, role, data.is_active
    )
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return user.to_dict()


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session)
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="No puede eliminarse a si mismo")
    auth_service = AuthService(db)
    success, message = await auth_service.delete_user(user_id)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"success": True, "message": message}


@router.post("/users/{user_id}/reset-password")
async def reset_password(
    user_id: int,
    data: ResetPasswordRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session)
):
    auth_service = AuthService(db)
    success, message = await auth_service.reset_password(user_id, data.new_password)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"success": True, "message": message}


@router.get("/logs")
async def get_logs(
    limit: int = 100,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session)
):
    auth_service = AuthService(db)
    logs = await auth_service.get_access_logs(limit=limit)
    return [l.to_dict() for l in logs]