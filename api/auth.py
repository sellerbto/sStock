from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from .database import db
from .models import UserRole

security = HTTPBearer(scheme_name="TOKEN")

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    user = db.get_user_by_api_key(credentials.credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    return user

async def get_admin_user(current_user: str = Depends(get_current_user)) -> str:
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return current_user 