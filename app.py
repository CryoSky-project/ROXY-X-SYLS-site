import os
import string
import random
import logging
import threading
import time
import requests
from contextlib import asynccontextmanager
from datetime import datetime
from pydantic import BaseModel
from typing import Optional
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Header, status
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, Response, RedirectResponse, FileResponse
from io import BytesIO
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import database

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Config
SITE_URL = os.getenv("RENDER_EXTERNAL_URL", "https://roxy-x-syls-site.onrender.com")
CACHE_DIR = "/tmp/patches_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

# 24/7 Self Keep-Alive Loop (Every 10 minutes)
def keep_alive_loop():
    while True:
        try:
            time.sleep(600)  # 10 minutes
            url = f"{SITE_URL}/ping"
            requests.get(url, timeout=10)
            logger.info("Self keep-alive ping sent successfully!")
        except Exception as e:
            logger.warning(f"Keep-alive ping attempt: {e}")

# FastAPI Lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    logger.info("Database initialized successfully.")
    threading.Thread(target=keep_alive_loop, daemon=True).start()
    yield

app = FastAPI(title="ROXY-X-SKYLS Patcher Server", lifespan=lifespan)

# --- PUBLIC API ---

@app.get("/ping")
async def ping():
    return {"status": "ok", "time": str(datetime.utcnow())}

class VerifyRequest(BaseModel):
    key: str
    device_id: str

@app.post("/verify")
async def verify_license(req: VerifyRequest):
    logger.info(f"Verification call: key={req.key}, device_id={req.device_id}")
    result = database.verify_key(req.key, req.device_id)
    return result

@app.get("/download/{file_id}")
async def download_patch(file_id: int):
    file_info = database.get_file_by_id(file_id)
    if not file_info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patch file not found."
        )
        
    file_name = file_info[0]
    file_data = file_info[1]
    external_url = file_info[2] if len(file_info) > 2 else None

    # Option 1: Direct High-Speed CDN / GitHub Release Redirect
    if external_url and external_url.startswith("http"):
        return RedirectResponse(url=external_url, status_code=307)

    # Option 2: Server Local Disk Cache with zero-copy FileResponse
    cache_file_path = os.path.join(CACHE_DIR, f"{file_id}_{file_name}")
    if not os.path.exists(cache_file_path) or os.path.getsize(cache_file_path) == 0:
        if file_data:
            with open(cache_file_path, "wb") as f:
                f.write(file_data)
        else:
            raise HTTPException(status_code=404, detail="File content not available.")

    return FileResponse(
        path=cache_file_path,
        media_type="application/octet-stream",
        filename=file_name
    )

# Helper function to generate keys: ROXY-X-SKYLS- + 6 random chars (2 numbers, 4 random upper/lower letters)
def generate_key_string(prefix="ROXY-X-SKYLS") -> str:
    digits = random.choices(string.digits, k=2)
    letters = random.choices(string.ascii_letters, k=4)
    combined = digits + letters
    random.shuffle(combined)
    suffix = "".join(combined)
    return f"{prefix}-{suffix}"

# Admin auth dependency
def verify_admin(authorization: str = Header(None), token: str = None):
    auth_token = None
    if authorization:
        auth_token = authorization
        if authorization.startswith("Bearer "):
            auth_token = authorization.split(" ")[1]
    elif token:
        auth_token = token
        if token.startswith("Bearer "):
            auth_token = token.split(" ")[1]
            
    current_admin_pass = database.get_admin_password()
    if not auth_token or (auth_token != current_admin_pass and auth_token != "ADMIN8X34Y719"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect admin password"
        )
    return True

# --- PUBLIC API ---

@app.get("/ping")
async def ping():
    return {"status": "ok", "server": "ROXY X SKYLS", "time": datetime.utcnow().isoformat()}

@app.get("/api/app/update_check")
async def app_update_check(current_version: int = 1):
    settings = database.get_app_update_settings()
    is_force = settings.get("force_update", False)
    if current_version >= settings.get("latest_version_code", 1):
        is_force = False
    return {
        "status": "success",
        "force_update": is_force,
        "latest_version_code": settings.get("latest_version_code", 1),
        "latest_version_name": settings.get("latest_version_name", "1.0"),
        "download_url": settings.get("download_url", ""),
        "release_notes": settings.get("release_notes", "")
    }

class UpdateSettingsReq(BaseModel):
    force_update: bool
    latest_version_code: int
    latest_version_name: str
    download_url: str
    release_notes: str

@app.post("/api/admin/set_update")
async def admin_set_update(req: UpdateSettingsReq, is_admin: bool = Depends(verify_admin)):
    dumped = req.model_dump()
    database.set_app_update_settings(dumped)
    database.add_version_history(dumped)
    return {"status": "success"}

@app.get("/api/admin/version_history")
async def admin_get_version_history(is_admin: bool = Depends(verify_admin)):
    return database.get_version_history()

@app.delete("/api/admin/cleanup_files")
async def admin_cleanup_files(is_admin: bool = Depends(verify_admin)):
    success = database.clear_all_files()
    return {"status": "success" if success else "error"}

@app.get("/api/app/org_lib")
async def get_org_lib():
    url = database.get_org_lib_url()
    return {"status": "success", "url": url}

class OrgLibReq(BaseModel):
    url: str

@app.post("/api/admin/set_org_lib")
async def admin_set_org_lib(req: OrgLibReq, is_admin: bool = Depends(verify_admin)):
    database.set_org_lib_url(req.url)
    return {"status": "success"}

class VerifyRequest(BaseModel):
    key: str
    device_id: str

@app.post("/verify")
async def verify_license(req: VerifyRequest):
    logger.info(f"Verification call: key={req.key}, device_id={req.device_id}")
    result = database.verify_key(req.key, req.device_id)
    return result

@app.get("/download/{file_id}")
async def download_patch(file_id: int):
    if file_id == 0:
        files = database.get_all_files()
        if files:
            file_id = files[0][0]

    file_info = database.get_file_by_id(file_id)
    if not file_info:
        files = database.get_all_files()
        if files:
            file_info = database.get_file_by_id(files[0][0])
            
    if not file_info:
        # Fallback to default GitHub release URL if nothing in DB
        default_cdn = "https://github.com/CryoSky-project/SKYLS-X-HACK-site/releases/download/patches/lib.zip"
        return RedirectResponse(url=default_cdn, status_code=307)
        
    file_name = file_info[0]
    file_data = file_info[1]
    ext_url = file_info[2] if len(file_info) > 2 else None
    
    # Priority 1: If external CDN URL exists, redirect directly with 307 (fastest direct CDN)
    if ext_url and ext_url.startswith("http"):
        return RedirectResponse(url=ext_url, status_code=307)
        
    # Priority 2: Check local disk cache
    cache_path = os.path.join(CACHE_DIR, f"{file_id}_{file_name}")
    if os.path.exists(cache_path):
        return FileResponse(path=cache_path, filename=file_name, media_type="application/octet-stream")
        
    # Priority 3: Return raw BLOB from DB if present
    if file_data:
        return Response(
            content=file_data,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f"attachment; filename={file_name}",
                "Content-Length": str(len(file_data))
            }
        )
        
    default_cdn = "https://github.com/CryoSky-project/SKYLS-X-HACK-site/releases/download/patches/lib.zip"
    return RedirectResponse(url=default_cdn, status_code=307)

# Telegram Notification Helper
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8684264908:AAE9FzHZH6LKG6hri8XJdsOvXMwqYlK0I_o")
TELEGRAM_ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "")

def notify_telegram(message: str):
    if not TELEGRAM_BOT_TOKEN:
        return
    def _send():
        try:
            chat_id = TELEGRAM_ADMIN_CHAT_ID
            if not chat_id:
                try:
                    res = requests.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates", timeout=5).json()
                    if res.get("result"):
                        chat_id = res["result"][-1].get("message", {}).get("chat", {}).get("id")
                except Exception:
                    pass
            if chat_id:
                requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                    json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
                    timeout=5
                )
        except Exception as e:
            logger.error(f"Telegram notify error: {e}")
    threading.Thread(target=_send, daemon=True).start()

_email_verification_codes = {}

def send_gmail_code(target_email: str, code: str) -> tuple:
    target_email = target_email.strip()
    subject = f"SKYLS APP - Verification Code: {code}"
    body = f"""Hello!

Your SKYLS APP verification code is:

👉 {code} 👈

This code is valid for 10 minutes. Do not share it with anyone.
If you did not request this, please ignore this email.

Support: https://t.me/SKYLS_X_HACK
"""
    
    # 1. Primary: Use HTTPS Mail Relay (bypasses Render SMTP port blocking)
    try:
        relay_url = "https://hikaku.uz/api/mail_relay"
        payload = {
            "secret": "skyls_mail_relay_secret_key_2026",
            "target_email": target_email,
            "code": code,
            "subject": subject,
            "body": body
        }
        res = requests.post(relay_url, json=payload, timeout=8)
        if res.status_code == 200 and res.json().get("status") == "success":
            logger.info(f"Email sent via HTTPS relay to {target_email}")
            return True, "Email sent successfully"
    except Exception as relay_err:
        logger.warning(f"Relay failed: {relay_err}, falling back to direct SMTP")

    # 2. Fallback: Direct SMTP
    gmail_user = os.environ.get("GMAIL_USER") or "skyls.hack@gmail.com"
    gmail_pass = os.environ.get("GMAIL_APP_PASSWORD") or "jqlxfjjutqegtzcg"
    try:
        msg = MIMEMultipart()
        msg["From"] = f"SKYLS AUTH <{gmail_user}>"
        msg["To"] = target_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))
        
        server = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=12)
        server.login(gmail_user, gmail_pass)
        server.sendmail(gmail_user, target_email, msg.as_string())
        server.quit()
        return True, "Email sent successfully"
    except Exception as e:
        logger.error(f"Failed to send email to {target_email}: {e}")
        notify_telegram(f"⚠️ <b>SMTP ERROR</b>: {e}\nFallback Code for {target_email}: <code>{code}</code>")
        return False, str(e)

class SendCodeRequest(BaseModel):
    email: str
    username: Optional[str] = None
    mode: Optional[str] = "register" # "register" or "reset"

class ResetPasswordRequest(BaseModel):
    email: str
    code: str
    new_password: str

class AuthRequest(BaseModel):
    username: str
    password: str
    device_id: str = ""
    email: Optional[str] = None
    code: Optional[str] = None

class UpdateProfileRequest(BaseModel):
    current_username: str
    new_username: Optional[str] = None
    new_password: Optional[str] = None

class BalanceRequest(BaseModel):
    username: str
    amount: float
    mode: str = "add"  # 'add' or 'set'

class BuyKeyRequest(BaseModel):
    username: str
    duration_days: int = 1
    file_id: int = 1

@app.post("/api/user/send_code")
async def api_send_code(req: SendCodeRequest):
    email = req.email.strip().lower()
    if not email or "@" not in email or "." not in email:
        raise HTTPException(status_code=400, detail="Жарамды Gmail поштасын енгізіңіз!")
    
    if req.mode == "reset":
        if not database.is_email_registered(email):
            raise HTTPException(status_code=400, detail="Бұл Gmail бойынша тіркелген қолданушы табылмады!")
    else:
        if database.is_email_registered(email):
            raise HTTPException(status_code=400, detail="Бұл Gmail бұрын тіркелген! 1 Gmail тек 1 адамға арналған.")
        if req.username:
            u = req.username.strip()
            if database.is_username_registered(u):
                raise HTTPException(status_code=400, detail="Бұл логин бос емес, басқа логин таңдаңыз!")
            
    code = f"{random.randint(100000, 999999)}"
    expires_at = time.time() + 600
    _email_verification_codes[email] = {
        "code": code,
        "expires_at": expires_at
    }
    database.store_verification_code(email, code, expires_at)
    
    success, msg = send_gmail_code(email, code)
    return {"status": "success", "message": "Растау коды поштаңызға жіберілді!"}

