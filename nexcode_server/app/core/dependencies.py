from fastapi import Depends, HTTPException, status, Request, Header, WebSocket, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, Annotated

from app.core.database import get_db
from app.services.auth_service import auth_service
from app.models.database import User

# HTTP Bearer 认证
security = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """获取当前用户（JWT或API Key认证）"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    user = None

    if credentials:
        token = credentials.credentials

        # 首先尝试JWT验证
        token_data = auth_service.verify_token(token)
        if token_data and token_data.user_id:
            user = await auth_service.get_user_by_id(db, token_data.user_id)

        # 如果JWT验证失败，尝试API Key验证
        if not user:
            user = await auth_service.verify_api_key(db, token)

    # 检查Session Token（从Cookie或Header）
    if not user:
        session_token = None

        # 从Cookie获取
        if "session_token" in request.cookies:
            session_token = request.cookies["session_token"]

        # 从Header获取
        elif "X-Session-Token" in request.headers:
            session_token = request.headers["X-Session-Token"]

        if session_token:
            user = await auth_service.verify_session_token(db, session_token)

    if not user:
        raise credentials_exception

    return user


def require_scope(required_scope: str):
    """创建需要特定权限范围的依赖"""
    async def check_scope(
        request: Request,
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        credentials_exception = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
        permission_exception = HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Insufficient permissions. Required scope: {required_scope}",
        )

        user = None

        if credentials:
            token = credentials.credentials

            # 首先尝试JWT验证
            token_data = auth_service.verify_token(token)
            if token_data and token_data.user_id:
                user = await auth_service.get_user_by_id(db, token_data.user_id)
                # JWT token暂时默认有所有权限
                return user

            # 尝试API Key验证并检查权限
            user = await auth_service.verify_api_key_permission(db, token, required_scope)
            if user:
                return user

        # 检查Session Token（默认有完整权限）
        session_token = None
        if "session_token" in request.cookies:
            session_token = request.cookies["session_token"]
        elif "X-Session-Token" in request.headers:
            session_token = request.headers["X-Session-Token"]

        if session_token:
            user = await auth_service.verify_session_token(db, session_token)
            if user:
                return user

        if not user:
            raise credentials_exception
        else:
            raise permission_exception

    return check_scope


async def get_current_user_ws(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> int:
    """WebSocket认证，返回用户ID"""
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        raise HTTPException(status_code=403, detail="Missing token")

    # 尝试验证session token
    user = await auth_service.verify_session_token(db, token)

    if not user:
        # 尝试JWT验证
        token_data = auth_service.verify_token(token)
        if token_data and token_data.user_id:
            user = await auth_service.get_user_by_id(db, token_data.user_id)

    if not user:
        # 尝试API Key验证
        user = await auth_service.verify_api_key(db, token)

    if not user or not user.is_active:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        raise HTTPException(status_code=403, detail="Invalid credentials")

    return user.id


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """获取当前活跃用户"""
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


async def get_current_superuser(current_user: User = Depends(get_current_user)) -> User:
    """获取当前超级用户"""
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions"
        )
    return current_user


async def get_optional_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """获取可选用户（不强制认证）"""
    try:
        return await get_current_user(request, credentials, db)
    except HTTPException:
        return None


# 类型别名
CurrentUser = Annotated[User, Depends(get_current_active_user)]
CurrentSuperUser = Annotated[User, Depends(get_current_superuser)]
OptionalUser = Annotated[Optional[User], Depends(get_optional_user)]
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
