from typing import Dict, Optional
from .models import User, Balance
from uuid import UUID

class Database:
    def __init__(self):
        self.users: Dict[str, User] = {}  # api_key -> User
        self.users_by_name: Dict[str, User] = {}  # name -> User
        self.balances: Dict[UUID, Balance] = {}  # user_id -> Balance

    def add_user(self, user: User) -> None:
        self.users[user.api_key] = user
        self.users_by_name[user.name] = user

    def get_user_by_api_key(self, api_key: str) -> Optional[User]:
        return self.users.get(api_key)

    def get_user_by_name(self, name: str) -> Optional[User]:
        return self.users_by_name.get(name)

    def get_balance(self, user_id: UUID) -> Balance:
        if user_id not in self.balances:
            self.balances[user_id] = Balance(user_id=user_id)
        return self.balances[user_id]

    def update_balance(self, user_id: UUID, ticker: str, amount: int) -> None:
        balance = self.get_balance(user_id)
        current_amount = balance.balances.get(ticker, 0)
        balance.balances[ticker] = current_amount + amount

# Create a global database instance
db = Database() 