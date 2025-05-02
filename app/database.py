from typing import Dict, Optional
from .models import User

class Database:
    def __init__(self):
        self.users: Dict[str, User] = {}  # api_key -> User
        self.users_by_name: Dict[str, User] = {}  # name -> User

    def add_user(self, user: User) -> None:
        self.users[user.api_key] = user
        self.users_by_name[user.name] = user

    def get_user_by_api_key(self, api_key: str) -> Optional[User]:
        return self.users.get(api_key)

    def get_user_by_name(self, name: str) -> Optional[User]:
        return self.users_by_name.get(name)

# Create a global database instance
db = Database() 