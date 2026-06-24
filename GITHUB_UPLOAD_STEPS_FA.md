# راهنمای آپلود Clinical GraphRAG Pro روی GitHub

این نسخه برای GitHub پاک‌سازی شده است: `.git`، `.env`، دیتابیس‌های محلی، `.venv`، cacheها، فایل‌های macOS و خروجی‌های حجیم حذف شده‌اند.

## 1) قبل از هر چیز

اگر قبلاً فایل `.env` یا `backend/.env` را جایی آپلود کرده‌ای، کلیدهای داخل آن را revoke/rotate کن. در نسخه اصلی یک `GOOGLE_API_KEY` واقعی‌نما داخل `backend/.env` دیده شد.

## 2) ساخت Repository در GitHub

در GitHub یک repository جدید با نام زیر بساز:

```text
clinical-graphrag-pro
```

گزینه‌های README، .gitignore و License را در GitHub اضافه نکن، چون پروژه خودش این فایل‌ها را دارد.

## 3) دستورهای Terminal

داخل پوشه همین پروژه اجرا کن:

```bash
git init
git branch -M main
git add .
git commit -m "Initial clean portfolio release"
git remote add origin https://github.com/YOUR_USERNAME/clinical-graphrag-pro.git
git push -u origin main
```

به جای `YOUR_USERNAME` نام کاربری GitHub خودت را بگذار.

## 4) بعد از push

در GitHub این بخش‌ها را چک کن:

- تب Code: فایل‌های `.env`، `.venv`، `.db`، `.sqlite3` نباید وجود داشته باشند.
- تب Actions: اگر CI روشن شد، ممکن است تست‌ها اجرا شوند و خطا بدهند؛ این خطا لزوماً یعنی کد بد نیست، ممکن است وابستگی‌ها یا secretهای لازم تنظیم نشده باشند.
- README: لینک‌های `mohamad679` را به GitHub خودت تغییر بده.

## 5) اصلاح لینک‌های README و docs

بعد از ساخت repo، این دستور را در پروژه بزن:

```bash
python3 - <<'PY'
from pathlib import Path
old = 'https://github.com/mohamad679/clinical-graphrag-pro'
new = 'https://github.com/YOUR_USERNAME/clinical-graphrag-pro'
for p in [Path('README.md'), Path('docs/QUICKSTART.md'), Path('docs/SYSTEM_PAPER.md')]:
    if p.exists():
        txt = p.read_text(encoding='utf-8', errors='replace')
        p.write_text(txt.replace(old, new), encoding='utf-8')
PY

git add README.md docs/QUICKSTART.md docs/SYSTEM_PAPER.md
git commit -m "docs: update repository links"
git push
```

## 6) فایل‌های ممنوع برای commit

این‌ها را هرگز commit نکن:

```text
.env
backend/.env
backend/.venv/
*.db
*.sqlite3
uploads/
data/vector_store/*.faiss
data/vector_store/*.pkl
reports/release_artifacts/*.tar.gz
```
