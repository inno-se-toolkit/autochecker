"""Handler for /qwen_auth command — refresh Qwen OAuth token via device code flow.

The bot runs on Hetzner (outside university network), so Alibaba WAF
doesn't block the token exchange. The flow:
1. Bot requests a device code from chat.qwen.ai
2. Bot sends the auth URL to the student
3. Student opens URL in browser and authorizes
4. Student replies "done" (or any message while in the auth state)
5. Bot polls for the token from Hetzner (no WAF)
6. Bot pushes the token to the student's VM via relay
7. Bot restarts qwen-code-api on the VM
"""

import asyncio
import base64
import hashlib
import json
import logging
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from ..database import User, get_server_ip, get_vm_username

logger = logging.getLogger(__name__)

router = Router()

CLIENT_ID = "f0304373b74a44d2b584a3fb70ca9e56"
SCOPE = "openid profile email model.completion"
AUTH_URL = "https://chat.qwen.ai/api/v1/oauth2"
UA = "qwen-code/0.12.2"

RELAY_TOKEN = os.getenv("RELAY_TOKEN", "")
RELAY_URL = os.getenv("RELAY_URL", "http://dashboard:8000/relay/ssh")


class QwenAuthStates(StatesGroup):
    waiting_for_authorization = State()


def _auth_request(url, data_dict):
    """Make a request to Qwen auth endpoint with proper User-Agent."""
    data = urllib.parse.urlencode(data_dict).encode()
    req = urllib.request.Request(url, data, {
        "User-Agent": UA,
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    })
    body = urllib.request.urlopen(req, timeout=15).read()
    if b"<!doctype" in body.lower() or b"aliyun_waf" in body.lower():
        raise RuntimeError("WAF_BLOCK")
    return json.loads(body)


def _relay_ssh(host, username, command, timeout=20):
    """Run a command on a student VM via the relay."""
    if not RELAY_TOKEN:
        return None, "RELAY_TOKEN not configured"
    data = json.dumps({
        "host": host, "port": 22, "username": username,
        "command": command, "timeout": timeout,
    }).encode()
    req = urllib.request.Request(RELAY_URL, data, {
        "Authorization": f"Bearer {RELAY_TOKEN}",
        "Content-Type": "application/json",
    })
    try:
        resp = json.loads(urllib.request.urlopen(req, timeout=timeout + 5).read())
        if resp.get("error"):
            return None, resp["error"]
        return resp.get("stdout", ""), None
    except Exception as e:
        return None, str(e)


@router.message(Command("qwen_auth"))
async def cmd_qwen_auth(message: Message, db_user: User, state: FSMContext) -> None:
    """Start Qwen OAuth device code flow."""
    server_ip = await get_server_ip(db_user.tg_id)
    if not server_ip:
        await message.answer("You haven't registered a VM IP yet. Use the /start flow first.")
        return

    vm_user = await get_vm_username(db_user.tg_id)
    if not vm_user:
        await message.answer("You haven't set a VM username yet. Use the /start flow first.")
        return

    await message.answer("Starting Qwen OAuth flow...")

    try:
        # PKCE
        verifier = secrets.token_urlsafe(32)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).rstrip(b"=").decode()

        # Request device code
        resp = await asyncio.to_thread(_auth_request, f"{AUTH_URL}/device/code", {
            "client_id": CLIENT_ID,
            "scope": SCOPE,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        })

        device_code = resp["device_code"]
        verify_url = resp.get("verification_uri_complete", "")

        # Save state for polling
        await state.update_data(
            device_code=device_code,
            verifier=verifier,
            server_ip=server_ip,
            vm_user=vm_user,
        )
        await state.set_state(QwenAuthStates.waiting_for_authorization)

        await message.answer(
            f"Open this link in your browser and authorize:\n\n"
            f"{verify_url}\n\n"
            f"After you authorize, reply anything here (e.g. \"done\").\n"
            f"The link expires in 15 minutes."
        )

    except RuntimeError:
        await message.answer("Qwen auth endpoint blocked by WAF. Please try again later or contact the course instructor.")
    except Exception as e:
        logger.error(f"qwen_auth device code error: {e}")
        await message.answer(f"Error starting auth flow: {e}")


