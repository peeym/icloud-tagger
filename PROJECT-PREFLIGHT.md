# Project Preflight — שאלות שצריך לענות לפני שכותבים שורת קוד

> זה הקובץ שאמור להיות **בכותרת של כל פרוייקט** שעובדים עליו עם Claude Code.
> הוא לא מסמך תכנון. הוא **בדיקת רצינות** — אם אין תשובות לשאלות כאן, אנחנו עוד לא מוכנים להתחיל.
>
> **הציטוט המנחה (Brian Kernighan):** "Debugging is twice as hard as writing the code in the first place. So if you write code at the limit of your understanding, you can't debug it."
>
> אנחנו לא מפתחים. AI כותב את הקוד. לכן: **אם לא נוכל להסביר ולדבג כל שורה, אין לנו פרוייקט — יש לנו פצצה מתקתקת.**

---

## חלק 0 — Build vs Buy (הכי חשוב, וזה נשכח כל פעם)

לפני שמתחילים לבנות, **חובה** לענות:

- [ ] **למה אני בונה את זה מאפס במקום להשתמש במשהו קיים?**
  - האם בדקתי **ספציפית**: Airtable, Notion, HubSpot Free, Pipedrive, Retool, Softr, Bubble, Coda?
  - האם הבעיה שלי דורשת משהו שאף אחד מהם לא עושה? (אם כן — תכתוב למטה מה הדבר הספציפי)
  - האם אני מוכן לתחזק את הקוד הזה במשך **5 שנים**?
- [ ] **מה התקציב שלי לתחזוקה השנתית?** (אם זה $0 והפרוייקט הוא לא static — תחזור ל-Build vs Buy)
- [ ] **מה קורה אם אני לא יכול לתקן באג בעצמי?**
  - מי המפתח שיעזור? (כתוב שם או "אין")
  - עד כמה הפרוייקט קריטי? (אם פרודקשן ירד לשבוע — מה ההשלכות?)

---

## חלק 1 — תכלית ושימוש

- [ ] **מי המשתמשים?** (פנימי בלבד / לקוחות / כל העולם / משתמשים מאומתים)
- [ ] **כמה משתמשים מקסימום ב-12 חודשים הקרובים?** (10 / 100 / 1,000 / 100,000)
- [ ] **האם הם מקלידים מידע אישי? פיננסי? רגיש?**
- [ ] **האם המערכת מחויבת בחוקי פרטיות?** (GDPR / חוק הגנת הפרטיות הישראלי / HIPAA / PCI-DSS)
- [ ] **מה ההפסד אם המערכת תיפול לשעה? ליום? לשבוע?** (כסף / לקוחות / מוניטין)
- [ ] **מה ההפסד אם משתמש יראה מידע של משתמש אחר?**

---

## חלק 2 — Architecture (לפני שכותבים שורה)

- [ ] **Stack:** Astro / Next / Streamlit / Python script / אחר ___
- [ ] **DB:** Supabase / SQLite / Postgres / Airtable / אחר ___
- [ ] **Auth:** Supabase Auth / Custom / NextAuth / NONE — האם משתמשים נכנסים?
- [ ] **Hosting:** Vercel / Cloudflare / Railway / Streamlit Cloud / Server שלי
- [ ] **Background Jobs:** האם יש? (Cron / Queue / Webhook handlers) — איפה הם רצים?
- [ ] **קבצים:** איפה נשמרים? (Supabase Storage / S3 / DB blob — מה הגודל המקסימלי?)
- [ ] **מיילים:** מי שולח? (Resend / SendGrid / שרת SMTP) — מה ה-Rate Limit שלי?
- [ ] **שליחויות חיצוניות:** (CRM, WhatsApp, Make.com) — מה קורה אם הן נופלות?

---

## חלק 3 — Security Checklist (לפני Production)

### אם המערכת מקבלת קלט מ-internet:

