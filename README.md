# Respect Live

نظام احترافي لمراقبة قنوات البث — كيك + يوتيوب + تيليجرام + ديسكورد.

---

## ✨ الميزات

### 📡 مراقبة تلقائية
- **كيك**: فحص كل 90 ثانية، إشعار فوري عند بدء بث
- **يوتيوب**: فحص كل 5 دقائق، إشعار عند نشر فيديو جديد
- **تيليجرام**: جاهز لاستقبال أي قناة أو مجموعة

### 🤖 بوت ديسكورد
- يقرأ أي روم تحدده (`DISCORD_WATCH_CHANNELS`)
- يميّز المصدر تلقائياً: **تويتر** / **يوتيوب** / **عام**
- منع تكرار مضمون (لا يرسل نفس الرسالة مرتين)
- قوالب منفصلة لكل مصدر
- حماية من الحلقات (يتجاهل رسائل البوتات العادية)

### 🎨 تخصيص
- قوالب مخصصة لكل قناة ولكل مصدر
- ألوان وثيمات، شعار مخصص
- حدود قنوات لكل مستخدم

### 🔒 حماية
- PBKDF2 (100,000 دورة) لكلمات المرور
- Rate limiting متعدد الطبقات
- سجل أمني (5000 حدث)
- تحديد سيرفرات ديسكورد المسموحة
- إبطال الجلسات تلقائياً عند تغيير كلمة المرور

---

## 🚀 التشغيل المحلي

```bash
# 1. انسخ المتغيرات
cp .env.example .env
nano .env  # عدّل القيم

# 2. ثبّت المكتبات
pip install -r requirements.txt

# 3. شغّل
python main.py
```

افتح: http://localhost:8000

---

## 📦 النشر على Railway — خطوة بخطوة

### المرحلة 1: GitHub

```bash
# في مجلد المشروع
git init
git add .
git commit -m "Initial commit"

# أنشئ مستودعاً على GitHub ثم:
git branch -M main
git remote add origin https://github.com/USERNAME/respect-live.git
git push -u origin main
```

### المرحلة 2: Railway

