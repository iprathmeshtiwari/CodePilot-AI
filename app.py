import hashlib
import os
import secrets
import sqlite3
import uuid
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv
from openai import OpenAI

# ===================== ENVIRONMENT CONFIG =====================

load_dotenv(override=True)

api_key = os.getenv("NEBIUS_API_KEY")
model = os.getenv("NEBIUS_MODEL") or "nvidia/Nemotron-3_5-Lightning"
base_url = os.getenv("NEBIUS_BASE_URL") or "https://api.tokenfactory.nebius.com/v1"

st.set_page_config(
    page_title="CodePilot AI — Intelligent Coding Workspace",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ===================== DATABASE & PERSISTENCE =====================

DB_FILE = "codepilot_auth.db"

def init_auth_db():
    """Initializes the SQLite database with user auth, preferences, and persistent chat storage."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    # 1. Users table with onboarding tracking
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            onboarded INTEGER DEFAULT 0
        )
    """)
    conn.commit()

    # Safe migration: ensure 'onboarded' column exists for existing databases
    c.execute("PRAGMA table_info(users)")
    user_columns = [col[1] for col in c.fetchall()]
    if "onboarded" not in user_columns:
        c.execute("ALTER TABLE users ADD COLUMN onboarded INTEGER DEFAULT 0")
        conn.commit()
        # Mark pre-existing accounts as onboarded so existing users aren't interrupted
        c.execute("UPDATE users SET onboarded = 1 WHERE onboarded = 0")
        conn.commit()

    # 2. User preferences table
    c.execute("""
        CREATE TABLE IF NOT EXISTS user_preferences (
            username TEXT PRIMARY KEY,
            sidebar_open INTEGER DEFAULT 1,
            active_mode TEXT DEFAULT '💬 General',
            temperature REAL DEFAULT 0.7,
            stream_mode INTEGER DEFAULT 1,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    # 3. Persistent chats table
    c.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            chat_id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            title TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    # 4. Persistent messages table
    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(chat_id) REFERENCES chats(chat_id) ON DELETE CASCADE
        )
    """)
    conn.commit()

    # Seed demo account if database is fresh
    c.execute("SELECT COUNT(*) FROM users")
    if c.fetchone()[0] == 0:
        salt = secrets.token_hex(16)
        pwd_hash = hashlib.pbkdf2_hmac(
            "sha256", "demo123".encode("utf-8"), bytes.fromhex(salt), 100000
        ).hex()
        # Demo account has onboarded = 1 so demo testers start directly in workspace
        c.execute(
            "INSERT INTO users (username, password_hash, salt, onboarded) VALUES (?, ?, ?, 1)",
            ("demo", pwd_hash, salt),
        )
        conn.commit()

    conn.close()

def hash_password(password: str, salt: str = None) -> tuple[str, str]:
    if not salt:
        salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), 100000
    ).hex()
    return hashed, salt

def register_user(username: str, password: str) -> tuple[bool, str]:
    username = username.strip()
    if not username:
        return False, "Username cannot be empty."
    if len(username) < 3:
        return False, "Username must be at least 3 characters."
    if len(password) < 4:
        return False, "Password must be at least 4 characters."

    hashed, salt = hash_password(password)
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        # New users start with onboarded = 0 for the one-time onboarding tour
        c.execute(
            "INSERT INTO users (username, password_hash, salt, onboarded) VALUES (?, ?, ?, 0)",
            (username, hashed, salt),
        )
        # Initialize default user preferences
        c.execute(
            "INSERT OR REPLACE INTO user_preferences (username, sidebar_open, active_mode, temperature, stream_mode) VALUES (?, 1, '💬 General', 0.7, 1)",
            (username,)
        )
        conn.commit()
        conn.close()
        return True, "Account created successfully! Please sign in to launch your workspace."
    except sqlite3.IntegrityError:
        return False, "Username already exists. Please choose another."
    except Exception as e:
        return False, f"Registration error: {e}"

def verify_credentials(username: str, password: str) -> tuple[bool, str]:
    username = username.strip()
    if not username or not password:
        return False, "Please enter both username and password."

    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute(
            "SELECT password_hash, salt FROM users WHERE LOWER(username) = LOWER(?)",
            (username,),
        )
        row = c.fetchone()
        conn.close()

        if not row:
            return False, "Invalid username or password."

        stored_hash, salt = row
        hashed, _ = hash_password(password, salt)

        if secrets.compare_digest(stored_hash, hashed):
            return True, "Login successful!"
        return False, "Invalid username or password."
    except Exception as e:
        return False, f"Authentication error: {e}"

def is_user_onboarded(username: str) -> bool:
    """Checks whether the user has completed their one-time onboarding."""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT onboarded FROM users WHERE LOWER(username) = LOWER(?)", (username,))
        row = c.fetchone()
        conn.close()
        if row and row[0] is not None:
            return bool(row[0])
        return True
    except Exception:
        return True

def set_user_onboarded(username: str, onboarded: int = 1):
    """Marks onboarding as persistently completed in the database."""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("UPDATE users SET onboarded = ? WHERE LOWER(username) = LOWER(?)", (onboarded, username))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error persisting onboarded state: {e}")

def get_user_preferences(username: str) -> dict:
    """Retrieves stored user settings and personalization."""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute(
            "SELECT sidebar_open, active_mode, temperature, stream_mode FROM user_preferences WHERE LOWER(username) = LOWER(?)",
            (username,)
        )
        row = c.fetchone()
        conn.close()
        if row:
            return {
                "sidebar_open": bool(row[0]),
                "active_mode": row[1] or "💬 General",
                "temperature": float(row[2]) if row[2] is not None else 0.7,
                "stream_mode": bool(row[3]) if row[3] is not None else True,
            }
    except Exception as e:
        print(f"Error reading user preferences: {e}")

    return {
        "sidebar_open": True,
        "active_mode": "💬 General",
        "temperature": 0.7,
        "stream_mode": True,
    }

def save_user_preference(username: str, key: str, value):
    """Saves a user preference to the SQLite database."""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT username FROM user_preferences WHERE LOWER(username) = LOWER(?)", (username,))
        if not c.fetchone():
            c.execute(
                "INSERT INTO user_preferences (username, sidebar_open, active_mode, temperature, stream_mode) VALUES (?, 1, '💬 General', 0.7, 1)",
                (username,)
            )
        c.execute(f"UPDATE user_preferences SET {key} = ?, updated_at = CURRENT_TIMESTAMP WHERE LOWER(username) = LOWER(?)", (value, username))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error saving preference {key}: {e}")

