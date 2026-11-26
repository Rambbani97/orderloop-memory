# iOS Push Notifications Troubleshooting

**Applies to:** OrderLoop Mobile for iOS · **Last updated:** November 2026

## How push notifications work

OrderLoop sends new-order alerts through Apple Push Notification service
(APNs). Your device registers a device token with OrderLoop when you log in.
If the token is not registered — or if iOS permission is off — no alerts
arrive, even though orders still appear when you open the app.

## If notifications stop after an app update

App updates (and iOS updates) can invalidate the registered device token and
sometimes reset notification permissions. Work through these steps in order:

1. **Check iOS permission:** iPhone **Settings > OrderLoop > Notifications**
   — make sure **Allow Notifications** is ON, including Lock Screen and
   Banners.
2. **Re-register the device token:** in the OrderLoop app, log out and log
   back in. This registers a fresh APNs token. (Alternatively: in-app
   **Settings > Notifications**, toggle notifications OFF and back ON.)
3. **Send a test push:** from the OrderLoop web dashboard, go to **Settings >
   Mobile > Send test push**. You should receive it within seconds.
4. **Check Focus / Do Not Disturb:** make sure no Focus mode is silencing
   OrderLoop. Add OrderLoop to the allowed apps in the Focus settings if
   needed.
5. **Last resort:** delete the app and reinstall it from the App Store, then
   log in again.

## If only some devices are affected

Repeat steps 1–2 on each affected device — tokens are per device, so one phone
can work while another does not. The "Send test push" tool lets you target a
specific device.

## What is not the cause

- Notifications turned ON inside the app alone is not enough — the iOS-level
  permission (step 1) must also be on.
- A slow network does not silently disable push; if the app loads orders when
  opened, connectivity is fine and the problem is the token or the permission.

## Still not working?

Contact support with your device model, iOS version, and app version
(**Settings > About** in the app). We can check whether your token is
registered on our side.
