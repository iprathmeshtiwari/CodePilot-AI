
import os
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

api_key = st.secrets.get(
    "NEBIUS_API_KEY", os.getenv("NEBIUS_API_KEY", "")
)
model = st.secrets.get(
    "NEBIUS_MODEL", os.getenv("NEBIUS_MODEL", "")
)
base_url = st.secrets.get(
    "NEBIUS_BASE_URL",
    os.getenv(
        "NEBIUS_BASE_URL",
        "https://api.tokenfactory.us-central1.nebius.com/v1/"
    )
)

if not api_key or not model:
    st.error("Nebius settings missing. Configure your app secrets.")
    st.stop()


# ===================== DATABASE AUTH SYSTEM =====================

DB_FILE = "codepilot_auth.db"

def init_auth_db():
    """Initializes the SQLite database for user authentication and creates a demo user."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    # Pre-seed a demo account if database is fresh
    c.execute("SELECT COUNT(*) FROM users")
    if c.fetchone()[0] == 0:
        salt = secrets.token_hex(16)
        pwd_hash = hashlib.pbkdf2_hmac(
            "sha256", "demo123".encode("utf-8"), bytes.fromhex(salt), 100000
        ).hex()
        c.execute(
            "INSERT INTO users (username, password_hash, salt) VALUES (?, ?, ?)",
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
        c.execute(
            "INSERT INTO users (username, password_hash, salt) VALUES (?, ?, ?)",
            (username, hashed, salt),
        )
        conn.commit()
        conn.close()
        return True, "Account created successfully! Please sign in."
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

# Initialize DB on load
init_auth_db()

# Initialize Auth State
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "username" not in st.session_state:
    st.session_state.username = None

# ===================== BASE FUTURISTIC THEME =====================

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

:root {
    color-scheme: dark;
}

/* UNIFIED CODEPILOT BACKGROUND */
html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"], section.main {
    font-family: 'Inter', sans-serif !important;
    background:
        radial-gradient(ellipse at 50% 0%, #1b2350 0%, transparent 45%),
        linear-gradient(145deg, #080c18, #0b1020 55%, #090e1b) !important;
    background-attachment: fixed !important;
    color: #eaf0ff !important;
}

[data-testid="stHeader"] {
    background: transparent !important;
}

[data-testid="stToolbar"] {
    right: 1rem;
}

.block-container {
    max-width: 1350px;
    padding: 2rem 2.5rem 6rem;
}

/* GLOBAL TEXT CONTRAST */
[data-testid="stMarkdownContainer"],
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li {
    color: #e2edff !important;
}

[data-testid="stMarkdownContainer"] h1,
[data-testid="stMarkdownContainer"] h2,
[data-testid="stMarkdownContainer"] h3,
[data-testid="stMarkdownContainer"] h4 {
    color: #ffffff !important;
    font-weight: 700;
}

/* ========================================================= */
/* FIX: SUGGESTION BUTTONS & GENERAL BUTTONS (NO WHITE PILLS) */
/* ========================================================= */
.stButton > button,
[data-testid="stBaseButton-secondary"],
[data-testid="stButton"] button,
button[kind="secondary"] {
    background: linear-gradient(135deg, #131f38 0%, #0f182c 100%) !important;
    background-color: #121c32 !important;
    border: 1px solid #2d416b !important;
    border-radius: 14px !important;
    min-height: 52px !important;
    padding: 12px 18px !important;
    box-shadow: 0 4px 18px rgba(0, 0, 0, 0.4) !important;
    transition: all 0.25s ease !important;
}

/* Crisp, high-contrast text inside suggestion buttons */
.stButton > button p,
.stButton > button span,
.stButton > button div,
[data-testid="stBaseButton-secondary"] p,
[data-testid="stBaseButton-secondary"] span,
[data-testid="stButton"] button p,
[data-testid="stButton"] button span {
    color: #f1f6ff !important;
    -webkit-text-fill-color: #f1f6ff !important;
    font-weight: 600 !important;
    font-size: 14px !important;
}

/* Hover glow effect for suggestion buttons */
.stButton > button:hover,
[data-testid="stBaseButton-secondary"]:hover,
[data-testid="stButton"] button:hover {
    background: linear-gradient(135deg, #1b294d 0%, #15223e 100%) !important;
    background-color: #1b294d !important;
    border-color: #38bdf8 !important;
    box-shadow: 0 0 22px rgba(56, 189, 248, 0.35) !important;
    transform: translateY(-2px) !important;
}

.stButton > button:hover p,
.stButton > button:hover span {
    color: #38bdf8 !important;
    -webkit-text-fill-color: #38bdf8 !important;
}

/* ========================================================= */
/* FIX: INPUT & TEXTAREA VISIBILITY (REMOVES WHITE BOXES)     */
/* ========================================================= */
[data-baseweb="input"],
[data-baseweb="input"] > div,
[data-baseweb="base-input"],
[data-baseweb="base-input"] > div,
[data-baseweb="textarea"],
[data-baseweb="textarea"] > div,
.stTextInput > div > div {
    background: #111a2e !important;
    background-color: #111a2e !important;
    border: 1px solid #2b3d64 !important;
    border-radius: 12px !important;
}

input, textarea {
    color: #ffffff !important;
    -webkit-text-fill-color: #ffffff !important;
    caret-color: #38bdf8 !important;
    font-size: 14px !important;
    background: transparent !important;
    background-color: transparent !important;
}

input::placeholder, textarea::placeholder {
    color: #8da4c4 !important;
    -webkit-text-fill-color: #8da4c4 !important;
    opacity: 1 !important;
}

/* Browser autofill fix */
input:-webkit-autofill,
input:-webkit-autofill:hover, 
input:-webkit-autofill:focus,
input:-webkit-autofill:active {
    -webkit-box-shadow: 0 0 0 1000px #111a2e inset !important;
    -webkit-text-fill-color: #ffffff !important;
    caret-color: #38bdf8 !important;
}

/* ========================================================= */
/* FIX: BOTTOM CHAT COMPOSER (ELIMINATES GIANT WHITE BAR)    */
/* ========================================================= */
[data-testid="stBottom"],
[data-testid="stBottom"] > div,
[data-testid="stBottomBlockContainer"] {
    background: transparent !important;
    background-color: transparent !important;
}

[data-testid="stChatInput"],
[data-testid="stChatInput"] > div,
[data-testid="stChatInput"] [data-baseweb="base-input"],
[data-testid="stChatInput"] [data-baseweb="textarea"] {
    background-color: #111a2e !important;
    background: #111a2e !important;
    border: 1px solid #374a73 !important;
    border-radius: 18px !important;
    box-shadow: 0 4px 25px rgba(0, 0, 0, 0.6) !important;
}

[data-testid="stChatInput"] textarea {
    background: transparent !important;
    background-color: transparent !important;
    color: #ffffff !important;
    -webkit-text-fill-color: #ffffff !important;
    caret-color: #38bdf8 !important;
    font-size: 15px !important;
}

[data-testid="stChatInput"] textarea::placeholder {
    color: #8fa5c7 !important;
    -webkit-text-fill-color: #8fa5c7 !important;
}

[data-testid="stChatInput"] button {
    background: linear-gradient(110deg, #5046ef, #783df0) !important;
    border: 1px solid #7567ff !important;
    color: #ffffff !important;
    border-radius: 10px !important;
}

[data-testid="stChatInput"] button svg {
    fill: #ffffff !important;
    color: #ffffff !important;
}

/* ========================================================= */
/* FIX: SIDEBAR TEXT & COMPONENT VISIBILITY                  */
/* ========================================================= */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0e1628 0%, #080d1a 100%) !important;
    border-right: 1px solid #213250 !important;
}

[data-testid="stSidebar"] > div {
    padding: 1.5rem 1rem;
}

[data-testid="stSidebar"] * {
    color: #dce7f8 !important;
}

[data-testid="stSidebar"] strong,
[data-testid="stSidebar"] b,
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {
    color: #ffffff !important;
    font-weight: 700 !important;
}

[data-testid="stSidebar"] .stCaption,
[data-testid="stSidebar"] .stCaption p,
[data-testid="stSidebar"] [data-testid="stCaptionContainer"],
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {
    color: #9cb3d8 !important;
    font-size: 13px !important;
}

/* Sidebar chat items */
[data-testid="stSidebar"] .stButton > button {
    background: #111a2f !important;
    border: 1px solid #253654 !important;
    border-radius: 11px !important;
    text-align: left !important;
    min-height: 40px !important;
    padding: 8px 12px !important;
    box-shadow: none !important;
}

[data-testid="stSidebar"] .stButton > button p,
[data-testid="stSidebar"] .stButton > button span {
    color: #e2edff !important;
    font-weight: 500 !important;
    font-size: 13px !important;
}

[data-testid="stSidebar"] .stButton > button:hover {
    background: #192440 !important;
    border-color: #635bff !important;
}

/* Sidebar Expanders */
[data-testid="stSidebar"] [data-testid="stExpander"],
[data-testid="stSidebar"] [data-testid="stExpander"] details,
[data-testid="stSidebar"] [data-testid="stExpander"] summary,
[data-testid="stSidebar"] [data-testid="stExpander"] details[open] > summary {
    background: #101a2f !important;
    background-color: #101a2f !important;
    color: #ffffff !important;
    border: 1px solid #233554 !important;
    border-radius: 12px !important;
}

[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover {
    background: #172440 !important;
}

[data-testid="stSidebar"] [data-testid="stExpander"] summary p,
[data-testid="stSidebar"] [data-testid="stExpander"] summary span {
    color: #ffffff !important;
    font-weight: 600 !important;
}

[data-testid="stSidebar"] [data-testid="stExpander"] summary svg {
    fill: #a0b6db !important;
}

/* BRANDING & HERO */
.brand {
    font-size: 26px;
    font-weight: 800;
    letter-spacing: -1px;
    color: #ffffff !important;
}

.brand span, .hero span {
    background: linear-gradient(90deg, #9485ff, #39d9ff);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}

.brand-sub {
    color: #9cb1d4 !important;
    font-size: 12px;
    margin: 5px 0 28px;
}

.hero {
    text-align: center;
    padding: 25px 0 20px;
}

.hero-icon {
    width: 86px;
    height: 86px;
    margin: 0 auto 20px;
    display: flex;
    justify-content: center;
    align-items: center;
    border-radius: 26px;
    font-size: 44px;
    background: linear-gradient(135deg, #203dd9, #6328cf 70%, #a12be8);
    border: 1px solid #8b83ff;
    box-shadow: 0 0 30px #584bff55;
}

.hero h1 {
    color: #f5f7ff !important;
    font-size: 42px;
    font-weight: 800;
    letter-spacing: -1.5px;
    margin: 0;
}

.hero p {
    color: #c0d3f8 !important;
    font-size: 17px;
    margin-top: 8px;
}

/* FEATURE CARDS */
.feature {
    background: linear-gradient(145deg, #151f35, #0f1729);
    border: 1px solid #2b3b5d;
    border-radius: 18px;
    padding: 22px 18px;
    min-height: 205px;
    transition: all .25s ease;
}

.feature:hover {
    border-color: #8175ff;
    box-shadow: 0 0 28px #5d4bff25;
    transform: translateY(-3px);
}

.feature-icon {
    width: 49px;
    height: 49px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 15px;
    font-size: 24px;
    margin-bottom: 18px;
}

.feature h3 {
    color: #f2f5ff !important;
    font-size: 16px;
    margin: 0 0 10px;
}

.feature p {
    color: #bdcbe4 !important;
    font-size: 13px;
    line-height: 1.8;
    margin: 0;
}

/* CHAT MESSAGES */
[data-testid="stChatMessage"] {
    background: linear-gradient(135deg, #121c30, #101829) !important;
    border: 1px solid #293956 !important;
    border-radius: 16px;
    padding: 18px;
    margin-bottom: 15px;
}

[data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] p {
    color: #e8efff !important;
    font-size: 15px;
    line-height: 1.8;
}

[data-testid="stChatMessage"] code {
    color: #76e6ff !important;
    background: #0a1323 !important;
}

[data-testid="stChatMessage"] pre {
    background: #080e1b !important;
    border: 1px solid #304264 !important;
    border-radius: 12px;
}

.status {
    display: inline-block;
    background: #102b2a;
    color: #78f2c0 !important;
    border: 1px solid #1f5b50;
    border-radius: 30px;
    padding: 9px 14px;
    font-size: 12px;
}

hr {
    border-color: #21314f !important;
}

.small-note {
    text-align: center;
    color: #94a6c7 !important;
    font-size: 11px;
    margin-top: 14px;
}
</style>
""", unsafe_allow_html=True)


