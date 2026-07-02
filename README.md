# ENPRIZON LINDI — Salary System

Flask-based salary calculation system for ENPRIZON LINDI. Upload Excel attendance/production data, run automatic five-track salary computation, and review results in a single-page web UI.

Deployed on Alibaba Cloud Singapore (47.236.187.33) with Flask + Gunicorn + Nginx reverse proxy.

## Quick Start (Local)

```bash
pip install -r requirements.txt   # flask, openpyxl, pandas
python3 app.py                    # opens at http://localhost:8080+
```

Or via the helper script:

```bash
./start.sh start   # foreground
./start.sh bg      # background
./start.sh stop    # kill (scans ports 8080-8089)
```

Default login: `user` / `qweasd` (viewer role).

## How It Works

**Input:** Place `.xlsx` files in `data/source/`. The system auto-detects five file types by sheet name:

| File | Purpose |
|------|---------|
| Main attendance + production | Shift production (D/N), driller teams, daily wages |
| Address book (通讯录) | Employee roster with department and account IDs |
| Advance (预支) | Cash advance records |
| NSSF SDL list | Social security enrollment data |
| Crush team | Crushing production data |

**Pipeline:** Excel parsing → name matching (address book indexed) → five-track salary calculation → verification → cached in memory → served via API.

**Five salary tracks** (mutually exclusive per employee per day):

| Track | Logic |
|-------|-------|
| Underground piece rate | Daily production × unit price ÷ workers, split equally |
| Driller piece rate | Daily production × unit price ÷ (members + 1 captain), captain gets ×2 |
| Crushing piece rate | Bags × 300 TZS ÷ workers |
| Daily wage | Daily rate × attendance days |
| Monthly salary | Monthly base ÷ 26 × days worked (capped at 26) |

Net salary = Gross + Bonus + Driver Allowance − Advance − NSSF (10%) − Penalties

## Deployment

```bash
# On server (root@47.236.187.33:22222)
git pull
systemctl restart enprizon-salary

# Or one-step shortcut
save-salary "commit message"
```

Production runs Gunicorn with `workers=1` (SQLite constraint), `threads=2`, `timeout=120`.

### Environment Variables

| Variable | Purpose |
|----------|---------|
| `KILWA_SECRET_KEY` | Flask session secret. Without it, sessions reset on every restart. |
| `KILWA_SCRIPT_NAME` | Nginx sub-path prefix (e.g. `/salary`) |

## Database

SQLite at `data/kilwa.db` (gitignored). 11 tables: employees, overrides, attendance_overrides, settings, monthly_data, audit_log, shift_additions, driller_additions, bonus_penalties, dismissed_employees, admin_users.

**Never use `git stash drop`** — this caused an unrecoverable data loss on 2026-06-28.

## Testing

No automated test suite. Manual testing uses database swap isolation:

```bash
bash test-workflow.sh start    # create test DB from backup
bash test-workflow.sh swap     # swap test DB into production slot
# ... test in browser ...
bash test-workflow.sh restore  # restore production DB
bash test-workflow.sh clean    # remove test DB
```

## Project Structure

```
├── app.py                  # Flask app, routes, data pipeline orchestration (~2458 lines)
├── core/
│   ├── calculator.py       # Five-track salary engine (~1221 lines)
│   ├── parser.py           # Excel parsing (shift/driller/crush sheets)
│   ├── namematch.py        # Name normalization + address book index
│   ├── database.py         # SQLite ORM (~623 lines)
│   ├── verification.py     # Dual-path salary reconciliation
│   ├── addressbook.py      # Address book Excel parser
│   ├── advance.py          # Advance records parser
│   ├── nssf.py             # NSSF social security parser
│   ├── pricing.py          # Unit price config proxy
│   └── exceptions.py       # Override/exception loader
├── templates/
│   └── index.html          # Single-file SPA (~2488 lines, 6 tabs)
├── static/
│   ├── css/style.css       # Dark industrial theme (~1338 lines)
│   └── js/
│       ├── i18n.js         # Chinese/English i18n (~864 lines)
│       ├── chart.umd.min.js
│       └── chartjs-plugin-datalabels.min.js
├── backup.sh               # Server daily backup (30-day retention)
├── restore.sh              # Server stop → restore → restart
├── start.sh                # Local dev launcher
├── test-workflow.sh         # Test DB isolation workflow
└── gunicorn.conf.py        # Production config (1 worker, 127.0.0.1:8081)
```

## License

Internal use only.
