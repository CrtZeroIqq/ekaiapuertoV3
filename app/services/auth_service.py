"""
EKAIA Puerto - Authentication Service
"""
import secrets
from datetime import datetime, timedelta
from typing import Optional, Tuple
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
import bcrypt
import logging

from app.models.user import User, UserSession, AccessLog, UserRole, ActionType

logger = logging.getLogger(__name__)

MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 30
SESSION_DURATION_HOURS = 24
TOKEN_LENGTH = 64


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def hash_password(password: str) -> str:
        salt = bcrypt.gensalt(rounds=12)
        return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        try:
            print("====== VERIFY_PASSWORD DEBUG ======")
            print("Password (raw):", password)
            print("Password bytes:", password.encode('utf-8'))
            print("Hash (raw):", password_hash)
            print("Hash bytes:", password_hash.encode('utf-8'))
            print("bcrypt version:", getattr(bcrypt, "__version__", "NO VERSION FIELD"))
            print("bcrypt module:", bcrypt)
			
            result = bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
            print("bcrypt.checkpw result:", result)
            print("===================================")

            return result
        except Exception as e:
            print("VERIFY_PASSWORD ERROR:", e)
            return False

    @staticmethod
    def generate_session_token() -> str:
        return secrets.token_urlsafe(TOKEN_LENGTH)

    async def authenticate(
        self,
        username: str,
        password: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> Tuple[bool, Optional[User], Optional[str], str]:

        stmt = select(User).where(or_(User.username == username, User.email == username))
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            await self._log_access(None, username, ActionType.LOGIN_FAILED, ip_address, user_agent, "Usuario no encontrado")
            return False, None, None, "Credenciales invalidas"

        if user.is_locked():
            remaining = (user.locked_until - datetime.utcnow()).seconds // 60
            return False, None, None, f"Cuenta bloqueada. Intente en {remaining} minutos"

        if not user.is_active:
            return False, None, None, "Cuenta desactivada"

        # DEBUG LOGIN
        try:
            print("========== DEBUG LOGIN ==========")
            print("User:", user.username)
            print("Password ingresada:", password)
            print("Hash en BD:", user.password_hash)
            print("Longitud hash:", len(user.password_hash))
            print("Check bcrypt:", bcrypt.checkpw(password.encode('utf-8'), user.password_hash.encode('utf-8')))
            print("=================================")
        except Exception as e:
            print("DEBUG ERROR:", e)

        # Verificar password
        if not self.verify_password(password, user.password_hash):
            user.login_attempts += 1

            if user.login_attempts >= MAX_LOGIN_ATTEMPTS:
                user.locked_until = datetime.utcnow() + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
                await self._log_access(user.id, user.username, ActionType.ACCOUNT_LOCKED, ip_address, user_agent, "Bloqueado")
                await self.db.commit()
                return False, None, None, f"Cuenta bloqueada por {LOCKOUT_DURATION_MINUTES} minutos"

            await self._log_access(user.id, user.username, ActionType.LOGIN_FAILED, ip_address, user_agent,
                                   f"Intento {user.login_attempts}/{MAX_LOGIN_ATTEMPTS}")
            await self.db.commit()

            remaining = MAX_LOGIN_ATTEMPTS - user.login_attempts
            return False, None, None, f"Credenciales invalidas. {remaining} intentos restantes"

        # Login exitoso
        user.login_attempts = 0
        user.locked_until = None
        user.last_login = datetime.utcnow()

        session_token = self.generate_session_token()
        session = UserSession(
            user_id=user.id,
            session_token=session_token,
            ip_address=ip_address,
            user_agent=user_agent,
            expires_at=datetime.utcnow() + timedelta(hours=SESSION_DURATION_HOURS)
        )
        self.db.add(session)

        await self._log_access(user.id, user.username, ActionType.LOGIN, ip_address, user_agent, "Login exitoso")
        await self.db.commit()

        return True, user, session_token, "Login exitoso"

    async def validate_session(self, session_token: str) -> Optional[User]:
        stmt = select(UserSession).where(
            and_(
                UserSession.session_token == session_token,
                UserSession.expires_at > datetime.utcnow()
            )
        )
        result = await self.db.execute(stmt)
        session = result.scalar_one_or_none()

        if not session:
            return None

        stmt = select(User).where(and_(User.id == session.user_id, User.is_active == True))
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def logout(self, session_token: str, ip_address: Optional[str] = None, user_agent: Optional[str] = None) -> bool:
        stmt = select(UserSession).where(UserSession.session_token == session_token)
        result = await self.db.execute(stmt)
        session = result.scalar_one_or_none()

        if session:
            stmt = select(User).where(User.id == session.user_id)
            result = await self.db.execute(stmt)
            user = result.scalar_one_or_none()

            await self.db.delete(session)

            if user:
                await self._log_access(user.id, user.username, ActionType.LOGOUT, ip_address, user_agent, "Logout")

            await self.db.commit()
            return True

        return False

    async def create_user(
        self,
        username: str,
        email: str,
        password: str,
        full_name: str,
        role: UserRole = UserRole.VIEWER,
        created_by: Optional[int] = None
    ) -> Tuple[bool, Optional[User], str]:

        stmt = select(User).where(User.username == username)
        result = await self.db.execute(stmt)
        if result.scalar_one_or_none():
            return False, None, "El nombre de usuario ya existe"

        stmt = select(User).where(User.email == email)
        result = await self.db.execute(stmt)
        if result.scalar_one_or_none():
            return False, None, "El email ya está registrado"

        user = User(
            username=username,
            email=email,
            password_hash=self.hash_password(password),
            full_name=full_name,
            role=role,
            is_active=True,
            created_by=created_by
        )
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)

        return True, user, "Usuario creado"

    async def update_user(
        self,
        user_id: int,
        email: Optional[str] = None,
        full_name: Optional[str] = None,
        role: Optional[UserRole] = None,
        is_active: Optional[bool] = None
    ) -> Tuple[bool, Optional[User], str]:

        stmt = select(User).where(User.id == user_id)
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            return False, None, "Usuario no encontrado"

        if email and email != user.email:
            stmt = select(User).where(and_(User.email == email, User.id != user_id))
            result = await self.db.execute(stmt)
            if result.scalar_one_or_none():
                return False, None, "El email ya esta en uso"
            user.email = email

        if full_name:
            user.full_name = full_name
        if role:
            user.role = role
        if is_active is not None:
            user.is_active = is_active

        await self.db.commit()
        await self.db.refresh(user)
        return True, user, "Usuario actualizado"

    async def reset_password(self, user_id: int, new_password: str) -> Tuple[bool, str]:
        stmt = select(User).where(User.id == user_id)
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            return False, "Usuario no encontrado"

        user.password_hash = self.hash_password(new_password)
        user.login_attempts = 0
        user.locked_until = None

        stmt = select(UserSession).where(UserSession.user_id == user_id)
        result = await self.db.execute(stmt)
        for session in result.scalars().all():
            await self.db.delete(session)

        await self.db.commit()
        return True, "Contraseña restablecida"

    async def get_user_by_id(self, user_id: int) -> Optional[User]:
        stmt = select(User).where(User.id == user_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all_users(self, include_inactive: bool = False) -> list:
        if include_inactive:
            stmt = select(User).order_by(User.created_at.desc())
        else:
            stmt = select(User).where(User.is_active == True).order_by(User.created_at.desc())

        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def delete_user(self, user_id: int) -> Tuple[bool, str]:
        stmt = select(User).where(User.id == user_id)
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            return False, "Usuario no encontrado"

        if user.role == UserRole.ADMIN:
            stmt = select(User).where(and_(User.role == UserRole.ADMIN, User.is_active == True))
            result = await self.db.execute(stmt)
            if len(list(result.scalars().all())) <= 1:
                return False, "No se puede eliminar el último administrador"

        user.is_active = False

        stmt = select(UserSession).where(UserSession.user_id == user_id)
        result = await self.db.execute(stmt)
        for session in result.scalars().all():
            await self.db.delete(session)

        await self.db.commit()
        return True, "Usuario eliminado"

    async def _log_access(
        self,
        user_id: Optional[int],
        username: Optional[str],
        action: ActionType,
        ip_address: Optional[str],
        user_agent: Optional[str],
        details: Optional[str] = None
    ):
        log = AccessLog(
            user_id=user_id,
            username=username,
            action=action,
            ip_address=ip_address,
            user_agent=user_agent,
            details=details
        )
        self.db.add(log)

    async def get_access_logs(self, user_id: Optional[int] = None, limit: int = 100) -> list:
        stmt = select(AccessLog)
        if user_id:
            stmt = stmt.where(AccessLog.user_id == user_id)

        stmt = stmt.order_by(AccessLog.created_at.desc()).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
