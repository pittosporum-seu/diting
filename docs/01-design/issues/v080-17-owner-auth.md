# Task 17 — Owner session, CSRF and Origin protection

## Goal

Protect every v1 write/control operation with a revocable single-owner browser session.

## Contract

- `DITING_OWNER_TOKEN_HASH` uses salted PBKDF2-SHA256 (minimum 200,000 iterations; generated at
  600,000 by default); plaintext is never stored.
- A valid token creates a persistent random session id and a signed 12-hour cookie.
- Cookie flags are HttpOnly and SameSite=Strict; production adds Secure.
- Unsafe requests require both an exact allowed/same Origin and a per-session CSRF token.
- Logout revokes the server-side session and clears the cookie.
- Missing startup secrets return `AUTH_NOT_CONFIGURED`; invalid credentials use a generic 401.
- FastAPI resource startup/shutdown uses lifespan instead of deprecated event decorators.