- [ ] **Rate Limiting** על כל endpoint ציבורי (במיוחד login, register, contact, lead)
- [ ] **Bot Protection** (Cloudflare Turnstile / hCaptcha) על טפסי לידים
- [ ] **Validation בצד השרת** — אסור להסתמך על client-side בלבד
- [ ] **Sanitization** של הקלט לפני שמירה ב-DB ולפני הצגה
- [ ] **CORS** מוגדר במפורש (לא wildcard `*`)
- [ ] **CSRF Protection** אם משתמשים ב-cookies לאימות
- [ ] **Headers בטיחות:** CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy

### אם יש משתמשים ואימות:

- [ ] **Password Reset Flow** מאובטח — לא לחשוף אם email קיים
- [ ] **Account Enumeration** — login error לא מגלה "user not found" לעומת "wrong password"
- [ ] **Session expiry** מוגדר במפורש (לא forever)
- [ ] **Refresh tokens** לא בלוקאל סטורג' — ב-httpOnly cookie
- [ ] **MFA** אופציונלי (במיוחד למשתמשי admin)
- [ ] **RLS** ב-Supabase מוגדר על **כל טבלה** — בדקתי שזה עובד?
- [ ] **Service role key** **לעולם** לא ב-client bundle — בדקתי ב-build output?
- [ ] **Admin routes** מוגנים ב-middleware, לא רק ב-UI

### Secrets:

- [ ] **אין secrets ב-git** (לא בהיסטוריה!)
- [ ] **`.gitignore` כולל** `.env`, `credentials*`, `*.key`
- [ ] **Vercel/Cloudflare ENV** מסודר — production VS preview ENV נפרדים
- [ ] **Rotation policy** — מה אם key דולף?
- [ ] **No secret values in tool args** (Claude Code rule — sed-from-inbox)

---

## חלק 4 — Performance Checklist (כי "עובד אצלי" זה לא הבדיקה)

### על UI Inputs:

- [ ] **Debounce** על search/autocomplete/typeahead (300ms+)
- [ ] **Throttle** על scroll events
- [ ] **Loading states** על כל פעולה אסינכרונית
- [ ] **Error states** מוצגים — לא רק שתיקה אחרי כשל

### על DB:

- [ ] **Indexes** על כל עמודה שמסננים לפיה (`WHERE`, `ORDER BY`, `JOIN`)
- [ ] **N+1 Queries** — בדקתי? (loop שעושה query בכל איטרציה = N+1)
- [ ] **`SELECT *` רק כשצריך** — לא להחזיר עמודות לא נחוצות
- [ ] **Pagination** — לא לטעון את כל ה-DB ל-UI
- [ ] **Connection pooling** מתאים ל-serverless (Supabase pooler או PgBouncer)

### Caching:

- [ ] **CDN cache** (Cloudflare) על assets סטטיים
- [ ] **API response cache** עם TTL מתאים — מה משתנה? כמה זמן?
- [ ] **Cache invalidation strategy** — מתי חייבים לפסול?

---

## חלק 5 — Data Integrity (כי שלמות נתונים = אמון)

- [ ] **Idempotency** על כל endpoint שכותב כסף או יוצר רשומות (Idempotency-Key header)
- [ ] **Transactions** על כל פעולה שכוללת 2+ writes שצריכים להצליח יחד
- [ ] **Race conditions** — מה קורה אם 2 משתמשים עושים אותו דבר במקביל?
- [ ] **Optimistic concurrency** (version column) על שדות שעורכים יחד
- [ ] **Validation** של forms גם בצד השרת — לא רק client
- [ ] **Deduplication** — אותו מייל/טלפון לא יוצר 2 רשומות
- [ ] **Soft delete** או hard delete? (אחיד בכל הטבלאות)
- [ ] **Foreign key cascading** — מה קורה כשמוחקים parent record?

---

## חלק 6 — Observability (כי בלי לראות = בלי לדעת = בלי לתקן)

- [ ] **Structured logging** (JSON, עם request_id) — לא רק `console.log`
- [ ] **Error tracking** — Sentry / Logtail / לפחות טבלת errors ב-DB
- [ ] **Health check endpoint** (`/api/health`) שבודק DB + תלויות
- [ ] **Uptime monitor** (UptimeRobot / Pingdom) על פרוד
- [ ] **Alerts** למייל/טלגרם על errors קריטיים
- [ ] **Audit log** על פעולות רגישות (auth, payments, admin actions)
- [ ] **לא** להסתיר כשלים ב-`console.warn` ולשכוח

