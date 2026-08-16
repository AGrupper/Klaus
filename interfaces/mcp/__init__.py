"""The MCP surface Claude connects to.

Two scoped endpoints: interactive (live chat, may request approval) and
routine (scheduled reviews, can never approve). OAuth 2.1 + PKCE guards
both, and the gateway enforces scope, endpoint and idempotency on every
call before a tool runs."""
