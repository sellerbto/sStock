import os
import sys
from pathlib import Path

from api.models import Base
from api.database import db
from api.scripts.create_admin import create_admin

def init_db():
    try:
        Base.metadata.create_all(db.engine)
        print("Tables created successfully")

        create_admin()
        
        print("Database initialized successfully")
    except Exception as e:
        print(f"Error initializing database: {str(e)}")
        raise

if __name__ == "__main__":
    init_db() 