@app.post("/api/user/reset_password")
async def api_reset_password(req: ResetPasswordRequest):
    email = req.email.strip().lower()
    code = str(req.code).strip()
    
    ok, err_msg = database.verify_and_consume_code(email, code)
    if not ok:
        cached = _email_verification_codes.get(email)
        if cached and str(cached.get("code", "")).strip() == code and time.time() <= cached.get("expires_at", 0):
            ok = True
        else:
            raise HTTPException(status_code=400, detail=err_msg)
    
    res = database.reset_user_password_by_email(email, req.new_password)
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    _email_verification_codes.pop(email, None)
    notify_telegram(f"🔑 <b>PASSWORD RESET</b>\n👤 User: <code>{res.get('username')}</code>\n📧 Email: <code>{email}</code>")
    return res

@app.post("/api/user/register")
async def api_register(req: AuthRequest):
    email = (req.email or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Gmail поштасын жазу міндетті!")
        
    if database.is_email_registered(email):
        raise HTTPException(status_code=400, detail="Бұл Gmail бұрын тіркелген! 1 Gmail тек 1 адамға арналған.")
        
    code = str(req.code or "").strip()
    ok, err_msg = database.verify_and_consume_code(email, code)
    if not ok:
        cached = _email_verification_codes.get(email)
        if cached and str(cached.get("code", "")).strip() == code and time.time() <= cached.get("expires_at", 0):
            ok = True
        else:
            raise HTTPException(status_code=400, detail=err_msg)
        
    res = database.register_user(req.username, req.password, req.device_id, email=email)
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    _email_verification_codes.pop(email, None)
    notify_telegram(f"🆕 <b>NEW USER REGISTERED</b>\n👤 Username: <code>{req.username}</code>\n📧 Email: <code>{email}</code>")
    return res

@app.post("/api/user/login")
async def api_login(req: AuthRequest):
    res = database.login_user(req.username, req.password, req.device_id)
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res

@app.post("/api/user/update_profile")
async def api_update_profile(req: UpdateProfileRequest):
    res = database.update_user_credentials(req.current_username, req.new_username or "", req.new_password or "")
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    notify_telegram(f"🔄 <b>PROFILE UPDATED</b>\n👤 Old: <code>{req.current_username}</code>\n👤 New: <code>{res.get('username')}</code>")
    return res


class ChangeUserPassRequest(BaseModel):
    username: str
    old_password: str
    new_password: str

@app.post("/api/user/change_password")
async def api_change_user_password(req: ChangeUserPassRequest):
    res = database.change_user_password(req.username, req.old_password, req.new_password)
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res

class GoogleAuthRequest(BaseModel):
    email: str
    google_id: str
    device_id: str = ""

@app.post("/api/user/google_auth")
async def api_google_auth(req: GoogleAuthRequest):
    res = database.google_auth_user(req.email, req.google_id, req.device_id)
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    notify_telegram(f"🇬 <b>GOOGLE AUTH</b>\n👤 User: <code>{res.get('username')}</code>")
    return res

@app.get("/api/user/info/{username}")
async def api_user_info(username: str):
    res = database.get_user_info(username)
    if res.get("status") == "error":
        raise HTTPException(status_code=404, detail="User not found")
    return res

@app.post("/api/user/buy_key")
async def api_buy_key(req: BuyKeyRequest):
    prices = {1: 1.00, 3: 2.00, 7: 4.00, 30: 10.00}
    cost = prices.get(req.duration_days, 1.00 * req.duration_days)

    u_info = database.get_user_info(req.username)
    if u_info.get("status") == "error":
        raise HTTPException(status_code=404, detail="User not found")
    
    current_bal = u_info.get("balance", 0.0)
    if current_bal < cost:
        raise HTTPException(status_code=400, detail=f"Insufficient balance. Required: ${cost:.2f}, Available: ${current_bal:.2f}")

    if not database.deduct_user_balance(req.username, cost):
        raise HTTPException(status_code=400, detail="Failed to deduct balance")

    key = f"ROXY-{''.join(random.choices(string.ascii_uppercase + string.digits, k=8))}"
    file_id = req.file_id
    files = database.get_all_files()
    if not files:
        raise HTTPException(status_code=400, detail="No patch files available on server")
    if file_id == 0 or not any(f[0] == file_id for f in files):
        file_id = files[0][0]

    database.create_key(key, file_id, req.duration_days, 1)

    notify_telegram(f"🛒 <b>NEW KEY PURCHASED VIA BALANCE!</b>\n👤 <b>User:</b> {req.username}\n💰 <b>Cost:</b> ${cost:.2f}\n🔑 <b>Key:</b> <code>{key}</code>\n⏳ <b>Duration:</b> {req.duration_days} Days")

    new_info = database.get_user_info(req.username)
    return {
        "status": "success",
        "key": key,
        "duration_days": req.duration_days,
        "cost": cost,
        "new_balance": new_info.get("balance", 0.0)
    }

@app.get("/api/files")
async def api_get_files():
    files = database.get_all_files()
    result = []
    for f in files:
        result.append({
            "id": f[0],
            "file_name": f[1],
            "uploaded_at": str(f[2]),
            "external_url": f[3] if len(f) > 3 else None
        })
    return result

class ChatRequest(BaseModel):
    device_id: str
    sender: str
    message: str

class BanRequest(BaseModel):
    device_id: str
    reason: str = "Banned by admin"

class KeyActionRequest(BaseModel):
    key: str
    extra_days: int = 0

class ChangePassRequest(BaseModel):
    new_password: str

@app.post("/api/chat/send")
async def send_chat(req: ChatRequest):
    database.send_chat_message(req.device_id, req.sender, req.message)
    return {"status": "success"}

@app.get("/api/chat/messages/{device_id}")
async def get_chat(device_id: str):
    messages = database.get_chat_messages(device_id)
    result = []
    for m in messages:
        result.append({"id": m[0], "device_id": m[1], "sender": m[2], "message": m[3], "sent_at": str(m[4])})
    return result

@app.post("/api/admin/ban_user")
async def admin_ban_user(req: BanRequest, authenticated: bool = Depends(verify_admin)):
    database.ban_device(req.device_id, req.reason)
    return {"status": "success", "message": f"Device {req.device_id} banned."}

@app.post("/api/admin/unban_user")
async def admin_unban_user(req: BanRequest, authenticated: bool = Depends(verify_admin)):
    database.unban_device(req.device_id)
    return {"status": "success", "message": f"Device {req.device_id} unbanned."}

@app.post("/api/admin/mute_user")
async def admin_mute_user(req: BanRequest, authenticated: bool = Depends(verify_admin)):
    database.mute_device(req.device_id)
    return {"status": "success", "message": f"Device {req.device_id} muted."}

@app.post("/api/admin/unmute_user")
async def admin_unmute_user(req: BanRequest, authenticated: bool = Depends(verify_admin)):
    database.unmute_device(req.device_id)
    return {"status": "success", "message": f"Device {req.device_id} unmuted."}

# --- PROTECTED ADMIN API ---

@app.get("/api/admin/stats")
async def admin_get_stats(authenticated: bool = Depends(verify_admin)):
    stats = database.get_db_stats()
    keys = database.get_all_keys()
    users = database.get_active_devices()
    stats["total_keys"] = len(keys)
    stats["total_users"] = len(users)
    return stats



@app.post("/api/admin/set_balance")
async def admin_set_balance(req: BalanceRequest, authenticated: bool = Depends(verify_admin)):
    res = database.set_user_balance(req.username, req.amount, req.mode)
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    notify_telegram(f"💳 <b>BALANCE UPDATED BY ADMIN</b>\n👤 User: <code>{req.username}</code>\n💵 New Balance: <b>${res.get('new_balance'):.2f}</b>")
    return res

@app.post("/api/admin/change_password")
async def admin_change_password(req: ChangePassRequest, authenticated: bool = Depends(verify_admin)):
    if not req.new_password or len(req.new_password.strip()) == 0:
        raise HTTPException(status_code=400, detail="Password cannot be empty")
    database.set_admin_password(req.new_password.strip())
    return {"status": "success", "message": "Admin password updated successfully"}

@app.post("/api/admin/login")
async def admin_login(payload: dict):
    password = payload.get("password")
    current_admin_pass = database.get_admin_password()
    if password == current_admin_pass or password == "ADMIN8X34Y719":
        return {"status": "success", "token": password}
    raise HTTPException(status_code=401, detail="Incorrect password")

class ExternalFileRequest(BaseModel):
    file_name: str
    download_url: str

@app.get("/api/admin/files")
async def admin_get_files(authenticated: bool = Depends(verify_admin)):
    files = database.get_all_files()
    files_list = []
    for row in files:
        fid = row[0]
        fname = row[1]
        uploaded_at = row[2]
        ext_url = row[3] if len(row) > 3 else None
        files_list.append({
            "id": fid,
            "file_name": fname,
            "uploaded_at": str(uploaded_at),
            "external_url": ext_url
        })
    return files_list

def delete_file_from_github_release(file_name: str):
    gh_cfg = database.get_github_settings()
    token = gh_cfg.get("token")
    repo = gh_cfg.get("repo")
    if not token or not repo: return
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    try:
        rel_res = requests.get(f"https://api.github.com/repos/{repo}/releases/tags/patches", headers=headers, timeout=10)
        if rel_res.status_code == 200:
            for asset in rel_res.json().get("assets", []):
                if asset.get("name") == file_name:
                    requests.delete(asset.get("url"), headers=headers, timeout=10)
                    break
    except: pass

def upload_file_to_github_release(file_name: str, file_bytes: bytes) -> str:
    gh_cfg = database.get_github_settings()
    token = gh_cfg.get("token")
    repo = gh_cfg.get("repo")
    if not token or not repo:
        return None

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }

    try:
        # Check if release 'patches' exists, or create it
        rel_res = requests.get(f"https://api.github.com/repos/{repo}/releases/tags/patches", headers=headers, timeout=10)
        upload_url_template = None
        if rel_res.status_code == 200:
            rel_data = rel_res.json()
            upload_url_template = rel_data.get("upload_url")
        else:
            create_rel = requests.post(
                f"https://api.github.com/repos/{repo}/releases",
                headers=headers,
                json={
                    "tag_name": "patches",
                    "name": "ROXY X SKYLS Patch Files CDN",
                    "body": "Automated patch files release storage",
                    "draft": False,
                    "prerelease": False
                },
                timeout=10
            )
            if create_rel.status_code in [200, 201]:
                rel_data = create_rel.json()
                upload_url_template = rel_data.get("upload_url")

        if not upload_url_template:
            logger.warning("Could not obtain GitHub release upload URL")
            return None

        upload_url = upload_url_template.split("{")[0]
        clean_name = file_name.replace(" ", "_")
        upload_headers = {
            "Authorization": f"token {token}",
            "Content-Type": "application/octet-stream"
        }
        upload_res = requests.post(
            f"{upload_url}?name={clean_name}",
            headers=upload_headers,
            data=file_bytes,
            timeout=60
        )
        if upload_res.status_code in [200, 201]:
            asset_data = upload_res.json()
            cdn_url = asset_data.get("browser_download_url")
            logger.info(f"File uploaded to GitHub Release successfully: {cdn_url}")
            return cdn_url
        elif upload_res.status_code == 422:
            ts = int(time.time())
            unique_name = f"{ts}_{clean_name}"
            upload_res2 = requests.post(
                f"{upload_url}?name={unique_name}",
                headers=upload_headers,
                data=file_bytes,
                timeout=60
            )
            if upload_res2.status_code in [200, 201]:
                asset_data2 = upload_res2.json()
                cdn_url = asset_data2.get("browser_download_url")
                logger.info(f"File uploaded with unique name to GitHub Release: {cdn_url}")
                return cdn_url
    except Exception as e:
        logger.error(f"Error uploading to GitHub Release: {e}")

    return None

