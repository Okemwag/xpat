# Organisation readiness checklist

From a single-user prototype to a platform a reinsurer can roll out to its underwriting team.
Tick items as they are implemented **and tested**. Each item has an ID so commits and PRs can reference it (e.g. "Implements AUTH-07").

Status updated 2026-10-08. Legend: `[x]` done · `[~]` partly done today (see note) · `[ ]` to do · **P1** needed before any real organisation pilot · **P2** before general
availability · **P3** maturity / certification.

---

## 0. Where we are today (baseline)

| Area | Today | Gap for an organisation |
|---|---|---|
| Accounts | Local username/password, PBKDF2-SHA256 (310k iterations), password rules, 3 roles (analyst / reviewer / admin) | No organisations; "organisation" is a free-text field; self-sign-up open |
| Login protection | 5 failures → 5-minute lockout | Held **in memory**: resets on restart, not shared between server processes |
| Sessions | Streamlit `session_state` | Lost on browser refresh; no expiry, idle timeout or revocation |
| Guest access | "Explore as guest" with reviewer role | Must be **off** for organisation deployments |
| Data scope | Runs filtered by owner; evidence library and geocode cache global | No tenant isolation; no team sharing |
| Storage | Local JSON files (`runtime/store`), optional PostGIS for runs/evidence | JSON store is single-process; users never in the database |
| API | One shared `FLOODCAT_API_TOKEN` | No per-user or per-organisation identity, scopes or rotation |
| Audit | None (runs store config/input fingerprints only) | No record of who did what |
| Account flows | Register, sign in, change password | No invitation, e-mail verification, forgot password, MFA, deactivation |
| Admin | Admin can list users and change roles | No organisation admin console, no access reviews |

---

## 1. Decisions to make first

These change what gets built. Decide and record the answer next to each.

- [x] **DEC-01 Tenancy model.** One deployment per reinsurer (single-tenant) or one shared platform for many organisations (multi-tenant)?
  *Recommendation:* build multi-tenant data structures (an `organisation_id` on everything) even if the first customer gets a dedicated
  deployment. It costs little now and is very expensive to retrofit.
- [x] **DEC-02 Identity: SSO first or local accounts first?** Reinsurers usually run Microsoft Entra ID (Azure AD) or Google Workspace.
  *Recommendation:* **SSO via OpenID Connect as the primary login** (Streamlit 1.65 has built-in `st.login`/`st.user` for OIDC). The
  organisation's own identity provider then handles passwords, MFA, lockout and leavers. Keep local accounts only for small
  organisations and development. This removes most of section 3 from our responsibility for SSO organisations.
- [x] **DEC-03 Database.** Users, organisations, memberships, runs, evidence and audit must move to **PostgreSQL** (already optional for
  runs/evidence). The JSON store stays for development only.
- [ ] **DEC-04 Hosting and data residency.** Where does real client data live (Kenya, another African region, EU)? This drives the Kenya Data
  Protection Act cross-border analysis (see COMP-05) and the choice of AI provider region.
- [x] **DEC-05 E-mail provider** for invitations, password resets and alerts (needed only for local accounts and notifications).
- [ ] **DEC-06 AI data terms.** Use Gemini under terms that exclude training on customer data, with a known processing region; or let each
  organisation switch AI off (see GOV-06).
- [x] **DEC-07 Interface.** Stay on Streamlit (fastest; sessions and auth are its weak point) or move the authenticated app to a separate
  front-end on the existing FastAPI backend later. *Recommendation:* stay on Streamlit for the pilot with OIDC; revisit at P2.

---

## 2. Organisations and tenancy (foundation)