# ===================== LOGIN SCREEN CONTROLLER =====================

if not st.session_state.authenticated:
    st.markdown("""
    <style>
    [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] {
        display: none !important;
    }

    .block-container {
        max-width: 480px !important;
        margin: 0 auto !important;
        padding-top: 4rem !important;
        padding-bottom: 3rem !important;
    }

    [data-testid="stTabs"] [data-baseweb="tab-list"] {
        display: flex !important;
        width: 100% !important;
        background: #0e1628 !important;
        border: 1px solid #233454 !important;
        border-radius: 14px !important;
        padding: 5px !important;
        gap: 6px !important;
        box-sizing: border-box !important;
    }

    [data-testid="stTabs"] [data-baseweb="tab"] {
        flex: 1 1 0% !important;
        display: flex !important;
        justify-content: center !important;
        align-items: center !important;
        height: 42px !important;
        background: transparent !important;
        border: none !important;
        border-radius: 10px !important;
        color: #8fa5cb !important;
        font-size: 14px !important;
        font-weight: 600 !important;
        padding: 0 10px !important;
    }

    [data-testid="stTabs"] [aria-selected="true"] {
        background: linear-gradient(135deg, #222d4f, #162038) !important;
        color: #39d9ff !important;
        border: 1px solid #3c5485 !important;
    }

    [data-testid="stTabs"] [data-baseweb="tab-highlight"],
    [data-testid="stTabs"] [data-baseweb="tab-border"] {
        display: none !important;
    }

    [data-testid="stForm"] {
        background: linear-gradient(160deg, #121c32 0%, #0d1424 100%) !important;
        border: 1px solid #27385a !important;
        border-radius: 20px !important;
        padding: 26px 26px 22px !important;
        box-shadow: 0 16px 40px rgba(0, 0, 0, 0.55) !important;
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
        box-shadow: 0 4px 20px rgba(99, 102, 241, 0.35) !important;
    }

    [data-testid="stFormSubmitButton"] > button p,
    [data-testid="stFormSubmitButton"] > button span {
        color: #ffffff !important;
        font-weight: 700 !important;
    }
    </style>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div class="hero">
        <div class="hero-icon">🤖</div>
        <h1>CodePilot <span>AI</span></h1>
        <p>Your AI coding workspace</p>
    </div>
    """, unsafe_allow_html=True)

    login_tab, signup_tab = st.tabs(["🔑 Sign In", "✨ Create Account"])

    # SIGN IN TAB
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

    # SIGN UP TAB
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

    # Demo Credentials Pill
    st.markdown("""
    <div style="background: rgba(16, 26, 47, 0.7); border: 1px solid #233555; border-radius: 12px; padding: 12px 14px; margin-top: 16px; text-align: center; font-size: 12px; color: #9ab0d6;">
        <span style="color: #38bdf8; font-weight: 600;">⚡ Quick Demo:</span>
        &nbsp; User: <code style="background: #090f1d; padding: 2px 6px; border-radius: 6px; color: #a5b4fc; border: 1px solid #243454;">demo</code>
        &nbsp;&bull;&nbsp; Pass: <code style="background: #090f1d; padding: 2px 6px; border-radius: 6px; color: #a5b4fc; border: 1px solid #243454;">demo123</code>
    </div>
    """, unsafe_allow_html=True)

    st.stop()


