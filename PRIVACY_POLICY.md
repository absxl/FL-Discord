# Privacy Policy

**Last updated: November 3, 2026**

This Privacy Policy explains how **FL Discord RPC** (the “App”) handles
information. The App is a Windows desktop utility that displays information
about an FL Studio project in Discord Rich Presence.

This is a draft intended to describe the current App behavior. It is not legal
advice. Before publishing it, replace the bracketed information and have the
policy reviewed for the jurisdictions in which you distribute the App.

## 1. Who operates the App

The App is operated by **Marcello Carletti / absxl** (“we,” “us,” or
“our”).

Contact: **marcello@carletti.work**

## 2. Information the App handles

### Information read from your computer

When enabled and running, the App may:

- inspect visible window titles to identify an FL Studio window and read the
  project name shown in that title;
- read the local state needed to determine whether the activity is playing or
  idle; and
- read local Windows settings needed to support the optional “Run at Startup”
  feature.

The App does not read the contents of your FL Studio project, audio, MIDI,
keystrokes, Discord messages, or files outside the locations described below.
The optional keyboard shortcut requires the keyboard package and Windows
keyboard-hook functionality to respond to the configured shortcuts.

### Information stored locally

The App stores configuration and session information in:

`%APPDATA%\FLDiscordRPC\config.json`

This can include your preferences, custom statuses, custom project name,
activity settings, theme, startup preference, and accumulated session time.

The App also writes a diagnostic log to:

`%APPDATA%\FLDiscordRPC\fl_discord_rpc.log`

The log can contain timestamps, application state, project names shown by FL
Studio, connection status, and error or diagnostic messages. Log files are
limited to approximately 1 MB; an oversized log may be deleted. These files
remain on your computer until you delete them or uninstall/clean up the App.

### Information sent to third parties

When activity is enabled and Discord is running, the App sends Rich Presence
data to Discord using Discord’s local Rich Presence interface. This may
include the project name (or the custom name you choose), the selected status,
playing/idle state, session start time, and the App’s display artwork.
Discord receives and displays that information according to Discord’s own
terms and privacy policy.

If you choose an update check, the App requests the latest release information
from the GitHub API. GitHub may receive standard connection information such
as your IP address under GitHub’s privacy practices. The App does not send
your project name or local configuration to GitHub as part of this check.

If you select “Join Discord” or “Donate,” the App opens the relevant Discord
invite or PayPal page in your default browser. Those services process
information under their own privacy policies. We do not receive your payment
details through the App.

The App may download required Python packages from package providers during
first-time setup when running the script version. Package providers and
network operators may process standard request information. The packaged
Windows executable may have different setup behavior depending on how it was
distributed.

## 3. What we do not do

The App does not provide our own user accounts, advertising, analytics,
tracking pixels, cookies, or hosted database. We do not sell the information
described in this policy, and we do not intentionally collect it on our own
servers.

## 4. Legal bases and use

Where data-protection law requires a legal basis, we generally process
information to provide the App features you request, based on your
instructions and consent where applicable, and to maintain, secure, and
troubleshoot the App. Local configuration and logs are used only to operate
the App and diagnose errors.

## 5. Retention and deletion

Information stored by the App is retained locally until you remove it. You can
delete the configuration and log files by closing the App and deleting the
`%APPDATA%\FLDiscordRPC` folder. You can also disable Discord activity,
disable update checks by not selecting them, or stop using the App.

Discord, GitHub, PayPal, and package providers control their own retention of
information they process. Contact those providers for requests concerning
their services.

## 6. Your rights

Depending on where you live, you may have rights to access, correct, delete,
restrict, or object to processing of personal information, and to lodge a
complaint with a data-protection authority. Because the App is designed to
store information locally and we do not maintain an account database, most
requests can be fulfilled by deleting the local files described above.

For questions about information we control, contact **marcello@carletti.work**.

## 7. Children

The App is not directed to children under **13**.
We do not knowingly collect personal information from children.

## 8. Security

The App is designed to keep configuration and logs on your device. No method
of storage or transmission is completely secure, and security also depends on
your Windows account, device, Discord installation, browser, and the
third-party services you use.

## 9. Changes

We may update this Privacy Policy when the App or its data practices change.
The “Last updated” date will identify the latest version. Continued use of the
App after an update means the revised policy applies to future use.

## 10. Contact

For privacy questions, contact:

**Marcello Carletti / absxl**

**marcello@carletti.work**