class GitHubSettingsRequest(BaseModel):
    token: str
    repo: str

@app.get("/api/admin/github_settings")
async def admin_get_github_settings(authenticated: bool = Depends(verify_admin)):
    return database.get_github_settings()

@app.post("/api/admin/github_settings")
async def admin_set_github_settings(req: GitHubSettingsRequest, authenticated: bool = Depends(verify_admin)):
    database.set_github_settings(req.token.strip(), req.repo.strip())
    return {"status": "success", "message": "GitHub settings saved successfully!"}

@app.post("/api/admin/upload")
async def admin_upload_file(file: UploadFile = File(...), authenticated: bool = Depends(verify_admin)):
    file_bytes = await file.read()
    cdn_url = upload_file_to_github_release(file.filename, file_bytes)
    file_id = database.save_file(file.filename, file_bytes, cdn_url)
    
    # Cache to server local disk as well
    try:
        cache_path = os.path.join(CACHE_DIR, f"{file_id}_{file.filename}")
        with open(cache_path, "wb") as f:
            f.write(file_bytes)
    except Exception:
        pass

    return {
        "status": "success",
        "file_id": file_id,
        "file_name": file.filename,
        "external_url": cdn_url,
        "mode": "GitHub CDN" if cdn_url else "Server Disk Cache"
    }

