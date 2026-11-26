# Setting Up SSO/SAML and Renewing Your IdP Certificate

**Applies to:** Scale and Enterprise plans · **Last updated:** November 2026

## Overview

OrderLoop supports SAML 2.0 single sign-on (SSO) with Okta, Azure AD (Entra ID),
Google Workspace, and other SAML 2.0 identity providers (IdPs). Your IdP signs
each login response with an X.509 certificate. That certificate typically
expires after about one year.

## Symptoms of an expired IdP certificate

- Users authenticate successfully at the IdP, then get bounced straight back
  to the OrderLoop login page (a login loop) with no clear error message.
- SAML traces show "Signature validation failed".
- Password login still works if it is enabled.

## Setting up SSO (first time)

1. In OrderLoop, go to **Settings > Security > SSO/SAML** and copy the
   **ACS URL** and **Entity ID**.
2. In your IdP, create an application for OrderLoop (SAML 2.0) using those
   values.
3. Download the IdP metadata XML from your IdP.
4. Back in OrderLoop, upload the metadata XML (or paste the certificate) and
   click **Save**.
5. Test with one staff account before enforcing SSO for everyone.
6. Note the certificate expiry date and set a reminder 30 days before it.

## Renewing an expired certificate

1. In your IdP, open the OrderLoop application and check the signing
   certificate's expiry date. If it is expired, generate a new certificate or
   download fresh federation metadata:
   - **Okta:** Applications > OrderLoop > Sign On > View Setup Instructions,
     or download the metadata XML.
   - **Azure AD:** Enterprise applications > OrderLoop > Single sign-on >
     SAML Certificates > download the Federation Metadata XML.
2. In OrderLoop, go to **Settings > Security > SSO/SAML** and upload the new
   metadata XML (or paste the new certificate). Click **Save**.
3. Test SSO login with one account and confirm it reaches the dashboard.
4. Record the new expiry date and set a reminder 30 days before it.

## Troubleshooting

- **Only one user fails, everyone else works:** the user is probably not
  assigned to the OrderLoop application in the IdP. Check Assignments in the
  IdP — authentication can succeed while authorisation fails.
- **"Not authorised / access denied" after IdP login:** same cause — check
  group assignments, not the certificate.
- **Keep a break-glass account:** always keep one password-based admin account
  (or an emergency login) so a certificate expiry never locks the whole team
  out.