- [x] **ORG-01 P1** `organisations` table: name, legal entity, country, status (trial / active / suspended / closed), created date, plan.
- [x] **ORG-02 P1** `memberships`: a user belongs to one or more organisations with a role in each; the active organisation is part of the session.
- [x] **ORG-03 P1** `organisation_id` on every business record: runs, uploaded-document metadata, extractions, evidence, assumption sets, audit events, API tokens.
- [x] **ORG-04 P1** Isolation enforced in **one place** (repository layer or PostgreSQL row-level security), never in page code.
- [x] **ORG-05 P1** Isolation tests: a user of organisation A can never list, open, export or delete anything of organisation B, through the UI or the API.
- [x] **ORG-06 P2** Teams within an organisation (e.g. "Property Treaty", "Facultative", "East Africa desk"), used for sharing and visibility.
- [~] **ORG-07 P1** Evidence library and geocode cache scoped per organisation (evidence is one organisation's judgement; today it is global). *(Evidence is per organisation; the geocode cache is shared public OSM data.)*
- [x] **ORG-08 P2** Organisation settings: default assumptions, policy-term defaults, AI on/off, data retention, allowed sign-in domains.
- [x] **ORG-09 P1** Guest access disabled for organisation deployments (`FLOODCAT_ALLOW_GUEST=0`), kept only for public demos.
- [x] **ORG-10 P2** Organisation suspension (read-only, no new runs) and closure (export, then delete) — see DATA-06.

---

## 3. Authentication

### 3.1 Single sign-on (recommended primary)
- [x] **AUTH-01 P1** OIDC login (Entra ID, Google Workspace, Okta…) via `st.login`; map the IdP user to our user by verified e-mail / subject ID.
- [x] **AUTH-02 P1** Per-organisation IdP configuration and **allowed e-mail domains**; users from other domains cannot join.
- [x] **AUTH-03 P2** Just-in-time provisioning: first SSO login creates the membership with a default role (Viewer), never admin.
- [x] **AUTH-04 P2** Role mapping from IdP groups (optional), so HR/IT changes in the IdP flow through.
- [ ] **AUTH-05 P2** SCIM or scheduled sync for leavers: a user removed in the IdP loses access here the same day.
- [ ] **AUTH-06 P3** SAML for organisations that cannot use OIDC.

### 3.2 Local accounts (fallback)
- [x] **AUTH-07 P1** Password hashing: PBKDF2-SHA256 310k iterations exists; move to **Argon2id** (or keep PBKDF2 at OWASP-current iterations) with automatic re-hash on login.
- [x] **AUTH-08 P1** Password policy: today ≥10 chars + mixed case + digit. Move to NIST SP 800-63B style: **≥12 characters, no composition
  rules, check against a breached-password list**, no forced periodic change.
- [x] **AUTH-09 P1** Brute-force protection: today in memory. Persist failed-attempt counters in the database, per account **and** per IP,
  with progressive delays; generic error messages (no "user not found"). Timing-safe comparison exists.
- [x] **AUTH-10 P1** **MFA**: TOTP authenticator app, with recovery codes; **mandatory for admins**, configurable per organisation for everyone.
- [ ] **AUTH-11 P2** WebAuthn / passkeys as a second factor or passwordless option.
- [x] **AUTH-12 P1** Self-sign-up disabled for organisations: accounts are created only by **invitation** (FLOW-01).

### 3.3 Sessions
- [x] **AUTH-13 P1** Persistent, server-side sessions with a secure, HttpOnly, SameSite cookie (survive a page refresh; today they do not).
- [x] **AUTH-14 P1** Absolute session lifetime (e.g. 12 h) and idle timeout (e.g. 30 min, organisation-configurable).
- [x] **AUTH-15 P1** Revoke all sessions on password change, password reset, role change, deactivation and MFA reset.
- [x] **AUTH-16 P2** "Active sessions" list in the profile with sign-out of other devices.
- [x] **AUTH-17 P2** Re-authentication (step-up) before sensitive actions: changing e-mail, MFA, roles, SSO settings, exporting all data, deleting.

---

## 4. Account lifecycle flows

- [x] **FLOW-01 P1 Invitation.** Admin invites by e-mail with a role → single-use link (random token stored **hashed**, expires in 72 h) →
  user sets a password (or signs in with SSO) and MFA → membership active. Invitations can be resent and revoked.
- [x] **FLOW-02 P1 E-mail verification** for any e-mail address added or changed.
- [x] **FLOW-03 P1 Forgot password** (local accounts):
  - [ ] the request page always answers "If an account exists, we have sent a link" (no account enumeration);
  - [ ] token: random, single-use, stored hashed, expires in 30 minutes, previous tokens invalidated;
  - [ ] rate-limited per e-mail and per IP;
  - [ ] the reset requires MFA if the user has it;
  - [ ] on success: all sessions revoked, confirmation e-mail sent, event audited.
- [x] **FLOW-04 P1 Change password**: exists (requires current password). Add: breached-password check, session revocation, notification e-mail, audit.
- [x] **FLOW-05 P1 Change e-mail**: verify the new address, notify the old one, re-authentication required.
- [x] **FLOW-06 P1 MFA enrolment, recovery codes, and admin-assisted MFA reset** (audited, requires a second admin or support ticket).
- [x] **FLOW-07 P1 Deactivation (leaver)**: immediate loss of access, sessions and API tokens revoked, runs and evidence kept and **re-assigned**
  to another user; reversible within the retention period.
- [x] **FLOW-08 P2 Role change** flow with reason, audited, notification to the user.
- [x] **FLOW-09 P2 Account deletion / anonymisation** after retention (keeps audit records with a pseudonymous actor ID).
- [x] **FLOW-10 P1 Profile page**: exists (name, role). Add organisation, teams, MFA status, sessions, API tokens.

---

## 5. Roles and permissions (RBAC)

### 5.1 Roles (proposed)

| Role | Who | Summary |
|---|---|---|
| **Organisation owner** | Contract holder at the reinsurer | Everything an admin can do, plus plan, billing, closing the organisation. At least one, at most a few |
| **Organisation admin** | IT / underwriting operations | Users, invitations, roles, teams, SSO, security policy, audit log; **cannot** approve model or evidence by default |
| **Head of underwriting / model owner** | Senior underwriter or cat modeller | Approves organisation-wide assumption sets ("house view"); referral approvals |
| **Underwriter** | Day-to-day users | Upload schedules and documents, run analyses, export, use AI extraction |
| **Analyst / cat modeller** | Modelling team | As underwriter, plus sensitivity, personal assumption sandboxes, proposing assumption changes |
| **Evidence reviewer** | Designated reviewers | Approve or withdraw AI-extracted flood evidence |
| **Viewer** | Management, other departments | Read runs shared with them; no uploads, no AI |
| **Auditor / compliance** | Internal audit, compliance | Read-only access to the audit log and run records; no business actions |
| **Platform super-admin** | Xpat staff only | Tenant management; **no access to customer data** except audited, time-limited, customer-approved support access |

- [x] **RBAC-01 P1** Replace the three hard-coded roles with the role set above (today: analyst, reviewer, admin).
- [x] **RBAC-02 P1** Permissions defined **as code** (role → permissions) and checked by one function used by the UI and the API; pages hide what a role cannot do, the backend enforces it.
- [x] **RBAC-03 P1** A user can hold several roles (e.g. Underwriter + Evidence reviewer).
- [x] **RBAC-04 P1** Separation of duties: the person who **adds** evidence or **proposes** an assumption change cannot **approve** it.
- [x] **RBAC-05 P1** Admins do not automatically get business permissions (an IT admin cannot approve evidence or read every run unless granted).
- [x] **RBAC-06 P2** Data visibility levels per run: private · team · organisation, set by the owner; default team.
- [x] **RBAC-07 P2** Underwriting authority limits: e.g. an underwriter can mark a risk "recommended" only up to a TIV or modelled 1-in-250
  loss threshold; above it, a referral to Head of underwriting is required.
- [x] **RBAC-08 P1** Test suite: one test per row of the permission matrix (allowed and denied), for UI actions and API endpoints.
- [x] **RBAC-09 P2** Quarterly **access review** report for admins: who has which role, last login, dormant accounts (>90 days) flagged for removal.

### 5.2 Permission matrix (to implement and test — RBAC-08)

| Action | Owner | Admin | Head UW | Underwriter | Analyst | Reviewer | Viewer | Auditor |
|---|---|---|---|---|---|---|---|---|
| Invite / deactivate users, change roles | ✓ | ✓ | | | | | | |
| Configure SSO, MFA policy, session policy, retention | ✓ | ✓ | | | | | | |
| View audit log | ✓ | ✓ | | | | | | ✓ |
| Upload schedule / document, run analysis | ✓ | | ✓ | ✓ | ✓ | | | |
| Use AI extraction (sends text to Gemini) | ✓ | | ✓ | ✓ | ✓ | | | |
| View runs shared with them | ✓ | | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Export results | ✓ | | ✓ | ✓ | ✓ | | ✓ | |
| Edit personal assumption sandbox | | | ✓ | | ✓ | | | |
| Approve organisation assumption set | | | ✓ | | | | | |
| Add flood evidence | | | ✓ | ✓ | ✓ | ✓ | | |
| Approve / withdraw evidence | | | ✓ | | | ✓ | | |
| Delete a run | owner of the run, or Head UW | | | | | | | |
| Plan, billing, close organisation | ✓ | | | | | | | |

---

## 6. Audit log

- [x] **AUD-01 P1** An `audit_events` table: timestamp (UTC), organisation, actor (user ID, role at the time), action, target type and ID,
  outcome (success / denied / error), IP address, user agent, request ID, and a structured `details` field (before/after for changes).
- [x] **AUD-02 P1** Events recorded:
  - [ ] **Identity:** sign-in success and failure, MFA challenge and failure, lockout, sign-out, session revoked, password changed,
        reset requested and completed, MFA enrolled/reset, e-mail changed.
  - [ ] **Administration:** user invited, invitation accepted/revoked, role granted/removed, user deactivated/reactivated, SSO or security
        settings changed, API token created/revoked, support access granted/used.
  - [ ] **Data:** file uploaded (hash, type, size — never the content), AI extraction (document hash, model, prompt version, redaction counts,
        consent given), run created / opened / exported / shared / deleted, evidence added / approved / withdrawn / deleted,
        assumption set proposed / approved / activated (with the diff), data export, retention deletion.
  - [ ] **Access denied** events (permission checks that fail) — the early sign of misuse.
- [x] **AUD-03 P1** **Append-only**: no update or delete through the application; database permissions enforce it.
- [x] **AUD-04 P2** Tamper evidence: each event stores a hash of the previous one (hash chain); a daily job verifies the chain.
- [x] **AUD-05 P1** Never log secrets, passwords, tokens, document text or personal contact details.
- [x] **AUD-06 P1** Audit viewer for admins and auditors: filter by user, action, date, target; export to CSV.
- [~] **AUD-07 P2** Retention of audit records (e.g. 7 years, to match underwriting record-keeping) separate from business-data retention. *(Retention setting exists; deletion of audit rows needs a privileged maintenance role, not the app.)*
- [x] **AUD-08 P2** Alerts: repeated failed sign-ins, sign-in from a new country, mass export, role escalation, audit chain break.
- [x] **AUD-09 P1** Tests: every action in AUD-02 produces exactly one event with the right actor and outcome.

---

## 7. Security

### 7.1 Application
- [x] **SEC-01** Upload hardening: size and page limits, type detection from bytes, zip-bomb limits, no macros executed, scanned-PDF rejection.
- [x] **SEC-02** AI input/output hardening: document text treated as data, JSON-schema responses, quotes verified, outputs re-validated, bounded group counts.
- [x] **SEC-03** Contact details redacted before AI; consent before sending text to Gemini; original files not stored.
- [x] **SEC-04 P1** Malware scanning of uploaded files before parsing (e.g. ClamAV), or parsing in an isolated worker with no network.
- [x] **SEC-05 P1** Rate limits and quotas: sign-in, password reset, uploads, AI calls per user and per organisation (cost and abuse control).
- [x] **SEC-06 P1** API: replace the single shared token with **per-user or per-organisation API tokens** (scoped, hashed at rest, expiring, revocable, audited).
- [x] **SEC-07 P1** Security headers and HTTPS only (HSTS), CORS restricted to known origins (exists, env-configured), CSRF protection on any non-Streamlit forms.
- [~] **SEC-08 P1** Secrets in a secrets manager (not `.env`) in production; rotate the Gemini key and database credentials; separate keys per environment. *(FLOODCAT_SECRET_KEY required in production; a vault integration is still to do.)*
- [ ] **SEC-09 P2** Dependency and container scanning in CI; static analysis (bandit/semgrep); pinned lockfile (exists: `uv.lock`).
- [ ] **SEC-10 P2** Independent penetration test before general availability; fix findings; re-test.
- [x] **SEC-11 P1** Error pages never show stack traces or internal paths to users.

### 7.2 Data and infrastructure
- [~] **SEC-12 P1** Encryption in transit (TLS 1.2+) everywhere, including to the database. *(HTTPS via Caddy in compose; TLS to the database still to configure per host.)*
- [~] **SEC-13 P1** Encryption at rest for the database, backups and any file storage. *(Secrets and stored inputs encrypted in the application; disk/backup encryption is the host's job.)*
- [ ] **SEC-14 P1** Backups: daily, encrypted, retained per policy, **restore tested** quarterly; defined RPO/RTO (e.g. 24 h / 8 h).
- [ ] **SEC-15 P2** Separate environments (development, staging, production); no real client data outside production.
- [ ] **SEC-16 P2** Monitoring and alerting: uptime, errors, latency, AI provider failures, unusual usage.
- [ ] **SEC-17 P2** Incident response plan: severity levels, on-call, customer notification, regulator notification (COMP-07).
- [ ] **SEC-18 P3** Vulnerability disclosure policy and security contact.

---

## 8. Privacy and compliance

*Not legal advice — confirm each item with counsel. Kenya-specific items reflect the Data Protection Act, 2019 and its regulations.*

- [ ] **COMP-01 P1** Roles under data-protection law: the reinsurer is usually the **data controller** for its submissions; Xpat is a
  **data processor**. Sign a **data processing agreement** with each organisation.
- [ ] **COMP-02 P1** Registration with the **Office of the Data Protection Commissioner (ODPC)** as required for Xpat's role.
- [ ] **COMP-03 P1** **Data protection impact assessment (DPIA)** for AI processing of submission documents (personal data of brokers, clients and tenants may appear).
- [ ] **COMP-04 P1** Sub-processor list published and kept current (cloud host, Google Gemini, e-mail provider, geocoding), with notice of changes.
- [ ] **COMP-05 P1** Cross-border transfer assessment: where Gemini and the hosting process data, and the safeguards relied on; organisation-level option to disable AI.
- [ ] **COMP-06 P1** Retention schedule: runs, extractions, evidence, audit logs, accounts — with automatic deletion jobs (DATA-04).
- [ ] **COMP-07 P1** Breach procedure, including notification to the ODPC within the statutory deadline (72 hours) and to affected organisations.
- [ ] **COMP-08 P2** Data-subject requests: find and export or erase personal data about a person on request (mostly names in quotes and user accounts).
- [ ] **COMP-09 P2** Insurance-regulator expectations: check the Insurance Regulatory Authority's requirements on outsourcing, cyber security and
  record keeping for insurers and reinsurers using third-party platforms; record the outcome.
- [ ] **COMP-10 P2** Model governance documentation for customers' model-risk teams: methodology (docs/REPORT.md), assumptions register,
  validation evidence, change log, known limitations — versioned per release.
- [ ] **COMP-11 P2** Terms of use stating that results are indicative and not a price or underwriting advice (the app already says so).
- [ ] **COMP-12 P3** Security certification roadmap (ISO 27001 or SOC 2) — usually requested in reinsurer vendor due diligence.

---

## 9. Data management

- [x] **DATA-01 P1** Move users, organisations, memberships, sessions, runs, evidence, assumption sets and audit events to PostgreSQL with migrations (Alembic exists).
- [x] **DATA-02 P1** Store an **extraction record** per document: file hash, type, page count, model, prompt version, extracted fields with quotes, checks shown, user decisions (location chosen, deductible basis), consent — but not the document text.
- [ ] **DATA-03 P2** Optional encrypted storage of the original document per organisation setting (some customers will want it attached to the file; default off).
- [x] **DATA-04 P1** Retention jobs that delete expired runs and extractions per organisation setting; deletions audited.
- [x] **DATA-05 P2** Organisation data export (all runs, extractions, evidence, assumption sets, audit log) for portability and exit.
- [x] **DATA-06 P2** Organisation closure: export window, then verified deletion, including backups after their rotation period.
- [x] **DATA-07** Real vs synthetic origin recorded per record and shown as REAL / SYNTHETIC on every result.

---

## 10. Model governance (organisation-level)

- [x] **GOV-01 P1** Organisation assumption sets ("house view"): versioned copies of `configs/default.json` owned by the organisation.
- [x] **GOV-02 P1** Maker–checker: analysts propose a change (with reason), Head of underwriting approves; only approved sets can be the organisation default.
- [x] **GOV-03 P2** Personal sandboxes: users can try assumptions without changing the house view; results show "custom assumptions" (exists as a session badge).
- [x] **GOV-04** Every run records its config version and fingerprint, input fingerprint and evidence snapshot (reproducible).
- [ ] **GOV-05 P2** Re-run a past analysis under a newer assumption set and compare (model-change impact).
- [x] **GOV-06 P1** Organisation switch for AI features (off / extraction only / extraction + evidence), with the provider and region shown.
- [ ] **GOV-07 P2** Organisation-level evaluation: re-run `make eval-ingestion` on organisation-approved test cases and show the result.

---

## 11. Collaboration and underwriting workflow

- [x] **WF-01 P2** "Submission" (account / deal) object: cedant or broker, inception date, documents, runs, status.
- [x] **WF-02 P2** Status workflow: received → under review → referred → quoted → bound / declined, with who and when (audited).
- [x] **WF-03 P2** Assignment to an underwriter and team; "my submissions" view.
- [x] **WF-04 P2** Notes and comments on a submission and on individual checks (e.g. "GPS confirmed with broker").
- [x] **WF-05 P2** Referral to Head of underwriting when authority limits are exceeded (RBAC-07).
- [~] **WF-06 P2** Notifications (in-app and e-mail): assignment, referral, evidence awaiting review, approvals. *(In-app notifications done; e-mail only for security alerts and account flows.)*
- [ ] **WF-07 P3** Portfolio view across all bound submissions: accumulation by area for the whole organisation.

---

## 12. Admin panel — is it necessary?

**Yes, and it should be two separate panels.**

- An **organisation admin console** lets the reinsurer run its own team: without it, every new underwriter, leaver, role change and access
  review becomes a support ticket to us, and the reinsurer cannot evidence its access controls to auditors or the regulator.
- A **platform super-admin console** (Xpat staff) manages tenants and support. It must not see customer data by default.

### 12.1 Organisation admin console
- [x] **ADM-01 P1** Users: list, invite, resend/revoke invitations, deactivate/reactivate, change roles, reset MFA (audited). *(Today: list users and change role.)*
- [x] **ADM-02 P1** Security policy: MFA required (all / admins), session timeout, allowed e-mail domains, SSO configuration.
- [x] **ADM-03 P1** Audit log viewer and export (AUD-06).
- [x] **ADM-04 P2** Teams management.
- [x] **ADM-05 P2** Access review report (RBAC-09).
- [x] **ADM-06 P2** Organisation settings: AI features, data retention, default assumption set, policy-term defaults.
- [~] **ADM-07 P2** API tokens for integrations (SEC-06). *(Users create scoped tokens in Profile; an admin-wide token list is not yet in the UI.)*
- [x] **ADM-08 P2** Usage: properties modelled, documents read, AI calls, against plan limits.

### 12.2 Platform super-admin console
- [x] **ADM-09 P1** Create, suspend and close organisations; assign the first owner.
- [x] **ADM-10 P2** Support access: time-limited, customer-approved, fully audited "break-glass" access; visible to the customer.
- [x] **ADM-11 P2** Feature flags per organisation; global health and AI provider status.

---

## 13. Organisation account and commercial

- [x] **ACC-01 P2** Organisation profile: legal name, address, data-protection contact, technical contact, billing contact.
- [~] **ACC-02 P2** Plan and seats (ties to the Pricing page), trial period and limits. *(Plan and seats enforced; no Pricing page or trial billing.)*
- [~] **ACC-03 P3** Usage metering and invoices. *(Usage metered; no invoices.)*
- [ ] **ACC-04 P2** Customer onboarding checklist: DPA signed, SSO configured, admins invited, house assumptions approved, test run done.
- [ ] **ACC-05 P2** Help centre, support channel, service status page.

---

## 14. Acceptance tests (definition of done for this checklist)

- [x] **TEST-01 P1** Tenant isolation (ORG-05) passes for every list, open, export and delete path in UI and API.
- [x] **TEST-02 P1** Permission matrix (RBAC-08): allowed and denied for every cell.
- [x] **TEST-03 P1** Auth flows end to end: invite → accept → MFA → sign in → forgot password → reset → old sessions revoked.
- [x] **TEST-04 P1** Audit completeness (AUD-09).
- [x] **TEST-05 P1** Leaver test: deactivated user loses UI, API and session access within one minute.
- [ ] **TEST-06 P2** Restore from backup into a clean environment and verify a past run reproduces.
- [ ] **TEST-07 P2** External penetration test passed (SEC-10).

---

## 15. Suggested order of work

1. **Foundation (P1):** DEC-01…07 → DATA-01 → ORG-01…05, 07, 09 → AUD-01…03, 05.
2. **Identity (P1):** AUTH-01, 02 (SSO) **or** AUTH-07…12 + FLOW-01…07 (local) → AUTH-13…15.
3. **Access control (P1):** RBAC-01…05, 08 → ADM-01…03, 09.
4. **Hardening and compliance (P1):** SEC-04…08, 11…14 → COMP-01…07 → DATA-02, 04 → GOV-01, 02, 06.
5. **Pilot with one reinsurer.**
6. **P2:** workflow, teams, access reviews, alerts, exports, penetration test.
7. **P3:** certification, SAML, portfolio-wide accumulation.
