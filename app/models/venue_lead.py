"""Venue-lead domain enum. Documents live in the ``venue_leads`` collection."""
import enum


class VenueLeadStatus(str, enum.Enum):
    new = "new"
    contacted = "contacted"
    approved = "approved"
    rejected = "rejected"
