"""Curated Juice Shop hacking-lab exercises for Phase 12 T5.

Zero-deps Python module (stdlib only). The seed script imports ``LABS`` and
inserts each entry into ``practice_problems`` with ``question_type =
"lab_exercise"``.

Juice Shop is expected to be reachable at ``http://localhost:3100``.

Schema per lab entry (all fields required unless noted):

    id:                   snake-case slug, unique within the catalogue
    title:                short human title
    category:             "XSS" | "SQLi" | "IDOR" | "Broken Auth"
                          | "Sensitive Data" | "Forged Coupon"
    difficulty:           "easy" | "medium" | "hard"
    task:                 multi-line markdown shown to the learner
    target_url:           deep link into Juice Shop (string)
    hints:                progressive list[str] (3 hints is the norm)
    verification_rubric:  server-side only — describes what the LLM grader
                          should accept as proof-of-solve. Never exposed
                          to UI.
    knowledge_points:     list[str] tags for the knowledge graph
    explanation:          post-solve teaching note

All URLs are anchored at ``http://localhost:3100`` because that's where the
local Juice Shop container is expected to be listening. If the port changes
in a future phase, update here and re-seed.
"""

from __future__ import annotations

from typing import Literal, TypedDict

Category = Literal[
    "XSS",
    "SQLi",
    "IDOR",
    "Broken Auth",
    "Sensitive Data",
    "Forged Coupon",
]
Difficulty = Literal["easy", "medium", "hard"]


class Lab(TypedDict):
    """One curated Juice Shop lab entry."""

    id: str
    title: str
    category: Category
    difficulty: Difficulty
    task: str
    target_url: str
    hints: list[str]
    verification_rubric: str
    knowledge_points: list[str]
    explanation: str