# ===================== NEBIUS CONFIG =====================

load_dotenv(override=True)

api_key = os.getenv("NEBIUS_API_KEY")
model = os.getenv("NEBIUS_MODEL")
base_url = os.getenv("NEBIUS_BASE_URL")

if not api_key or not model or not base_url:
    st.error("Nebius settings missing. Check your .env file.")
    st.stop()

client = OpenAI(
    api_key=api_key,
    base_url=base_url
)


# ===================== PER-USER SESSION STATE =====================

current_user = st.session_state.username
user_chat_store = f"chats_{current_user}"
user_active_chat = f"active_chat_{current_user}"

if user_chat_store not in st.session_state:
    initial_chat_id = str(uuid.uuid4())
    st.session_state[user_chat_store] = {
        initial_chat_id: {
            "title": "New Chat",
            "messages": []
        }
    }
    st.session_state[user_active_chat] = initial_chat_id

if "search_chats" not in st.session_state:
    st.session_state.search_chats = ""


def create_chat():
    chat_id = str(uuid.uuid4())
    st.session_state[user_chat_store][chat_id] = {
        "title": "New Chat",
        "messages": []
    }
    st.session_state[user_active_chat] = chat_id


# System prompt templates tailored for each developer mode
MODE_PROMPTS = {
    "💬 General": (
        "You are CodePilot AI, an elite coding assistant. Help users write, "
        "understand, and improve code. Use well-formatted markdown and fenced code blocks."
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

def send_prompt(prompt):
    chat = st.session_state[user_chat_store][
        st.session_state[user_active_chat]
    ]

    if not chat["messages"]:
        chat["title"] = prompt[:32] + (
            "..." if len(prompt) > 32 else ""
        )

    # Prefix user message with current mode if not General
    mode = st.session_state.get("active_mode", "💬 General")
    display_content = prompt

    chat["messages"].append({
        "role": "user",
        "content": display_content
    })

    # Pick the system prompt for the currently active mode
    active_system_prompt = MODE_PROMPTS.get(mode, MODE_PROMPTS["💬 General"])

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": active_system_prompt
                },
                *chat["messages"]
            ],
            max_tokens=2200
        )

        answer = response.choices[0].message.content

        if not answer:
            answer = "I couldn't generate a response. Please try again."

        chat["messages"].append({
            "role": "assistant",
            "content": answer
        })

    except Exception as error:
        chat["messages"].pop()
        st.session_state.api_error = str(error)

    st.rerun()


