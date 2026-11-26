# Resetting Two-Factor Authentication (2FA)

**Applies to:** All plans · **Last updated:** November 2026

## When you need a 2FA reset

- You got a new phone and your authenticator app was not transferred (the
  TOTP entry does not move with a normal phone backup).
- Your recovery codes are lost, already used, or from an old 2FA setup.
- The authenticator generates codes that OrderLoop rejects as "invalid code".

## Important: do not keep guessing

After **5 failed code attempts** your account is temporarily locked. Stop
guessing and start the reset flow instead — guessing cannot fix a missing
authenticator entry.

## Steps

1. On the login page, click **"Lost access to authenticator?"** and submit a
   2FA reset request.
2. **Verify your identity.** Support will ask for:
   - Access to the account owner's email address, and
   - A government-issued photo ID, and
   - The last 4 digits of the billing card, or your latest invoice number.
3. Once verified, support disables the old 2FA on your account.
4. Log in with your password, then re-enable 2FA on the new phone:
   **Settings > Security > Two-factor authentication > Set up** and scan the
   QR code with your authenticator app.
5. **Save the new recovery codes in a password manager** — not on paper, and
   not in an email thread. Each code can be used once.
6. Register a backup method: a mobile number for SMS backup, and nominate a
   **second administrator** so one locked-out person never blocks the whole
   team.

## After the reset

- Test a login with the new authenticator before closing the support ticket.
- If you are the only admin, add a second admin the same day.
- Recovery codes generated before the reset are invalid and should be
  discarded.
