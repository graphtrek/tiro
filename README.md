# Nothing Gets Out AI

> **GDPR-konform, on-premise AI asszisztens vállalkozások számára**

Minden adat a saját szerveren marad — csevegések, feltöltött dokumentumok és e-mailek soha nem hagyják el a vállalat infrastruktúráját. Biztonságos alternatíva a ChatGPT, Gemini és Copilot felhőalapú szolgáltatásokkal szemben.

---

## Üzleti funkcionalitás

### Adatvédelem és GDPR-megfelelőség

Az alkalmazás teljesen on-premise üzemel: nincs felhőbe küldött adat, nincs külső naplózás, nincs harmadik fél általi adatgyűjtés. Az összes dokumentum, e-mail és beszélgetési előzmény kizárólag a vállalat saját szerverén tárolódik. Az LLM inferencia is egy dedikált, izolált végponton (Scaleway) fut.

---

### Chat módok

#### Internet mód
Az asszisztens minden kérdés megválaszolásakor valós idejű webes keresést végez (DuckDuckGo), majd az aktuális találatokat beépíti a kontextusba, mielőtt az LLM-hez továbbítja a kérdést. Az eredmény naprakész, internetre támaszkodó válasz — felhasználói API kulcs vagy előfizetés nélkül.

#### DropBox mód
A felhasználó PDF, DOCX, XLSX, TXT és Markdown fájlokat tölthet fel. Az alkalmazás ezeket feldolgozza, szöveg-darabokra bontja, és szemantikus vektoros indexbe szervezi. Kérdés feltevésekor a rendszer a leginkább releváns dokumentum-részleteket keresi ki, és azokat nyújtja kontextusként az LLM-nek — így a vállalati tudásbázis közvetlenül elérhető az AI számára.

#### Gmail mód
Az asszisztens teljes hozzáféréssel rendelkezik a csatlakoztatott Gmail-fiókhoz. Természetes nyelven adott utasítások alapján képes:
- e-maileket listázni, megnyitni, keresni,
- új üzenetet írni és elküldeni,
- e-mailre válaszolni,
- üzeneteket cimkézni, olvasottnak jelölni,
- e-maileket a kukába helyezni.

A műveleteket az LLM koordinálja automatikus eszközhívás-láncolattal, egészen addig, amíg a feladatot be nem fejezi.

#### Google Drive mód
Az asszisztens hozzáfér a csatlakoztatott Google Drive-hoz. Természetes nyelven adott utasítások alapján képes:
- fájlokat és mappákat listázni, keresni,
- fájl metaadatait lekérdezni (méret, módosítás dátuma, megosztás),
- fájlok szöveges tartalmát olvasni (Google Docs, Sheets, sima szöveg, CSV),
- új fájlt feltölteni vagy mappát létrehozni,
- fájlt áthelyezni, másolni,
- fájlt a kukába helyezni,
- fájlt megosztani egy Google-fiókkal (olvasó / szerkesztő / megjegyzés).

A Drive-integráció közvetlenül elérhető a chat felületen (oldalsáv → Drive kontextus), és MCP szerveren keresztül VS Code GitHub Copilot Agentből is hívható.

---

### Képfeldolgozás (Vision)

A Mistral modell multimodális képességeinek köszönhetően képek csatolhatók a chat üzenetekhez. Az asszisztens elemzi, leírja, összehasonlítja az uploadolt képeket, és válaszokat ad rájuk a szöveges kéréssel együtt.

---

### Token-használat követése

Minden LLM-hívás bemeneti és kimeneti token-száma naplózásra kerül és az oldalsávban megjelenik. Ez lehetővé teszi a vállalat számára, hogy nyomon kövesse az AI-használat mértékét és költségeit.

---

### Dinamikus programgenerátor

A **Programs** oldalon a felhasználó természetes nyelven leírhat egy FastAPI-alapú mikroszolgáltatást, amelyet a Qwen3-Coder modell automatikusan legenerál, lemezre ment és azonnal el is indít. A generált programok hozzáférnek a Gmail- és Google Drive-segédfüggvényekhez, valamint a közös naplózóhoz.

**Generált program életciklusa:**
- Névmegadás, leírás, követelmények és futtatási mód (service / on_demand) megadása
- Kódgenerálás Qwen3-Coder-rel → egyedi ID + port kiosztása → `main.py` + `manifest.json` mentése
- Start / Stop gombokkal indítható és leállítható az uvicorn-alapú szerver
- Beépített kódszerkesztő: a forráskód közvetlenül szerkeszthető és mentehető a böngészőből
- Valós idejű log néző az egyes programok kimenetéhez

**Módosítás funkció:**
Minden generált programhoz elérhető egy **✏️ Modify** gomb, amely előtölti az összes beviteli mezőt (név, leírás, követelmények, mód). Küldéskor az alkalmazás automatikusan eldönti:
- **Csak a leírás változott** → a program kódja helyben újragenerálódik (azonos ID, port, név megmarad)
- **Bármi más is változott** (név / követelmények / mód) → új program jön létre

