"""Match domain enum. Documents live in the ``matches`` collection."""
import enum


class MatchStatus(str, enum.Enum):
    pending   = "pending"
    confirmed = "confirmed"
    cancelled = "cancelled"
    completed = "completed"