LABS: list[Lab] = [
    {
        "id": "reflected-xss-search",
        "title": "Reflected XSS in the Search Bar",
        "category": "XSS",
        "difficulty": "easy",
        "task": (
            "The Juice Shop search bar echoes your query back into the\n"
            "results header without escaping HTML. Craft a payload that\n"
            "pops a JavaScript `alert` dialog when the search runs.\n\n"
            "Target page: **Home → search bar** (top nav).\n\n"
            "Submit the exact payload you used **and** the text that\n"
            "appeared inside the resulting alert as your evidence."
        ),
        "target_url": "http://localhost:3100/#/search",
        "hints": [
            "Browsers execute JavaScript inside `<script>` tags and inside "
            "certain tag attributes like `onerror=`.",
            "Try a self-closing image tag with an `onerror` handler if "
            "plain `<script>` gets filtered: `<img src=x onerror=alert(1)>`.",
            "The search query is reflected into the DOM via the URL fragment. "
            "You can also hit the route directly: "
            '`/#/search?q=<iframe src="javascript:alert(`xss`)">`.',
        ],
        "verification_rubric": (
            "Accept the solve when the learner submits (a) a concrete XSS "
            "payload containing `<script>`, `onerror=`, or "
            "`javascript:` scheme AND (b) the alert text they observed "
            "(e.g. `1`, `xss`, or whatever their payload passed to "
            "`alert()`). Reject generic descriptions like `I saw a popup` "
            "without a payload. The canonical Juice Shop solved-flag for "
            "this challenge is `DOM XSS` / `xss-reflected-solved`; the "
            "score-board confirmation banner also counts as proof."
        ),
        "knowledge_points": ["xss", "input-validation", "dom", "reflected-xss"],
        "explanation": (
            "This is a textbook **reflected/DOM XSS**: user input flows "
            "into the page as HTML without sanitisation. The fix is to "
            "treat the query string as *text*, not markup — Angular's "
            "`{{ }}` interpolation escapes by default, but Juice Shop "
            "intentionally uses `bypassSecurityTrustHtml` here so you can "
            "see the attack. In production code, never call "
            "`innerHTML = userInput`; use `textContent` or a framework's "
            "safe-binding syntax."
        ),
    },
    {
        "id": "sqli-admin-login",
        "title": "Bypass Admin Login with SQL Injection",
        "category": "SQLi",
        "difficulty": "easy",
        "task": (
            "The login form builds its SQL query by string-concatenating\n"
            "the email and password. Log in as **admin** without knowing\n"
            "the password.\n\n"
            "Target page: **Account → Login**.\n\n"
            "Submit the exact email-field payload you used and paste the\n"
            "URL you landed on after login (it should contain\n"
            "`/administration` or show admin-only UI)."
        ),
        "target_url": "http://localhost:3100/#/login",
        "hints": [
            "SQL line-comments (`--` followed by a space in SQLite/MySQL) "
            "let you chop off the rest of a query, including the password "
            "check.",
            "Classic payloads for the email field: `' OR 1=1--` or simply "
            "`admin@juice-sh.op'--`. The password field can be anything.",
            "If `OR 1=1` returns the first user (often a non-admin), "
            "target admin explicitly: `' OR email LIKE '%admin%'--`.",
        ],
        "verification_rubric": (
            "Accept the solve when the learner submits: (a) an email-field "
            "payload containing a SQL meta-character sequence — a single "
            "quote plus one of `OR`, `--`, `/*`, or `UNION`; AND (b) proof "
            "they reached admin UI: either the URL `#/administration`, a "
            "screenshot/description of the admin user-list, or the Juice "
            "Shop banner `You successfully solved a challenge: Login "
            "Admin`. The canonical solved-flag is `loginAdminChallenge`. "
            "Reject payloads that merely mention SQLi in prose with no "
            "actual injection string."
        ),
        "knowledge_points": [
            "sqli",
            "authentication-bypass",
            "input-validation",
            "parameterised-queries",
        ],
        "explanation": (
            "Juice Shop's login concatenates user input into a raw SQL "
            "string, so `' OR 1=1--` turns `WHERE email='<x>' AND "
            "password='<y>'` into `WHERE email='' OR 1=1--...`, which "
            "matches every row. The real-world fix is **parameterised "
            "queries** (prepared statements) — the driver sends the SQL "
            "and the values on separate channels, so user input can never "
            "be interpreted as SQL syntax."
        ),
    },
    {
        "id": "idor-view-other-basket",
        "title": "View Another User's Shopping Basket (IDOR)",
        "category": "IDOR",
        "difficulty": "medium",
        "task": (
            "Shopping baskets are fetched from `/rest/basket/<id>`, where\n"
            "`<id>` is just a numeric basket id. The server checks that\n"
            "you are logged in — but *not* that the basket belongs to\n"
            "you. View someone else's basket.\n\n"
            "Target endpoint: **`/rest/basket/<bid>`** (use DevTools\n"
            "Network tab, Burp, or `curl` with your JWT cookie).\n\n"
            "Submit the basket id you accessed and paste the JSON response\n"
            "(or at least the `Products` array) as evidence."
        ),
        "target_url": "http://localhost:3100/#/basket",
        "hints": [
            "Log in as any user first, then open DevTools → Network and "
            "watch the request your own basket page makes. You'll see "
            "`GET /rest/basket/<your_id>` with an `Authorization` header.",
            "Replay the same request but change the numeric id — try "
            "`1`, `2`, `3` until you get someone else's data back.",
            '`curl -H "Authorization: Bearer <your_jwt>" '
            "http://localhost:3100/rest/basket/2` is the fastest way to "
            "sweep ids from the terminal.",
        ],
        "verification_rubric": (
            "Accept the solve when the learner submits: (a) a basket id "
            "different from their own logged-in user's basket id, AND "
            "(b) a JSON snippet (or faithful paraphrase) showing product "
            "rows — at minimum a `Products` array or a `BasketItems` "
            "array with items they did not add. A screenshot of the "
            "Network-tab response is also acceptable. The canonical "
            "Juice Shop flag is `viewBasketChallenge`. Reject submissions "
            "that only describe the attack without showing cross-tenant "
            "data."
        ),
        "knowledge_points": [
            "idor",
            "authorization",
            "broken-access-control",
            "owasp-a01",
        ],
        "explanation": (
            "**Insecure Direct Object Reference (IDOR)** — the server "
            "authenticates the request (valid JWT) but doesn't authorise "
            "it (does this basket belong to this user?). Fix: on every "
            "resource read, compare `resource.owner_id == "
            "current_user.id` before returning data. This class of bug is "
            "OWASP Top-10 A01: Broken Access Control, and it consistently "
            "ranks as the most common web vulnerability."
        ),
    },
    {
        "id": "email-enumeration-forgot-password",
        "title": "Enumerate Valid Emails via Forgot-Password",
        "category": "Broken Auth",
        "difficulty": "easy",
        "task": (
            "The forgot-password flow returns subtly different responses\n"
            "for real vs non-existent accounts — a classic user\n"
            "enumeration flaw. Identify a valid Juice Shop account email\n"
            "without being told which ones exist.\n\n"
            "Target page: **Account → Forgot Password**.\n\n"
            "Submit: (1) the email that got a 'valid user' response,\n"
            "(2) a random email that did NOT, and (3) the exact wording\n"
            "or behavioural difference between the two responses."
        ),
        "target_url": "http://localhost:3100/#/forgot-password",
        "hints": [
            "Try `bender@juice-sh.op` — a well-known default account in "
            "Juice Shop — and compare with `nobody-12345@example.invalid`.",
            "Look for differences in: the security question that appears, "
            "the HTTP status code, the response body length, or how long "
            "the request takes.",
            "A valid account typically reveals its security question "
            "(e.g. *'Your eldest siblings middle name?'*); an invalid one "
            "shows a generic error or nothing at all.",
        ],
        "verification_rubric": (
            "Accept the solve when the learner submits all three: "
            "(a) a real Juice Shop email — acceptable ones include any "
            "`@juice-sh.op` address (`admin@`, `jim@`, `bender@`, "
            "`bjoern.kimminich@gmail.com`, etc.); (b) a clearly-fake "
            "email they tried (e.g. `asdf@asdf.invalid`); AND (c) a "
            "concrete behavioural delta — the security question appears "
            "for the valid one, or the invalid one returns a different "
            "error / 404 / empty body. Reject answers missing any of the "
            "three components."
        ),
        "knowledge_points": [
            "user-enumeration",
            "broken-auth",
            "information-disclosure",
            "owasp-a07",
        ],
        "explanation": (
            "**User enumeration** leaks which emails are registered — "
            "the first step of credential-stuffing or targeted phishing. "
            "Mitigation: make the forgot-password endpoint return an "
            "identical response (status, body, timing) whether the email "
            "exists or not, and send the reset link asynchronously. Also "
            "applies to signup (`email already taken`) and login "
            "(`unknown user` vs `wrong password`)."
        ),
    },
    {
        "id": "ftp-directory-traversal",
        "title": "Leak Internal Files via the /ftp Directory",
        "category": "Sensitive Data",
        "difficulty": "medium",
        "task": (
            "Juice Shop serves an `/ftp` directory that was meant for\n"
            "public downloads (invoices, menus) but accidentally lists\n"
            "internal files. Find and download a file that clearly was\n"
            "not meant to be public.\n\n"
            "Target URL: **`http://localhost:3100/ftp`**.\n\n"
            "Submit the filename you retrieved and a one-sentence quote\n"
            "or summary of its content as evidence it was genuinely\n"
            "sensitive (e.g. acquisition terms, private notes, keys)."
        ),
        "target_url": "http://localhost:3100/ftp",
        "hints": [
            "Open `/ftp` directly in the browser — it renders as an Apache-"
            "style directory listing.",
            "Most files are `.pdf`/`.md` and open in the browser. If a "
            "download is blocked by extension whitelist, try a URL-encoded "
            "null byte trick: `?file.bak%2500.md` (classic Juice Shop).",
            "`acquisitions.md` is a juicy target — it contains unannounced "
            "M&A plans. Other interesting filenames: "
            "`suspicious_errors.yml`, `package.json.bak`, "
            "`coupons_2013.md.bak`.",
        ],
        "verification_rubric": (
            "Accept the solve when the learner submits: (a) a filename "
            "from `/ftp` that is clearly not a public invoice — accept "
            "`acquisitions.md`, `suspicious_errors.yml`, "
            "`package.json.bak`, `coupons_2013.md.bak`, "
            "`eastere.gg`, or any `.bak` / `.yml` / `.log` file; AND "
            "(b) a short quote, summary, or screenshot of content that "
            "reasonably matches that filename (e.g. for "
            "`acquisitions.md`: mention of a company being acquired, "
            "terms, signing date). Reject submissions that only name a "
            "public-looking file like `legal.md` without evidence of "
            "sensitive content."
        ),
        "knowledge_points": [
            "sensitive-data-exposure",
            "directory-listing",
            "path-traversal",
            "owasp-a01",
            "owasp-a05",
        ],
        "explanation": (
            "Two bugs chained: (1) **directory listing enabled** on a "
            "folder that holds more than just public downloads, and "
            "(2) **extension whitelist** that can be bypassed with a "
            "null-byte / poison-null trick. Fix: disable directory "
            "listings (`Options -Indexes` / explicit route whitelist), "
            "keep private files outside the web root entirely, and "
            "validate file requests against an allow-list of IDs, not "
            "user-supplied paths."
        ),
    },
    {
        "id": "forged-coupon-discount",
        "title": "Forge a Coupon Code for a Heavy Discount",
        "category": "Forged Coupon",
        "difficulty": "hard",
        "task": (
            "Juice Shop's coupon codes are generated by a weak,\n"
            "time-based algorithm that's baked into the client-side\n"
            "JavaScript. Redeem a coupon that gives at least a **80%**\n"
            "discount on your basket — without having been sent one.\n\n"
            "Target page: **Basket → Coupon field**.\n\n"
            "Submit: (1) the coupon string you used, (2) the discount\n"
            "percentage shown, and (3) a one-line description of how you\n"
            "generated it (algorithm name or source of the code)."
        ),
        "target_url": "http://localhost:3100/#/basket",
        "hints": [
            "Open DevTools → Sources and search the bundled JS for the "
            "word `coupon`. You'll find a `campaign` / `z85` encoder "
            "that wraps a date string.",
            "The coupon is the ASCII-85 (z85) encoding of "
            "`<CAMPAIGN>-<MMDDYY>` where the campaign is a 3-letter code. "
            "You can reproduce it in Node: `require('z85').encode(Buffer."
            "from('WMNSDY' + dateStr))`.",
            "If reversing the algorithm is too much, the source code is "
            "public: Juice Shop's `coupon.ts` / `config/default.yml` "
            "leaks the campaign codes. Pick one whose valid-until date "
            "covers today and encode it.",
        ],
        "verification_rubric": (
            "Accept the solve when the learner submits: (a) a coupon "
            "string of roughly 10 characters in z85 / ASCII-85 alphabet "
            "(`0-9 A-Z a-z .:+=^!/*?&<>()[]{}@%$#`); (b) a discount "
            "percentage of **≥ 80%** shown in the basket total (Juice "
            "Shop's forged-coupon challenge fires at 80%+); AND (c) a "
            "plausible one-liner on provenance — 'decoded the z85 in "
            "`main.js`', 'ran the generator from `coupon.ts`', or the "
            "campaign code they used (`WMNSDY`, `ORANGE`, `MAY`, etc.). "
            "The canonical Juice Shop flag is "
            "`forgedCouponChallenge`. Reject screenshots that show a "
            "discount below 80% even if a valid-looking code was used."
        ),
        "knowledge_points": [
            "cryptography-misuse",
            "client-side-secrets",
            "reverse-engineering",
            "business-logic",
        ],
        "explanation": (
            "Classic **client-side-secret** failure: anything shipped to "
            "the browser — JS bundles, mobile-app binaries, SPA source "
            "maps — must be treated as public. Juice Shop's coupon "
            "generator lives entirely in the frontend, so any attacker "
            "can read the algorithm and mint their own codes. The fix is "
            "to move coupon generation + validation server-side and treat "
            "each coupon as an opaque, signed token (e.g. HMAC over "
            "`campaign|expiry|discount`)."
        ),
    },
]


__all__ = ["LABS", "Lab", "Category", "Difficulty"]
