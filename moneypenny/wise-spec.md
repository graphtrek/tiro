---
title: "Specifikáció: Wise Integráció Microservice"
description: "Wise banki kivonatok letöltése és szinkronizálás a szamla-db ökoszisztémával"
language: "HU"
last_updated: "2026-06-10"
related: [INDEX.md, szamla-db-spec.md, wise-prompt.md]
---

# Prompt: Wise Integráció Microservice Fejlesztés

## Cél
A [Wise API dokumentáció](https://docs.wise.com/api-reference) alapján implementálni egy robusztus, Python-alapú microservicot CLI és FastAPI használatával, amely automatizálja a Wise banki kivonatai letöltését, és szinkronizálja a tranzakciós adatokat a meglévő `szamla-db` ökoszisztémával.

## Szerepkör és kontextus
Te egy Senior Python Backend Engineer vagy. A feladatod egy olyan microservice fejlesztése, amely adatbeolgatási hídként funkcionál a Wise API és a `szamla-db` orchestrátor között. Ez a szolgáltatás a Moneypenny automatizálási folyamatának kritikus része, amely biztosítja, hogy a banki mozgások pontosan tükröződjenek az accounting adatbázisban.

## Részletes követelmények

### 1. Hitelesítés és kapcsolat
- Implementálj egy biztonságos kapcsolatot a Wise API-hoz technikai felhasználói hitelesítéssel (API Key/OAuth2).
- Támogasd a konfigurációt környezeti változókon keresztül (pl. `WISE_API_KEY`, `WISE_ACCOUNT_ID`).

### 2. Adatkinyerés (Ingestion)
- Szerezz meg tranzakció előzményeket/banki kivonatokat a Wise API-ból.
- Támogasd a dátumintervallum szűrést (`start_date`, `end_date`) az iteratív szinkronizálás lehetővé tétele érdekében.
- Implementálj hibakezelést és újrapróbálási logikát az API kapcsolati hibákkal szemben.

### 3. Adatátalakítás és mapolás
- Parsolj ki a Wise JSON választ egy strukturált Pydantic modelbe.
- Mapold a Wise tranzakció mezőket a `szamla-db` sémájához:
    - **Tranzakció összege és pénzneme** $\rightarrow$ `invoices.amount_total`
    - **Partner információk** $\rightarrow$ `suppliers.name`, `customers.name`, `address`, `tax_id`
    - **Tranzakció dátuma** $\rightarrow$ `invoices.invoice_date`
    - **Referencia/Leírás** $\rightarrow$ Metadata a megesezés logikához.

### 4. Adatbázis integráció és orchestráció
A szolgáltatásnak a `szamla-db` PostgreSQL példányával kell interakálnia az adatok konzisztenciája érdekében:
- **Idempotencia:** Győződj meg róla, hogy ugyanazt a Wise tranzakciót nem olvassák be többször. Ellenőrizd a meglévő `nav_transaction_id` vagy egyoszerű metaadatokat a beszúrás előtt.
- **Entitás megelőzés:**
    - **Számlás partnerek/Ügyfelek:** Ha egy partner nem található a `suppliers` vagy a `customers` táblákban, hozz létre egy új rekordot a Wise tranzakció részletei alapján.
    - **Számlák:** Hozz létre új bejegyzéseket az `invoices` táblában, összekötve őket a (új vagy meglévő) `supplier_id` és `customer_id` azonosítókkal.
- **Státusz kezelés:** Jelölj meg tranzakciókat szinkronizáltnak/feldolgozottnak.

## Technológiai stack
- **Nyelv:** Python 3.10+
- **Framework:** FastAPI (RESTful végpontokhoz)
- **CLI:** Typer (CLI kezeléshez)
- **ORM:** SQLAlchemy 2.0+ (aszkron支援álással)
- **Adatvalidáció:** Pydantic v2
- **Környezetkezelés:** `python-dotenv`
- **Adatbázis:** PostgreSQL (Primary)

## API Interface (tervezett)
- `GET /health`: Állapotellenőrző végpont.
- `POST /sync`: Elindítja a szinkronizálási folyamatot egy megadott dátumintervallumhoz.
- `GET /transactions/{transaction_id}`: Lekérdezi egy feldolgozott tranzakció részleteit.

## CLI Interface (tervezett)
- `sync --start-date <date> --end-date <date>`: Megindítja a szinkronizálást.
- `list-transactions --last <n>`: Listázza a legutóbbi feldolgozott tranzakciókat.
- `status`: Megtekintheti az utolsó szinkronizálás állapotát.

## Sikerfeltételek
- Sikeres hitelesítés és adatmegszerzés a Wise-tól.
- Pontos adatmapolás az `invoices`, `suppliers` és `customers` táblákhoz.
- Nincs duplikált rekord létrehozása az adatbázisban.
- A szinkronizálási folyamat umfassító logolása (indulás, siker/hiba, feldolgozott rekordok száma).

---

## 🔗 Wiki Linkek
- **Prompt**: [[wise-prompt.md|Wise Integráció Prompt]]
- **Adatbeolvasási híd**: Wise API → közvetlen írás a [[szamla-db-spec.md|Szamla-DB]] PostgreSQL példányába
- **Önálló belépési pont**: `POST /sync` (nem a szamla-db hívja)
- **Wise API Docs**: https://docs.wise.com/api-reference
- **Projekt Index**: [[INDEX.md|Moneypenny - Mikorszervízek Indexe]]