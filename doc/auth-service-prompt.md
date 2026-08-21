---
title: "Auth – Központi Authentication Mikroszerviz"
description: "Bővíthető authentication szolgáltatás Google OAuth 2.0 / OpenID Connect belépéssel; a többi mikroszerviz csak JWT tokent ellenőriz"
type: "service-prompt"
status: "tervezett"
port: 8007
language: "HU"
last_updated: "2026-07-15"
depends_on: [vision-spec.md, invoice-core-spec.md]
related: [INDEX.md, vision-prompt.md, invoice-core-prompt.md, bank-prompt.md]
tags: [auth, google, oauth2, openid-connect, jwt, fastapi, security]
---

# Auth – Központi Authentication Mikroszerviz - Prompt

Implementálni kell egy robusztus, Python-alapú authentication mikroszervizt, mert a Tiro rendszer **minden végponthívását authenticálni kell**.

A szolgáltatás legyen **bővíthető** (provider architektúra), első körben csak **Google Authentication** (Google OAuth 2.0 / OpenID Connect) támogatással.

A mikroszervizes architektúra best practice-ét kell követni:
- **Csak ez az egy Authentication Service kommunikál közvetlenül a Google-lel** (OAuth 2.0 authorization code flow, callback kezelés).
- Sikeres belépés után a szolgáltatás **JWT tokent állít ki** (access + refresh token).
- **A többi mikroszerviz nem hívja a Google-t**, hanem kizárólag a kiállított JWT tokent ellenőrzi lokálisan (aláírás-validálás, lejárat, claims).

A szolgáltatáshoz készüljön CLI és FastAPI REST interface.

A projektstruktúra kövesse a bank projektet.

---

## 🔗 Wiki Linkek
- **Minta projekt**: [[bank-prompt.md|Bank Prompt]] | [[bank-spec.md|Bank Spec]] (projektstruktúra alapja)
- **Frontend (login UI)**: [[vision-spec.md|Vision Spec]] → [[vision-prompt.md|Vision Prompt]]
- **Védendő szolgáltatások (JWT ellenőrzés)**: [[invoice-core-spec.md|Invoice-Core Spec]] · [[nav-invoice-spec.md|NAV Invoice Spec]] · [[invoice-file-filter-spec.md|Invoice-File-Filter Spec]] · [[attachment-downloader-spec.md|Attachment Downloader Spec]] · [[bank-spec.md|Bank Spec]] · [[uploader-spec.md|Uploader Spec]]
- **Specifikáció**: [[auth-service-spec.md|Auth Service Spec]]
- **Login oldal minta**: [NiceAdmin auth-login](https://bootstrapmade.com/content/demo/NiceAdmin/auth-login.html) → `vision/templates/login.html`
- **Projekt Index**: [[INDEX.md|Tiro Index]]