# ===================== SIDEBAR =====================

with st.sidebar:
    st.markdown(
        '<div class="brand">🤖 CodePilot <span>AI</span></div>'
        '<div class="brand-sub">Your AI coding workspace</div>',
        unsafe_allow_html=True
    )

    if st.button("＋   New Chat", use_container_width=True):
        create_chat()
        st.rerun()

    st.text_input(
        "Search chats",
        placeholder="🔎 Search conversations...",
        key="search_chats",
        label_visibility="collapsed"
    )

    st.markdown("### 🕘 Chat History")

    search = st.session_state.search_chats.lower().strip()
    chat_items = list(st.session_state[user_chat_store].items())
    chat_items.reverse()

    visible_chats = [
        (chat_id, ch)
        for chat_id, ch in chat_items
        if search in ch["title"].lower()
    ]

    if not visible_chats:
        st.caption("No matching chats.")

    for chat_id, ch in visible_chats:
        prefix = (
            "● " if chat_id == st.session_state[user_active_chat]
            else "▹ "
        )

        if st.button(
            prefix + ch["title"],
            key="history_" + chat_id,
            use_container_width=True
        ):
            st.session_state[user_active_chat] = chat_id
            st.rerun()

    st.divider()

    with st.expander("⚙️ Settings"):
        st.markdown("**AI Provider**")
        st.caption("Nebius Token Factory")
        st.markdown("**Model**")
        st.caption(model)
        st.caption("API key is loaded from .env")

    with st.expander("❔ Help"):
        st.caption("Ask questions about coding, debugging and projects.")
        st.caption("Select New Chat to start another conversation.")

    st.divider()

    # User Profile & Logout section
    st.markdown(f"**👤 {current_user}**")
    st.caption("Personal Workspace")

    if st.button("🚪  Sign Out", use_container_width=True, key="logout_btn"):
        st.session_state.authenticated = False
        st.session_state.username = None
        st.rerun()


