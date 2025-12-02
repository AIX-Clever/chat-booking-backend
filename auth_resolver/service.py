"""
API Key Authentication Service (Application Layer)

Use Case: Resolve tenant from API Key and validate authorization
Following Clean Architecture / Hexagonal Architecture
"""

import sys
import os

# Add parent directory to path for shared imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from shared.domain.entities import TenantId, ApiKey
from shared.domain.repositories import IApiKeyRepository, ITenantRepository
from shared.domain.exceptions import (
    InvalidApiKeyError,
    OriginNotAllowedError,
    TenantNotActiveError,
    EntityNotFoundError
)
from shared.utils import hash_api_key, Logger


class AuthenticationService:
    """
    Application service for API Key authentication
    Follows Single Responsibility Principle
    """

    def __init__(
        self,
        api_key_repository: IApiKeyRepository,
        tenant_repository: ITenantRepository
    ):
        """
        Dependency Injection: depends on abstractions, not implementations
        """
        self.api_key_repo = api_key_repository
        self.tenant_repo = tenant_repository
        self.logger = Logger()

    def authenticate_api_key(
        self,
        api_key: str,
        origin: str
    ) -> TenantId:
        """
        Authenticate request using API Key
        
        Args:
            api_key: Public API key from request header
            origin: Request origin URL
            
        Returns:
            TenantId if authentication successful
            
        Raises:
            InvalidApiKeyError: API key not found or revoked
            OriginNotAllowedError: Origin not in allowed list
            TenantNotActiveError: Tenant account is not active
        """
        self.logger.info("Authenticating API key", origin=origin)

        # Hash the key to search in database
        api_key_hash = hash_api_key(api_key)

        # Find API key by hash
        api_key_entity = self.api_key_repo.find_by_hash(api_key_hash)

        if not api_key_entity:
            self.logger.warning("API key not found", api_key_hash=api_key_hash[:10])
            raise InvalidApiKeyError()

        # Validate API key is active
        if not api_key_entity.is_valid():
            self.logger.warning(
                "API key is not active",
                tenant_id=str(api_key_entity.tenant_id),
                status=api_key_entity.status
            )
            raise InvalidApiKeyError()

        # Validate origin is allowed
        if not api_key_entity.is_origin_allowed(origin):
            self.logger.warning(
                "Origin not allowed",
                tenant_id=str(api_key_entity.tenant_id),
                origin=origin,
                allowed_origins=api_key_entity.allowed_origins
            )
            raise OriginNotAllowedError(origin)

        # Get tenant and validate it's active
        tenant = self.tenant_repo.get_by_id(api_key_entity.tenant_id)

        if not tenant:
            self.logger.error(
                "Tenant not found for API key",
                tenant_id=str(api_key_entity.tenant_id)
            )
            raise EntityNotFoundError("Tenant", str(api_key_entity.tenant_id))

        if not tenant.is_active():
            self.logger.warning(
                "Tenant is not active",
                tenant_id=str(tenant.tenant_id),
                status=tenant.status.value
            )
            raise TenantNotActiveError(str(tenant.tenant_id))

        # Update last used timestamp (fire and forget)
        from datetime import datetime
        api_key_entity.last_used_at = datetime.utcnow()
        try:
            self.api_key_repo.save(api_key_entity)
        except Exception as e:
            # Don't fail authentication if update fails
            self.logger.warning("Failed to update last_used_at", error=str(e))

        self.logger.info(
            "Authentication successful",
            tenant_id=str(tenant.tenant_id)
        )

        return tenant.tenant_id


class RateLimiter:
    """
    Rate limiting service
    Open/Closed Principle: can be extended without modifying AuthenticationService
    """

    def __init__(self):
        # In production, this would use Redis or DynamoDB
        # For now, this is a placeholder
        self.logger = Logger()

    def check_rate_limit(self, tenant_id: TenantId, api_key_id: str) -> bool:
        """
        Check if request is within rate limits
        
        Returns:
            True if within limits, False otherwise
        """
        # TODO: Implement actual rate limiting with Redis/DynamoDB
        # For now, always return True
        self.logger.info(
            "Rate limit check (not implemented)",
            tenant_id=str(tenant_id),
            api_key_id=api_key_id
        )
        return True

    def increment_counter(self, tenant_id: TenantId, api_key_id: str) -> None:
        """Increment request counter for rate limiting"""
        # TODO: Implement counter
        pass
