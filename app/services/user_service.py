from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.models.user import User
from app.schemas.user import NewUser, UserRole
from app.core.security import create_api_key
from uuid import UUID, uuid4
import logging

async def create_user(db: Session, user_data: NewUser) -> User:
    """Создание нового пользователя"""
    logger = logging.getLogger(__name__)
    logger.info(f"Creating new user with name: {user_data.name}")
    
    # Создаём временный UUID для генерации временного api_key
    temp_uuid = uuid4()
    
    # Создаём пользователя с временным api_key
    user = User(
        name=user_data.name,
        role=UserRole.USER,
        api_key=create_api_key(temp_uuid)
    )
    
    db.add(user)
    try:
        db.commit()
        db.refresh(user)
        # Обновляем api_key с реальным id пользователя
        user.api_key = create_api_key(user.id)
        db.commit()
        logger.info(f"Successfully created user {user.id} (name: {user.name})")
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create user: {str(e)}")
        raise HTTPException(status_code=400, detail="Ошибка при создании пользователя")
    
    return user

async def delete_user(db: Session, user_id: UUID) -> User:
    """Удаление пользователя"""
    logger = logging.getLogger(__name__)
    logger.info(f"Attempting to delete user {user_id}")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        logger.error(f"User {user_id} not found")
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    try:
        logger.info(f"Deleting user {user_id} (name: {user.name})")
        db.delete(user)
        db.commit()
        logger.info(f"Successfully deleted user {user_id}")
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete user {user_id}: {str(e)}")
        raise HTTPException(status_code=400, detail="Ошибка при удалении пользователя")
    
    return user

async def get_user(db: Session, user_id: UUID) -> User:
    """Получение пользователя по ID"""
    logger = logging.getLogger(__name__)
    logger.debug(f"Getting user {user_id}")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        logger.error(f"User {user_id} not found")
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    logger.debug(f"Found user {user_id} (name: {user.name})")
    return user 