# ===================== MAIN WORKSPACE =====================

chat = st.session_state[user_chat_store][
    st.session_state[user_active_chat]
]

left, right = st.columns([3, 1])

with left:
    st.caption("CODEPILOT AI  /  YOUR CODING WORKSPACE")

with right:
    st.markdown(
        '<div class="status">🟢 &nbsp; Nebius AI configured</div>',
        unsafe_allow_html=True
    )


# ===================== WELCOME SCREEN =====================

if not chat["messages"]:
    st.markdown("""
    <div class="hero">
        <div class="hero-icon">🤖</div>
        <h1>CodePilot <span>AI</span></h1>
        <p>Your AI coding assistant</p>
        <div class="description" style="max-width: 650px; margin: 14px auto; color: #b2c3e2; font-size: 15px; line-height: 1.9;">
            Write code, fix errors, learn new concepts, and build
            amazing projects with the power of Nebius AI.
        </div>
    </div>
    """, unsafe_allow_html=True)

    features = [
        (
            "💻", "#293fae", "Write Code",
            "Generate clean, efficient code in Python, JavaScript and more."
        ),
        (
            "🐛", "#087c65", "Debug & Fix",
            "Find errors, understand issues, and get solutions."
        ),
        (
            "📚", "#662bc1", "Learn & Explore",
            "Get clear explanations with examples and step-by-step guides."
        ),
        (
            "⚡", "#b97910", "Build Projects",
            "Plan features, design architecture, and create real-world projects."
        )
    ]

    columns = st.columns(4)

    for column, item in zip(columns, features):
        icon, color, title, description = item

        with column:
            st.markdown(f"""
            <div class="feature">
                <div class="feature-icon" style="background:{color}">
                    {icon}
                </div>
                <h3>{title}</h3>
                <p>{description}</p>
            </div>
            """, unsafe_allow_html=True)

    st.markdown(
        '<div class="section-label" style="color: #e8edff; font-weight: 600; font-size: 15px; margin: 28px 0 14px;">✨ &nbsp; Try asking something like</div>',
        unsafe_allow_html=True
    )

    suggestions = [
        "Write a Python program to sort a list",
        "Fix this error in my code",
        "Explain decorators in Python",
        "Create a Flask web app example"
    ]

    left_col, right_col = st.columns(2)

    for index, suggestion in enumerate(suggestions):
        column = left_col if index % 2 == 0 else right_col

        with column:
            if st.button(
                "✦  " + suggestion,
                key="suggestion_" + str(index),
                use_container_width=True
            ):
                send_prompt(suggestion)

else:
    st.markdown("## 💬 " + chat["title"])

    for message in chat["messages"]:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])


# ===================== API ERROR =====================

if "api_error" in st.session_state:
    st.error(f"Nebius API Error: {st.session_state.api_error}")
    del st.session_state.api_error

# ===================== CODING MODE SWITCHER =====================

if "active_mode" not in st.session_state:
    st.session_state.active_mode = "💬 General"

mode_cols = st.columns([1, 1, 1, 1])
modes = ["💬 General", "🔍 Explain", "🐛 Debug & Fix", "⚡ Optimize"]

for col, m in zip(mode_cols, modes):
    with col:
        is_active = (st.session_state.active_mode == m)
        label = f"● {m}" if is_active else m
        if st.button(label, key=f"mode_{m}", use_container_width=True):
            st.session_state.active_mode = m
            st.rerun()
            
# ===================== CHAT INPUT =====================

prompt = st.chat_input("Message CodePilot AI...")

if prompt:
    send_prompt(prompt)

st.markdown(
    '<div class="small-note">'
    'CodePilot AI can make mistakes. Verify important code before using it.'
    '</div>',
    unsafe_allow_html=True
)