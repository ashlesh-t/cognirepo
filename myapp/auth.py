from utils import compute_hash, verify_hash

class AuthManager:
    def login(self, username: str, password: str) -> bool:
        stored_hash = self._get_hash(username)
        return verify_hash(password, stored_hash)

    def _get_hash(self, username: str) -> str:
        return ""