---

## חלק 7 — Operability (Deploy, Rollback, Recovery)

- [ ] **CI/CD** מוגדר — לא רק push ידני
- [ ] **Rollback strategy** — איך מחזירים גרסה קודמת תוך 5 דקות?
- [ ] **Database migrations** — מסודרות, ניתנות להחזרה
- [ ] **Backups** — אוטומטיים? נבדקו לאחרונה?
- [ ] **Restore tested** — באמת ניסיתי לשחזר?
- [ ] **Env var drift** — dev/preview/prod מסונכרנים?
- [ ] **Cache busting** עובד אחרי deploy?

---

## חלק 8 — שאלות AI-ספציפיות (שלא לשכוח)

- [ ] **האם אני יכול להסביר כל קובץ במערכת?** (אם לא → עוצרים)
- [ ] **האם יש קוד שכתב Claude שלא ביקרתי?** (יש בו שגיאות "מובנות מאליהן")
- [ ] **האם יש TODO/FIXME בפרוד?** (כן → סכנה)
- [ ] **האם יש placeholder values שנשארו?** (`PASTE_HERE`, `your-api-key-here`, `lorem ipsum`)
- [ ] **האם תוכן הקוד תואם להערות?** (AI לפעמים כותב תיאור שונה ממה שעושה)
- [ ] **האם המערכת בודקת case שלא צוין ב-prompt?** (null, empty, unicode, רוסית, אמוג'י, RTL)
- [ ] **האם הבדיקה היא רק "זה ירץ"?** (חייב גם: "מה קורה כש-1000 משתמשים")

---

## חלק 9 — שאלות ישראל-ספציפיות

- [ ] **RTL** — האם ה-UI עובד בעברית כהלכה? (לא רק `dir="rtl"` באלמנט)
- [ ] **טלפונים** — מנורמלים לפורמט אחיד? (+972 vs 0501234567)
- [ ] **תז"** — אם נשמר, יש validation (אלגוריתם בדיקת ספרת ביקורת)?
- [ ] **חוק הגנת הפרטיות** — האם יש מאגר רשום אם נדרש? תנאי שימוש? מדיניות פרטיות?
- [ ] **חוק הספאם** — opt-in מתועד? לחיצת unsubscribe עובדת?
- [ ] **חשבונית** — אם מקבלים תשלום, יש פתרון ירוק (Greeninvoice / Hashavshevet API)?
- [ ] **מע"מ** — מחושב נכון בכל המקומות? (כרגע 17%)

---

## חלק 10 — Pre-Launch Final Gate

לפני שהפרוייקט יוצא לפרוד:

- [ ] **Load test** עשיתי? (לפחות k6 או artillery על endpoints קריטיים)
- [ ] **Security audit** עשיתי? (לפחות OWASP Top 10 checklist + הגלוי לעיל)
- [ ] **Backup tested** ניסיתי לשחזר ב-staging?
- [ ] **Rollback tested** הרצתי deploy + rollback ב-staging?
- [ ] **Documentation** — README ברור: איך מריצים, איך עושים deploy, איך מתקנים בעיות נפוצות
- [ ] **Runbook** — מה עושים אם הדף קורס ב-3 לפנות בוקר? (טופס פעולה כתוב!)
- [ ] **Privacy/Terms** קיימים ומחוברים?

---

## הערה אחרונה

הצ'קליסט הזה לא נועד להבהיל. הוא נועד **להגן עליך**.

אם פרוייקט מסוים זקוק רק ל-30% מזה — מצוין. תסמן בלי משוב מה רלוונטי ומה לא.
אבל **אסור לדלג** על שאלות הסקשן 0 (Build vs Buy) ועל שאלות סקשן 9 (Israeli compliance).

---

> **מי שדורך על מוקש כי לא קרא צ'קליסט — הוא לא ויב-קודר. הוא קרבן של ויב-קוד.**
