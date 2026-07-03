# Telegram and Avito Setup

## Telegram account mode

Use this mode if CRM must read messages from the working Telegram account, not from a bot.

Required data:

- `TG_API_ID`
- `TG_API_HASH`
- `TG_PHONE` in international format, for example `+79991234567`
- One-time login code from Telegram
- Telegram 2FA password, if it is enabled

Environment variables:

```env
TG_INTEGRATION_MODE=account
TG_API_ID=12345678
TG_API_HASH=your_api_hash
TG_PHONE=+79991234567
TG_SESSION_NAME=telegram_account
TG_DIALOG_LIMIT=50
TG_HISTORY_LIMIT=40
```

Launch sequence:

1. Rebuild the app after updating `requirements.txt`.
2. Add the variables above to the server `.env`.
3. Run `python manage.py setup_tg_session`.
4. Enter the code from Telegram.
5. If Telegram asks for 2FA, enter the password.
6. Run `python manage.py poll_tg`.

What CRM will do:

- Read private dialogs from the working account
- Import both inbound and outbound messages into `crm_message`
- Create or reuse clients in `crm_client`
- Use `tg://user?id=...` as the stable Telegram contact link

## Telegram bot mode

Use this mode only if clients write directly to the bot.

```env
TG_INTEGRATION_MODE=bot
TG_BOT_TOKEN=your_bot_token
TG_GROUP_ID=
```

## Avito via Playwright

Required data:

- `AVITO_USERNAME`
- `AVITO_PASSWORD`
- SMS code when logging in, if Avito requests it

Environment variables:

```env
AVITO_USERNAME=your_login
AVITO_PASSWORD=your_password
AVITO_AUTH_FILE=avito_auth.json
AVITO_COOKIES_FILE=avito_cookies.json
AVITO_POLL_LIMIT=20
```

Launch sequence:

1. Add the variables above to the server `.env`.
2. Run `python manage.py avito_playwright_setup` on a machine with a visible browser.
3. Log in to Avito manually in the opened browser window.
4. Enter the SMS code if needed.
5. Open `https://www.avito.ru/messages`.
6. Save the session.
7. Place `avito_auth.json` in the project root on the server.
8. Run `python manage.py poll_avito_playwright`.

What CRM will do:

- Open the Avito messages page via Playwright
- Reuse the saved session
- Import messages into `crm_message`
- Create or reuse clients in `crm_client`

## What to send tomorrow

Telegram:

- `API ID`
- `API Hash`
- Phone number of the working Telegram account
- Confirmation code when I ask for it
- 2FA password if enabled

Avito:

- Login
- Password
- Confirmation code if Avito requests it