def load_user_chats_from_db(username: str) -> dict:
    """Loads all conversations and messages for a specific user."""
    chats = {}
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute(
            "SELECT chat_id, title FROM chats WHERE LOWER(username) = LOWER(?) ORDER BY updated_at DESC",
            (username,)
        )
        chat_rows = c.fetchall()
        for chat_id, title in chat_rows:
            c.execute(
                "SELECT role, content FROM messages WHERE chat_id = ? ORDER BY id ASC",
                (chat_id,)
            )
            messages = [{"role": r, "content": cnt} for r, cnt in c.fetchall()]
            chats[chat_id] = {
                "title": title,
                "messages": messages
            }
        conn.close()
    except Exception as e:
        print(f"Error loading chats from DB: {e}")

    return chats

def save_chat_to_db(username: str, chat_id: str, title: str):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO chats (chat_id, username, title, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
            (chat_id, username, title)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error saving chat {chat_id}: {e}")

def update_chat_title_in_db(chat_id: str, title: str):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute(
            "UPDATE chats SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE chat_id = ?",
            (title, chat_id)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error updating title for chat {chat_id}: {e}")

def save_message_to_db(chat_id: str, role: str, content: str):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute(
            "INSERT INTO messages (chat_id, role, content) VALUES (?, ?, ?)",
            (chat_id, role, content)
        )
        c.execute(
            "UPDATE chats SET updated_at = CURRENT_TIMESTAMP WHERE chat_id = ?",
            (chat_id,)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error saving message to chat {chat_id}: {e}")

def delete_chat_from_db(chat_id: str):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
        c.execute("DELETE FROM chats WHERE chat_id = ?", (chat_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error deleting chat {chat_id}: {e}")

# Initialize database on startup
init_auth_db()

# Initialize Auth State
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "username" not in st.session_state:
    st.session_state.username = None


# ===================== GLOBAL MODERN STYLING =====================

def inject_app_styles(sidebar_open: bool):
    """Injects the dark-navy theme.

    SIDEBAR DESIGN: `st.session_state.sidebar_open` is the ONLY source of truth.
    Streamlit's own collapse/expand controls are hidden and its collapse transform is
    neutralised, so the real <section data-testid="stSidebar"> is shown/hidden purely
    from Python state on every rerun (no one-shot JavaScript, no second state machine).
    """
    display = "block" if sidebar_open else "none"
    content_max = "1000px" if sidebar_open else "1240px"

    sidebar_css = f"""
    /* REAL SIDEBAR: visibility is driven only by Python state.
       transform/margin/visibility resets stop Streamlit's native "collapsed" state
       from pushing the sidebar off-canvas while we show it. */
    [data-testid="stSidebar"] {{
        display: {display} !important;
        transform: none !important;
        margin-left: 0 !important;
        visibility: visible !important;
        background: linear-gradient(180deg, #0b1122 0%, #060913 100%) !important;
        border-right: 1px solid #1a2742 !important;
    }}

    /* DESKTOP / TABLET (>= 769px): sidebar sits in the flex layout; when closed it is
       display:none so the main area reclaims the full width. */
    @media (min-width: 769px) {{
        [data-testid="stSidebar"] {{
            position: relative !important;
            flex: 0 0 320px !important;
            width: 320px !important;
            min-width: 320px !important;
            max-width: 320px !important;
            z-index: 99 !important;
        }}
        .block-container {{
            max-width: {content_max} !important;
            margin: 0 auto !important;
            padding: 4.25rem 2rem 5rem !important;
        }}
        [data-testid="stBottomBlockContainer"] {{
            max-width: {content_max} !important;
            margin: 0 auto !important;
            padding-left: 2rem !important;
            padding-right: 2rem !important;
        }}
        /* Backdrop and in-sidebar close button are mobile-only */
        .st-key-sidebar_backdrop, .st-key-sidebar_close_btn {{
            display: none !important;
        }}
    }}

    /* MOBILE (<= 768px): sidebar is a fixed overlay above a clickable backdrop. */
    @media (max-width: 768px) {{
        [data-testid="stSidebar"] {{
            position: fixed !important;
            top: 0 !important;
            left: 0 !important;
            bottom: 0 !important;
            width: 82vw !important;
            min-width: 0 !important;
            max-width: 320px !important;
            height: 100vh !important;
            height: 100dvh !important;
            z-index: 999999 !important;
            background: #090e1d !important;
            border-right: 1px solid #233555 !important;
            box-shadow: 0 0 60px rgba(0, 0, 0, 0.95) !important;
            overflow-y: auto !important;
        }}
        .block-container {{
            max-width: 100% !important;
            padding: 4.25rem 1rem 5rem !important;
        }}
        [data-testid="stBottomBlockContainer"] {{
            max-width: 100% !important;
            padding-left: 1rem !important;
            padding-right: 1rem !important;
        }}
        .st-key-sidebar_close_btn {{
            display: block !important;
        }}
        /* Full-screen backdrop is a REAL Streamlit button (rendered only while open) */
        .st-key-sidebar_backdrop {{
            display: block !important;
            position: fixed !important;
            top: 0 !important;
            left: 0 !important;
            width: 100vw !important;
            height: 100vh !important;
            height: 100dvh !important;
            margin: 0 !important;
            padding: 0 !important;
            z-index: 999998 !important;
            background: rgba(2, 6, 16, 0.7) !important;
        }}
        .st-key-sidebar_backdrop [data-testid="stButton"],
        .st-key-sidebar_backdrop .stButton {{
            width: 100% !important;
            height: 100% !important;
        }}
        .st-key-sidebar_backdrop button,
        .st-key-sidebar_backdrop button:hover,
        .st-key-sidebar_backdrop button:active {{
            width: 100% !important;
            height: 100% !important;
            min-height: 100% !important;
            opacity: 0 !important;
            background: transparent !important;
            border: 0 !important;
            box-shadow: none !important;
            transform: none !important;
            cursor: pointer !important;
        }}
    }}
    """

    st.markdown(f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap');

    :root {{
        color-scheme: dark;
        --bg-main: #080c18;
        --bg-surface: #111a2f;
        --bg-surface-hover: #16223e;
        --border-subtle: #1e2c49;
        --border-active: #38bdf8;
        --accent-violet: #6366f1;
        --accent-violet-glow: rgba(99, 102, 241, 0.35);
        --accent-cyan: #38bdf8;
        --text-primary: #f8fafc;
        --text-secondary: #cbd5e1;
        --text-muted: #94a3b8;
    }}

    /* APP FOUNDATION */
    html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"], section.main {{
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
        background:
            radial-gradient(ellipse at 50% 0%, #151e3d 0%, transparent 55%),
            linear-gradient(160deg, #070b16 0%, #0a0f21 50%, #080c18 100%) !important;
        background-attachment: fixed !important;
        color: var(--text-primary) !important;
        overflow-x: hidden !important;
    }}

    /* Streamlit's fixed header stays transparent; page content is padded below it
       (see .block-container padding-top) so it can never cover the hamburger button. */
    [data-testid="stHeader"] {{
        background: transparent !important;
        z-index: 10 !important;
    }}

    /* Hide EVERY native sidebar collapse/expand control (names vary by Streamlit
       version). The hamburger in the top bar is the only toggle. */
    [data-testid="stSidebarCollapsedControl"],
    [data-testid="stExpandSidebarButton"],
    [data-testid="collapsedControl"],
    [data-testid="stSidebarCollapseButton"] {{
        display: none !important;
    }}

    {sidebar_css}

    /* TOP BAR: one row at every width, hamburger always visible */
    .st-key-topbar [data-testid="stHorizontalBlock"] {{
        flex-wrap: nowrap !important;
        align-items: center !important;
        gap: 0.5rem !important;
    }}
    .st-key-topbar [data-testid="stHorizontalBlock"] > div:nth-child(1) {{
        flex: 0 0 52px !important;
        width: 52px !important;
        min-width: 52px !important;
    }}
    .st-key-topbar [data-testid="stHorizontalBlock"] > div:nth-child(2) {{
        flex: 1 1 0 !important;
        width: auto !important;
        min-width: 0 !important;
    }}
    .st-key-topbar [data-testid="stHorizontalBlock"] > div:nth-child(3),
    .st-key-topbar [data-testid="stHorizontalBlock"] > div:nth-child(4) {{
        flex: 0 0 auto !important;
        width: auto !important;
        min-width: 0 !important;
    }}
    .st-key-topbar button {{
        padding: 6px 10px !important;
        white-space: nowrap !important;
    }}
    @media (max-width: 640px) {{
        .st-key-topbar [data-testid="stHorizontalBlock"] > div:nth-child(3) {{
            display: none !important;
        }}
    }}

    /* GLOBAL TYPOGRAPHY */
    p, span, label, div {{
        color: var(--text-secondary);
        word-break: break-word;
    }}
    h1, h2, h3, h4, strong, b {{
        color: #ffffff !important;
        font-weight: 700;
        letter-spacing: -0.02em;
    }}

    /* MODERN CODE BLOCKS */
    code, pre {{
        font-family: 'JetBrains Mono', Consolas, monospace !important;
    }}
    code {{
        background: #0d1527 !important;
        color: #38bdf8 !important;
        padding: 3px 7px !important;
        border-radius: 6px !important;
        border: 1px solid #1c2b48 !important;
        font-size: 0.88em !important;
    }}
    [data-testid="stChatMessage"] pre {{
        background: #090e1c !important;
        border: 1px solid #1e2e4f !important;
        border-radius: 12px !important;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.45) !important;
    }}

    /* TOP WORKSPACE TOOLBAR */
    .codepilot-topbar {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        background: rgba(14, 22, 42, 0.7);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        border: 1px solid #1d2b4a;
        border-radius: 14px;
        padding: 8px 16px;
        margin-bottom: 20px;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.35);
    }}
    .topbar-left {{
        display: flex;
        align-items: center;
        gap: 12px;
    }}
    .topbar-right {{
        display: flex;
        align-items: center;
        gap: 10px;
    }}
    .brand-pill {{
        font-weight: 800;
        font-size: 16px;
        color: #ffffff !important;
        display: flex;
        align-items: center;
        gap: 8px;
    }}
    .brand-pill span {{
        background: linear-gradient(90deg, #9385ff, #38bdf8);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }}
    .status-badge {{
        display: inline-flex;
        align-items: center;
        gap: 6px;
        background: rgba(16, 185, 129, 0.12);
        color: #34d399 !important;
        border: 1px solid rgba(16, 185, 129, 0.3);
        padding: 4px 10px;
        border-radius: 20px;
        font-size: 12px;
        font-weight: 600;
    }}
    .mode-badge {{
        background: rgba(99, 102, 241, 0.15);
        color: #a5b4fc !important;
        border: 1px solid rgba(99, 102, 241, 0.35);
        padding: 4px 10px;
        border-radius: 20px;
        font-size: 12px;
        font-weight: 600;
    }}

    /* BUTTONS: CRISP HIGH CONTRAST */
    .stButton > button {{
        background: linear-gradient(135deg, #131f38 0%, #0f182c 100%) !important;
        border: 1px solid #273a61 !important;
        border-radius: 12px !important;
        color: #f1f6ff !important;
        font-weight: 600 !important;
        font-size: 14px !important;
        min-height: 44px !important;
        padding: 8px 16px !important;
        box-shadow: 0 4px 14px rgba(0, 0, 0, 0.35) !important;
        transition: all 0.2s ease !important;
    }}
    .stButton > button:hover {{
        background: linear-gradient(135deg, #1c2b4d 0%, #15223e 100%) !important;
        border-color: #38bdf8 !important;
        box-shadow: 0 0 20px rgba(56, 189, 248, 0.3) !important;
        transform: translateY(-1px) !important;
    }}
    .stButton > button:active {{
        transform: translateY(0px) !important;
    }}

    /* PRIMARY CTA BUTTONS */
    .cta-primary button {{
        background: linear-gradient(110deg, #5046ef 0%, #7c3aed 100%) !important;
        border: 1px solid #8275ff !important;
        color: #ffffff !important;
        font-weight: 700 !important;
        box-shadow: 0 4px 22px rgba(99, 102, 241, 0.45) !important;
    }}
    .cta-primary button:hover {{
        border-color: #38bdf8 !important;
        box-shadow: 0 0 26px rgba(56, 189, 248, 0.5) !important;
    }}

    /* CHAT MESSAGES */
    [data-testid="stChatMessage"] {{
        background: #0f1628 !important;
        border: 1px solid #1e2b47 !important;
        border-radius: 16px !important;
        padding: 18px 20px !important;
        margin-bottom: 16px !important;
        box-shadow: 0 4px 24px rgba(0, 0, 0, 0.35) !important;
    }}
    [data-testid="stChatMessage"][data-role="user"] {{
        background: #141e35 !important;
        border: 1px solid #273859 !important;
    }}
    [data-testid="stChatMessage"] p {{
        font-size: 15px !important;
        line-height: 1.75 !important;
        color: #e2edff !important;
    }}

    /* BOTTOM CHAT INPUT BAR */
    [data-testid="stBottom"], [data-testid="stBottomBlockContainer"] {{
        background: transparent !important;
    }}
    [data-testid="stChatInput"] {{
        background: #0f172a !important;
        border: 1px solid #27395c !important;
        border-radius: 18px !important;
        box-shadow: 0 6px 30px rgba(0, 0, 0, 0.65) !important;
        padding: 4px 8px !important;
    }}
    [data-testid="stChatInput"] textarea {{
        color: #ffffff !important;
        caret-color: #38bdf8 !important;
        font-size: 15px !important;
    }}
    [data-testid="stChatInput"] textarea::placeholder {{
        color: #7b93b8 !important;
    }}
    [data-testid="stChatInput"] button {{
        background: linear-gradient(110deg, #5046ef, #783df0) !important;
        border: 1px solid #8275ff !important;
        border-radius: 10px !important;
        color: #ffffff !important;
    }}

    /* INPUTS & TEXTFIELDS */
    [data-baseweb="input"], [data-baseweb="input"] > div,
    [data-baseweb="base-input"], [data-baseweb="base-input"] > div,
    [data-baseweb="textarea"], [data-baseweb="textarea"] > div {{
        background: #10192e !important;
        border: 1px solid #243555 !important;
        border-radius: 12px !important;
    }}
    input, textarea {{
        color: #ffffff !important;
        background: transparent !important;
        font-size: 14px !important;
    }}

    /* SIDEBAR COMPONENT POLISH */
    [data-testid="stSidebar"] > div {{
        padding: 1.25rem 1rem !important;
    }}
    [data-testid="stSidebar"] .stButton > button {{
        background: #111a2f !important;
        border: 1px solid #1e2c48 !important;
        border-radius: 10px !important;
        min-height: 38px !important;
        padding: 6px 12px !important;
        font-size: 13px !important;
    }}
    [data-testid="stSidebar"] .stButton > button:hover {{
        background: #192644 !important;
        border-color: #6366f1 !important;
    }}
    [data-testid="stSidebar"] [data-testid="stExpander"] {{
        background: #0f1629 !important;
        border: 1px solid #1f2e4d !important;
        border-radius: 12px !important;
    }}

    /* ONBOARDING & HERO CARDS */
    .onboarding-card {{
        background: linear-gradient(145deg, #131d36 0%, #0d1527 100%);
        border: 1px solid #233555;
        border-radius: 18px;
        padding: 24px;
        min-height: 190px;
        box-shadow: 0 8px 30px rgba(0, 0, 0, 0.4);
        transition: all 0.25s ease;
    }}
    .onboarding-card:hover {{
        border-color: #38bdf8;
        box-shadow: 0 0 28px rgba(56, 189, 248, 0.25);
        transform: translateY(-2px);
    }}
    .onboarding-icon {{
        width: 46px;
        height: 46px;
        border-radius: 14px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 22px;
        margin-bottom: 14px;
    }}

    /* ACCESSIBILITY: REDUCED MOTION */
    @media (prefers-reduced-motion: reduce) {{
        * {{
            animation-duration: 0.01ms !important;
            transition-duration: 0.01ms !important;
        }}
    }}
    </style>
    """, unsafe_allow_html=True)


# ===================== LOGIN / AUTH VIEW =====================

if not st.session_state.authenticated:
    st.markdown("""
    <style>
    [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] {
        display: none !important;
    }
    .block-container {
        max-width: 480px !important;
        margin: 0 auto !important;
        padding-top: 3.5rem !important;
        padding-bottom: 3rem !important;
    }
    [data-testid="stTabs"] [data-baseweb="tab-list"] {
        display: flex !important;
        width: 100% !important;
        background: #0b1122 !important;
        border: 1px solid #203150 !important;
        border-radius: 14px !important;
        padding: 4px !important;
        gap: 6px !important;
    }
    [data-testid="stTabs"] [data-baseweb="tab"] {
        flex: 1 1 0% !important;
        height: 42px !important;
        border-radius: 10px !important;
        color: #8fa5cb !important;
        font-size: 14px !important;
        font-weight: 600 !important;
        border: none !important;
        background: transparent !important;
    }
    [data-testid="stTabs"] [aria-selected="true"] {
        background: linear-gradient(135deg, #1e2a4a, #141e35) !important;
        color: #38bdf8 !important;
        border: 1px solid #324771 !important;
    }
    [data-testid="stTabs"] [data-baseweb="tab-highlight"],
    [data-testid="stTabs"] [data-baseweb="tab-border"] {
        display: none !important;
    }
    [data-testid="stForm"] {
        background: linear-gradient(160deg, #101a2f 0%, #0a1122 100%) !important;
        border: 1px solid #243557 !important;
        border-radius: 20px !important;
        padding: 26px 24px 22px !important;
        box-shadow: 0 16px 44px rgba(0, 0, 0, 0.6) !important;
        margin-top: 14px;
    }
    [data-testid="stFormSubmitButton"] > button {
        background: linear-gradient(110deg, #5046ef 0%, #7c3aed 100%) !important;
        color: #ffffff !important;
        border: 1px solid #8275ff !important;
        border-radius: 12px !important;
        min-height: 46px !important;
        font-size: 15px !important;
        font-weight: 700 !important;
        width: 100% !important;
        box-shadow: 0 4px 20px rgba(99, 102, 241, 0.4) !important;
    }
    </style>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div style="text-align: center; padding: 10px 0 20px;">
        <div style="width: 76px; height: 76px; margin: 0 auto 16px; border-radius: 24px; display: flex; align-items: center; justify-content: center; font-size: 38px; background: linear-gradient(135deg, #2563eb, #7c3aed); border: 1px solid #818cf8; box-shadow: 0 0 32px rgba(124, 58, 237, 0.4);">
            🤖
        </div>
        <h1 style="font-size: 36px; margin: 0; font-weight: 800; letter-spacing: -1px;">CodePilot <span style="background: linear-gradient(90deg, #9385ff, #38bdf8); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">AI</span></h1>
        <p style="color: #9cb1d6; margin-top: 6px; font-size: 15px;">Your AI Pair Programmer & Code Studio</p>
    </div>
    """, unsafe_allow_html=True)

    login_tab, signup_tab = st.tabs(["🔑 Sign In", "✨ Create Account"])

    with login_tab:
        with st.form("login_form"):
            login_user = st.text_input("Username", placeholder="e.g. demo", key="login_username")
            login_pwd = st.text_input("Password", type="password", placeholder="••••••••", key="login_password")
            submit_login = st.form_submit_button("Sign In", use_container_width=True)

            if submit_login:
                success, msg = verify_credentials(login_user, login_pwd)
                if success:
                    st.session_state.authenticated = True
                    st.session_state.username = login_user.strip()
                    st.rerun()
                else:
                    st.error(msg)

    with signup_tab:
        with st.form("register_form"):
            new_user = st.text_input("Choose Username", placeholder="at least 3 characters", key="reg_username")
            new_pwd = st.text_input("Choose Password", type="password", placeholder="at least 4 characters", key="reg_password")
            confirm_pwd = st.text_input("Confirm Password", type="password", placeholder="••••••••", key="reg_confirm")
            submit_register = st.form_submit_button("Create Account", use_container_width=True)

            if submit_register:
                if new_pwd != confirm_pwd:
                    st.error("Passwords do not match.")
                else:
                    registered, reg_msg = register_user(new_user, new_pwd)
                    if registered:
                        st.success(reg_msg)
                    else:
                        st.error(reg_msg)

    st.markdown("""
    <div style="background: rgba(16, 26, 47, 0.75); border: 1px solid #233555; border-radius: 12px; padding: 12px 14px; margin-top: 18px; text-align: center; font-size: 12.5px; color: #9ab0d6;">
        <span style="color: #38bdf8; font-weight: 600;">⚡ Quick Demo Account:</span>
        &nbsp; User: <code style="background: #080d1a; padding: 2px 6px; border-radius: 6px; color: #a5b4fc; border: 1px solid #243454;">demo</code>
        &nbsp;&bull;&nbsp; Pass: <code style="background: #080d1a; padding: 2px 6px; border-radius: 6px; color: #a5b4fc; border: 1px solid #243454;">demo123</code>
    </div>
    """, unsafe_allow_html=True)

    st.stop()


# ===================== NEBIUS CLIENT SETUP =====================

if not api_key:
    st.error("Nebius API key is missing. Please verify your `.env` file contains NEBIUS_API_KEY.")
    st.stop()

client = OpenAI(
    api_key=api_key,
    base_url=base_url
)


# ===================== USER SESSION STATE INITIALIZATION =====================

current_user = st.session_state.username
user_chat_store = f"chats_{current_user}"
user_active_chat = f"active_chat_{current_user}"

# Load user preferences from DB once PER USER (not once per browser session), so a
# different account signing in on the same session gets its own sidebar state.
if st.session_state.get("prefs_loaded_for") != current_user:
    prefs = get_user_preferences(current_user)
    st.session_state.sidebar_open = prefs["sidebar_open"]
    st.session_state.active_mode = prefs["active_mode"]
    st.session_state.temperature = prefs["temperature"]
    st.session_state.stream_mode = prefs["stream_mode"]
    st.session_state.prefs_loaded_for = current_user

# Load onboarding state
if f"onboarded_{current_user}" not in st.session_state:
    st.session_state[f"onboarded_{current_user}"] = is_user_onboarded(current_user)

# Load persistent user chats from database
if user_chat_store not in st.session_state:
    db_chats = load_user_chats_from_db(current_user)
    if not db_chats:
        initial_chat_id = str(uuid.uuid4())
        initial_title = "New Chat"
        db_chats = {
            initial_chat_id: {
                "title": initial_title,
                "messages": []
            }
        }
        save_chat_to_db(current_user, initial_chat_id, initial_title)
        st.session_state[user_active_chat] = initial_chat_id
    else:
        st.session_state[user_active_chat] = list(db_chats.keys())[0]

    st.session_state[user_chat_store] = db_chats

if "search_chats" not in st.session_state:
    st.session_state.search_chats = ""

# Make sure active chat exists
if st.session_state.get(user_active_chat) not in st.session_state[user_chat_store]:
    if st.session_state[user_chat_store]:
        st.session_state[user_active_chat] = list(st.session_state[user_chat_store].keys())[0]
    else:
        new_id = str(uuid.uuid4())
        st.session_state[user_chat_store][new_id] = {"title": "New Chat", "messages": []}
        save_chat_to_db(current_user, new_id, "New Chat")
        st.session_state[user_active_chat] = new_id


def create_new_chat():
    new_id = str(uuid.uuid4())
    st.session_state[user_chat_store][new_id] = {
        "title": "New Chat",
        "messages": []
    }
    save_chat_to_db(current_user, new_id, "New Chat")
    st.session_state[user_active_chat] = new_id


# ---- Sidebar state callbacks -------------------------------------------------
# Callbacks run BEFORE the script reruns, so the new state is already in place when
# the CSS is generated below. They read the username from session_state (not from a
# module-level variable) because callbacks execute before the script body.
def set_sidebar_open(value: bool):
    st.session_state.sidebar_open = bool(value)
    save_user_preference(st.session_state.username, "sidebar_open", int(bool(value)))


def toggle_sidebar():
    set_sidebar_open(not st.session_state.sidebar_open)


# Apply styling based on current sidebar state
inject_app_styles(st.session_state.sidebar_open)

# Escape-key support. Re-runs safely: on every load it REMOVES the previously bound
# handler from the parent document and binds a fresh one, so there are never duplicate
# or stale listeners. The handler looks up the live Streamlit "close" button at key-press
# time (nothing is cached across reruns) and only acts while the sidebar is open
# (the backdrop button exists in the DOM only while open).
components.html("""
<script>
(function () {
    const win = window.parent;
    const doc = win.document;
    if (win.__codepilotEscHandler) {
        doc.removeEventListener('keydown', win.__codepilotEscHandler);
    }
    win.__codepilotEscHandler = function (e) {
        if (e.key !== 'Escape') return;
        if (!doc.querySelector('.st-key-sidebar_backdrop')) return;   // sidebar not open
        const btn = doc.querySelector('.st-key-sidebar_close_btn button');
        if (btn) btn.click();
    };
    doc.addEventListener('keydown', win.__codepilotEscHandler);
})();
</script>
""", height=0)


# ===================== DEVELOPER PROMPT MODES =====================

MODE_PROMPTS = {
    "💬 General": (
        "You are CodePilot AI, an elite coding assistant. Help users write, "
        "understand, and improve code. Output production-ready, clean, idiomatic code "
        "in formatted markdown fenced code blocks."
    ),
    "🔍 Explain": (
        "You are CodePilot AI in EXPLAIN MODE. Analyze the user's code in depth:\n"
        "1. High-level Summary: What does this code do in plain English?\n"
        "2. Step-by-Step Breakdown: Explain the key logic and control flow.\n"
        "3. Complexity Analysis: State Time Complexity and Space Complexity with Big-O notation.\n"
        "4. Edge Cases: Highlight boundary conditions or potential pitfalls."
    ),
    "🐛 Debug & Fix": (
        "You are CodePilot AI in DEBUG MODE. Diagnose the user's code issue:\n"
        "1. Bug Identification: Point out the exact error or logical flaw.\n"
        "2. Root Cause: Explain why the bug occurs.\n"
        "3. Corrected Code: Provide the complete, tested, drop-in replacement code in fenced blocks.\n"
        "4. Prevention Tip: How to avoid this type of error in the future."
    ),
    "⚡ Optimize": (
        "You are CodePilot AI in OPTIMIZE MODE. Improve and refactor the user's code:\n"
        "1. Bottlenecks: Identify performance, memory, or readability inefficiencies.\n"
        "2. Optimized Version: Provide clean, idiomatic, and efficient refactored code.\n"
        "3. Key Improvements: List what was optimized (e.g., algorithmic speedup, reduced memory)."
    )
}


# ===================== SEND PROMPT & STREAMING DISPATCHER =====================

def send_prompt(prompt_text: str):
    active_id = st.session_state[user_active_chat]
    chat = st.session_state[user_chat_store][active_id]

    # If first message, auto-title chat
    if not chat["messages"]:
        new_title = prompt_text[:30].strip() + ("..." if len(prompt_text) > 30 else "")
        chat["title"] = new_title
        update_chat_title_in_db(active_id, new_title)

    # Append user message
    chat["messages"].append({
        "role": "user",
        "content": prompt_text
    })
    save_message_to_db(active_id, "user", prompt_text)

    # If user is in first-time onboarding mode, complete it immediately
    if not st.session_state.get(f"onboarded_{current_user}", False):
        set_user_onboarded(current_user, 1)
        st.session_state[f"onboarded_{current_user}"] = True

    st.session_state.pending_generation = True
    st.rerun()


# ===================== SIDEBAR VIEW =====================

with st.sidebar:
    # Sidebar Header with Close button (shown on mobile only; the hamburger is the
    # single toggle everywhere else). Same state setter as the hamburger.
    head_left, head_right = st.columns([4, 1])
    with head_left:
        st.markdown(
            '<div style="font-weight: 800; font-size: 20px; color: #ffffff; letter-spacing: -0.5px;">'
            '🤖 CodePilot <span style="background: linear-gradient(90deg, #9385ff, #38bdf8); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">AI</span>'
            '</div>'
            '<div style="font-size: 11.5px; color: #8ea3c7; margin-bottom: 8px;">AI Coding Environment</div>',
            unsafe_allow_html=True
        )
    with head_right:
        st.button(
            "✕",
            key="sidebar_close_btn",
            help="Close Sidebar (Esc)",
            on_click=set_sidebar_open,
            args=(False,),
        )

    # New Chat Button
    if st.button("＋   New Conversation", key="new_chat_btn", use_container_width=True):
        create_new_chat()
        st.rerun()

    st.markdown("<div style='height: 6px;'></div>", unsafe_allow_html=True)

    # Search conversations
    st.text_input(
        "Search conversations",
        placeholder="🔎 Search conversations...",
        key="search_chats",
        label_visibility="collapsed"
    )

    st.markdown("<div style='font-size: 12px; font-weight: 700; color: #94a7cb; margin: 10px 0 6px;'>CHATS</div>", unsafe_allow_html=True)

    search = st.session_state.search_chats.lower().strip()
    chat_items = list(st.session_state[user_chat_store].items())

    visible_chats = [
        (c_id, ch)
        for c_id, ch in chat_items
        if search in ch["title"].lower()
    ]

    if not visible_chats:
        st.caption("No matching conversations found.")

    for c_id, ch in visible_chats:
        is_active = (c_id == st.session_state[user_active_chat])
        prefix = "● " if is_active else "▹ "

        c_col1, c_col2 = st.columns([5, 1])
        with c_col1:
            if st.button(
                prefix + ch["title"],
                key="hist_" + c_id,
                use_container_width=True,
                help=ch["title"]
            ):
                st.session_state[user_active_chat] = c_id
                st.rerun()
        with c_col2:
            # Delete chat icon
            if st.button("🗑", key="del_" + c_id, help="Delete conversation"):
                delete_chat_from_db(c_id)
                del st.session_state[user_chat_store][c_id]
                if st.session_state[user_active_chat] == c_id:
                    if st.session_state[user_chat_store]:
                        st.session_state[user_active_chat] = list(st.session_state[user_chat_store].keys())[0]
                    else:
                        create_new_chat()
                st.rerun()

    st.divider()

    # Settings and Personalization
    with st.expander("⚙️ Settings & Model"):
        st.markdown("**AI Provider**")
        st.caption("Nebius Token Factory")
        st.markdown("**Model Engine**")
        st.caption(f"`{model}`")

        # Temperature setting
        new_temp = st.slider(
            "Creativity (Temperature)",
            min_value=0.0,
            max_value=1.0,
            value=st.session_state.temperature,
            step=0.1,
            key="temp_slider"
        )
        if new_temp != st.session_state.temperature:
            st.session_state.temperature = new_temp
            save_user_preference(current_user, "temperature", new_temp)

        # Stream mode toggle
        stream_toggle = st.checkbox(
            "Live Streaming Response",
            value=st.session_state.stream_mode,
            key="stream_checkbox"
        )
        if stream_toggle != st.session_state.stream_mode:
            st.session_state.stream_mode = stream_toggle
            save_user_preference(current_user, "stream_mode", int(stream_toggle))

        # Replay onboarding option
        if st.button("🔄 Replay Onboarding Tour", use_container_width=True):
            set_user_onboarded(current_user, 0)
            st.session_state[f"onboarded_{current_user}"] = False
            st.rerun()

    with st.expander("❔ Keyboard & Help"):
        st.caption("• **Enter**: Send message")
        st.caption("• **Shift + Enter**: New line")
        st.caption("• **Esc**: Close sidebar")
        st.caption("• **☰** (top bar): Open / close sidebar")
        st.caption("• Code blocks include built-in one-click copy.")

    st.divider()

    # User Profile & Sign Out
    st.markdown(
        f'<div style="display: flex; align-items: center; gap: 10px; margin-bottom: 10px;">'
        f'<div style="width: 34px; height: 34px; border-radius: 10px; background: #1c2c4d; display: flex; align-items: center; justify-content: center; font-weight: 700; color: #38bdf8; border: 1px solid #334d7a;">'
        f'{current_user[0].upper()}'
        f'</div>'
        f'<div>'
        f'<div style="font-weight: 700; font-size: 14px; color: #ffffff;">{current_user}</div>'
        f'<div style="font-size: 11px; color: #8da4c4;">Personal Workspace</div>'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True
    )

    if st.button("🚪   Sign Out", use_container_width=True, key="logout_btn"):
        st.session_state.authenticated = False
        st.session_state.username = None
        st.rerun()


# ===================== MOBILE BACKDROP =====================
# A real Streamlit button, rendered only while the sidebar is open. CSS makes it a
# full-screen invisible click target on mobile and hides it on desktop.
if st.session_state.sidebar_open:
    st.button(
        "Close sidebar",
        key="sidebar_backdrop",
        help="Close sidebar",
        on_click=set_sidebar_open,
        args=(False,),
    )


# ===================== TOP NAVIGATION BAR =====================

with st.container(key="topbar"):
    top_c1, top_c2, top_c3, top_c4 = st.columns([1, 4, 2, 1])

    with top_c1:
        # The ONE sidebar toggle. It lives in the main area, so it is visible whether
        # the sidebar is open or closed.
        st.button(
            "☰",
            key="navbar_sidebar_toggle",
            help="Close sidebar" if st.session_state.sidebar_open else "Open sidebar",
            on_click=toggle_sidebar,
        )

    with top_c2:
        active_chat_obj = st.session_state[user_chat_store][st.session_state[user_active_chat]]
        st.markdown(
            f'<div style="display: flex; align-items: center; gap: 10px; height: 44px;">'
            f'<span style="font-weight: 700; color: #ffffff; font-size: 15px;">🤖 CodePilot AI</span>'
            f'<span style="color: #4b638a;">/</span>'
            f'<span style="color: #a5b8d8; font-size: 13.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 280px;">{active_chat_obj["title"]}</span>'
            f'</div>',
            unsafe_allow_html=True
        )

    with top_c3:
        st.markdown(
            f'<div style="display: flex; align-items: center; justify-content: flex-end; gap: 8px; height: 44px;">'
            f'<span class="mode-badge">{st.session_state.active_mode}</span>'
            f'<span class="status-badge">🟢 Nebius AI</span>'
            f'</div>',
            unsafe_allow_html=True
        )

    with top_c4:
        if st.button("＋ New", key="navbar_new_chat", help="Start New Chat", use_container_width=True):
            create_new_chat()
            st.rerun()


# ===================== MAIN CHAT & ONBOARDING AREA =====================

chat = st.session_state[user_chat_store][st.session_state[user_active_chat]]
is_new_user_onboarding = not st.session_state.get(f"onboarded_{current_user}", False)

# ----------------- BRANCH 1: ONE-TIME ONBOARDING TOUR (GENUINELY NEW USERS) -----------------
if is_new_user_onboarding:
    st.markdown(f"""
    <div style="text-align: center; padding: 24px 0 16px;">
        <div style="width: 78px; height: 78px; margin: 0 auto 18px; border-radius: 26px; display: flex; align-items: center; justify-content: center; font-size: 40px; background: linear-gradient(135deg, #1d4ed8, #7c3aed); border: 1px solid #818cf8; box-shadow: 0 0 35px rgba(124, 58, 237, 0.45);">
            🤖
        </div>
        <h1 style="font-size: 38px; font-weight: 800; letter-spacing: -1.2px; margin: 0;">
            Welcome to CodePilot <span>AI</span>, {current_user}!
        </h1>
        <p style="color: #adc2e2; font-size: 16px; max-width: 680px; margin: 12px auto 0; line-height: 1.8;">
            Your modern AI pair programmer powered by <b>Nebius Token Factory</b>. 
            Write code, diagnose runtime bugs, explore complexity, and optimize architecture in one unified workspace.
        </p>
    </div>
    """, unsafe_allow_html=True)

    # 4 Core Onboarding Feature Cards
    f_cols = st.columns(4)
    features = [
        ("💻", "#1d4ed8", "Write & Refactor", "Generate clean, modern code across Python, TypeScript, SQL, and more with typing and edge handling."),
        ("🔍", "#0f766e", "Deep Explanation", "Analyze intricate algorithms with step-by-step logic and Big-O Time & Space complexity breakdown."),
        ("🐛", "#7c2d12", "Debug & Fix", "Identify syntax errors, logical bugs, and race conditions with verified drop-in code fixes."),
        ("⚡", "#6d28d9", "Performance", "Eliminate performance bottlenecks and refactor memory or concurrency patterns.")
    ]

    for col, (icon, color, f_title, f_desc) in zip(f_cols, features):
        with col:
            st.markdown(f"""
            <div class="onboarding-card">
                <div class="onboarding-icon" style="background: {color};">
                    {icon}
                </div>
                <h3 style="font-size: 16px; margin: 0 0 8px; color: #ffffff;">{f_title}</h3>
                <p style="font-size: 13px; color: #b1c3e0; line-height: 1.7; margin: 0;">{f_desc}</p>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)

    # Starter prompts
    st.markdown(
        '<div style="font-size: 15px; font-weight: 600; color: #e2edff; margin: 18px 0 10px;">'
        '✨ Try starting with a common task:'
        '</div>',
        unsafe_allow_html=True
    )

    onboarding_suggestions = [
        "Write a Python script to sort a list using quicksort with comments",
        "Explain how Python decorators work under the hood with a timer example",
        "Fix this bug: TypeError: 'list' object cannot be interpreted as an integer",
        "Create a production-ready FastAPI endpoint with Pydantic validation"
    ]

    p_col1, p_col2 = st.columns(2)
    for idx, prompt_text in enumerate(onboarding_suggestions):
        target_col = p_col1 if idx % 2 == 0 else p_col2
        with target_col:
            if st.button("✦  " + prompt_text, key=f"onb_sug_{idx}", use_container_width=True):
                send_prompt(prompt_text)

    st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)

    # Launch Workspace CTA Button
    cta_col1, cta_col2, cta_col3 = st.columns([1, 2, 1])
    with cta_col2:
        st.markdown('<div class="cta-primary">', unsafe_allow_html=True)
        if st.button("🚀   Launch Coding Workspace", key="complete_onboarding_btn", use_container_width=True):
            set_user_onboarded(current_user, 1)
            st.session_state[f"onboarded_{current_user}"] = True
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)


# ----------------- BRANCH 2: REGULAR CHAT WORKSPACE (RETURNING / ONBOARDED USERS) -----------------
else:
    # DEVELOPER MODE SELECTOR
    m_col1, m_col2, m_col3, m_col4 = st.columns(4)
    mode_options = ["💬 General", "🔍 Explain", "🐛 Debug & Fix", "⚡ Optimize"]

    for col, m in zip([m_col1, m_col2, m_col3, m_col4], mode_options):
        with col:
            is_active = (st.session_state.active_mode == m)
            label = f"● {m}" if is_active else m
            if st.button(label, key=f"mode_btn_{m}", use_container_width=True):
                st.session_state.active_mode = m
                save_user_preference(current_user, "active_mode", m)
                st.rerun()

    st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)

    # EMPTY CONVERSATION CANVAS (NO GIANT ONBOARDING, JUST MODERN DEV HERO)
    if not chat["messages"]:
        st.markdown(f"""
        <div style="text-align: center; padding: 40px 10px 24px;">
            <div style="width: 68px; height: 68px; margin: 0 auto 16px; border-radius: 22px; display: flex; align-items: center; justify-content: center; font-size: 34px; background: linear-gradient(135deg, #1e3a8a, #581c87); border: 1px solid #6366f1; box-shadow: 0 0 30px rgba(99, 102, 241, 0.35);">
                🤖
            </div>
            <h2 style="font-size: 30px; font-weight: 800; letter-spacing: -0.8px; margin: 0; color: #ffffff;">
                What would you like to build or debug today?
            </h2>
            <p style="color: #9cb1d6; font-size: 14.5px; margin-top: 8px;">
                Mode: <strong style="color: #38bdf8;">{st.session_state.active_mode}</strong> &bull; Engine: <span style="color: #a5b4fc;">{model}</span>
            </p>
        </div>
        """, unsafe_allow_html=True)

        suggestions = [
            "Write a Python lambda and list comprehension example",
            "Explain time and space complexity of merge sort",
            "Debug API connection timeout in Python requests",
            "Optimize a slow SQL query with indexes and batching"
        ]

        sg_left, sg_right = st.columns(2)
        for i, sug in enumerate(suggestions):
            col = sg_left if i % 2 == 0 else sg_right
            with col:
                if st.button("✦  " + sug, key=f"sug_{i}", use_container_width=True):
                    send_prompt(sug)

    # CONVERSATION STREAM
    else:
        for message in chat["messages"]:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

    # HANDLE ASYNC/STREAMING RESPONSE DISPATCH
    if st.session_state.get("pending_generation", False):
        st.session_state.pending_generation = False
        active_sys_prompt = MODE_PROMPTS.get(st.session_state.active_mode, MODE_PROMPTS["💬 General"])

        with st.chat_message("assistant"):
            try:
                # Prepare payload
                messages_payload = [
                    {"role": "system", "content": active_sys_prompt},
                    *chat["messages"]
                ]

                if st.session_state.stream_mode:
                    stream = client.chat.completions.create(
                        model=model,
                        messages=messages_payload,
                        max_tokens=2500,
                        temperature=st.session_state.temperature,
                        stream=True
                    )

                    def response_generator():
                        for chunk in stream:
                            if chunk.choices and len(chunk.choices) > 0:
                                delta = chunk.choices[0].delta
                                if delta and delta.content:
                                    yield delta.content

                    full_response = st.write_stream(response_generator())
                else:
                    with st.spinner("CodePilot is thinking..."):
                        response = client.chat.completions.create(
                            model=model,
                            messages=messages_payload,
                            max_tokens=2500,
                            temperature=st.session_state.temperature
                        )
                        full_response = response.choices[0].message.content or "No response received."
                        st.markdown(full_response)

                if full_response:
                    chat["messages"].append({
                        "role": "assistant",
                        "content": full_response
                    })
                    save_message_to_db(st.session_state[user_active_chat], "assistant", full_response)

            except Exception as error:
                st.session_state.api_error = str(error)
                st.rerun()

        st.rerun()


# ===================== ERROR & RETRY HANDLER =====================

if "api_error" in st.session_state:
    st.error(f"⚠️ Nebius API Error: {st.session_state.api_error}")
    err_col1, err_col2 = st.columns([1, 4])
    with err_col1:
        if st.button("🔄  Retry Request", key="retry_btn", use_container_width=True):
            del st.session_state.api_error
            st.session_state.pending_generation = True
            st.rerun()
    with err_col2:
        if st.button("Dismiss", key="dismiss_err_btn"):
            del st.session_state.api_error
            st.rerun()


# ===================== CHAT INPUT BAR =====================

prompt = st.chat_input("Message CodePilot AI (Enter to send, Shift+Enter for newline)...")

if prompt:
    send_prompt(prompt)

st.markdown(
    '<div style="text-align: center; color: #7289ab; font-size: 11.5px; margin-top: 14px;">'
    'CodePilot AI can make mistakes. Verify critical code before deploying.'
    '</div>',
    unsafe_allow_html=True
)