@router.message(QwenAuthStates.waiting_for_authorization)
async def process_qwen_auth_done(message: Message, db_user: User, state: FSMContext) -> None:
    """Student confirmed authorization — poll for token and push to VM."""
    data = await state.get_data()
    device_code = data.get("device_code")
    verifier = data.get("verifier")
    server_ip = data.get("server_ip")
    vm_user = data.get("vm_user")

    if not device_code or not verifier:
        await state.clear()
        await message.answer("Auth session expired. Run /qwen_auth again.")
        return

    await message.answer("Exchanging token...")

    # Poll for token (with retries for WAF)
    token = None
    for attempt in range(5):
        try:
            token = await asyncio.to_thread(_auth_request, f"{AUTH_URL}/token", {
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": CLIENT_ID,
                "device_code": device_code,
                "code_verifier": verifier,
            })
            if "access_token" in token:
                break
            elif token.get("error") == "authorization_pending":
                await message.answer("You haven't authorized yet. Open the link first, then reply again.")
                return  # Keep state, let them retry
            elif token.get("error") == "expired_token":
                await state.clear()
                await message.answer("Auth link expired. Run /qwen_auth again.")
                return
            else:
                await state.clear()
                await message.answer(f"Auth failed: {token.get('error', 'unknown error')}. Run /qwen_auth again.")
                return
        except RuntimeError:
            if attempt < 4:
                await asyncio.sleep(2)
                continue
            await state.clear()
            await message.answer("Token exchange blocked by WAF after retries. Contact the course instructor.")
            return
        except Exception as e:
            await state.clear()
            await message.answer(f"Token exchange error: {e}. Run /qwen_auth again.")
            return

    if not token or "access_token" not in token:
        await state.clear()
        await message.answer("Could not get token. Run /qwen_auth again.")
        return

    # Build credentials file
    creds = json.dumps({
        "access_token": token["access_token"],
        "token_type": token.get("token_type", "Bearer"),
        "refresh_token": token.get("refresh_token", ""),
        "resource_url": token.get("resource_url", "portal.qwen.ai"),
        "expiry_date": int(time.time() * 1000) + token.get("expires_in", 3600) * 1000,
    })
    creds_b64 = base64.b64encode(creds.encode()).decode()

    await message.answer("Token received! Pushing to your VM...")

    # Push to VM via relay
    cmd = (
        f"mkdir -p ~/.qwen && "
        f"echo '{creds_b64}' | base64 -d > ~/.qwen/oauth_creds.json && "
        f"chmod 600 ~/.qwen/oauth_creds.json && "
        f"cd ~/se-toolkit-lab-8 && "
        f"docker compose --env-file .env.docker.secret restart qwen-code-api 2>&1 | tail -2 && "
        f"sleep 3 && "
        f"curl -s http://localhost:42005/health | head -c 100"
    )

    stdout, error = await asyncio.to_thread(_relay_ssh, server_ip, vm_user, cmd, 25)

    await state.clear()

    if error:
        await message.answer(
            f"Token saved but could not push to VM: {error}\n\n"
            f"Manually copy the token: the file is at ~/.qwen/oauth_creds.json on your VM."
        )
        return

    verify_msg = (
        "Verify on your VM with these 3 checks:\n\n"
        "1. Proxy health:\n"
        "<code>curl -s http://localhost:42005/health</code>\n"
        "(should show \"status\": \"healthy\")\n\n"
        "2. LLM call:\n"
        "<code>curl -m 15 -s http://localhost:42005/v1/chat/completions "
        "-H 'X-API-Key: YOUR_QWEN_CODE_API_KEY' "
        "-H 'Content-Type: application/json' "
        "-d '{\"model\":\"coder-model\",\"messages\":[{\"role\":\"user\",\"content\":\"say ok\"}],\"max_tokens\":5}'</code>\n"
        "(should return a JSON response within seconds)\n\n"
        "3. Nanobot agent:\n"
        "<code>cd ~/se-toolkit-lab-8/nanobot &amp;&amp; "
        "NANOBOT_LMS_BACKEND_URL=http://localhost:42002 "
        "NANOBOT_LMS_API_KEY=YOUR_LMS_KEY "
        "uv run nanobot agent -c ./config.json -m 'What labs are available?'</code>\n"
        "(should return real lab names)\n\n"
        "⚠️ Replace YOUR_QWEN_CODE_API_KEY and YOUR_LMS_KEY with your actual values from .env.docker.secret:\n"
        "<code>grep QWEN_CODE_API_KEY ~/se-toolkit-lab-8/.env.docker.secret</code>\n"
        "<code>grep LMS_API_KEY ~/se-toolkit-lab-8/.env.docker.secret</code>"
    )

    if stdout and "healthy" in stdout:
        await message.answer(
            "Done! Qwen token refreshed and proxy restarted.\n\n" + verify_msg,
            parse_mode="HTML",
        )
    else:
        await message.answer(
            f"Token pushed and proxy restarted, but health check returned:\n"
            f"<code>{stdout or '(empty)'}</code>\n\n" + verify_msg,
            parse_mode="HTML",
        )
