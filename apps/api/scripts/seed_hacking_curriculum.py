"""Seed Hacking Foundations track — path + 6 rooms + inline MVP cards.

Mirrors ``seed_python_paths.py`` for the path/room upserts but also
bundles ~50 hand-crafted multiple-choice cards so the user can drill
from minute one without waiting for URL-ingest LLM runs.

Usage (inside api container)::

    python scripts/seed_hacking_curriculum.py [--dry-run]

Idempotent:
  * Path upsert by slug ``hacking-foundations``.
  * Rooms upsert by ``(path_id, slug)``.
  * Cards upsert by ``(course_id, question)`` — re-running won't dupe.

Cards are LLM-free so this script completes in under a second. URL
ingestion from ``content/hacking/curriculum.yaml`` remains available
later for deeper content enrichment (tracked as a follow-up).

Legality: every card text / explanation references the local Juice
Shop container (:3100) or explicit CTF labs as the practice target.
Never references attacking real third-party systems.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_API_DIR = Path(__file__).resolve().parent.parent
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from database import async_session  # noqa: E402
from models.course import Course  # noqa: E402
from models.learning_path import LearningPath, PathRoom  # noqa: E402
from models.practice import PracticeProblem  # noqa: E402
from models.user import User  # noqa: E402

# ── Cards library (inline, hand-crafted) ───────────────────────────────

# Each entry: (room_slug, question, options_dict, correct_key, explanation)
# Options are letter-keyed. ``correct_answer`` column stores the option
# value (not the letter), matching existing card convention.

_CARDS: list[tuple[str, str, dict[str, str], str, str]] = [
    # ── Room 1: Networking and HTTP basics ────────────────────────────
    (
        "networking-and-http",
        "Which HTTP method is meant to be idempotent and safe — repeating it should not change server state?",
        {"a": "POST", "b": "GET", "c": "PUT", "d": "DELETE"},
        "b",
        "GET is the classic 'safe + idempotent' method: it should only read. Attackers abuse GET-state-changing endpoints for CSRF.",
    ),
    (
        "networking-and-http",
        "A response with status code 401 means:",
        {"a": "Server is offline", "b": "Authentication required", "c": "Forbidden for this user", "d": "Resource moved"},
        "b",
        "401 Unauthorized = the request lacks valid authentication. 403 is 'authenticated but not allowed'.",
    ),
    (
        "networking-and-http",
        "Which header tells the browser to only send the cookie over HTTPS?",
        {"a": "HttpOnly", "b": "SameSite", "c": "Secure", "d": "Domain"},
        "c",
        "Secure flag restricts cookies to HTTPS. HttpOnly blocks JS access. SameSite restricts cross-site sending.",
    ),
    (
        "networking-and-http",
        "TCP handshake order is:",
        {"a": "SYN → SYN-ACK → ACK", "b": "ACK → SYN → SYN-ACK", "c": "SYN → ACK → FIN", "d": "GET → 200 → CLOSE"},
        "a",
        "Client sends SYN, server replies SYN-ACK, client confirms with ACK. Then data flows.",
    ),
    (
        "networking-and-http",
        "What does DNS do?",
        {"a": "Encrypts traffic", "b": "Resolves domain names to IP addresses", "c": "Routes packets across continents", "d": "Provides TLS certificates"},
        "b",
        "DNS maps human-readable names (example.com) to IP addresses. Attacks: DNS spoofing, cache poisoning.",
    ),
    (
        "networking-and-http",
        "Why is HTTPS important for login pages specifically?",
        {
            "a": "It makes pages load faster",
            "b": "It encrypts credentials in transit so eavesdroppers can't read them",
            "c": "It prevents SQL injection",
            "d": "It makes the session cookie longer",
        },
        "b",
        "Plain HTTP sends credentials in cleartext. HTTPS (TLS) encrypts the channel so sniffers on the network see only ciphertext.",
    ),
    (
        "networking-and-http",
        "Which HTTP status code family signals a server-side error?",
        {"a": "2xx", "b": "3xx", "c": "4xx", "d": "5xx"},
        "d",
        "5xx means the server failed. 4xx is client error. 2xx success. 3xx redirect.",
    ),
    (
        "networking-and-http",
        "What is a common marker an attacker looks for in HTTP response headers to fingerprint the server?",
        {"a": "Cache-Control", "b": "Server / X-Powered-By", "c": "Content-Length", "d": "Date"},
        "b",
        "Server and X-Powered-By headers often leak software + version. Strip them in prod.",
    ),
    # ── Room 2: Linux command line and Bash ───────────────────────────
    (
        "linux-and-bash",
        "Which command lists files including hidden dotfiles in long format?",
        {"a": "ls", "b": "ls -l", "c": "ls -la", "d": "dir"},
        "c",
        "-l = long format, -a = all including dotfiles. Combined: ls -la.",
    ),
    (
        "linux-and-bash",
        "How do you read the last 20 lines of a live-updating log file?",
        {"a": "cat -20 file.log", "b": "tail -20 file.log", "c": "tail -n 20 -f file.log", "d": "head -20 file.log"},
        "c",
        "-n 20 limits lines; -f follows the file as it grows. Essential for watching attack/defense logs live.",
    ),
    (
        "linux-and-bash",
        "Which operator appends command output to a file instead of overwriting?",
        {"a": ">", "b": ">>", "c": "<", "d": "|"},
        "b",
        ">> appends. > overwrites. | pipes to another command. < reads from file as stdin.",
    ),
    (
        "linux-and-bash",
        "How would you find every .php file under /var/www that contains the word 'admin'?",
        {
            "a": "find /var/www -name '*.php' | xargs grep -l admin",
            "b": "grep admin /var/www",
            "c": "ls /var/www/*.php | grep admin",
            "d": "cat /var/www | grep admin",
        },
        "a",
        "find narrows by name, xargs passes paths to grep -l (list-filenames-with-match). Classic recon one-liner.",
    ),
    (
        "linux-and-bash",
        "What does `curl -I https://example.com` do?",
        {
            "a": "Downloads the page body",
            "b": "Sends a HEAD request and prints response headers only",
            "c": "Runs an HTTPS scan",
            "d": "Fetches the SSL certificate",
        },
        "b",
        "-I = HEAD request. Fast way to see status + headers without downloading body. Useful for scanning endpoints.",
    ),
    (
        "linux-and-bash",
        "Which file on Linux stores user account entries (not passwords)?",
        {"a": "/etc/shadow", "b": "/etc/passwd", "c": "/etc/hosts", "d": "/etc/sudoers"},
        "b",
        "/etc/passwd = usernames, UIDs, home dirs. /etc/shadow = password hashes (root-only). Post-compromise recon target.",
    ),
    (
        "linux-and-bash",
        "How do you run a command in the background and detach it from your shell?",
        {"a": "nohup cmd &", "b": "cmd &&", "c": "bg cmd", "d": "wait cmd"},
        "a",
        "nohup makes the command survive shell exit; & backgrounds it. Reverse-shell persistence trick (in labs).",
    ),
    # ── Room 3: OWASP Top 10 ──────────────────────────────────────────
    (
        "owasp-top-10",
        "What does XSS stand for, and what does it let an attacker do?",
        {
            "a": "Cross-Site Scripting — inject JS that runs in the victim's browser",
            "b": "XML Script Service — parse malicious XML",
            "c": "External Secure Session — hijack user sessions",
            "d": "eXtreme Service Scanning — brute-force endpoints",
        },
        "a",
        "XSS injects attacker-controlled JavaScript into pages that other users load. Steals cookies, keys, session state.",
    ),
    (
        "owasp-top-10",
        "A login form concatenates: `SELECT * FROM users WHERE name='` + input + `'`. What input lets an attacker log in as any user?",
        {
            "a": "' OR 1=1 --",
            "b": "admin",
            "c": "password123",
            "d": "SELECT *",
        },
        "a",
        "Classic SQL injection: ' closes the string, OR 1=1 makes the WHERE always true, -- comments out the rest. Always parameterise queries.",
    ),
    (
        "owasp-top-10",
        "What does CSRF exploit?",
        {
            "a": "The user's trust in the attacker's site",
            "b": "The server's trust that requests with the user's cookies came from the user",
            "c": "A weak password",
            "d": "An outdated SSL certificate",
        },
        "b",
        "Cross-Site Request Forgery: the attacker's page silently submits a form to the target site; the browser attaches the victim's cookies. SameSite=Lax blocks most flavours.",
    ),
    (
        "owasp-top-10",
        "Which OWASP category is the bug where you change ?user_id=42 to ?user_id=43 and see someone else's data?",
        {
            "a": "Injection",
            "b": "Broken Access Control (IDOR)",
            "c": "Security Misconfiguration",
            "d": "Cryptographic Failures",
        },
        "b",
        "IDOR = Insecure Direct Object Reference, a flavour of Broken Access Control. The server didn't verify you're allowed to read user 43.",
    ),
    (
        "owasp-top-10",
        "A site's login accepts `admin:admin`. Which class of vuln is this?",
        {
            "a": "Default / weak credentials",
            "b": "SQL injection",
            "c": "Missing rate limit",
            "d": "XXE",
        },
        "a",
        "Default creds are a flavour of Identification and Authentication Failures in OWASP Top 10. Always force password reset on first login.",
    ),
    (
        "owasp-top-10",
        "Which header mitigates reflected XSS in modern browsers?",
        {
            "a": "X-Frame-Options",
            "b": "Content-Security-Policy",
            "c": "Strict-Transport-Security",
            "d": "X-Content-Type-Options",
        },
        "b",
        "CSP restricts which scripts can execute. Properly configured CSP blocks most reflected XSS even if the server echoed attacker input.",
    ),
    (
        "owasp-top-10",
        "An API accepts JWTs but doesn't verify the signature. An attacker changes the payload to {\"role\":\"admin\"} and the server trusts it. What category?",
        {
            "a": "Broken Authentication",
            "b": "Cryptographic Failures",
            "c": "Security Misconfiguration",
            "d": "Server-Side Request Forgery",
        },
        "a",
        "Broken Auth in OWASP Top 10. Never accept an unsigned or self-declared-alg=none JWT. Verify with the public key.",
    ),
    (
        "owasp-top-10",
        "You paste `<img src=x onerror=alert(1)>` into a comment box and it pops an alert. What vuln?",
        {
            "a": "Stored XSS",
            "b": "Clickjacking",
            "c": "Open redirect",
            "d": "HTTP response splitting",
        },
        "a",
        "The payload survived to the page body and ran in the next viewer's browser — that's stored (persistent) XSS. Escape + CSP fix it.",
    ),
    (
        "owasp-top-10",
        "A form sends `filename=../../etc/passwd`. What attack?",
        {
            "a": "Path traversal / directory traversal",
            "b": "Cross-site scripting",
            "c": "Command injection",
            "d": "Buffer overflow",
        },
        "a",
        "Path traversal / LFI. Never concatenate user input into a filesystem path — always resolve + verify the path stays inside the allowed root.",
    ),
    (
        "owasp-top-10",
        "A site fetches a URL you provide (?url=...) server-side. You change the URL to http://169.254.169.254/ — what are you testing for?",
        {
            "a": "SSRF (Server-Side Request Forgery)",
            "b": "DNS rebinding only",
            "c": "Open redirect",
            "d": "Reflected XSS",
        },
        "a",
        "SSRF. 169.254.169.254 is the AWS/GCP metadata endpoint — a classic target. Fix: allow-list destinations + block link-local.",
    ),
    (
        "owasp-top-10",
        "A report endpoint responds faster for valid usernames than invalid ones. What does this enable?",
        {
            "a": "Username enumeration",
            "b": "SQL injection",
            "c": "XXE",
            "d": "Clickjacking",
        },
        "a",
        "Timing side-channel username enumeration. Mitigation: make the response time constant whether the user exists or not.",
    ),
    (
        "owasp-top-10",
        "Your target's login is rate-limited per IP to 5/min. How do attackers typically bypass?",
        {
            "a": "Rotate through a proxy / residential IP pool",
            "b": "Use a bigger password list",
            "c": "Disable JavaScript",
            "d": "Send the password twice",
        },
        "a",
        "Per-IP rate limits fall to IP rotation. Mitigate with per-account lockouts + CAPTCHA at threshold + anomaly detection.",
    ),
    (
        "owasp-top-10",
        "A cookie called `session=eyJ1aWQi...` is a JWT. The attacker decodes its payload — what's their next move?",
        {
            "a": "Try to crack or bypass its signature",
            "b": "Encrypt it again",
            "c": "Delete it",
            "d": "Nothing — decoding means nothing",
        },
        "a",
        "JWT payloads are base64 (not encrypted). An attacker will try weak-secret HS256 cracking, alg=none tricks, or key confusion attacks.",
    ),
    (
        "owasp-top-10",
        "Which OWASP category covers 'using an outdated library with a known CVE'?",
        {
            "a": "Vulnerable and Outdated Components",
            "b": "Injection",
            "c": "Broken Access Control",
            "d": "Identification Failures",
        },
        "a",
        "A06:2021 in OWASP Top 10. Run dependency audits (pip-audit, npm audit) in CI.",
    ),
    # ── Room 4: Recon and scanning ────────────────────────────────────
    (
        "recon-and-scanning",
        "Which nmap flag does a TCP SYN 'stealth' scan (doesn't complete the handshake)?",
        {"a": "-sS", "b": "-sT", "c": "-sU", "d": "-sn"},
        "a",
        "-sS sends SYN, waits for SYN-ACK, RSTs instead of ACKing. Faster and less logged. Requires raw socket privileges.",
    ),
    (
        "recon-and-scanning",
        "What does `nmap -p- target` mean?",
        {"a": "Scan default ports", "b": "Scan all 65535 TCP ports", "c": "Scan UDP only", "d": "Stop on first open port"},
        "b",
        "-p- = all ports 1-65535. Slow but thorough — attackers hide services on high ports.",
    ),
    (
        "recon-and-scanning",
        "Which tool brute-forces directory + file names over HTTP to discover hidden paths?",
        {"a": "nmap", "b": "ffuf or dirsearch", "c": "tcpdump", "d": "netstat"},
        "b",
        "ffuf / dirsearch / gobuster. Feed a wordlist (common.txt, raft-*), filter by status code. Finds /admin, /.git, /backup.",
    ),
    (
        "recon-and-scanning",
        "What's the right follow-up after nmap reports 'Apache 2.4.49' on port 80?",
        {
            "a": "Look up CVEs for that exact version",
            "b": "Immediately run metasploit",
            "c": "Reboot the target",
            "d": "Close the port",
        },
        "a",
        "CVE lookup first — Apache 2.4.49 has the notorious CVE-2021-41773 path traversal. Only run exploits against systems you have permission to test.",
    ),
    (
        "recon-and-scanning",
        "A `robots.txt` file lists `/internal/` and `/old-admin/`. As an attacker, why does this matter?",
        {
            "a": "It signals paths the site owner doesn't want indexed — often sensitive",
            "b": "It blocks your scanner",
            "c": "It encrypts those paths",
            "d": "It has no security impact",
        },
        "a",
        "robots.txt is a disclosure, not an access control. Attackers specifically read it to find what the site tried to hide.",
    ),
    (
        "recon-and-scanning",
        "Why use `-T2` or `-T3` timing rather than `-T5` against a production target in a lab?",
        {
            "a": "Slower scans are stealthier and less likely to trip IDS / rate limits",
            "b": "Faster scans are more accurate",
            "c": "T5 only works on localhost",
            "d": "It's a random preference",
        },
        "a",
        "Nmap timing 0-5 (paranoid → insane). T3 default. T5 floods and triggers IDS / rate limits. Slow = subtle.",
    ),
    (
        "recon-and-scanning",
        "What is banner grabbing?",
        {
            "a": "Saving site banners as images",
            "b": "Reading the service's welcome text to fingerprint software and version",
            "c": "Intercepting TLS banners",
            "d": "Measuring HTTP cache",
        },
        "b",
        "Banner grabbing reads the text a service announces on connect (SSH-2.0-OpenSSH_8.9, Server: nginx/1.18). Feeds CVE lookups.",
    ),
    (
        "recon-and-scanning",
        "You want to see all HTTP endpoints on a SPA without guessing. Which technique works best?",
        {
            "a": "Read the JS bundle — routes, API URLs, and feature flags are often inlined",
            "b": "nmap the DNS",
            "c": "Port scan with -sU",
            "d": "Request /sitemap.xml only",
        },
        "a",
        "SPA JS bundles commonly leak API routes + internal endpoints in plain text. Download, prettify, grep for 'fetch(', '/api/', etc.",
    ),
    # ── Room 5: Exploitation toolkit ──────────────────────────────────
    (
        "exploitation-toolkit",
        "What does Burp Suite's Repeater tab do?",
        {
            "a": "Sends the same HTTP request at intervals",
            "b": "Lets you modify a captured request and replay it manually",
            "c": "Brute-forces login forms",
            "d": "Scans for XSS automatically",
        },
        "b",
        "Repeater = manual iterative request surgery. Change a param, replay, see the response. The workhorse tab for testing injections.",
    ),
    (
        "exploitation-toolkit",
        "Burp Intruder is best at:",
        {
            "a": "Automating variations of one request over a payload list",
            "b": "Proxying traffic passively",
            "c": "Decoding JWT tokens",
            "d": "Generating SSL certs",
        },
        "a",
        "Intruder fuzzes: pick positions in a request, feed a payload list, launch, analyse responses. Used for username enumeration, IDOR, parameter fuzzing.",
    ),
    (
        "exploitation-toolkit",
        "Your browser must trust Burp's CA to proxy HTTPS. What happens if you skip that step?",
        {
            "a": "HTTPS sites show cert errors; Burp can't decode traffic",
            "b": "Burp silently logs plaintext anyway",
            "c": "The browser downloads a special TLS version",
            "d": "Nothing changes",
        },
        "a",
        "Burp does TLS MITM using its own CA. Without importing + trusting it in the browser, you get invalid-cert warnings and Burp sees ciphertext only.",
    ),
    (
        "exploitation-toolkit",
        "In Metasploit, what is a 'payload'?",
        {
            "a": "The code that runs on the target after the exploit succeeds",
            "b": "The exploit itself",
            "c": "The scan output",
            "d": "The user's password",
        },
        "a",
        "Exploit = delivery mechanism. Payload = what runs on success (reverse shell, meterpreter session). Pair wisely for the target OS/arch.",
    ),
    (
        "exploitation-toolkit",
        "A `reverse shell` connects:",
        {
            "a": "From the target OUTBOUND to the attacker's listener",
            "b": "From the attacker INBOUND to the target",
            "c": "Over DNS only",
            "d": "Over IPv6 only",
        },
        "a",
        "Reverse shells flip the direction so outbound-only firewalls don't block the callback. Listener (nc -lnvp 4444) waits on the attacker side.",
    ),
    (
        "exploitation-toolkit",
        "You have a web form that lets you upload an image. What's the most common exploit vector if uploads aren't sanitised?",
        {
            "a": "Upload a web shell disguised as an image + find its URL",
            "b": "Upload a large file to DoS",
            "c": "Upload a file with no extension",
            "d": "There is no vector",
        },
        "a",
        "Classic web-shell-as-image. Mitigations: re-encode images, store outside web root, verify MIME + magic bytes, random filename.",
    ),
    (
        "exploitation-toolkit",
        "What is 'privilege escalation'?",
        {
            "a": "Going from low-privilege shell to root/admin on the compromised box",
            "b": "Scanning more ports",
            "c": "Upgrading your Burp license",
            "d": "Running sudo",
        },
        "a",
        "Priv-esc = turn initial foothold into full control. Tools: LinPEAS, WinPEAS, GTFOBins. Always second phase after initial exploit.",
    ),
    (
        "exploitation-toolkit",
        "Why are pentest reports usually the longest phase of a real engagement?",
        {
            "a": "Because the value is in the writeup + fix advice, not the exploit itself",
            "b": "Because tools take long to run",
            "c": "Because clients charge per page",
            "d": "Reports are usually shortest",
        },
        "a",
        "Clean writeup — reproducible steps, impact, CVSS, mitigation — is the deliverable. An exploit you can't document is useless to the client.",
    ),
    # ── Room 6: Juice Shop practice ───────────────────────────────────
    (
        "juice-shop-practice",
        "Where is the LearnDopamine local Juice Shop target running?",
        {
            "a": "http://localhost:3100",
            "b": "http://localhost:80",
            "c": "https://juice-shop.example.com",
            "d": "Inside the api container",
        },
        "a",
        "Phase 12 shipped Juice Shop as a sibling docker container on :3100. It's the legal practice target. Never test your techniques on third-party sites without written permission.",
    ),
    (
        "juice-shop-practice",
        "Juice Shop's scoreboard is hidden by default. How do you usually reveal it?",
        {
            "a": "Brute-force its URL or inspect the JS bundle",
            "b": "Ask the maintainer",
            "c": "Run nmap",
            "d": "Use admin credentials",
        },
        "a",
        "Classic Juice Shop first challenge: find the scoreboard. The path is /#/score-board — you can find it by reading the SPA bundle's route table.",
    ),
    (
        "juice-shop-practice",
        "When exploiting Juice Shop, what should you keep a running log of?",
        {
            "a": "Each vuln: description, steps to reproduce, what broke, what would fix it",
            "b": "Just the flags",
            "c": "Nothing — it's a lab",
            "d": "Only high-severity issues",
        },
        "a",
        "Practice the muscle of real pentest: structured notes are the deliverable. Even in a lab, writing steps + impact + fix turns practice into portfolio.",
    ),
    (
        "juice-shop-practice",
        "If an exploit technique you learn on Juice Shop works on a site you don't own, what do you do?",
        {
            "a": "Stop, document, and report it through a coordinated disclosure process — never exploit",
            "b": "Exploit it fully to 'prove' the bug",
            "c": "Share the exploit on social media",
            "d": "Sell the exploit",
        },
        "a",
        "Without explicit permission or a bug-bounty program, even benign probing can be illegal. Coordinated disclosure or bug bounty is the only safe path.",
    ),
    (
        "juice-shop-practice",
        "Juice Shop ships with an admin account using a weak credential. What's the lesson after you crack it?",
        {
            "a": "Default creds + weak hashes are a real-world win condition; deploy with forced rotation + strong hashing (argon2/bcrypt)",
            "b": "Juice Shop is fake, lessons don't transfer",
            "c": "Admin accounts are always weak",
            "d": "There is no lesson",
        },
        "a",
        "Every real pentest finds default/weak creds somewhere. Defense: forced password change on first login, argon2 hashing, MFA for privileged accounts.",
    ),
]


# ── Seed logic ─────────────────────────────────────────────────────────


_CURRICULUM_SUBPATH = Path("content") / "hacking" / "curriculum.yaml"


def _locate_curriculum() -> Path | None:
    """Walk up from this script looking for content/hacking/curriculum.yaml."""
    current = Path(__file__).resolve().parent
    for _ in range(8):
        candidate = current / _CURRICULUM_SUBPATH
        if candidate.is_file():
            return candidate
        if current.parent == current:
            break
        current = current.parent
    return None


async def _get_or_create_hacking_course(db: AsyncSession) -> uuid.UUID:
    """Ensure a dedicated ``Hacking Foundations`` course exists.

    Cards need a ``course_id``. We use one canonical course row per
    track so Phase 16a ``learning_paths`` joining stays straightforward.
    """
    user = (await db.execute(select(User).limit(1))).scalar_one_or_none()
    if user is None:
        user = User(id=uuid.uuid4(), name="Yurii")
        db.add(user)
        await db.flush()

    existing = (
        await db.execute(select(Course).where(Course.name == "Hacking Foundations"))
    ).scalar_one_or_none()
    if existing is not None:
        return existing.id
    course = Course(id=uuid.uuid4(), user_id=user.id, name="Hacking Foundations")
    db.add(course)
    await db.flush()
    return course.id


async def _upsert_path(db: AsyncSession, path_doc: dict[str, Any]) -> LearningPath:
    slug = path_doc["slug"]
    existing = (
        await db.execute(select(LearningPath).where(LearningPath.slug == slug))
    ).scalar_one_or_none()
    if existing is not None:
        existing.title = path_doc["title"]
        existing.track_id = path_doc["track_id"]
        existing.difficulty = path_doc["difficulty"]
        existing.description = path_doc.get("description")
        existing.room_count_target = len(path_doc.get("modules_count", [])) or 6
        await db.flush()
        return existing
    row = LearningPath(
        id=uuid.uuid4(),
        slug=slug,
        title=path_doc["title"],
        track_id=path_doc["track_id"],
        difficulty=path_doc["difficulty"],
        description=path_doc.get("description"),
        room_count_target=6,
    )
    db.add(row)
    await db.flush()
    return row


async def _upsert_room(
    db: AsyncSession,
    *,
    path_id: uuid.UUID,
    module: dict[str, Any],
    room_order: int,
) -> PathRoom:
    slug = module["slug"]
    existing = (
        await db.execute(
            select(PathRoom).where(PathRoom.path_id == path_id, PathRoom.slug == slug)
        )
    ).scalar_one_or_none()
    payload = {
        "title": module["title"],
        "room_order": room_order,
        "intro_excerpt": module.get("outcome") or "",
        "outcome": module.get("outcome") or "Complete this mission",
        "difficulty": int(module.get("difficulty", 2)),
        "eta_minutes": int(module.get("eta_minutes", 30)),
        "module_label": module.get("module_label", ""),
        "task_count_target": 8,
    }
    if existing is not None:
        for k, v in payload.items():
            setattr(existing, k, v)
        await db.flush()
        return existing
    row = PathRoom(id=uuid.uuid4(), path_id=path_id, slug=slug, **payload)
    db.add(row)
    await db.flush()
    return row


async def _upsert_card(
    db: AsyncSession,
    *,
    course_id: uuid.UUID,
    room_id: uuid.UUID,
    room_slug: str,
    question: str,
    options: dict[str, str],
    correct_key: str,
    explanation: str,
    task_order: int,
) -> bool:
    """Return True if a new row was inserted."""
    existing = (
        await db.execute(
            select(PracticeProblem).where(
                PracticeProblem.course_id == course_id,
                PracticeProblem.question == question,
            )
        )
    ).scalar_one_or_none()
    correct_value = options.get(correct_key, "")
    if existing is not None:
        existing.path_room_id = room_id
        existing.task_order = task_order
        existing.options = options
        existing.correct_answer = correct_value
        existing.explanation = explanation
        existing.difficulty_layer = 1
        existing.problem_metadata = {
            "concept_slug": f"hacking-{room_slug}",
            "source": "hand-crafted-mvp",
        }
        await db.flush()
        return False
    db.add(
        PracticeProblem(
            id=uuid.uuid4(),
            course_id=course_id,
            path_room_id=room_id,
            task_order=task_order,
            question_type="multiple_choice",
            question=question,
            options=options,
            correct_answer=correct_value,
            explanation=explanation,
            difficulty_layer=1,
            problem_metadata={
                "concept_slug": f"hacking-{room_slug}",
                "source": "hand-crafted-mvp",
            },
        )
    )
    await db.flush()
    return True


async def main(dry_run: bool = False, session_factory=async_session) -> int:
    yaml_path = _locate_curriculum()
    if yaml_path is None or not yaml_path.is_file():
        print("ERROR: content/hacking/curriculum.yaml not found")
        return 2
    print(f"Reading curriculum: {yaml_path}")

    doc = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    path_doc = doc.get("path", {})
    modules = doc.get("modules", []) or []
    if len(modules) != 6:
        print(f"WARNING: expected 6 modules, got {len(modules)}")

    async with session_factory() as db:
        course_id = await _get_or_create_hacking_course(db)
        path = await _upsert_path(db, path_doc)
        rooms_by_slug: dict[str, PathRoom] = {}
        for idx, module in enumerate(modules):
            room = await _upsert_room(
                db, path_id=path.id, module=module, room_order=idx
            )
            rooms_by_slug[module["slug"]] = room

        # Seed cards bucketed by room.
        task_counter: dict[str, int] = {slug: 0 for slug in rooms_by_slug}
        created = 0
        updated = 0
        for room_slug, question, options, correct, explanation in _CARDS:
            room = rooms_by_slug.get(room_slug)
            if room is None:
                print(f"  skip — unknown room: {room_slug}")
                continue
            order = task_counter[room_slug]
            is_new = await _upsert_card(
                db,
                course_id=course_id,
                room_id=room.id,
                room_slug=room_slug,
                question=question,
                options=options,
                correct_key=correct,
                explanation=explanation,
                task_order=order,
            )
            task_counter[room_slug] += 1
            if is_new:
                created += 1
            else:
                updated += 1

        if dry_run:
            await db.rollback()
            print(f"[DRY RUN] Would create {created} new cards, update {updated}.")
            return 0
        await db.commit()
        print(f"Path: {path.slug}  rooms: {len(rooms_by_slug)}  "
              f"cards: {created} new / {updated} updated")
        for slug, n in task_counter.items():
            print(f"  {slug:<28} {n} cards")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(dry_run=args.dry_run)))
