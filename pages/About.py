import streamlit as st

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Névjegy", page_icon="ℹ️", layout="wide", menu_items={})

# ── CSS (matches main app style) ───────────────────────────────────────────────
st.markdown(
    "<style>"
    "section[data-testid='stSidebar'] > div:first-child { padding-top: 0.25rem; }"
    "[data-testid='stSidebarHeader'] { display: none; }"
    "[data-testid='stAppDeployButton'] { display: none; }"
    "footer { display: none; }"
    ".stMenuVersionCopyButton { display: none; }"
    "html, body, [class*='css'] { font-size: 18px; }"
    ".stMarkdown p, .stMarkdown li { font-size: 1.1rem; }"
    "[data-testid='stSidebarNav'] { display: none; }"
    "section[data-testid='stSidebar'] .stToggle label p { font-size: 0.78rem !important; }"
    "section[data-testid='stSidebar'] .stButton button { font-size: 0.78rem !important; }"
    "section[data-testid='stSidebar'] .stExpander summary { font-size: 0.85rem !important; }"
    "section[data-testid='stSidebar'] h2 { font-size: 1rem !important; }"
    ".highlight-box { background: linear-gradient(135deg, #1a1f2e 0%, #1e2d1e 100%); border-left: 4px solid #4ade80; border-radius: 0.5rem; padding: 1.2rem 1.5rem; margin: 1.5rem 0; }"
    ".price-box { background: linear-gradient(135deg, #1a1f2e 0%, #1f1f2e 100%); border: 2px solid #60a5fa; border-radius: 0.75rem; padding: 1.5rem 2rem; margin: 1.5rem 0; text-align: center; }"
    ".price-amount { font-size: 3rem; font-weight: 800; color: #60a5fa; line-height: 1.1; }"
    ".price-label { font-size: 1rem; color: #94a3b8; margin-top: 0.25rem; }"
    ".risk-box { background-color: #2d1515; border-left: 4px solid #ff6b6b; border-radius: 0.5rem; padding: 1rem 1.5rem; margin: 1rem 0; }"
    "</style>",
    unsafe_allow_html=True,
)

# ── Navigation dropdown ────────────────────────────────────────────────────────
with st.sidebar:
    _PAGES = {
        "💬 Chat": "Chat.py",
        "📁 DropBox": "pages/DropBox.py",
        "📋 Logs": "pages/Logs.py",
        "ℹ️ Névjegy": "pages/About.py",
    }
    _nav = st.selectbox("Page", list(_PAGES.keys()), index=3, label_visibility="collapsed")
    if _nav != "ℹ️ Névjegy":
        st.switch_page(_PAGES[_nav])

# ── Page content ───────────────────────────────────────────────────────────────
st.title("ℹ️ Miért válassza a Privát AI megoldást?")

st.markdown(
    "<div class='highlight-box'>"
    "<strong style='font-size:1.25rem;'>Az Ön adatai soha nem hagyják el a vállalatát.</strong><br>"
    "Teljes adatvédelem, korlátlan AI-használat — a saját szerveren, a saját feltételek szerint."
    "</div>",
    unsafe_allow_html=True,
)

# ── Section 1 ─────────────────────────────────────────────────────────────────
st.header("🔒 Az adatvédelem alapkérdése")

st.markdown("""
A legtöbb vállalat ma már olyan felhőalapú AI-eszközöket használ, mint a ChatGPT, a Google Gemini
vagy a Microsoft Copilot. Ezek kényelmesek — de komoly kockázatot rejtenek.

**Amikor felhős AI-t használ, az alábbi adatok kerülhetnek idegen szerverekre:**

- Szerződések, ajánlatok, üzleti tervek
- Pénzügyi kimutatások, belső riportok
- Munkavállalói adatok, HR-dokumentumok
- Ügyféllisták, kapcsolattartói adatok
""")

st.markdown(
    "<div class='risk-box'>"
    "A felhős AI-szolgáltatók feltételei szerint az Önnek beküldött adatokat felhasználhatják "
    "modelljeik fejlesztésére, auditálhatják harmadik felek, és kiszolgáltatottak lehetnek "
    "adatvédelmi incidenseknek. Ez GDPR-kockázatot és üzleti titoksértést jelent."
    "</div>",
    unsafe_allow_html=True,
)

