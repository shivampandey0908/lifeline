from dataclasses import dataclass
from enum import StrEnum
from typing import Optional


class BookingStatus(StrEnum):
    CREATED = "CREATED"
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


TRANSITIONS = {
    BookingStatus.CREATED: {BookingStatus.PENDING, BookingStatus.CANCELLED},
    BookingStatus.PENDING: {BookingStatus.ACCEPTED, BookingStatus.REJECTED, BookingStatus.EXPIRED, BookingStatus.CANCELLED},
    BookingStatus.REJECTED: {BookingStatus.CANCELLED},
    BookingStatus.ACCEPTED: {BookingStatus.CANCELLED},
    BookingStatus.EXPIRED: {BookingStatus.CANCELLED},
    BookingStatus.CANCELLED: set(),
}


@dataclass(frozen=True)
class Provider:
    provider_id: str
    name: str
    provider_type: str
    service_area: str
    services: str
    contact: str
    available: bool
    is_demo: bool


@dataclass(frozen=True)
class ServiceRequest:
    request_id: str
    user_location: str
    category: str
    description: str
    selected_provider_id: str
    status: BookingStatus
    created_at: str
    updated_at: str
    provider_response_at: Optional[str]
    eta_minutes: Optional[int]
