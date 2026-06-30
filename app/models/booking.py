"""Booking domain enum. Documents live in the ``bookings`` collection."""
import enum


class BookingStatus(str, enum.Enum):
    pending   = "pending"
    confirmed = "confirmed"
    cancelled = "cancelled"
    refunded  = "refunded"
