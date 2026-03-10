# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |

## Reporting a Vulnerability

If you discover a security vulnerability in OpenTutor, please report it responsibly:

1. **Do NOT** open a public GitHub issue for security vulnerabilities.
2. Email your report to the maintainer (see `package.json` or the repository owner's profile).
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

We aim to acknowledge reports within 48 hours and provide a fix within 7 days for critical issues.

## Security Best Practices for Deployment

- **Never expose OpenTutor to the public internet without authentication enabled.**
  Set `AUTH_ENABLED=true` and configure a strong `JWT_SECRET_KEY` (>= 32 characters).
- **Rotate API keys regularly.** Never commit `.env` files to version control.
- **Use HTTPS in production.** The CSRF middleware automatically sets `Secure` cookies in production mode.
- **Keep dependencies updated.** Run `pip-audit` and `npm audit` regularly.
- **Use container isolation for code sandbox.** Set `CODE_SANDBOX_BACKEND=container` in production.