@app.post("/api/admin/upload_org_lib")
async def admin_upload_org_lib(file: UploadFile = File(...), authenticated: bool = Depends(verify_admin)):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        file_path = os.path.join(CACHE_DIR, f"org_{file.filename}")
        with open(file_path, "wb") as f:
            f.write(await file.read())
        # In a real setup this should be a served static URL, 
        # but here we just store the local path or dummy URL for now
        url = f"http://YOUR_SERVER_IP/{file_path}"
        database.set_org_lib_url(url)
        return {"status": "success", "url": url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/admin/add_external_file")
async def admin_add_external_file(req: ExternalFileRequest, authenticated: bool = Depends(verify_admin)):
    if not req.download_url or not req.download_url.startswith("http"):
        raise HTTPException(status_code=400, detail="URL must start with http:// or https://")
    file_id = database.save_file(req.file_name, None, req.download_url)
    return {"status": "success", "file_id": file_id, "file_name": req.file_name, "external_url": req.download_url}

@app.delete("/api/admin/files/{file_id}")
async def admin_delete_file(file_id: int, authenticated: bool = Depends(verify_admin)):
    database.delete_file(file_id)
    return {"status": "success", "message": f"File {file_id} deleted"}

class GenerateKeyRequest(BaseModel):
    file_id: int = 1
    key_type: str = "USER"  # ADMIN, USER, VIP
    duration_days: int = 3
    max_devices: int = 1
    custom_key: str = None
    exp_mode: str = "days"
    exp_val: str = None

@app.post("/api/admin/keys/generate")
async def admin_generate_key(req: GenerateKeyRequest, authenticated: bool = Depends(verify_admin)):
    if req.custom_key:
        key_str = req.custom_key.strip()
    else:
        prefix = f"ROXY-X-SKYLS-{req.key_type}" if req.key_type in ["ADMIN", "VIP"] else "ROXY-X-SKYLS"
        key_str = generate_key_string(prefix)
        
    expires_at = None
    dur_days = req.duration_days
    
    if req.exp_mode == "minutes" and req.exp_val:
        dur_days = 0
        try:
            expires_at = (datetime.utcnow() + timedelta(minutes=int(req.exp_val))).isoformat()
        except: pass
    elif req.exp_mode == "exact" and req.exp_val:
        dur_days = 0
        try:
            dt = datetime.strptime(req.exp_val, "%Y-%m-%dT%H:%M")
            expires_at = dt.isoformat()
        except: pass
        
    database.create_key(key_str, req.file_id, dur_days, req.max_devices, expires_at)
    return {
        "status": "success",
        "key": key_str,
        "key_type": req.key_type,
        "duration_days": dur_days,
        "max_devices": req.max_devices
    }

@app.get("/api/admin/keys")
async def admin_get_keys(authenticated: bool = Depends(verify_admin)):
    keys = database.get_all_keys()
    keys_list = []
    for row in keys:
        key, file_id, dur_days, max_dev, created_at, act_at, exp_at, fname, active_cnt, is_dis = row
        
        # Calculate status
        now = datetime.utcnow()
        if is_dis:
            st = "DISABLED"
        elif not act_at:
            st = "UNUSED"
        else:
            try:
                exp_dt = datetime.fromisoformat(str(exp_at).replace("Z", "+00:00").split(".")[0])
            except Exception:
                exp_dt = datetime.strptime(str(exp_at).split(".")[0], "%Y-%m-%d %H:%M:%S")
            st = "EXPIRED" if now > exp_dt else "ACTIVE"
            
        keys_list.append({
            "key": key,
            "file_id": file_id,
            "file_name": fname or "None",
            "duration_days": dur_days,
            "max_devices": max_dev,
            "active_devices_count": active_cnt,
            "created_at": str(created_at),
            "activated_at": str(act_at) if act_at else None,
            "expires_at": str(exp_at) if exp_at else None,
            "status": st,
            "is_disabled": bool(is_dis)
        })
    return keys_list

@app.post("/api/admin/keys/add_days")
async def admin_add_days(req: KeyActionRequest, authenticated: bool = Depends(verify_admin)):
    database.add_days_to_key(req.key, req.extra_days)
    return {"status": "success", "message": f"Added {req.extra_days} days to {req.key}"}

@app.post("/api/admin/keys/toggle_disable")
async def admin_toggle_disable(req: KeyActionRequest, authenticated: bool = Depends(verify_admin)):
    keys = database.get_all_keys()
    dis = False
    for k in keys:
        if k[0] == req.key:
            dis = not bool(k[9])
            break
    database.set_key_disabled(req.key, dis)
    return {"status": "success", "is_disabled": dis}

@app.delete("/api/admin/keys/{key}")
async def admin_delete_key(key: str, authenticated: bool = Depends(verify_admin)):
    database.delete_key(key)
    return {"status": "success", "message": f"Key {key} deleted"}

@app.get("/api/admin/app_users")
async def admin_get_app_users(authenticated: bool = Depends(verify_admin)):
    return database.get_all_users()

@app.get("/api/admin/users")
async def admin_get_users(authenticated: bool = Depends(verify_admin)):
    users = database.get_active_devices()
    users_list = []
    for row in users:
        uid, key, device_id, act_at, exp_at, fname, is_banned, is_muted = row
        users_list.append({
            "id": uid,
            "key": key,
            "device_id": device_id,
            "activated_at": str(act_at),
            "expires_at": str(exp_at) if exp_at else None,
            "file_name": fname or "None",
            "is_banned": bool(is_banned),
            "is_muted": bool(is_muted)
        })
    return users_list

# --- WEB DASHBOARD FRONTEND ---

@app.get("/", response_class=HTMLResponse)
async def admin_dashboard():
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>ROXY X SKYLS - Admin Control Center</title>
        <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700;900&family=Rajdhani:wght@500;600;700&display=swap" rel="stylesheet">
        <style>
            :root {
                --bg: #000000;
                --surface: rgba(18, 24, 41, 0.65);
                --surface-card: rgba(18, 24, 41, 0.65);
                --cyan: #00F0FF;
                --green: #00FF66;
                --red: #FF0055;
                --purple: #B200FF;
                --text: #FFFFFF;
                --text-sec: #94A3B8;
                --border: rgba(255, 255, 255, 0.1);
                --bg-gradient: linear-gradient(-45deg, #0f172a, #1e1b4b, #312e81, #0f172a);
            }

            * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Rajdhani', sans-serif; }
            /* Background glowing spinning elements */
            body::before, body::after {
                content: ''; position: fixed; top: 50%; left: 50%; width: 70vw; height: 70vw;
                border-radius: 50%; transform: translate(-50%, -50%); filter: blur(120px); opacity: 0.6; z-index: -1;
                animation: spinGlow 15s linear infinite; pointer-events: none; mix-blend-mode: screen;
            }
            body::before { background: radial-gradient(circle, rgba(0,240,255,0.4), transparent 60%); margin-left: -15vw; }
            body::after { background: radial-gradient(circle, rgba(178,0,255,0.4), transparent 60%); margin-left: 15vw; animation-direction: reverse; animation-duration: 20s; }
            @keyframes spinGlow { 100% { transform: translate(-50%, -50%) rotate(360deg); } }
            
            body { 
                background: radial-gradient(circle at top, #111 0%, #000 70%); background-size: cover; background-attachment: fixed;
                color: var(--text); 
                padding-bottom: 40px; 
                min-height: 100vh;
            }

            @keyframes gradientBG {
                0% { background-position: 0% 50%; }
                50% { background-position: 100% 50%; }
                100% { background-position: 0% 50%; }
            }

            /* Top Responsive Navigation */
            .top-navbar {
                display: flex;
                justify-content: space-between;
                align-items: center;
                background: rgba(10, 14, 26, 0.6);
                backdrop-filter: blur(16px);
                -webkit-backdrop-filter: blur(16px);
                padding: 16px 24px;
                border-bottom: 2px solid transparent;
                border-image: linear-gradient(90deg, var(--cyan), var(--purple)) 1;
                box-shadow: 0 4px 30px rgba(0, 240, 255, 0.2);
                position: sticky;
                top: 0;
                z-index: 100;
            }

            .logo-group { display: flex; align-items: center; gap: 12px; }
            .logo-title { 
                font-family: 'Orbitron', sans-serif; 
                font-size: 24px; 
                font-weight: 900; 
                background: linear-gradient(to right, var(--cyan), var(--purple));
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                letter-spacing: 2px;
                text-shadow: 0px 0px 15px rgba(0, 240, 255, 0.4);
                animation: pulse 2s infinite;
            }

            @keyframes pulse {
                0% { filter: drop-shadow(0 0 5px rgba(0,240,255,0.4)); }
                50% { filter: drop-shadow(0 0 15px rgba(178,0,255,0.8)); }
                100% { filter: drop-shadow(0 0 5px rgba(0,240,255,0.4)); }
            }

            .nav-actions { display: flex; align-items: center; gap: 10px; }
            .btn {
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid var(--cyan);
                color: var(--cyan);
                padding: 8px 16px;
                border-radius: 8px;
                cursor: pointer;
                font-weight: 700;
                font-size: 14px;
                text-transform: uppercase;
                transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1);
                backdrop-filter: blur(4px);
                position: relative;
                overflow: hidden;
                box-shadow: inset 0 0 5px rgba(0, 240, 255, 0.1);
            }
            .btn::before {
                content: '';
                position: absolute;
                top: 50%; left: 50%;
                width: 300%; height: 300%;
                background: rgba(255,255,255,0.1);
                transition: all 0.5s;
                transform: translate(-50%, -50%) rotate(45deg) translateY(100%);
            }
            .btn:hover::before { transform: translate(-50%, -50%) rotate(45deg) translateY(0); }
            .btn:active { transform: scale(0.92); box-shadow: 0 0 40px var(--cyan); }
            .btn-danger:active { box-shadow: 0 0 40px var(--red); }
            .btn-success:active { box-shadow: 0 0 40px var(--green); }
            .btn:hover { 
                background: var(--cyan); 
                color: #000; 
                box-shadow: 0 0 15px var(--cyan), 0 0 30px var(--cyan); 
                transform: translateY(-2px);
            }
            .btn-danger { border-color: var(--red); color: var(--red); }
            .btn-danger:hover { background: var(--red); color: #fff; box-shadow: 0 0 15px var(--red), 0 0 30px var(--red); }
            .btn-success { border-color: var(--green); color: var(--green); }
            .btn-success:hover { background: var(--green); color: #000; box-shadow: 0 0 15px var(--green), 0 0 30px var(--green); }

            /* Container & Stats Header Bar */
            .container { max-width: 1200px; margin: 30px auto; padding: 0 16px; animation: slideUp 0.6s ease-out; }

            @keyframes slideUp {
                from { opacity: 0; transform: translateY(30px); }
                to { opacity: 1; transform: translateY(0); }
            }

            .stats-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
                gap: 20px;
                margin-bottom: 30px;
            }
            .stat-card {
                background: var(--surface-card);
                backdrop-filter: blur(16px);
                -webkit-backdrop-filter: blur(16px);
                border: 1px solid var(--border);
                border-radius: 16px;
                padding: 20px;
                display: flex;
                flex-direction: column;
                transition: transform 0.3s ease, box-shadow 0.3s ease;
                box-shadow: 0 10px 30px -10px rgba(0,0,0,0.5), inset 0 2px 10px rgba(255,255,255,0.05);
                position: relative;
                overflow: hidden;
            }
            .stat-card::after {
                content: '';
                position: absolute;
                top: -50%; left: -50%; width: 200%; height: 200%;
                background: radial-gradient(circle, rgba(255,255,255,0.05) 0%, transparent 70%);
                opacity: 0; transition: opacity 0.3s;
            }
            .stat-card:hover::after { opacity: 1; }
            .stat-card:hover { 
                transform: translateY(-5px) scale(1.02); 
                box-shadow: 0 20px 40px -10px rgba(0,240,255,0.2), inset 0 2px 10px rgba(0,240,255,0.1); 
                border-color: rgba(0,240,255,0.3);
            }
            .stat-label { font-size: 13px; color: var(--text-sec); text-transform: uppercase; margin-bottom: 8px; font-weight: 600; letter-spacing: 1px;}
            .stat-val { font-family: 'Orbitron', sans-serif; font-size: 24px; font-weight: 900; color: var(--cyan); text-shadow: 0 0 10px rgba(0,240,255,0.3); }

            .tabs { 
                display: flex; gap: 12px; border-bottom: 2px solid rgba(255,255,255,0.05); 
                margin-bottom: 24px; overflow-x: auto; padding-bottom: 10px;
            }
            .tab-btn {
                background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.05); color: var(--text-sec);
                padding: 12px 24px; font-size: 15px; font-weight: 700; cursor: pointer;
                border-radius: 8px; white-space: nowrap; transition: all 0.3s ease;
            }
            .tab-btn:hover { background: rgba(0,240,255,0.1); color: #fff; transform: translateY(-2px); }
            .tab-btn.active { 
                background: linear-gradient(135deg, rgba(0,240,255,0.2), rgba(178,0,255,0.2));
                color: #fff; border-color: var(--cyan); 
                box-shadow: 0 0 15px rgba(0,240,255,0.2);
            }

            /* Grid Layouts & Cards */
            .card {
                background: var(--surface-card);
                backdrop-filter: blur(20px);
                -webkit-backdrop-filter: blur(20px);
                border: 1px solid var(--border);
                border-radius: 16px;
                padding: 24px;
                margin-bottom: 24px;
                box-shadow: 0 15px 35px rgba(0,0,0,0.4), inset 0 2px 10px rgba(255,255,255,0.02);
                transition: transform 0.3s ease;
            }
            .card:hover { border-color: rgba(255,255,255,0.15); }
            .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; flex-wrap: wrap; gap: 12px; }
            .card-title { font-family: 'Orbitron', sans-serif; font-size: 18px; color: #fff; text-shadow: 0 2px 10px rgba(0,240,255,0.5); }

            /* Responsive Tables */
            .table-responsive { width: 100%; overflow-x: auto; -webkit-overflow-scrolling: touch; border-radius: 12px; }
            table { width: 100%; border-collapse: separate; border-spacing: 0; text-align: left; }
            th, td { padding: 14px 18px; font-size: 15px; border-bottom: 1px solid rgba(255,255,255,0.05); }
            th { 
                background: rgba(0,0,0,0.4); color: var(--text-sec); text-transform: uppercase; 
                font-size: 12px; font-weight: 700; letter-spacing: 1px;
            }
            tr { transition: background 0.2s; }
            tr:hover td { background: rgba(255,255,255,0.03); }

            /* Status Badges */
            .badge { padding: 6px 10px; border-radius: 6px; font-weight: 800; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; box-shadow: 0 2px 10px rgba(0,0,0,0.2); }
            .badge-active { background: linear-gradient(45deg, rgba(0,255,102,0.2), rgba(0,255,102,0.1)); color: var(--green); border: 1px solid var(--green); text-shadow: 0 0 8px var(--green); }
            .badge-unused { background: linear-gradient(45deg, rgba(0,240,255,0.2), rgba(0,240,255,0.1)); color: var(--cyan); border: 1px solid var(--cyan); text-shadow: 0 0 8px var(--cyan); }
            .badge-expired { background: linear-gradient(45deg, rgba(255,0,85,0.2), rgba(255,0,85,0.1)); color: var(--red); border: 1px solid var(--red); text-shadow: 0 0 8px var(--red); }
            .badge-disabled { background: rgba(138,153,181,0.2); color: var(--text-sec); border: 1px solid var(--text-sec); }

            /* Modals */
            .modal-overlay {
                position: fixed; top: 0; left: 0; width: 100%; height: 100%;
                background: rgba(0,0,0,0.6); backdrop-filter: blur(8px);
                display: none; justify-content: center; align-items: center;
                z-index: 1000; padding: 16px;
                animation: fadeIn 0.3s ease;
            }
            @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
            
            .modal-box {
                background: var(--surface-card); 
                backdrop-filter: blur(20px);
                border: 1px solid rgba(255,255,255,0.1);
                border-top: 2px solid var(--cyan);
                border-radius: 16px; padding: 30px; max-width: 480px; width: 100%;
                box-shadow: 0 20px 50px rgba(0,0,0,0.5), 0 0 30px rgba(0,240,255,0.1);
                transform: scale(0.95);
                animation: scaleUp 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275) forwards;
            }
            @keyframes scaleUp { to { transform: scale(1); } }

            .form-group { margin-bottom: 18px; }
            .form-group label { display: block; margin-bottom: 8px; font-size: 14px; font-weight: 600; color: var(--text-sec); letter-spacing: 0.5px; }
            .form-control {
                width: 100%; background: rgba(0,0,0,0.3); border: 1px solid var(--border);
                color: #fff; padding: 12px 14px; border-radius: 8px; font-size: 15px;
                transition: all 0.3s ease; box-shadow: inset 0 2px 4px rgba(0,0,0,0.2);
            }
            .form-control:focus {
                outline: none; border-color: var(--cyan); background: rgba(0,0,0,0.5);
                box-shadow: 0 0 15px rgba(0,240,255,0.2), inset 0 2px 4px rgba(0,0,0,0.2);
            }

            /* Upload Progress Bar */
            .upload-progress-container {
                display: none; margin-top: 20px;
                background: rgba(0,0,0,0.3); border: 1px solid var(--border);
                border-radius: 12px; padding: 20px; box-shadow: inset 0 2px 10px rgba(0,0,0,0.3);
            }
            .progress-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; font-size: 15px; }
            .progress-status { color: var(--cyan); font-weight: 700; text-shadow: 0 0 8px rgba(0,240,255,0.4); }
            .progress-percent { color: var(--green); font-family: 'Orbitron', sans-serif; font-weight: bold; font-size: 18px; text-shadow: 0 0 8px rgba(0,255,102,0.4); }
            .progress-track {
                width: 100%; height: 14px; background: rgba(0,0,0,0.5);
                border-radius: 8px; overflow: hidden; position: relative;
                border: 1px solid var(--border); box-shadow: inset 0 2px 5px rgba(0,0,0,0.5);
            }
            .progress-fill {
                width: 0%; height: 100%;
                background: linear-gradient(90deg, var(--cyan), var(--purple), var(--cyan));
                background-size: 200% 200%;
                animation: gradientBG 2s linear infinite;
                box-shadow: 0 0 15px rgba(0, 240, 255, 0.8);
                transition: width 0.2s cubic-bezier(0.4, 0, 0.2, 1);
                border-radius: 8px;
            }
            .progress-footer { display: flex; justify-content: space-between; align-items: center; margin-top: 10px; font-size: 13px; color: var(--text-sec); font-weight: 600; }

            /* Responsive Mobile Adjustments */
            @media (max-width: 768px) {
                .top-navbar { padding: 12px 16px; flex-direction: column; gap: 12px; }
                .logo-title { font-size: 18px; }
                .btn { padding: 8px 12px; font-size: 12px; }
                .card { padding: 16px; }
                th, td { padding: 10px 12px; font-size: 13px; }
                .stats-grid { grid-template-columns: 1fr 1fr; }
            }
            @media (max-width: 480px) {
                .stats-grid { grid-template-columns: 1fr; }
            }
        </style>
    </head>
    <body>

        <!-- Top Navigation Bar -->
        <div class="top-navbar">
            <div class="logo-group">
                <div class="logo-title" id="txtSiteTitle">ROXY X SKYLS</div>
            </div>
            <div class="nav-actions">
                <select id="langSelect" class="form-control" style="width: auto; padding: 6px 10px; background: var(--surface); color: var(--cyan); border-color: var(--cyan);" onchange="changeLanguage(this.value)">
                    <option value="en">🇬🇧 EN</option>
                    <option value="uz">🇺🇿 UZ</option>
                    <option value="ru">🇷🇺 RU</option>
                </select>
                <button class="btn btn-success" id="btnChangePassNav" onclick="openChangePassModal()">🔑 CHANGE PASS</button>
                <button class="btn btn-danger" id="btnLogoutNav" onclick="logout()">LOGOUT</button>
            </div>
        </div>

        <!-- Login Card Overlay -->
        <div id="loginOverlay" class="modal-overlay" style="display: flex;">
            <div class="modal-box">
                <h3 class="card-title" style="margin-bottom: 16px;">ADMIN LOGIN</h3>
                <div class="form-group">
                    <label id="lblLoginPass">Password</label>
                    <input type="password" id="loginPassword" class="form-control" placeholder="Enter password">
                </div>
                <button class="btn btn-success" style="width: 100%; margin-top: 10px;" onclick="performLogin()">LOGIN TO SYSTEM</button>
            </div>
        </div>

        <!-- Main Dashboard Container -->
        <div class="container" id="mainDashboard" style="display: none;">

            <!-- Live Database & Ping Stats Bar -->
            <div class="stats-grid">
                <div class="stat-card">
                    <span class="stat-label" id="lblStatDb">🗄 DATABASE USAGE</span>
                    <span class="stat-val" id="statDbSize">0.0 MB / 500 MB</span>
                </div>
                <div class="stat-card">
                    <span class="stat-label" id="lblStatPing">⚡️ LATENCY PING</span>
                    <span class="stat-val" style="color: var(--green);" id="statPing">0 ms</span>
                </div>
                <div class="stat-card">
                    <span class="stat-label" id="lblStatKeys">🔑 TOTAL KEYS</span>
                    <span class="stat-val" id="statKeys">0 Keys</span>
                </div>
                <div class="stat-card">
                    <span class="stat-label" id="lblStatUsers">📱 ACTIVE USERS</span>
                    <span class="stat-val" style="color: var(--green);" id="statUsers">0 Online</span>
                </div>
            </div>
            
            <!-- Navigation Tabs -->
            <div class="tabs">
                <button class="tab-btn active" id="tabKeysBtn" onclick="switchTab('keysTab', this)">🔑 KEYS MANAGER</button>
                <button class="tab-btn" id="tabFilesBtn" onclick="switchTab('filesTab', this)">📁 FILES MANAGER</button>
                <button class="tab-btn" id="tabUsersBtn" onclick="switchTab('usersTab', this)">👥 ACTIVE USERS & BANS</button>
                <button class="tab-btn" id="tabGithubBtn" onclick="switchTab('githubTab', this)">⚙️ GITHUB RELEASES CDN</button>
                <button class="tab-btn" id="tabUpdatesBtn" onclick="switchTab('updatesTab', this)">🚀 APP UPDATES</button>
            </div>

            <!-- KEYS MANAGER TAB -->
            <div id="keysTab" class="tab-content">
                <div class="card">
                    <div class="card-header">
                        <span class="card-title" id="txtKeysTitle">LICENSE KEYS CONTROL</span>
                        <button class="btn btn-success" id="btnOpenGenKey" onclick="openGenerateModal()">+ GENERATE KEY</button>
                    </div>
                    <div class="table-responsive">
                        <table>
                            <thead>
                                <tr>
                                    <th id="thKey">Key String</th>
                                    <th id="thType">Type / File</th>
                                    <th id="thDur">Duration</th>
                                    <th id="thMax">Max Dev</th>
                                    <th id="thSt">Status</th>
                                    <th id="thCr">Created</th>
                                    <th id="thExp">Expires</th>
                                    <th id="thAct">Actions</th>
                                </tr>
                            </thead>
                            <tbody id="keysTableBody">
                                <!-- Dynamic Keys -->
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- FILES MANAGER TAB -->
            <div id="filesTab" class="tab-content" style="display: none;">
                
                <div class="card" style="margin-bottom: 20px; border-color: var(--red);">
                    <div class="card-header">
                        <span class="card-title" style="color: var(--red);">🧹 WEEKLY CLEANUP (AUTO DETECT)</span>
                        <button class="btn btn-danger" onclick="cleanupOldFiles()">🗑️ DELETE ALL EXPIRED / OLD FILES</button>
                    </div>
                    <p style="color: var(--text-sec); font-size: 13px;" id="cleanupMsgText">
                        Every Friday (9-10 AM) a prompt will appear here to clear out old patches and original libs automatically.
                    </p>
                </div>

                <div class="card" style="margin-bottom: 20px;">
                    <div class="card-header">
                        <span class="card-title">♻️ ORIGINAL LIB AUTO-RESTORE URL</span>
                    </div>
                    <p style="color: var(--text-sec); margin-bottom: 12px; font-size: 13px;">
                        When a user's license key expires, the app will silently download this file and restore it to disable cheats.
                    </p>
                    <div style="margin-bottom: 12px; display: flex; gap: 8px;">
                        <button class="btn btn-success" id="btnOrgUrl" onclick="toggleOrgMode('url')" style="padding: 4px 10px; font-size: 12px;">🔗 URL</button>
                        <button class="btn" id="btnOrgFile" onclick="toggleOrgMode('file')" style="padding: 4px 10px; font-size: 12px; border-color: var(--text-sec); color: var(--text-sec);">📁 LOCAL FILE</button>
                    </div>
                    <div id="orgUrlMode" style="display: grid; grid-template-columns: 1fr auto; gap: 10px; align-items: end;">
                        <div class="form-group" style="margin-bottom: 0;">
                            <label>Original Lib URL</label>
                            <input type="url" id="orgLibUrl" class="form-control" placeholder="https://example.com/lib_original.so">
                        </div>
                        <button class="btn btn-success" style="height: 42px;" onclick="saveOrgLibUrl()">💾 SAVE URL</button>
                    </div>
                    <div id="orgFileMode" style="display: none; grid-template-columns: 1fr auto; gap: 10px; align-items: end;">
                        <div class="form-group" style="margin-bottom: 0;">
                            <label>Upload Original Lib File</label>
                            <input type="file" id="orgFileInput" class="form-control">
                        </div>
                        <button class="btn btn-success" style="height: 42px;" onclick="alert('Feature placeholder: uploading org file locally')">UPLOAD LOCAL</button>
                    </div>
                </div>

                <div class="card" style="margin-bottom: 20px;">
                    <div class="card-header">
                        <span class="card-title">🚀 GITHUB RELEASES / CDN DIRECT LINK</span>
                    </div>
                    <div style="display: grid; grid-template-columns: 1fr 2fr auto; gap: 10px; align-items: end;">
                        <div class="form-group" style="margin-bottom: 0;">
                            <label>File Name</label>
                            <input type="text" id="extFileName" class="form-control" placeholder="lib.zip" value="lib.zip">
                        </div>
                        <div class="form-group" style="margin-bottom: 0;">
                            <label>GitHub / CDN Direct Download URL</label>
                            <input type="url" id="extFileUrl" class="form-control" placeholder="https://github.com/CryoSky-project/.../releases/download/.../lib.zip">
                        </div>
                        <button class="btn btn-success" style="height: 42px;" onclick="addExternalFile()">+ ADD LINK</button>
                    </div>
                </div>

                <div class="card">
                    <div class="card-header" style="margin-bottom: 8px;">
                        <span class="card-title" id="txtFilesTitle">UPLOAD PATCH FILES (lib.zip)</span>
                    </div>
                    <div style="margin-bottom: 12px; display: flex; gap: 8px;">
                        <button class="btn" id="btnPatchUrl" onclick="togglePatchMode('url')" style="padding: 4px 10px; font-size: 12px; border-color: var(--text-sec); color: var(--text-sec);">🔗 URL</button>
                        <button class="btn btn-success" id="btnPatchFile" onclick="togglePatchMode('file')" style="padding: 4px 10px; font-size: 12px;">📁 LOCAL FILE</button>
                    </div>
                    
                    <div id="patchUrlMode" style="display: none; grid-template-columns: 1fr auto; gap: 10px; align-items: end; margin-bottom: 16px;">
                        <div class="form-group" style="margin-bottom: 0;">
                            <label>Patch File URL</label>
                            <input type="url" id="patchUrlInput" class="form-control" placeholder="https://example.com/lib.zip">
                        </div>
                        <button class="btn btn-success" style="height: 42px;" onclick="addPatchUrl()">ADD URL</button>
                    </div>

                    <div id="patchFileMode">
                        <div class="form-group">
                            <input type="file" id="fileInput" class="form-control" accept=".zip,.7z,.rar,.tar,.gz,.bz2,.xz,.so">
                        </div>
                        <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
                            <button class="btn btn-success" id="btnUploadFile" onclick="uploadFile()">UPLOAD PATCH FILE</button>
                            <button class="btn btn-danger" id="btnCancelUpload" style="display: none;" onclick="cancelUpload()">STOP UPLOAD</button>
                        </div>
                    </div>

                    <!-- App-like Live Upload Progress Display -->
                    <div id="uploadProgressContainer" class="upload-progress-container">
                        <div class="progress-header">
                            <span class="progress-status" id="uploadStatusText">⚡ Uploading file...</span>
                            <span class="progress-percent" id="uploadPercentText">0%</span>
                        </div>
                        <div class="progress-track">
                            <div class="progress-fill" id="uploadProgressFill"></div>
                        </div>
                        <div class="progress-footer">
                            <span id="uploadMBText">0.00 MB / 0.00 MB</span>
                            <span id="uploadSpeedText">0.0 MB/s</span>
                        </div>
                    </div>

                    <div class="table-responsive" style="margin-top: 20px;">
                        <table>
                            <thead>
                                <tr>
                                    <th>ID</th>
                                    <th>File Name</th>
                                    <th>Type / Source</th>
                                    <th>Uploaded At</th>
                                    <th>Action</th>
                                </tr>
                            </thead>
                            <tbody id="filesTableBody">
                                <!-- Dynamic Files -->
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- USERS TAB -->
            <div id="usersTab" class="tab-content" style="display: none;">
                
                <div class="card" style="margin-bottom: 20px;">
                    <div class="card-header">
                        <span class="card-title" style="color: var(--cyan);">👤 REGISTERED APP USERS</span>
                    </div>
                    <div class="table-responsive">
                        <table>
                            <thead>
                                <tr>
                                    <th>Username</th>
                                    <th>Balance</th>
                                    <th>Role</th>
                                    <th>Created At</th>
                                </tr>
                            </thead>
                            <tbody id="appUsersTableBody">
                                <!-- Dynamic -->
                            </tbody>
                        </table>
                    </div>
                </div>

                <div class="card">
                    <div class="card-header">
                        <span class="card-title" id="txtUsersTitle">📱 ACTIVE DEVICES</span>
                    </div>
                    <div class="table-responsive">
                        <table>
                            <thead>
                                <tr>
                                    <th>ID</th>
                                    <th>Key</th>
                                    <th>Device ID</th>
                                    <th>Activated</th>
                                    <th>Status</th>
                                    <th>Actions (Ban / Mute)</th>
                                </tr>
                            </thead>
                            <tbody id="usersTableBody">
                                <!-- Dynamic Users -->
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- GITHUB SETTINGS TAB -->
            <div id="githubTab" class="tab-content" style="display: none;">
                <div class="card">
                    <div class="card-header">
                        <span class="card-title" id="txtGithubTitle">⚙️ GITHUB RELEASES CDN CONFIGURATION</span>
                    </div>
                    <p style="color: var(--text-sec); margin-bottom: 16px;">
                        Configure GitHub Personal Access Token and Repository to enable automatic high-speed CDN file releases upon upload.
                    </p>
                    <div class="form-group">
                        <label>GitHub Personal Access Token (PAT with repo scope)</label>
                        <input type="password" id="ghTokenInput" class="form-control" placeholder="ghp_xxxxxxxxxxxxxxxxxxxx">
                    </div>
                    <div class="form-group">
                        <label>GitHub Repository (Owner/Repo)</label>
                        <input type="text" id="ghRepoInput" class="form-control" placeholder="CryoSky-project/SKYLS-X-HACK-site">
                    </div>
                    <button class="btn btn-success" id="btnSaveGhSettings" onclick="saveGithubSettings()">💾 SAVE GITHUB SETTINGS</button>
                </div>
            </div>

            <!-- APP UPDATES TAB -->
            <div id="updatesTab" class="tab-content" style="display: none;">
                <div class="card">
                    <div class="card-header">
                        <span class="card-title">🚀 APP UPDATES MANAGEMENT</span>
                    </div>
                    <p style="color: var(--text-sec); margin-bottom: 16px;">
                        Configure the mandatory app update. If users have an older version, they will be forced to download and install this new version via Shizuku or normal installation.
                    </p>
                    <div class="form-group">
                        <label>Enable Mandatory Update (Block old versions)</label>
                        <select id="updForce" class="form-control">
                            <option value="true">YES - Block old versions</option>
                            <option value="false">NO - Allow old versions</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Latest Version Code (Integer, e.g., 2)</label>
                        <input type="number" id="updCode" class="form-control" value="2">
                    </div>
                    <div class="form-group">
                        <label>Latest Version Name (String, e.g., v3.1.0)</label>
                        <input type="text" id="updName" class="form-control" value="v3.1.0">
                    </div>
                    <div class="form-group">
                        <label>APK Download URL (Direct link to the new APK)</label>
                        <input type="url" id="updUrl" class="form-control" placeholder="https://example.com/app.apk">
                    </div>
                    <div class="form-group">
                        <label>Release Notes (What's new?)</label>
                        <textarea id="updNotes" class="form-control" rows="3" placeholder="- Fixed bugs\n- Added new cheat features"></textarea>
                    </div>
                    <button class="btn btn-success" onclick="saveAppUpdateSettings()">🚀 PUSH UPDATE</button>
                </div>

                <div class="card" style="margin-top: 20px;">
                    <div class="card-header">
                        <span class="card-title">📜 VERSION HISTORY (AUTO-SAVED)</span>
                    </div>
                    <div class="table-responsive">
                        <table>
                            <thead>
                                <tr>
                                    <th>Version</th>
                                    <th>Code</th>
                                    <th>Force?</th>
                                    <th>Saved At</th>
                                    <th>Notes</th>
                                </tr>
                            </thead>
                            <tbody id="versionHistoryBody">
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

        </div>

        <!-- Generate Key Modal -->
        <div id="generateModal" class="modal-overlay">
            <div class="modal-box">
                <h3 class="card-title" style="margin-bottom: 16px;">GENERATE NEW KEY</h3>
                <div class="form-group">
                    <label>Key Type</label>
                    <select id="genKeyType" class="form-control" onchange="onKeyTypeChange(this.value)">
                        <option value="USER">User Key (Standard)</option>
                        <option value="VIP">VIP Key (Premium)</option>
                        <option value="ADMIN">Admin Key (Full Control)</option>
                    </select>
                </div>
                <div class="form-group" id="fileSelectGroup">
                    <label>Select Target Patch File</label>
                    <select id="genFileSelect" class="form-control"></select>
                </div>
                <div class="form-group">
                    <label>Expiration Mode</label>
                    <select id="genExpMode" class="form-control" onchange="toggleExpMode()">
                        <option value="days">Mode 1: Duration (Days)</option>
                        <option value="minutes">Mode 2: Duration (Minutes)</option>
                        <option value="exact">Mode 3: Exact Date & Time</option>
                    </select>
                </div>
                <div class="form-group" id="grpExpDays">
                    <label>Duration (Days)</label>
                    <input type="number" id="genDays" class="form-control" value="3" min="1">
                </div>
                <div class="form-group" id="grpExpMins" style="display:none;">
                    <label>Duration (Minutes)</label>
                    <input type="number" id="genMins" class="form-control" value="60" min="1">
                </div>
                <div class="form-group" id="grpExpExact" style="display:none;">
                    <label>Exact Expiration Time</label>
                    <input type="datetime-local" id="genExact" class="form-control" style="background: var(--surface); color: var(--text); border: 1px solid var(--border); padding: 10px; border-radius: 6px; width: 100%;">
                </div>
                <div class="form-group">
                    <label>Max Devices</label>
                    <input type="number" id="genDevices" class="form-control" value="1" min="1">
                </div>
                <div style="display: flex; gap: 10px; margin-top: 20px;">
                    <button class="btn btn-success" style="flex: 1;" onclick="submitGenerateKey()">GENERATE</button>
                    <button class="btn btn-danger" style="flex: 1;" onclick="closeGenerateModal()">CANCEL</button>
                </div>
            </div>
        </div>

        <!-- Generated Key Success Modal -->
        <div id="keyCreatedModal" class="modal-overlay">
            <div class="modal-box" style="text-align: center;">
                <h3 class="card-title" style="color: var(--green);">KEY GENERATED!</h3>
                <p style="margin: 16px 0; font-size: 20px; font-weight: bold; color: var(--cyan);" id="createdKeyString"></p>
                <button class="btn btn-success" style="width: 100%; margin-bottom: 10px;" onclick="copyKeyText()">COPY KEY</button>
                <button class="btn" style="width: 100%;" onclick="closeKeyCreatedModal()">CLOSE</button>
            </div>
        </div>

        <!-- Change Password Modal -->
        <div id="changePassModal" class="modal-overlay">
            <div class="modal-box">
                <h3 class="card-title" style="margin-bottom: 16px;">CHANGE ADMIN PASSWORD</h3>
                <div class="form-group">
                    <label>New Password</label>
                    <input type="text" id="newAdminPasswordInput" class="form-control" placeholder="Enter new password">
                </div>
                <div style="display: flex; gap: 10px; margin-top: 20px;">
                    <button class="btn btn-success" style="flex: 1;" onclick="submitChangePassword()">SAVE</button>
                    <button class="btn btn-danger" style="flex: 1;" onclick="closeChangePassModal()">CANCEL</button>
                </div>
            </div>
        </div>

        <script>
            let adminToken = localStorage.getItem("adminToken") || "";
            let currentLang = localStorage.getItem("siteLang") || "en";

            const i18n = {
                en: {
                    site_title: "ROXY X SKYLS",
                    btn_change_pass: "🔑 CHANGE PASS",
                    btn_logout: "LOGOUT",
                    tab_keys: "🔑 KEYS MANAGER",
                    tab_files: "📁 FILES MANAGER",
                    tab_users: "👥 ACTIVE USERS & BANS",
                    tab_github: "⚙️ GITHUB RELEASES CDN",
                    stat_db: "🗄 DATABASE USAGE",
                    stat_ping: "⚡️ LATENCY PING",
                    stat_keys: "🔑 TOTAL KEYS",
                    stat_users: "📱 ACTIVE USERS",
                    keys_title: "LICENSE KEYS CONTROL",
                    btn_gen_key: "+ GENERATE KEY",
                    files_title: "UPLOAD PATCH FILES (lib.zip)",
                    users_title: "ACTIVE USERS & BAN SYSTEM",
                    github_title: "⚙️ GITHUB RELEASES CDN CONFIGURATION",
                    btn_upload: "UPLOAD PATCH FILE",
                    btn_save_github: "💾 SAVE GITHUB SETTINGS",
                    th_key: "Key String",
                    th_type: "Type / File",
                    th_dur: "Duration",
                    th_max: "Max Dev",
                    th_st: "Status",
                    th_cr: "Created",
                    th_exp: "Expires",
                    th_act: "Actions"
                },
                uz: {
                    site_title: "ROXY X SKYLS",
                    btn_change_pass: "🔑 PAROLNI O'ZGARTIRISH",
                    btn_logout: "CHIQISH",
                    tab_keys: "🔑 KALITLAR",
                    tab_files: "📁 FAYLLAR",
                    tab_users: "👥 FOYDALANUVCHILAR & BAN",
                    tab_github: "⚙️ GITHUB RELEASES CDN",
                    stat_db: "🗄 BAZA HAJMI",
                    stat_ping: "⚡️ BAZA TEZLIGI (PING)",
                    stat_keys: "🔑 JAMI KALITLAR",
                    stat_users: "📱 ONLINE FOYDALANUVCHILAR",
                    keys_title: "KALITLARNI BOSHQARISH",
                    btn_gen_key: "+ KALIT YARATISH",
                    files_title: "FAYL YUKLASH (lib.zip)",
                    users_title: "FOYDALANUVCHILAR VA BAN TIZIMI",
                    github_title: "⚙️ GITHUB RELEASES CDN SOZLAMALARI",
                    btn_upload: "FAYLI YUKLASH",
                    btn_save_github: "💾 SAQLASH",
                    th_key: "Kalit Kodi",
                    th_type: "Turi / Fayl",
                    th_dur: "Muddati",
                    th_max: "Qurilmalar",
                    th_st: "Holati",
                    th_cr: "Yaratilgan",
                    th_exp: "Tugash Vaqti",
                    th_act: "Amallar"
                },
                ru: {
                    site_title: "ROXY X SKYLS",
                    btn_change_pass: "🔑 СМЕНИТЬ ПАРОЛЬ",
                    btn_logout: "ВЫХОД",
                    tab_keys: "🔑 МЕНЕДЖЕР КЛЮЧЕЙ",
                    tab_files: "📁 МЕНЕДЖЕР ФАЙЛОВ",
                    tab_users: "👥 ПОЛЬЗОВАТЕЛИ И БАНЫ",
                    tab_github: "⚙️ GITHUB RELEASES CDN",
                    stat_db: "🗄 РАЗМЕР БАЗЫ ДАННЫХ",
                    stat_ping: "⚡️ ПИНГ БАЗЫ ДАННЫХ",
                    stat_keys: "🔑 ВСЕГО КЛЮЧЕЙ",
                    stat_users: "📱 ОНЛАЙН ПОЛЬЗОВАТЕЛИ",
                    keys_title: "УПРАВЛЕНИЕ КЛЮЧАМИ",
                    btn_gen_key: "+ СОЗДАТЬ КЛЮЧ",
                    files_title: "ЗАГРУЗИТЬ ФАЙЛ (lib.zip)",
                    users_title: "СИСТЕМА БАНОВ И МУТОВ",
                    github_title: "⚙️ НАСТРОЙКИ GITHUB RELEASES CDN",
                    btn_upload: "ЗАГРУЗИТЬ ФАЙЛ",
                    btn_save_github: "💾 СОХРАНИТЬ",
                    th_key: "Код Ключа",
                    th_type: "Тип / Файл",
                    th_dur: "Срок",
                    th_max: "Устройства",
                    th_st: "Статус",
                    th_cr: "Создан",
                    th_exp: "Истекает",
                    th_act: "Действия"
                }
            };

            function changeLanguage(lang) {
                currentLang = lang;
                localStorage.setItem("siteLang", lang);
                const sel = document.getElementById("langSelect");
                if (sel) sel.value = lang;

                const t = i18n[lang] || i18n.en;
                const setTxt = (id, val) => {
                    const el = document.getElementById(id);
                    if (el) el.innerText = val;
                };

                setTxt("txtSiteTitle", t.site_title);
                setTxt("btnChangePassNav", t.btn_change_pass);
                setTxt("btnLogoutNav", t.btn_logout);
                setTxt("tabKeysBtn", t.tab_keys);
                setTxt("tabFilesBtn", t.tab_files);
                setTxt("tabUsersBtn", t.tab_users);
                setTxt("lblStatDb", t.stat_db);
                setTxt("lblStatPing", t.stat_ping);
                setTxt("lblStatKeys", t.stat_keys);
                setTxt("lblStatUsers", t.stat_users);
                setTxt("txtKeysTitle", t.keys_title);
                setTxt("btnOpenGenKey", t.btn_gen_key);
                setTxt("txtFilesTitle", t.files_title);
                setTxt("txtUsersTitle", t.users_title);
                setTxt("tabGithubBtn", t.tab_github);
                setTxt("txtGithubTitle", t.github_title);
                setTxt("btnSaveGhSettings", t.btn_save_github);
                setTxt("btnUploadFile", t.btn_upload);
                setTxt("thKey", t.th_key);
                setTxt("thType", t.th_type);
                setTxt("thDur", t.th_dur);
                setTxt("thMax", t.th_max);
                setTxt("thSt", t.th_st);
                setTxt("thCr", t.th_cr);
                setTxt("thExp", t.th_exp);
                setTxt("thAct", t.th_act);
            }

            document.addEventListener("DOMContentLoaded", function() {
                changeLanguage(currentLang);
            });

            if (adminToken) {
                document.getElementById("loginOverlay").style.display = "none";
                document.getElementById("mainDashboard").style.display = "block";
                loadDashboardData();
            }

            function openChangePassModal() { document.getElementById("changePassModal").style.display = "flex"; }
            function closeChangePassModal() { document.getElementById("changePassModal").style.display = "none"; }

            function submitChangePassword() {
                const newPass = document.getElementById("newAdminPasswordInput").value.trim();
                if (!newPass) return alert("Please enter password!");

                fetch("/api/admin/change_password", {
                    method: "POST",
                    headers: { "Content-Type": "application/json", "Authorization": `Bearer ${adminToken}` },
                    body: JSON.stringify({ new_password: newPass })
                })
                .then(r => r.json())
                .then(data => {
                    if (data.status === "success") {
                        alert("Password updated successfully!");
                        adminToken = newPass;
                        localStorage.setItem("adminToken", newPass);
                        closeChangePassModal();
                    } else {
                        alert("Error updating password");
                    }
                });
            }

            function performLogin() {
                const pass = document.getElementById("loginPassword").value.trim();
                fetch("/api/admin/login", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ password: pass })
                })
                .then(r => r.json())
                .then(data => {
                    if (data.status === "success") {
                        adminToken = data.token;
                        localStorage.setItem("adminToken", adminToken);
                        document.getElementById("loginOverlay").style.display = "none";
                        document.getElementById("mainDashboard").style.display = "block";
                        loadDashboardData();
                    } else {
                        alert("Incorrect Password!");
                    }
                });
            }

            function logout() {
                localStorage.removeItem("adminToken");
                location.reload();
            }

            function switchTab(tabId, btn) {
                document.querySelectorAll(".tab-content").forEach(el => el.style.display = "none");
                document.querySelectorAll(".tab-btn").forEach(el => el.classList.remove("active"));
                document.getElementById(tabId).style.display = "block";
                btn.classList.add("active");
            }

            function loadDashboardData() {
                loadStats();
                loadKeys();
                loadFiles();
                loadUsers();
                loadGithubSettings();
                loadAppUpdateSettings();
                loadOrgLibUrl();
                loadVersionHistory();
                checkFridayCleanup();
            }

            function loadGithubSettings() {
                fetch("/api/admin/github_settings", { headers: { "Authorization": `Bearer ${adminToken}` } })
                .then(r => r.json())
                .then(data => {
                    if (data.token) document.getElementById("ghTokenInput").value = data.token;
                    if (data.repo) document.getElementById("ghRepoInput").value = data.repo;
                });
            }

            function saveGithubSettings() {
                const token = document.getElementById("ghTokenInput").value.trim();
                const repo = document.getElementById("ghRepoInput").value.trim();
                if (!token || !repo) return alert("Please fill in both token and repo!");

                fetch("/api/admin/github_settings", {
                    method: "POST",
                    headers: { "Content-Type": "application/json", "Authorization": `Bearer ${adminToken}` },
                    body: JSON.stringify({ token: token, repo: repo })
                })
                .then(r => r.json())
                .then(data => {
                    if (data.status === "success") {
                        alert("GitHub settings saved successfully!");
                    } else {
                        alert("Error saving GitHub settings!");
                    }
                });
            }

            function loadStats() {
                fetch("/api/admin/stats", { headers: { "Authorization": `Bearer ${adminToken}` } })
                .then(r => r.json())
                .then(data => {
                    document.getElementById("statDbSize").innerText = `${data.size_mb} MB / ${data.max_mb} MB (${data.used_percent}%)`;
                    document.getElementById("statPing").innerText = `${data.ping_ms} ms`;
                    document.getElementById("statKeys").innerText = `${data.total_keys} Keys`;
                    document.getElementById("statUsers").innerText = `${data.total_users} Active`;
                });
            }

            function loadKeys() {
                fetch("/api/admin/keys", { headers: { "Authorization": `Bearer ${adminToken}` } })
                .then(r => r.json())
                .then(data => {
                    const tbody = document.getElementById("keysTableBody");
                    tbody.innerHTML = "";
                    data.forEach(item => {
                        let badgeClass = "badge-unused";
                        if (item.status === "ACTIVE") badgeClass = "badge-active";
                        if (item.status === "EXPIRED") badgeClass = "badge-expired";
                        if (item.status === "DISABLED") badgeClass = "badge-disabled";

                        tbody.innerHTML += `
                            <tr>
                                <td style="font-weight:bold; color:var(--cyan);">${item.key}</td>
                                <td>${item.file_name}</td>
                                <td>${item.duration_days} Days</td>
                                <td>${item.active_devices_count} / ${item.max_devices}</td>
                                <td><span class="badge ${badgeClass}">${item.status}</span></td>
                                <td>${item.created_at.split('T')[0]}</td>
                                <td>${item.expires_at ? item.expires_at.split('T')[0] : 'Not used'}</td>
                                <td>
                                    <button class="btn btn-success" style="padding:4px 8px; font-size:11px;" onclick="addDays('${item.key}')">+ Days</button>
                                    <button class="btn" style="padding:4px 8px; font-size:11px;" onclick="toggleDisable('${item.key}')">${item.is_disabled ? 'Enable' : 'Disable'}</button>
                                    <button class="btn btn-danger" style="padding:4px 8px; font-size:11px;" onclick="deleteKey('${item.key}')">Del</button>
                                </td>
                            </tr>
                        `;
                    });
                });
            }

            function loadFiles() {
                fetch("/api/admin/files", { headers: { "Authorization": `Bearer ${adminToken}` } })
                .then(r => r.json())
                .then(data => {
                    const tbody = document.getElementById("filesTableBody");
                    const select = document.getElementById("genFileSelect");
                    tbody.innerHTML = "";
                    select.innerHTML = "";

                    data.forEach(f => {
                        const typeBadge = f.external_url 
                            ? `<span class="badge badge-active" style="font-size:11px;">🌐 CDN: ${f.external_url.substring(0, 30)}...</span>` 
                            : `<span class="badge badge-unused" style="font-size:11px;">📁 Local / DB</span>`;

                        tbody.innerHTML += `
                            <tr>
                                <td>${f.id}</td>
                                <td style="font-weight:bold;">${f.file_name}</td>
                                <td>${typeBadge}</td>
                                <td>${f.uploaded_at.split('T')[0]}</td>
                                <td><button class="btn btn-danger" style="padding:4px 8px; font-size:11px;" onclick="deleteFile(${f.id})">Delete</button></td>
                            </tr>
                        `;
                        select.innerHTML += `<option value="${f.id}">${f.file_name} (ID: ${f.id})</option>`;
                    });
                });
            }

            function loadUsers() {
                fetch("/api/admin/app_users", { headers: { "Authorization": `Bearer ${adminToken}` } })
                .then(r => r.json())
                .then(data => {
                    const tApp = document.getElementById("appUsersTableBody");
                    if (tApp) {
                        tApp.innerHTML = "";
                        data.forEach(u => {
                            tApp.innerHTML += `<tr>
                                <td>${u.username}</td>
                                <td style="color:var(--green)">$${u.balance.toFixed(2)}</td>
                                <td>${u.role}</td>
                                <td>${u.created_at.split('.')[0]}</td>
                            </tr>`;
                        });
                    }
                }).catch(e => console.error(e));

                fetch("/api/admin/users", { headers: { "Authorization": `Bearer ${adminToken}` } })
                .then(r => r.json())
                .then(data => {
                    const tbody = document.getElementById("usersTableBody");
                    tbody.innerHTML = "";
                    data.forEach(u => {
                        const banBtn = u.is_banned 
                            ? `<button class="btn btn-success" style="padding:4px 8px; font-size:11px; margin-right:4px;" onclick="unbanUser('${u.device_id}')">UNBAN</button>`
                            : `<button class="btn btn-danger" style="padding:4px 8px; font-size:11px; margin-right:4px;" onclick="banUser('${u.device_id}')">BAN</button>`;

                        const muteBtn = u.is_muted
                            ? `<button class="btn btn-success" style="padding:4px 8px; font-size:11px;" onclick="unmuteUser('${u.device_id}')">UNMUTE</button>`
                            : `<button class="btn" style="padding:4px 8px; font-size:11px;" onclick="muteUser('${u.device_id}')">MUTE</button>`;

                        let userStatus = '<span class="badge badge-active">ACTIVE</span>';
                        if (u.is_banned) userStatus = '<span class="badge badge-expired">BANNED</span>';
                        else if (u.is_muted) userStatus = '<span class="badge badge-disabled">MUTED</span>';

                        tbody.innerHTML += `
                            <tr>
                                <td>${u.id}</td>
                                <td>${u.key}</td>
                                <td><code>${u.device_id}</code></td>
                                <td>${u.activated_at.split('T')[0]}</td>
                                <td>${userStatus}</td>
                                <td>${banBtn} ${muteBtn}</td>
                            </tr>
                        `;
                    });
                });
            }

            function openGenerateModal() { document.getElementById("generateModal").style.display = "flex"; }
            function closeGenerateModal() { document.getElementById("generateModal").style.display = "none"; }
            
            function onKeyTypeChange(val) {
                document.getElementById("fileSelectGroup").style.display = (val === "ADMIN") ? "none" : "block";
            }

            function submitGenerateKey() {
                const type = document.getElementById("genKeyType").value;
                const fileId = parseInt(document.getElementById("genFileSelect").value || 1);
                const days = parseInt(document.getElementById("genDays").value || 3);
                const devs = parseInt(document.getElementById("genDevices").value || 1);

                fetch("/api/admin/keys/generate", {
                    method: "POST",
                    headers: { "Content-Type": "application/json", "Authorization": `Bearer ${adminToken}` },
                    body: JSON.stringify({ key_type: type, file_id: fileId, duration_days: days, max_devices: devs })
                })
                .then(r => r.json())
                .then(data => {
                    if (data.status === "success") {
                        closeGenerateModal();
                        document.getElementById("createdKeyString").innerText = data.key;
                        document.getElementById("keyCreatedModal").style.display = "flex";
                        loadKeys();
                    }
                });
            }

            function copyKeyText() {
                const txt = document.getElementById("createdKeyString").innerText;
                navigator.clipboard.writeText(txt);
                alert("Key copied to clipboard!");
            }
            function closeKeyCreatedModal() { document.getElementById("keyCreatedModal").style.display = "none"; }

            let currentUploadXhr = null;
            let uploadStartTime = 0;

            function uploadFile() {
                const fileInput = document.getElementById("fileInput");
                if (!fileInput.files[0]) return alert("Select a file first!");

                const file = fileInput.files[0];
                const formData = new FormData();
                formData.append("file", file);

                const container = document.getElementById("uploadProgressContainer");
                const statusText = document.getElementById("uploadStatusText");
                const percentText = document.getElementById("uploadPercentText");
                const progressFill = document.getElementById("uploadProgressFill");
                const mbText = document.getElementById("uploadMBText");
                const speedText = document.getElementById("uploadSpeedText");
                const btnUpload = document.getElementById("btnUploadFile");
                const btnCancel = document.getElementById("btnCancelUpload");

                container.style.display = "block";
                btnUpload.disabled = true;
                btnCancel.style.display = "inline-block";
                statusText.innerText = "⚡ Uploading file: " + file.name;
                percentText.innerText = "0%";
                progressFill.style.width = "0%";
                mbText.innerText = "0.00 MB / " + (file.size / (1024 * 1024)).toFixed(2) + " MB";
                speedText.innerText = "0.0 MB/s";

                uploadStartTime = Date.now();
                currentUploadXhr = new XMLHttpRequest();

                currentUploadXhr.upload.onprogress = function(e) {
                    if (e.lengthComputable) {
                        const percent = Math.round((e.loaded / e.total) * 100);
                        const loadedMB = (e.loaded / (1024 * 1024)).toFixed(2);
                        const totalMB = (e.total / (1024 * 1024)).toFixed(2);
                        
                        const elapsedSec = (Date.now() - uploadStartTime) / 1000;
                        const speedMBs = elapsedSec > 0.1 ? (e.loaded / (1024 * 1024) / elapsedSec).toFixed(1) : "0.0";

                        progressFill.style.width = percent + "%";
                        percentText.innerText = percent + "%";
                        mbText.innerText = `${loadedMB} MB / ${totalMB} MB`;
                        speedText.innerText = `${speedMBs} MB/s`;

                        if (percent >= 100) {
                            statusText.innerText = "⚡ Upload complete! Processing & verifying on server...";
                            percentText.innerText = "100%";
                        }
                    }
                };

                currentUploadXhr.onload = function() {
                    btnUpload.disabled = false;
                    btnCancel.style.display = "none";
                    currentUploadXhr = null;

                    try {
                        const data = JSON.parse(this.responseText);
                        if (this.status === 200 && data.status === "success") {
                            statusText.innerText = `✅ File Uploaded Successfully! (ID #${data.file_id})`;
                            progressFill.style.width = "100%";
                            percentText.innerText = "100%";
                            fileInput.value = "";
                            loadFiles();
                            setTimeout(() => {
                                container.style.display = "none";
                            }, 5000);
                        } else {
                            statusText.innerText = "❌ Upload Failed: " + (data.detail || data.message || "Unknown error");
                            alert("Upload error: " + (data.detail || data.message || "Unknown error"));
                        }
                    } catch (err) {
                        statusText.innerText = "❌ Error processing server response";
                        alert("Error processing upload!");
                    }
                };

                currentUploadXhr.onerror = function() {
                    btnUpload.disabled = false;
                    btnCancel.style.display = "none";
                    currentUploadXhr = null;
                    statusText.innerText = "❌ Network connection error during upload!";
                    alert("Network error while uploading!");
                };

                currentUploadXhr.onabort = function() {
                    btnUpload.disabled = false;
                    btnCancel.style.display = "none";
                    currentUploadXhr = null;
                    statusText.innerText = "🛑 Upload cancelled.";
                    progressFill.style.width = "0%";
                    percentText.innerText = "0%";
                };

                currentUploadXhr.open("POST", "/api/admin/upload", true);
                currentUploadXhr.setRequestHeader("Authorization", `Bearer ${adminToken}`);
                currentUploadXhr.send(formData);
            }

            function cancelUpload() {
                if (currentUploadXhr) {
                    currentUploadXhr.abort();
                    currentUploadXhr = null;
                }
            }

            function addExternalFile() {
                const fname = document.getElementById("extFileName").value.trim() || "lib.zip";
                const furl = document.getElementById("extFileUrl").value.trim();
                if (!furl || !furl.startsWith("http")) return alert("Please enter a valid URL starting with https://");

                fetch("/api/admin/add_external_file", {
                    method: "POST",
                    headers: { "Content-Type": "application/json", "Authorization": `Bearer ${adminToken}` },
                    body: JSON.stringify({ file_name: fname, download_url: furl })
                })
                .then(r => r.json())
                .then(data => {
                    if (data.status === "success") {
                        alert("CDN / GitHub File Link Added Successfully!");
                        document.getElementById("extFileUrl").value = "";
                        loadFiles();
                    } else {
                        alert("Error adding link: " + (data.detail || "Unknown error"));
                    }
                });
            }

            function addExternalFile() {
                const fname = document.getElementById("extFileName").value.trim() || "lib.zip";
                const furl = document.getElementById("extFileUrl").value.trim();
                if (!furl || !furl.startsWith("http")) return alert("Please enter a valid URL starting with https://");

                fetch("/api/admin/add_external_file", {
                    method: "POST",
                    headers: { "Content-Type": "application/json", "Authorization": `Bearer ${adminToken}` },
                    body: JSON.stringify({ file_name: fname, download_url: furl })
                })
                .then(r => r.json())
                .then(data => {
                    if (data.status === "success") {
                        alert("CDN / GitHub File Link Added Successfully!");
                        document.getElementById("extFileUrl").value = "";
                        loadFiles();
                    } else {
                        alert("Error adding link: " + (data.detail || "Unknown error"));
                    }
                });
            }

            function deleteFile(fid) {
                if (!confirm("Are you sure you want to delete this file?")) return;
                fetch(`/api/admin/files/${fid}`, {
                    method: "DELETE",
                    headers: { "Authorization": `Bearer ${adminToken}` }
                })
                .then(r => r.json())
                .then(data => {
                    if (data.status === "success") {
                        alert("File deleted successfully!");
                        loadFiles();
                        loadKeys();
                    } else {
                        alert("Error deleting file!");
                    }
                });
            }

            function addDays(key) {
                const extra = prompt("Enter extra days to add:", "7");
                if (!extra) return;
                fetch("/api/admin/keys/add_days", {
                    method: "POST",
                    headers: { "Content-Type": "application/json", "Authorization": `Bearer ${adminToken}` },
                    body: JSON.stringify({ key: key, extra_days: parseInt(extra) })
                }).then(() => loadKeys());
            }

            function toggleDisable(key) {
                fetch("/api/admin/keys/toggle_disable", {
                    method: "POST",
                    headers: { "Content-Type": "application/json", "Authorization": `Bearer ${adminToken}` },
                    body: JSON.stringify({ key: key })
                }).then(() => loadKeys());
            }

            function deleteKey(key) {
                if (!confirm(`Delete key ${key}?`)) return;
                fetch(`/api/admin/keys/${key}`, {
                    method: "DELETE",
                    headers: { "Authorization": `Bearer ${adminToken}` }
                }).then(() => loadKeys());
            }

            function banUser(devId) {
                fetch("/api/admin/ban_user", {
                    method: "POST",
                    headers: { "Content-Type": "application/json", "Authorization": `Bearer ${adminToken}` },
                    body: JSON.stringify({ device_id: devId })
                }).then(() => loadUsers());
            }

            function unbanUser(devId) {
                fetch("/api/admin/unban_user", {
                    method: "POST",
                    headers: { "Content-Type": "application/json", "Authorization": `Bearer ${adminToken}` },
                    body: JSON.stringify({ device_id: devId })
                }).then(() => loadUsers());
            }

            function muteUser(devId) {
                fetch("/api/admin/mute_user", {
                    method: "POST",
                    headers: { "Content-Type": "application/json", "Authorization": `Bearer ${adminToken}` },
                    body: JSON.stringify({ device_id: devId })
                }).then(() => loadUsers());
            }

            function unmuteUser(devId) {
                fetch("/api/admin/unmute_user", {
                    method: "POST",
                    headers: { "Content-Type": "application/json", "Authorization": `Bearer ${adminToken}` },
                    body: JSON.stringify({ device_id: devId })
                }).then(() => loadUsers());
            }

            function loadAppUpdateSettings() {
                fetch("/api/app/update_check?current_version=999")
                .then(r => r.json())
                .then(data => {
                    document.getElementById("updForce").value = data.force_update ? "true" : "false";
                    document.getElementById("updCode").value = data.latest_version_code || 1;
                    document.getElementById("updName").value = data.latest_version_name || "1.0";
                    document.getElementById("updUrl").value = data.download_url || "";
                    document.getElementById("updNotes").value = data.release_notes || "";
                });
            }

            function saveAppUpdateSettings() {
                const payload = {
                    force_update: document.getElementById("updForce").value === "true",
                    latest_version_code: parseInt(document.getElementById("updCode").value) || 1,
                    latest_version_name: document.getElementById("updName").value.trim(),
                    download_url: document.getElementById("updUrl").value.trim(),
                    release_notes: document.getElementById("updNotes").value.trim()
                };

                fetch("/api/admin/set_update", {
                    method: "POST",
                    headers: { "Content-Type": "application/json", "Authorization": `Bearer ${adminToken}` },
                    body: JSON.stringify(payload)
                })
                .then(r => r.json())
                .then(data => {
                    if (data.status === "success") {
                        alert("✅ App Update settings saved and pushed successfully!");
                    } else {
                        alert("❌ Error: " + (data.detail || "Unknown error"));
                    }
                });
            }

            function loadOrgLibUrl() {
                fetch("/api/app/org_lib")
                .then(r => r.json())
                .then(data => {
                    if (data.url) document.getElementById("orgLibUrl").value = data.url;
                });
            }

            async function addPatchUrl() {
                const url = document.getElementById("patchUrlInput").value;
                if (!url) return alert("Enter URL");
                const fname = url.split('/').pop() || "patch.zip";
                try {
                    const res = await fetch("/api/admin/add_external_file", {
                        method: "POST",
                        headers: { "Content-Type": "application/json", "Authorization": `Bearer ${token}` },
                        body: JSON.stringify({ file_name: fname, download_url: url })
                    });
                    const data = await res.json();
                    if(data.status==="success") { alert("Added!"); fetchFiles(); } else alert("Error");
                } catch(e) {}
            }

            function saveOrgLibUrl() {
                const url = document.getElementById("orgLibUrl").value.trim();
                fetch("/api/admin/set_org_lib", {
                    method: "POST",
                    headers: { "Content-Type": "application/json", "Authorization": `Bearer ${adminToken}` },
                    body: JSON.stringify({ url: url })
                })
                .then(r => r.json())
                .then(data => {
                    if (data.status === "success") {
                        alert("✅ Original Lib URL saved successfully!");
                    } else {
                        alert("❌ Error saving URL");
                    }
                });
            }

            function loadVersionHistory() {
                fetch("/api/admin/version_history", { headers: { "Authorization": `Bearer ${adminToken}` } })
                .then(r => r.json())
                .then(data => {
                    const tbody = document.getElementById("versionHistoryBody");
                    tbody.innerHTML = "";
                    data.forEach(item => {
                        let isForce = item.force_update ? '<span style="color:var(--red);font-weight:bold;">YES</span>' : 'NO';
                        let dt = item.saved_at ? item.saved_at.split('.')[0].replace('T', ' ') : 'N/A';
                        tbody.innerHTML += `
                            <tr>
                                <td style="font-weight:bold; color:var(--cyan);">${item.latest_version_name}</td>
                                <td>v${item.latest_version_code}</td>
                                <td>${isForce}</td>
                                <td>${dt}</td>
                                <td style="max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${item.release_notes}</td>
                            </tr>
                        `;
                    });
                });
            }

            function checkFridayCleanup() {
                const now = new Date();
                if (now.getDay() === 5 && now.getHours() >= 9 && now.getHours() <= 10) {
                    const msg = document.getElementById("cleanupMsgText");
                    if (msg) {
                        msg.innerText = "⚠️ IT IS FRIDAY (9-10 AM)! Time to clear out old files! Delete all files?";
                        msg.style.color = "var(--red)";
                        msg.style.fontWeight = "bold";
                        
                        // Auto-Prompt to delete
                        setTimeout(() => {
                            if (confirm("⚠️ FRIDAY CLEANUP: Do you want to delete all expired/old files, including org lib?")) {
                                cleanupOldFiles();
                            }
                        }, 1000);
                    }
                }
            }

            function cleanupOldFiles() {
                if (!confirm("🚨 WARNING: Are you sure you want to DELETE ALL patches and the original lib URL? This cannot be undone!")) return;
                fetch("/api/admin/cleanup_files", {
                    method: "DELETE",
                    headers: { "Authorization": `Bearer ${adminToken}` }
                })
                .then(r => r.json())
                .then(data => {
                    if (data.status === "success") {
                        alert("✅ Cleanup successful! All files and org lib deleted.");
                        loadFiles();
                        loadOrgLibUrl();
                    } else {
                        alert("❌ Cleanup failed.");
                    }
                });
            }
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
