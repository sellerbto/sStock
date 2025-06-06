from api.models import User, UserRole
from api.database import db
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_admin():
    try:
        admin = db.get_user_by_name("admin")
        if admin:
            logger.info("Admin user already exists")
            return

        admin = User.create(
            name="admin",
            password="12345678",
            role=UserRole.ADMIN
        )
        
        db.add_user(admin)
        logger.info("Admin user created successfully")
        
        admin = db.get_user_by_name("admin")
        if admin:
            logger.info(f"Admin user verified: {admin.name}, role: {admin.role}")
        else:
            logger.error("Failed to verify admin user creation")
            
    except Exception as e:
        logger.error(f"Error creating admin user: {str(e)}")
        raise

if __name__ == "__main__":
    create_admin() 