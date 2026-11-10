"""Respect Live — نقطة الدخول (نفس أمر التشغيل: uvicorn main:app)."""
import os

from app.main import app  # noqa: F401

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), proxy_headers=True, forwarded_allow_ips="*")
