"""One-time reconciliation: push every known user's current manager-mode state
to the CRM, so the CRM can correct stale modes.

For each user we know about (seen_users table + anyone currently in Redis), we
read the authoritative mode from Redis (`manager_mode:{bot_id}:{chat_id}` ->
true, absent -> false) and POST it to the CRM's
{CRM_BASE_URL}/api/autopilot/telegram/sync, HMAC-signed.

The manager-mode=true set comes straight from Redis, so no real handoff is ever
dropped. Users the CRM tracks but who never hit our /start won't be in our
records — the CRM should treat any user it did NOT receive a `true` for as AI
mode (false).

Run inside the app container:
    docker compose exec app python app/scripts/resync_manager_modes.py hardteamru_bot
"""
import asyncio
import sys

import httpx
import redis.asyncio as aioredis
from sqlalchemy import select

from app.config.settings import settings
from app.database.models import BotSeenUser
from app.database.session import async_session
from app.services.crm_signing import sign

CONCURRENCY = 10


def _bot_id_from_token(token: str) -> int:
    return int(token.split(":", 1)[0])


async def _post_one(client, url, chat_id, manager_mode):
    body = {"bot_username": BOT_USERNAME, "chat_id": int(chat_id), "manager_mode": manager_mode}
    ts, sig = sign(body, settings.octo_secret)
    headers = {
        "Content-Type": "application/json",
        "x-octo-key": settings.octo_api_key,
        "x-octo-timestamp": ts,
        "x-octo-signature": sig,
    }
    try:
        resp = await client.post(url, json=body, headers=headers, follow_redirects=False)
        return chat_id, resp.status_code, (resp.text[:120] if resp.status_code >= 300 else "")
    except Exception as e:
        return chat_id, None, str(e)[:120]


async def main():
    if not (settings.crm_base_url and settings.octo_api_key and settings.octo_secret):
        print("CRM not configured (CRM_BASE_URL / OCTO_API_KEY / OCTO_SECRET). Aborting.")
        return

    url = settings.crm_base_url.rstrip("/") + "/api/autopilot/telegram/sync"
    r = aioredis.from_url(settings.redis_url)

    # 1. Collect every user we know FOR THIS BOT: bot_seen_users (Postgres,
    # scoped by bot_id) + any current Redis manager-mode sessions.
    async with async_session() as s:
        seen = set((await s.execute(
            select(BotSeenUser.telegram_user_id).where(BotSeenUser.bot_id == BOT_ID)
        )).scalars().all())

    in_mm = set()
    async for key in r.scan_iter(match=f"manager_mode:{BOT_ID}:*"):
        key = key.decode("utf-8") if isinstance(key, bytes) else key
        try:
            in_mm.add(int(key.rsplit(":", 1)[1]))
        except ValueError:
            pass

    all_users = sorted(seen | in_mm)
    print(f"bot=@{BOT_USERNAME} (id={BOT_ID})")
    print(f"users known: {len(all_users)} (seen_users={len(seen)}, in manager mode={len(in_mm)})")
    print(f"posting to: {url}\n")

    sent_true = sent_false = failed = 0
    async with httpx.AsyncClient(timeout=10.0) as client:
        for i in range(0, len(all_users), CONCURRENCY):
            chunk = all_users[i:i + CONCURRENCY]
            tasks = [_post_one(client, url, uid, uid in in_mm) for uid in chunk]
            for chat_id, status, info in await asyncio.gather(*tasks):
                if status is not None and status < 300:
                    if chat_id in in_mm:
                        sent_true += 1
                    else:
                        sent_false += 1
                else:
                    failed += 1
                    print(f"  FAIL {chat_id}: {status} {info}")
            print(f"  progress: {min(i + CONCURRENCY, len(all_users))}/{len(all_users)}")

    print(f"\nDONE. manager_mode=true sent: {sent_true}, false sent: {sent_false}, failed: {failed}")
    await r.aclose()


if __name__ == "__main__":
    BOT_USERNAME = sys.argv[1] if len(sys.argv) > 1 else "hardteamru_bot"
    if not settings.telegram_bot_token_2:
        print("TELEGRAM_BOT_TOKEN_2 not set. Aborting.")
        sys.exit(1)
    BOT_ID = _bot_id_from_token(settings.telegram_bot_token_2)
    asyncio.run(main())