1. اذهب إلى [railway.app](https://railway.app) → **Login with GitHub**
2. **New Project** → **Deploy from GitHub repo**
3. اختر مستودع `respect-live`
4. سيبدأ البناء تلقائياً

### المرحلة 3: Volume (مهم جداً — لحفظ قاعدة البيانات)

1. في مشروعك → **+ Create** → **Volume**
2. الإعدادات:
   - **Volume Name**: `data`
   - **Mount Path**: `/app/data`
3. اذهب إلى الخدمة → **Variables** → أضف:
   ```
   DB_PATH=/app/data/respect.db
   ```

> ⚠️ بدون Volume، كل Redeploy يمسح كل شيء.

### المرحلة 4: Variables (المتغيرات)

في خدمة الويب → **Variables** → **New Variable** → أضف واحداً واحداً:

| المتغير | القيمة |
|---|---|
| `ADMIN_USERNAME` | `admin` |
| `ADMIN_PASSWORD` | كلمة قوية |
| `SESSION_SECRET` | 64 حرف hex |
| `DISCORD_BOT_TOKEN` | من لوحة المطورين |
| `DISCORD_WATCH_CHANNELS` | `112233...,445566...` |
| `DISCORD_ALLOWED_GUILDS` | IDs سيرفراتك |
| `SITE_NAME` | `Respect Live` |
| `DB_PATH` | `/app/data/respect.db` |
| `TELEGRAM_TOKEN` | (عند تجهيزه) |

### المرحلة 5: النطاق

1. **Settings** → **Networking** → **Generate Domain**
2. سيعطيك رابط مثل: `respect-live-production.up.railway.app`
3. **Settings** → **Networking** → **Custom Domain** → أضف دومينك

في DNS مزودك:
- **CNAME** `@` → `xxxx.up.railway.app`
- أو **A** → IP من Railway

---

## 🤖 إعداد بوت ديسكورد

### 1. أنشئ البوت

1. اذهب إلى [discord.com/developers/applications](https://discord.com/developers/applications)
2. **New Application** → اسم التطبيق
3. **Bot** → **Reset Token** → انسخه
4. ضعه في `DISCORD_BOT_TOKEN`

### 2. فعّل Intents

في **Bot** → **Privileged Gateway Intents**:
- ✅ **Presence Intent** (اختياري)
- ✅ **Server Members Intent** (اختياري)
- ✅ **Message Content Intent** ← **مهم جداً (إجباري)**

### 3. ادعُ البوت

في **OAuth2** → **URL Generator**:
- **Scopes**: `bot`
- **Bot Permissions**:
  - `Read Messages`
  - `Read Message History`
  - `Send Messages` (اختياري)
  - `Embed Links`

انسخ الرابط وافتحه، اختر السيرفر، أضف البوت.

### 4. احصل على IDs

- **Server ID**: كليك يمين على السيرفر → **Copy Server ID** (فعّل Developer Mode أولاً من إعدادات المستخدم)
- **Channel ID**: كليك يمين على الروم → **Copy Channel ID**

### 5. ضعها في Variables

- `DISCORD_WATCH_CHANNELS`: IDs الرومات (مفصولة بـ `,`)
- `DISCORD_ALLOWED_GUILDS`: IDs السيرفرات (مفصولة بـ `,`)

### 6. اربط من الموقع

1. سجّل دخولك في موقعك
2. تبويب **Discord**
3. **ربط روم جديد** → اختر الروم
4. اختر القالب (أو اتركه فارغاً للافتراضي)
5. احفظ

---

## 🎯 كيف يعمل الجسر

```
[بوت تويتر] → [روم ديسكورد] → [Respect Live Bot] → [قنوات تيليجرام]
[بوت يوتيوب] ↗
```

1. أي بوت (تويتر/يوتيوب/غيره) يرسل رسالة في الروم المراقب
2. البوت يلتقطها ويميّز المصدر
3. يطبّق القالب المناسب
4. يرسل لقنوات تيليجرام المستخدم

**منع التكرار**: جدول `discord_seen` يحفظ `message_id`. نفس الرسالة لا تُرسل مرتين أبداً حتى بعد إعادة التشغيل.

---

## 🛡️ تأمين البوت العام

| الحماية | الآلية |
|---|---|
| **Bots ignored** | لا يلتقط رسائل البوتات العادية (فقط embeds) |
| **DMs ignored** | لا يستقبل رسائل خاصة |
| **Guild whitelist** | `DISCORD_ALLOWED_GUILDS` — السيرفرات المسموحة فقط |
| **Channel whitelist** | `DISCORD_WATCH_CHANNELS` — الرومات المسموحة فقط |
| **Rate limit** | 30 رسالة/دقيقة لكل مستخدم |
| **Dedup** | `message_id` UNIQUE في DB |
| **Intents مقيدة** | فقط ما يحتاجه البوت |

### 🚨 إذا انكشف التوكن

1. اذهب للوحة المطورين → **Bot** → **Reset Token**
2. حدّث `DISCORD_BOT_TOKEN` في Railway
3. ✅ تم — يعمل تلقائياً

---

## 📁 هيكل المشروع

```
respect-live/
├── main.py             ← FastAPI + Discord Bot + كل المنطق
├── index.html          ← الواجهة الكاملة
├── requirements.txt    ← المكتبات
├── Procfile            ← أمر التشغيل
├── runtime.txt         ← إصدار Python
├── .env.example        ← نموذج المتغيرات
├── .gitignore          ← ملفات مُستثناة
└── README.md           ← هذا الملف
```

**6 ملفات فقط.** نظيف وسهل.

---

## 🔧 أوامر مساعدة

### توليد SESSION_SECRET
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### فحص حالة البوت
```bash
curl https://your-app.up.railway.app/health
# {"ok":true,"discord_ready":true,"watching":3}
```

### عرض السجلات
في Railway: **Deployments** → اختر البناء → **View Logs**

---

## 📞 الدعم

- وثائق Discord.py: https://discordpy.readthedocs.io
- وثائق FastAPI: https://fastapi.tiangolo.com
- وثائق Railway: https://docs.railway.app

---

**بُني بواسطة Respect Live**
