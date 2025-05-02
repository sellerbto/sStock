from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from .models import NewUser, User, LoginUser
from .database import db
from .auth import get_current_user
import os

app = FastAPI(
    title="Stock Exchange",
    description="A stock exchange trading platform",
    version="0.1.0",
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.get("/")
async def root():
    try:
        return FileResponse("app/static/index.html", media_type="text/html")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/public/register", response_model=User)
async def register(new_user: NewUser):
    # Проверяем, не существует ли уже пользователь с таким именем
    if db.get_user_by_name(new_user.name):
        raise HTTPException(status_code=400, detail="Пользователь с таким именем уже существует")
    
    user = User.create(name=new_user.name, password=new_user.password)
    db.add_user(user)
    return user

@app.post("/api/v1/public/login", response_model=User)
async def login(login_data: LoginUser):
    user = db.get_user_by_name(login_data.name)
    if not user or not user.check_password(login_data.password):
        raise HTTPException(status_code=401, detail="Неверное имя пользователя или пароль")
    return user

@app.get("/api/v1/me")
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user
