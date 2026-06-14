---
title: "Specifikáció: Gmail PDF Letöltő Mikroszerviz"
description: "Gmail API-val PDF mellékleteket letöltő mikroszerviz"
language: "HU"
last_updated: "2026-06-09"
related: [INDEX.md, pdf-szamla-spec.md]
---

# Gmail PDF Letöltő Mikroszerviz - Specifikáció

> 🔗 **Hívási Lánc**: [[pdf-szamla-spec.md|← PDF Feldolgozó]]

> 📄 **Implementáció**: [attachment-downloader/README.md](../attachment-downloader/README.md)

---

## Szerepkör és kontextus
Te egy Email Integrációs Mérnök vagy. A feladatod Gmail API-n keresztül biztonságosan letölteni és szervezni a számlakonnektált PDF mellékleteket. Ez a szolgáltatás a Moneypenny rendszer adatgyűjtési végpontjaként működik, amely automatizálja a bejövő dokumentumok feldolgozásának kezdetét és gondoskodik az adatok szabványosított kezeléséről.

## Funkció
Gmail levélekből PDF mellékleteket letölt és menti szabványosított fájlnév-konvencióval.

## Request paraméterek
- `start_date` (YYYY-MM-DD) - szűrés kezdete
- `end_date` (YYYY-MM-DD) - szűrés vége  
- `output_dir` (optional) - alkönyvtár a `DOWNLOAD_ROOT_DIR` alatt (default: a gyökér maga)

## Fájlnév formátum
`YYYY-MM-DDD_eredeti_fajlnev.pdf`
- DDD = napi sorrendi szám (001-tól)

## Interface
- **CLI**: `attachment-downloader download --start 2026-05-01 --end 2026-05-31 --output ./pdfs/`
- **REST API**: 
  - `POST /api/v1/jobs` - feladat indítás
  - `GET /api/v1/jobs/{job_id}` - státusz
  - `GET /api/v1/jobs/{job_id}/logs` - logok

## Tech stack
- Python 3.10+
- FastAPI, Typer, google-api-python-client
- OAuth2 (Gmail)

## Függőségek
- OAuth2 token (credentials.json)
- Helyi fájlrendszer írási jog

---

## Kapcsolódások

### Hívási sorrend
```
szamla-db (MASTER)
  ↓ meghívja
nav-szamla
  ↓ meghívja
pdf-szamla
  ↓ meghívja
attachment-downloader (ÉN - VÉGPONT)
```

### Wiki linkek
- **Prompt**: [[attachment-downloader-prompt.md|Gmail Letöltő Prompt]]
- **Meghívva**: [[pdf-szamla-spec.md|PDF Feldolgozó]]
- **Lánc elődje**: [[nav-szamla-spec.md|NAV API]]
- **MASTER Orchestrator**: [[szamla-db-spec.md|Szamla-DB]]
- **Projekt Index**: [[INDEX.md|Moneypenny - Mikorszervízek Indexe]]
