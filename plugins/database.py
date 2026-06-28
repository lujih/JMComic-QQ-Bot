import sqlite3
import random
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

_db_lock = threading.RLock()
_DB_DIR = Path(__file__).parent.parent / "data"
_DB_PATH = _DB_DIR / "bot.db"

_UTC8 = timezone(timedelta(hours=8))


def _today_str() -> str:
    return datetime.now(_UTC8).strftime('%Y-%m-%d')


def _yesterday_str() -> str:
    return (datetime.now(_UTC8) - timedelta(days=1)).strftime('%Y-%m-%d')


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    _DB_DIR.mkdir(parents=True, exist_ok=True)
    with _get_conn() as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id  INTEGER NOT NULL,
                group_id INTEGER NOT NULL,
                points   INTEGER NOT NULL DEFAULT 0,
                daily_free  INTEGER NOT NULL DEFAULT 3,
                free_today  INTEGER NOT NULL DEFAULT 0,
                last_download_date TEXT,
                total_downloads INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, group_id)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS checkins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id  INTEGER NOT NULL,
                group_id INTEGER NOT NULL,
                checkin_date TEXT NOT NULL,
                streak  INTEGER NOT NULL DEFAULT 1,
                points_earned INTEGER NOT NULL DEFAULT 0,
                UNIQUE(user_id, group_id, checkin_date)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS config (
                group_id INTEGER NOT NULL,
                key   TEXT NOT NULL,
                value TEXT NOT NULL,
                PRIMARY KEY (group_id, key)
            )
        ''')
        conn.commit()


def _fetchone(sql: str, params=()) -> dict | None:
    with _get_conn() as conn:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None


def _execute(sql: str, params=()):
    with _get_conn() as conn:
        conn.execute(sql, params)
        conn.commit()


def ensure_user(user_id: int, group_id: int) -> dict:
    with _db_lock:
        user = _fetchone(
            'SELECT * FROM users WHERE user_id=? AND group_id=?',
            (user_id, group_id)
        )
        if user:
            return user
        today = _today_str()
        _execute(
            'INSERT INTO users (user_id, group_id, points, daily_free, free_today, '
            'last_download_date, total_downloads, created_at, is_admin) '
            'VALUES (?,?,0,3,0,?,0,?,0)',
            (user_id, group_id, today, today)
        )
        return {
            'user_id': user_id, 'group_id': group_id, 'points': 0,
            'daily_free': 3, 'free_today': 0, 'last_download_date': today,
            'total_downloads': 0, 'is_admin': 0
        }


def do_checkin(user_id: int, group_id: int) -> dict:
    with _db_lock:
        user = ensure_user(user_id, group_id)
        today = _today_str()

        existing = _fetchone(
            'SELECT * FROM checkins WHERE user_id=? AND group_id=? AND checkin_date=?',
            (user_id, group_id, today)
        )
        if existing:
            return {
                'ok': True,
                'already': True,
                'streak': existing['streak'],
                'total_points': user['points'],
                'msg': (
                    f"ℹ️ 你今天已签到\n"
                    f"🔥 连续签到 {existing['streak']} 天\n"
                    f"💰 当前积分: {user['points']}"
                )
            }

        yesterday = _yesterday_str()
        last = _fetchone(
            'SELECT * FROM checkins WHERE user_id=? AND group_id=? AND checkin_date=?',
            (user_id, group_id, yesterday)
        )
        streak = (last['streak'] + 1) if last else 1

        base = random.randint(5, 99)
        extra = 0
        bonus = ''
        if streak == 7:
            extra = 10
            bonus = f'\n🔥 连续签到 7 天，额外 +10 积分'
        elif streak == 30:
            extra = 30
            bonus = f'\n🔥 连续签到 30 天，额外 +30 积分'

        total = base + extra

        _execute(
            'INSERT INTO checkins (user_id, group_id, checkin_date, streak, points_earned) '
            'VALUES (?,?,?,?,?)',
            (user_id, group_id, today, streak, total)
        )
        _execute(
            'UPDATE users SET points=points+? WHERE user_id=? AND group_id=?',
            (total, user_id, group_id)
        )

        new_points = user['points'] + total

        return {
            'ok': True,
            'already': False,
            'streak': streak,
            'total_points': new_points,
            'msg': (
                f"✅ 签到成功！+{base} 积分"
                f"{bonus}"
                f"\n🔥 连续签到 {streak} 天"
                f"\n💰 当前积分: {new_points}"
            )
        }


def use_download_quota(user_id: int, group_id: int) -> dict:
    with _db_lock:
        user = ensure_user(user_id, group_id)
        today = _today_str()

        if user['last_download_date'] != today:
            free_today = 0
        else:
            free_today = user['free_today']

        daily_free = int(get_config(group_id, 'daily_free', '3'))
        cost = int(get_config(group_id, 'download_cost', '5'))

        if free_today < daily_free:
            _execute(
                'UPDATE users SET free_today=?, last_download_date=?, '
                'total_downloads=total_downloads+1 '
                'WHERE user_id=? AND group_id=?',
                (free_today + 1, today, user_id, group_id)
            )
            return {
                'ok': True,
                'msg': f'📊 免费 ({free_today + 1}/{daily_free})',
            }

        if user['points'] >= cost:
            _execute(
                'UPDATE users SET points=points-?, last_download_date=?, '
                'total_downloads=total_downloads+1 '
                'WHERE user_id=? AND group_id=?',
                (cost, today, user_id, group_id)
            )
            new_points = user['points'] - cost
            return {
                'ok': True,
                'msg': f'💰 扣除 {cost} 积分（剩余 {new_points} 积分）',
            }

        return {
            'ok': False,
            'msg': (
                f"❌ 今日免费已用完，积分不足（{user['points']} < {cost}）\n"
                f"💡 发送 /sign 签到获取积分"
            ),
        }


def get_config(group_id: int, key: str, default: str = '') -> str:
    with _db_lock:
        row = _fetchone(
            'SELECT value FROM config WHERE group_id=? AND key=?',
            (group_id, key)
        )
        return row['value'] if row else default


def set_config(group_id: int, key: str, value: str):
    with _db_lock:
        _execute(
            'INSERT OR REPLACE INTO config (group_id, key, value) VALUES (?,?,?)',
            (group_id, key, value)
        )


def vacuum_db():
    with _db_lock:
        conn = sqlite3.connect(str(_DB_PATH))
        try:
            conn.execute('VACUUM')
        finally:
            conn.close()


init_db()