### Log néző

Beépített, valós idejű log megjelenítő, amely szűrhető naplózási szint, keresési kifejezés és dátumtartomány szerint. Segíti a rendszergazdákat az alkalmazás működésének figyelemmel kísérésében — közvetlenül a böngészőből, terminálhozzáférés nélkül.

---

### MCP szerverek (VS Code Copilot Agent integráció)

A Gmail- és Google Drive-eszközök MCP (Model Context Protocol) szerveren keresztül is elérhetők, így VS Code GitHub Copilot Agentből közvetlenül hívhatók. Ez lehetővé teszi a fejlesztőknek, hogy kódírás közben is kezeljék a postaládájukat és a Drive-tartalmat az IDE-ből.

| MCP szerver | Eszközök száma | Indítófájl |
|---|---|---|
| `gmail` | 9 | `helpers/gmail_mcp_server.py` |
| `gdrive` | 9 | `helpers/drive_mcp_server.py` |

---

## Technológiai stack

| Technológia | Verzió | Szerepe |
|---|---|---|
| **[Streamlit](https://streamlit.io)** | 1.55 | Frontend / UI |
| **[LangChain](https://www.langchain.com)** | legújabb | LLM pipeline, RAG workflow |
| **[ChromaDB](https://www.trychroma.com)** | legújabb | Vektoros adatbázis |
| **[OpenAI SDK](https://github.com/openai/openai-python)** | 2.30 | LLM API kliens |
| **[DuckDuckGo Search](https://pypi.org/project/duckduckgo-search/)** | legújabb | Webes keresés |
| **[Gmail API](https://developers.google.com/gmail/api)** | v1 | E-mail integráció |
| **[Google Drive API](https://developers.google.com/drive/api)** | v3 | Fájlkezelés, megosztás |
| **[FastMCP](https://github.com/jlowin/fastmcp)** | legújabb | MCP szerver |
| **[FastAPI](https://fastapi.tiangolo.com)** | legújabb | Manager API + generált programok |
| **[Docker](https://www.docker.com)** | legújabb | Konténerizáció |

---

### [Streamlit](https://streamlit.io)
Python-alapú webes alkalmazás-keretrendszer, amely lehetővé teszi interaktív adatvizualizációs és AI alkalmazások gyors fejlesztését kizárólag Python kóddal. Natívan támogatja a session state kezelést, oldalnavigációt és valós idejű UI frissítéseket.

### [LangChain](https://www.langchain.com)
Nyílt forráskódú keretrendszer LLM-alapú alkalmazások felépítéséhez. Az alkalmazásban dokumentum-betöltésre (PDF, DOCX, XLSX, TXT, MD), szöveg-darabolásra (`RecursiveCharacterTextSplitter`), ChromaDB integrációra és webes keresésre (`DuckDuckGoSearchResults`) használjuk. A RAG pipeline teljes egészében LangChain komponensekre épül.

### [ChromaDB](https://www.trychroma.com)
Nyílt forráskódú, helyi vektoros adatbázis szemantikus kereséshez. Az alkalmazás négy kollekcióban tárol adatot: dokumentum-indexek (`dropbox_docs`), indexelési metaadatok (`index_stats`), token-használati napló (`usage_history`) és felhasználói beállítások (`chat_settings`). Az embedding modell: ONNX MiniLM-L6-v2, amely a Docker image-be van beépítve a gyors indulás érdekében.

### [OpenAI SDK](https://github.com/openai/openai-python) ([Scaleway](https://www.scaleway.com/en/generative-apis/) inference)
Az OpenAI Python SDK-t Scaleway saját inferencia végpontjára irányítja egy egyedi `BASE_URL` és `API_KEY` segítségével. Ez lehetővé teszi az OpenAI-kompatibilis API használatát anélkül, hogy az adatok az OpenAI szervereire kerülnének.

#### Használt modellek

| Modell | Képességek |
|---|---|
| `mistral-small-3.2-24b-instruct-2506` | Chat, kód, képelemzés (vision), streaming |
| `qwen3-coder-30b-a3b-instruct` | Chat, kódgenerálás, streaming |

### [DuckDuckGo Search](https://pypi.org/project/duckduckgo-search/)
Privátszféra-barát keresőmotor-integráció, amely nem igényel API kulcsot vagy regisztrációt. Az Internet módban minden felhasználói kérdéshez automatikusan webes keresést végez, és az eredményeket injektálja az LLM kontextusába.

### [Gmail API](https://developers.google.com/gmail/api) (Google)
A Google hivatalos REST API-ja Gmail-műveletek végrehajtásához. Az alkalmazás OAuth2 protokollon keresztül kap felhatalmazást, és a `gmail.modify` jogosultsági hatókörrel rendelkezik. A hozzáférési token helyileg tárolódik (`token.json`).

### [Google Drive API](https://developers.google.com/drive/api) v3 (Google)
A Google hivatalos REST API-ja Drive-fájlok kezeléséhez. Az alkalmazás OAuth2 protokollon hitelesít, és a `drive` (teljes hozzáférés) hatókörrel rendelkezik. A token a Gmail-tokennel közös `token.json` fájlban tárolódik — az `auth_drive.py` egyszeri futtatása kombinált (`gmail.modify` + `drive`) scope-okkal frissíti azt, így mindkét service egyszerre használható. A Drive-integráció elérhető közvetlenül a Streamlit chat felületről és MCP szerveren keresztül is.

### [FastMCP](https://github.com/jlowin/fastmcp)
A Model Context Protocol (MCP) Python implementációja. Az alkalmazás két MCP szervert regisztrál `stdio` transzporton: `gmail` (Gmail-műveletek) és `gdrive` (Drive-műveletek). Mindkettő közvetlenül elérhető VS Code GitHub Copilot Agent-ből.

### [Docker](https://www.docker.com) és [Docker Compose](https://docs.docker.com/compose/)
Az alkalmazás Docker konténerben fut `python:3.12-slim` alapképre építve. Az ONNX embedding modell a build során a konténer-image-be kerül, így az első indítás is azonnali. A `docker-compose.yml` kezeli a volume-csatolásokat (feltöltések, vektoros adatbázis, naplók, OAuth tokenek).

---

## Architektúra

```
Chat.py  ── Streamlit belépési pont
│
├── helpers/chat_config.py       Konfiguráció, OpenAI és LangChain kliensek
├── helpers/chat_prompts.py      Rendszer-promptok (DropBox / Internet / Gmail módhoz)
├── helpers/chat_settings.py     Beállítások mentése/betöltése ChromaDB-ből
├── helpers/chat_context.py      Kontextusépítés: RAG keresés + webkeresés + üzenet-összeállítás
├── helpers/chat_handlers.py     Gmail eszközhívás-láncolat, token-stream kezelő
├── helpers/chat_ui.py           Streamlit UI komponensek
├── helpers/chat_utils.py        Token-becslés, kontextus-nyirbálás, üzenet-formázás
│
├── helpers/rag_utils_langchain.py   Dokumentum-indexelés, ChromaDB keresés, webkeresés, token-napló
│
├── helpers/gmail_utils.py       Gmail API hívások (lista, olvasás, küldés, válasz, cimke, törlés)
├── helpers/auth_gmail.py        Egyszeri OAuth2 hozzájárulás-kérő segédprogram (gmail.modify)
├── helpers/gmail_mcp_server.py  FastMCP szerver: Gmail eszközök MCP-n keresztül
│
├── helpers/drive_utils.py       Drive API hívások (lista, olvasás, feltöltés, mozgatás, megosztás)
├── helpers/auth_drive.py        Egyszeri OAuth2 hozzájárulás-kérő segédprogram (gmail.modify + drive)
├── helpers/drive_mcp_server.py  FastMCP szerver: Drive eszközök MCP-n keresztül
│
├── manager_api.py               FastAPI Manager API (port 8500) — programgenerálás és életciklus
├── helpers/program_generator.py Qwen3-Coder alapú kódgenerálás
├── helpers/program_manager.py   Program létrehozás, indítás, leállítás, törlés, módosítás, logok
├── generated_programs/          Generált FastAPI programok ({slug}-{id}/main.py + manifest.json)
│
├── pages/Programs.py            Dinamikus programgenerátor UI (generálás, módosítás, kódszerkesztő)
├── pages/DropBox.py             Fájl feltöltés + index kezelő UI
├── pages/Logs.py                Napló néző UI
└── pages/About.py               Az alkalmazás bemutatása
```

### Manager API végpontok

| Metódus | Végpont | Leírás |
|---|---|---|
| `POST` | `/programs/generate` | Új program generálása Qwen-nel |
| `POST` | `/programs/{id}/regenerate` | Program kódjának helybeni újragenerálása (csak leírás változik) |
| `GET` | `/programs` | Összes program listázása |
| `GET` | `/programs/{id}` | Egy program részletei |
| `GET` | `/programs/{id}/code` | Forráskód lekérése |
| `PUT` | `/programs/{id}/code` | Forráskód frissítése |
| `POST` | `/programs/{id}/start` | Program indítása |
| `POST` | `/programs/{id}/stop` | Program leállítása |
| `DELETE` | `/programs/{id}` | Program törlése |
| `GET` | `/programs/{id}/logs` | Stdout/stderr napló |

### ChromaDB kollekciók

| Kollekció | Tartalom |
|---|---|
| `dropbox_docs` | Dokumentum-darabolatok és vektoros embeddingjük (RAG) |
| `index_stats` | Fájlonkénti indexelési metaadatok |
| `usage_history` | LLM hívásonkénti token-használat |
| `chat_settings` | Felhasználói beállítások (modell, chat mód) |

---

*Nothing Gets Out AI — Mert ami a cégen belül marad, az marad is.*