# ── Section 2 ─────────────────────────────────────────────────────────────────
st.header("🏢 Teljes kontroll, nulla kockázat")

st.markdown("""
A Privát AI rendszer az **Ön saját szerverén vagy adatközpontjában** fut. Egyetlen byte sem
kerül ki a vállalati hálózatból.

**Mit jelent ez a gyakorlatban?**

- **Adatok helyben maradnak** — a modellek a saját infrastruktúrán futnak, internet-kapcsolat nélkül is
- **Vezető és IT-admin teljes rálátása** — ki, mikor, mit kérdezett az AI-tól (auditnapló)
- **Nincs külső adatmegosztás** — sem az AI-fejlesztőnek, sem más harmadik félnek
- **GDPR-kompatibilis alapból** — az adatkezelés teljes mértékben az Ön irányítása alatt áll
- **Nincs szállítófüggőség** — ha az OpenAI megváltoztatja feltételeit, az Önre nem vonatkozik
""")

# ── Section 3 ─────────────────────────────────────────────────────────────────
st.header("📈 Üzleti előnyök")

col1, col2 = st.columns(2)

with col1:
    st.markdown("""
**Produktivitás**
- Dokumentumok elemzése percek alatt
- E-mailek, jelentések gyors megírása
- Keresés a feltöltött céges anyagokban
- Kódfejlesztés és technikai támogatás

**Kiszámítható költség**
- Havi fix díj, nincs meglepetés
- Korlátlan lekérdezés — per-query díj nincs
- Nincsenek rejtett API-költségek
""")

with col2:
    st.markdown("""
**Testreszabhatóság**
- Saját rendszerutasítások és hangnem
- Céges tudásbázis feltölthető (PDF, Word, Excel...)
- Modellek cserélhetők az igények szerint

**Biztonság**
- Alkalmazottak bátran használhatják érzékeny anyagokhoz is
- Belső auditnapló minden tevékenységről
- Hozzáférés-kezelés IT-admin szinten
""")

# ── Section 4 ─────────────────────────────────────────────────────────────────
st.header("💶 Árazás")

col_price, col_details = st.columns([1, 2])

with col_price:
    st.markdown(
        "<div class='price-box'>"
        "<div class='price-amount'>80 €</div>"
        "<div class='price-label'>felhasználó / hónap</div>"
        "</div>",
        unsafe_allow_html=True,
    )

with col_details:
    st.markdown("""
**Ami benne van:**

- Korlátlan AI-használat — nincs per-lekérdezés díj
- Telepítés az Ön saját szerverén vagy adatközpontjában
- Dokumentumfeltöltés és szemantikus keresés (RAG)
- Auditnapló és felhasználókövetés
- Több AI-modell elérhetősége (chat, kód, látás)

**Feltételek:**
- Minimum **5 felhasználótól** igénybe vehető
- Az infrastruktúra (szerver) biztosítása az ügyfél feladata
- Egyszeri telepítési és beállítási díj külön egyeztetés szerint
""")

# ── Section 5 ─────────────────────────────────────────────────────────────────
st.header("⚙️ Technikai jellemzők")

st.markdown("""
| Jellemző | Részlet |
|---|---|
| **AI modellek** | Mistral, Qwen és más nyílt forráskódú modellek |
| **Dokumentumkeresés** | PDF, Word, Excel, Markdown és más formátumok |
| **Webes keresés** | Opcionálisan engedélyezhető (DuckDuckGo) |
| **Auditnapló** | Minden lekérdezés és esemény naplózva (Logs oldal) |
| **Telepítési mód** | On-premise — ügyfél saját szervere vagy privát cloud |
| **Felhasználói felület** | Böngészőalapú, telepítés nélkül használható |
""")

# ── CTA ───────────────────────────────────────────────────────────────────────
st.divider()

st.markdown(
    "<div class='highlight-box'>"
    "<strong>Érdekli a megoldás?</strong><br><br>"
    "Vegye fel velünk a kapcsolatot egy ingyenes bemutatóért, és megmutatjuk, hogyan illeszkedik "
    "a Privát AI a vállalata munkafolyamataiba — az Ön adatainak teljes védelmével."
    "</div>",
    unsafe_allow_html=True,
)
