class VippsError(Exception):
    """Base error for the Vipps integration."""


class VippsAuthError(VippsError):
    """Failed to obtain or refresh an access token."""


class VippsAPIError(VippsError):
    """Vipps returned a non-success HTTP status."""

    def __init__(
        self,
        status_code: int,
        body: str,
        request_id: str | None = None,
        retryable: bool = False,
    ) -> None:
        self.status_code = status_code
        self.body = body
        self.request_id = request_id
        self.retryable = retryable
        super().__init__(
            f'Vipps API error: status={status_code} request_id={request_id} body={body[:500]}'
        )


class VippsSignatureError(VippsError):
    """HMAC verification failed on an incoming webhook."""
