from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from .database import db

security = HTTPBearer(scheme_name="TOKEN")

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    user = db.get_user_by_api_key(credentials.credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    return user 