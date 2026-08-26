# gunicorn 3.0+ — production config for enprizon-salary
# KILWA_SECRET_KEY: Flask session secret — MUST be set in production.
#   - Production (ENV=production or KILWA_SECRET_KEY_REQUIRED=1) without it:
#     app.py fail-fasts with RuntimeError("KILWA_SECRET_KEY must be set").
#     Set it via systemd Environment= or export before launch; value must be
#     stable across restarts or all sessions are invalidated.
#   - Development (no ENV/KILWA_SECRET_KEY_REQUIRED): app.py auto-generates
#     and pins a key to data/.kilwa_secret (gitignored) so the second restart
#     reuses the same key and keeps login sessions alive.
#   - data/flask_session (if filesystem sessions are enabled) must survive
#     restarts — do not clean data/ on deploy/restart.
bind = '127.0.0.1:8081'
workers = 1
threads = 2
timeout = 120
accesslog = '/root/enprizon-salary/access.log'
errorlog = '/root/enprizon-salary/error.log'
loglevel = 'info'
