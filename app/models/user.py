"""User domain enums. Documents live in the ``users`` collection (see app.db.mongo)."""
import enum


class UserRole(str, enum.Enum):
    dater = "dater"
    venue = "venue"
    admin = "admin"
