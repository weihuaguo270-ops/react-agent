# Rate limits

The Claude API enforces rate limits per organization.

When you exceed a rate limit, the API returns HTTP 429. Use exponential backoff and honor the `retry-after` header when present.

Rate limits are separate from token spend limits.
