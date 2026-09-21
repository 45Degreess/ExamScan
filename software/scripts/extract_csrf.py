"""Read a JSON response from stdin (POST /auth/login) and print its
csrf_token to stdout, or exit 1 with the error on stderr. Used by the
Makefile so login failures stop `make` instead of writing a bad token."""
import json
import sys

body = json.load(sys.stdin)
token = body.get("csrf_token")
if not token:
    print(f"Login failed: {body}", file=sys.stderr)
    sys.exit(1)
print(token, end="")
