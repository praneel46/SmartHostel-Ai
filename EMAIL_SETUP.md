# SmartHostel AI Gmail Setup

The app sends mail like this:

From: SmartHostel AI sender Gmail
To: the student email used during registration

Example:

Student registers with `student123@gmail.com`.
After clicking **Generate Match and Send Mail**, the confirmation goes to `student123@gmail.com`.

## One-Time Setup

1. Create a dedicated Gmail account for the project, for example:
   `smarthostelai.project@gmail.com`
2. Turn on 2-Step Verification for that Gmail account.
3. Create a Gmail App Password.
4. Open `.env`.
5. Set:

```text
SMART_HOSTEL_MAIL_ENABLED=true
SMART_HOSTEL_MAIL_USERNAME=smarthostelai.project@gmail.com
SMART_HOSTEL_MAIL_PASSWORD=your-16-character-app-password
SMART_HOSTEL_MAIL_FROM=SmartHostel AI <smarthostelai.project@gmail.com>
```

Do not use your normal Gmail password. Use only the Gmail App Password.

After changing `.env`, restart the Flask server.
