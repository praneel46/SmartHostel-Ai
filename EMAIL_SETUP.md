# SmartHostel AI Resend Setup

The app sends mail like this:

From: SmartHostel AI via Resend
To: the student email used during registration

Example:

Student registers with `student123@gmail.com`.
After an admin approves the request, the allocation confirmation goes to `student123@gmail.com`.

## One-Time Setup

1. Create or open a Resend account.
2. Create a Resend API key.
3. Verify your sending domain in Resend, or use Resend's test sender while developing.
4. Open `.env`.
5. Set:

```text
SMART_HOSTEL_MAIL_ENABLED=true
RESEND_API_KEY=your-resend-api-key
SMART_HOSTEL_RESEND_API_KEY=your-resend-api-key
SMART_HOSTEL_MAIL_FROM=SmartHostel AI <onboarding@resend.dev>
```

On Render, add `RESEND_API_KEY` in **Environment** settings. The local `.env` file is not uploaded to Render.

For production, replace `onboarding@resend.dev` with an address on your verified Resend domain.

After changing `.env`, restart the Flask server.
