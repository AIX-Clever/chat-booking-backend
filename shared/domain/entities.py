"""
Domain Entities for Chat Booking SaaS

Following Hexagonal Architecture principles:
- Pure domain objects
- No infrastructure dependencies
- Business logic encapsulation
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from enum import Enum


class BookingStatus(Enum):
    """Booking lifecycle states"""
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class PaymentStatus(Enum):
    """Payment states"""
    NONE = "NONE"
    PENDING = "PENDING"
    PAID = "PAID"
    FAILED = "FAILED"


class ConversationState(Enum):
    """FSM states for conversation flow"""
    INIT = "INIT"
    SERVICE_PENDING = "SERVICE_PENDING"
    SERVICE_SELECTED = "SERVICE_SELECTED"
    PROVIDER_PENDING = "PROVIDER_PENDING"
    PROVIDER_SELECTED = "PROVIDER_SELECTED"
    SLOT_PENDING = "SLOT_PENDING"
    CONFIRM_PENDING = "CONFIRM_PENDING"
    BOOKING_CONFIRMED = "BOOKING_CONFIRMED"


class TenantStatus(Enum):
    """Tenant account status"""
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TRIAL = "TRIAL"
    CANCELLED = "CANCELLED"


class TenantPlan(Enum):
    """Subscription plans"""
    LITE = "LITE"
    PRO = "PRO"
    BUSINESS = "BUSINESS"
    ENTERPRISE = "ENTERPRISE"


# Definición de límites por plan (Hardcoded por ahora - Source of Truth)
PLAN_LIMITS = {
    TenantPlan.LITE: {
        'messages': 500,
        'bookings': 50,
        'tokensIA': 0,        # No AI
        'ai_enabled': False
    },
    TenantPlan.PRO: {
        'messages': 2000,
        'bookings': 200,
        'tokensIA': 100000,   # ~100k tokens
        'ai_enabled': True
    },
    TenantPlan.BUSINESS: {
        'messages': 10000,
        'bookings': 1000,
        'tokensIA': 500000,   # ~500k tokens
        'ai_enabled': True
    },
    TenantPlan.ENTERPRISE: {
        'messages': 100000,
        'bookings': 10000,
        'tokensIA': 5000000,  # ~5m tokens
        'ai_enabled': True
    }
}


@dataclass
class TenantId:
    """Value Object for Tenant ID"""
    value: str

    def __post_init__(self):
        if not self.value or len(self.value) < 3:
            raise ValueError("TenantId must be at least 3 characters")

    def __str__(self) -> str:
        return self.value

    def __eq__(self, other) -> bool:
        if isinstance(other, TenantId):
            return self.value == other.value
        return False

    def __hash__(self) -> int:
        return hash(self.value)


@dataclass
class Tenant:
    """Tenant aggregate root"""
    tenant_id: TenantId
    name: str
    slug: str
    status: TenantStatus
    plan: TenantPlan
    owner_user_id: str
    billing_email: str
    settings: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def is_active(self) -> bool:
        """Check if tenant can use the service"""
        return self.status == TenantStatus.ACTIVE

    def can_create_booking(self) -> bool:
        """Business rule: only active tenants can create bookings"""
        return self.is_active()

    def get_plan_limits(self) -> Dict[str, Any]:
        """Get limits for current plan"""
        return PLAN_LIMITS.get(self.plan, PLAN_LIMITS[TenantPlan.LITE])

    def check_limit(self, metric: str, current_usage: int) -> bool:
        """
        Check if usage is within limits
        Returns True if ALLOWED (usage < limit), False if EXCEEDED
        """
        limits = self.get_plan_limits()
        limit = limits.get(metric, 0)
        
        # If limit is -1, it means unlimited (future proofing)
        if limit == -1:
            return True
            
        return current_usage < limit



@dataclass
class Category:
    """Category entity"""
    category_id: str
    tenant_id: TenantId
    name: str
    description: Optional[str] = None
    is_active: bool = True
    display_order: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class Service:
    """Service entity"""
    service_id: str
    tenant_id: TenantId
    name: str
    description: Optional[str]
    category: str
    duration_minutes: int
    price: Optional[float]
    currency: str = "USD"
    required_room_ids: Optional[List[str]] = None
    location_type: List[str] = field(default_factory=lambda: ["PHYSICAL"])
    active: bool = True

    def is_available(self) -> bool:
        """Check if service can be booked"""
        return self.active and self.duration_minutes > 0


@dataclass
class Provider:
    """Provider (professional) entity"""
    provider_id: str
    tenant_id: TenantId
    name: str
    bio: Optional[str]
    service_ids: List[str]
    timezone: str
    photo_url: Optional[str] = None
    photo_url_thumbnail: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    active: bool = True

    def can_provide_service(self, service_id: str) -> bool:
        """Check if provider offers specific service"""
        return self.active and service_id in self.service_ids


@dataclass
class TimeRange:
    """Value Object for time ranges"""
    start_time: str  # Format: "HH:MM"
    end_time: str    # Format: "HH:MM"

    def __post_init__(self):
        # Validate time format
        for time_str in [self.start_time, self.end_time]:
            try:
                hours, minutes = map(int, time_str.split(':'))
                if not (0 <= hours < 24 and 0 <= minutes < 60):
                    raise ValueError
            except (ValueError, AttributeError):
                raise ValueError(f"Invalid time format: {time_str}. Use HH:MM")

    def overlaps_with(self, other: 'TimeRange') -> bool:
        """Check if this time range overlaps with another"""
        return not (self.end_time <= other.start_time or self.start_time >= other.end_time)


@dataclass
class ProviderAvailability:
    """Provider availability for a specific day"""
    tenant_id: TenantId
    provider_id: str
    day_of_week: str  # MON, TUE, WED, THU, FRI, SAT, SUN
    time_ranges: List[TimeRange]
    breaks: List[TimeRange] = field(default_factory=list)
    exceptions: List[str] = field(default_factory=list)  # ISO date strings


@dataclass
class TimeSlot:
    """Value Object for available time slot"""
    provider_id: str
    service_id: str
    start: datetime
    end: datetime
    is_available: bool = True

    def duration_minutes(self) -> int:
        """Calculate slot duration"""
        return int((self.end - self.start).total_seconds() / 60)


@dataclass
class CustomerInfo:
    """Value Object for customer information"""
    customer_id: Optional[str]
    name: Optional[str]
    email: Optional[str]
    phone: Optional[str]

    def is_valid(self) -> bool:
        """At least email or phone should be provided"""
        return bool(self.email or self.phone)


@dataclass
class Booking:
    """Booking aggregate root"""
    booking_id: str
    tenant_id: TenantId
    service_id: str
    provider_id: str
    customer_info: CustomerInfo
    start_time: datetime
    end_time: datetime
    status: BookingStatus
    payment_status: PaymentStatus = PaymentStatus.NONE
    room_id: Optional[str] = None
    conversation_id: Optional[str] = None
    notes: Optional[str] = None
    # Payment fields
    payment_intent_id: Optional[str] = None
    payment_client_secret: Optional[str] = None # Not persisted usually, but needed for frontend
    total_amount: Optional[float] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def confirm(self):
        """Confirm booking"""
        if self.status == BookingStatus.PENDING:
            self.status = BookingStatus.CONFIRMED
        else:
            raise ValueError(f"Cannot confirm booking with status {self.status}")

    def cancel(self):
        """Cancel booking"""
        if self.status in [BookingStatus.PENDING, BookingStatus.CONFIRMED]:
            self.status = BookingStatus.CANCELLED
        else:
            raise ValueError(f"Cannot cancel booking with status {self.status}")

    def mark_as_no_show(self):
        """Mark booking as no show"""
        if self.status == BookingStatus.CONFIRMED:
            self.status = BookingStatus.NO_SHOW
        else:
            raise ValueError(f"Cannot mark as no show a booking with status {self.status}")

    def is_active(self) -> bool:
        """Check if booking is active"""
        return self.status in [BookingStatus.PENDING, BookingStatus.CONFIRMED]

    def overlaps_with(self, other: 'Booking') -> bool:
        """Check if this booking overlaps with another"""
        return (self.provider_id == other.provider_id and
                not (self.end_time <= other.start_time or self.start_time >= other.end_time))


@dataclass
class Message:
    """Chat message entity"""
    message_id: str
    sender: str  # USER, AGENT, SYSTEM
    text: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Conversation:
    """Conversation aggregate root"""
    conversation_id: str
    tenant_id: TenantId
    state: ConversationState
    service_id: Optional[str] = None
    provider_id: Optional[str] = None
    slot_start: Optional[datetime] = None
    slot_end: Optional[datetime] = None
    booking_id: Optional[str] = None
    workflow_id: Optional[str] = None
    current_step_id: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def transition_to(self, new_state: ConversationState):
        """Transition to new state"""
        self.state = new_state
        self.updated_at = datetime.now(timezone.utc)

    def set_service(self, service_id: str):
        """Set selected service"""
        self.service_id = service_id
        self.transition_to(ConversationState.SERVICE_SELECTED)

    def set_provider(self, provider_id: str):
        """Set selected provider"""
        self.provider_id = provider_id
        self.transition_to(ConversationState.PROVIDER_SELECTED)

    def set_slot(self, start: datetime, end: datetime):
        """Set selected time slot"""
        self.slot_start = start
        self.slot_end = end
        self.transition_to(ConversationState.SLOT_PENDING)

    def is_ready_for_booking(self) -> bool:
        """Check if all required data is present"""
        return all([
            self.service_id,
            self.provider_id,
            self.slot_start,
            self.slot_end
        ])

    def add_message(self, role: str, content: str, metadata: Dict[str, Any] = None):
        """Add a message to conversation history"""
        if not hasattr(self, 'messages') or self.messages is None:
            self.messages = []
            
        msg = {
            'role': role,
            'content': content,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        if metadata:
            msg['metadata'] = metadata
            
        self.messages.append(msg)
        self.updated_at = datetime.now(timezone.utc)

    def get_history(self) -> List[Dict[str, Any]]:
        """Get conversation history in standardized format"""
        if not hasattr(self, 'messages') or self.messages is None:
            return []
        return self.messages


@dataclass
class ApiKey:
    """API Key entity"""
    api_key_id: str
    tenant_id: TenantId
    api_key_hash: str
    status: str  # ACTIVE, REVOKED
    name: Optional[str] = None
    key_preview: Optional[str] = None  # e.g. "sk_live_12..."
    allowed_origins: List[str] = field(default_factory=list)
    rate_limit: int = 100
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_used_at: Optional[datetime] = None

    def is_valid(self) -> bool:
        """Check if API key is usable"""
        return self.status == "ACTIVE"

    def is_origin_allowed(self, origin: str) -> bool:
        """Check if origin is in allowed list"""
        if "*" in self.allowed_origins:
            return True
        return origin in self.allowed_origins


@dataclass
class FAQ:
    """Frequently Asked Question entity"""
    faq_id: str
    tenant_id: TenantId
    question: str
    answer: str
    category: str
    active: bool = True

@dataclass
class WorkflowStep:
    step_id: str
    type: str  # MESSAGE, QUESTION, TOOL, CONDITION, DYNAMIC_OPTIONS
    content: Dict[str, Any]
    next_step: Optional[str] = None

@dataclass
class Workflow:
    workflow_id: str
    tenant_id: TenantId
    name: str
    steps: Dict[str, WorkflowStep]
    description: Optional[str] = None
    is_active: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class Room:
    """Room (Box) entity"""
    room_id: str
    tenant_id: TenantId
    name: str
    description: Optional[str] = None
    capacity: Optional[int] = None
    status: str = "ACTIVE"  # ACTIVE, INACTIVE
    is_virtual: bool = False
    min_duration: Optional[int] = None
    max_duration: Optional[int] = None
    operating_hours: Optional[List[Dict[str, Any]]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
