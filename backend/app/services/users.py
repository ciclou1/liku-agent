from dataclasses import dataclass

from app.core.security import create_access_token, verify_password


@dataclass
class Account:
    username: str
    password_hash: str
    role: str
    organization_id: str | None
    warehouse_ids: frozenset[str]


class UserService:
    def __init__(self, password_hasher) -> None:
        self.accounts: dict[str, Account] = {
            "admin": Account("admin", password_hasher("admin"), "admin", "default", frozenset()),
            "demo": Account("demo", password_hasher("demo"), "manager", "default", frozenset()),
            "planner": Account("planner", password_hasher("planner"), "planner", "default", frozenset({"W1", "W2"})),
            "worker": Account("worker", password_hasher("worker"), "worker", "default", frozenset({"W1"})),
        }

    def login(self, username: str, password: str) -> tuple[str, str]:
        account = self.accounts.get(username)
        if not account or not verify_password(password, account.password_hash):
            raise ValueError("用户名或密码错误")
        return create_access_token(account.username, account.role, account.organization_id, sorted(account.warehouse_ids)), account.role

    def list_accounts(self) -> list[dict[str, object]]:
        return [{"username": account.username, "role": account.role, "organization_id": account.organization_id, "warehouse_ids": sorted(account.warehouse_ids)} for account in self.accounts.values()]
