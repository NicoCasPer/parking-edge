"""
auth.py — Autenticación y RBAC básico para el dashboard.

Roles:
  admin    — lectura + escritura + gestión de whitelist.
  operator — lectura + override manual de barrera.
  viewer   — solo lectura (logs, telemetría).

En producción, reemplazar _USERS con consulta a base de datos o LDAP.
"""

import hashlib
import hmac
import os
from typing import Optional

# En producción: cargar usuarios desde base de datos con contraseñas hasheadas.
# Aquí solo se provee un default de desarrollo controlado por variable de entorno.
_ADMIN_PASSWORD_HASH = hashlib.sha256(
    os.getenv("DASHBOARD_ADMIN_PASSWORD", "admin").encode()
).hexdigest()

_USERS = {
    "admin":    {"password_hash": _ADMIN_PASSWORD_HASH, "role": "admin"},
    "operator": {"password_hash": hashlib.sha256(b"operator").hexdigest(), "role": "operator"},
    "viewer":   {"password_hash": hashlib.sha256(b"viewer").hexdigest(), "role": "viewer"},
}

_ROLE_PERMISSIONS = {
    "admin":    {"read", "write", "whitelist", "override"},
    "operator": {"read", "override"},
    "viewer":   {"read"},
}


def authenticate(username: str, password: str) -> Optional[dict]:
    """Retorna el usuario si las credenciales son válidas, None si no."""
    user = _USERS.get(username)
    if not user:
        return None
    pw_hash = hashlib.sha256(password.encode()).hexdigest()
    if not hmac.compare_digest(pw_hash, user["password_hash"]):
        return None
    return {"username": username, "role": user["role"]}


def has_permission(role: str, permission: str) -> bool:
    """Retorna True si el rol tiene el permiso indicado."""
    return permission in _ROLE_PERMISSIONS.get(role, set())
