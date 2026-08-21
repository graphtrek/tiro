---
title: “Vision – Tulajdonosi AI Platform”
description: “Tulajdonosi szintű pénzügyi AI Copilot — banki aggregáció, cashflow forecast, projekt profitabilitás, IBKR befektetések”
type: “service-prompt”
status: “tervezett”
port: 8009
language: “HU”
last_updated: “2026-06-18”
depends_on: [invoice-core-spec.md, srcprofit]
related: [INDEX.md, invoice-core-spec.md, invoice-core-prompt.md]
tags: [vision, dashboard, ai-copilot, fastapi, jinja2]
---

“Vision” szolgáltatás
(banki aggregáció + cashflow forecast + AI elemzés + projektprofitabilitás + tulajdonosi vagyonkép). 

Jelenleg az invoice-core van kész, illetve srcprofit néven https://srcprofit2.graphtrek.co/ 
futó IBKR befektetéseket nyomonkövető szolgáltatás user: admin pwd: Girafhus2

Kell készíteni egy új microservice-t a 8009-es portton vision névvel fastapi, jinja2 technológiával az invoice-core szolgáltatás mintájára ennek a feladata
hogy összegyűjtse az  high level információkat az invoice-core és az srcprofit szolgáltatásokból.

A Vison microservicenek:
- kezdőoldala ismertesse a koncepciót
- dasboard oldal mutatja high level adatokat az invoice-core ból és az srcprofit ból digrammokkal 
- lefúrás céljából legyen link az srcprofit és invoice-core alkalmazásokba


Adatok ami alapján a rendszer dolgozik
- bankszámla tranzakcióit (invoice-core) 
- számlák (invoice-core)
- befektetések (SrcProfit)
- futó projektjek (TODO)
- szerződések (TODO)
- cash-flow (invoice-core)

✅ Erste + Wise + IBKR + Kulcs Soft, EnableBankink stb összekötés egy helyen  
✅ Tulajdonosi szintű vagyonkimutatás több cégre  
✅ AI CFO chat (“Mennyi pénzt termel a cégcsoport?”)  
✅ Projektprofitabilitás automatikus számítása  
✅ Cash-flow előrejelzés Privát AI segítségével  
✅ Adóoptimalizálási és osztaléktervezési javaslatok

**“Tulajdonosi AI Copilot”**

Jellemző célcsoport ahol egy tulajdonosi körben több cég van, befektető cégek...

A tulajdonos nem szoftvert akar venni, hanem választ kapni olyan kérdésekre, mint:
- Mennyi készpénzem van összesen?
- Mennyi osztalékot vehetek ki cégenként?
- Melyik projektem a legnyereségesebb?
- Mikor fogy el a pénzem?
- Melyik költség nőtt meg?
- Melyik ügyfél termeli a profitot?
- Adókockázatok feltárása

 Hasonló rendszerek külföldön (pl.  Puzzle⁠,  Runway Financial,  Mosaic⁠).

## Önmagában nem a rendszerért kérünk pénzt hanem a szolgáltatásokért, az egyes témakörökben

## **1. Cash-flow előrejelzés**
- meddig elegendő a pénz
- mikor várható likviditási probléma
- várható havi egyenleg
## **2. Automatikus költségelemzés**
- mely költségek nőttek
- előfizetések
- szokatlan kiadások
## **3. Projekt profitabilitás**
 - Project A: +22% margin
 - Project B: veszteséges
## **4. CFO Owner Chat**
Kérdések:
- Mennyi pénzt költöttünk marketingre idén?
- Miért csökkent a profit?
- Melyik ügyfél a legnyereségesebb?
## **5. Adóoptimalizálási figyelmeztetések**
- osztalék időzítése
- ÁFA cash-flow
- beruházási lehetőségek
## **6. Tulajdonosi dashboard**
Tulajdonos számára:
- teljes vagyon
- céges pénzek
- Wise
- bankok
- IBKR
- projektek
### **7. AI alapú korai figyelmeztető rendszer**
- “3 hónapon belül cash-flow probléma várható”
- “A marketing ROI romlik”
- “Az ügyfélállomány koncentrációja veszélyes”

## Tanácsadói Workflow
A tulajdonosok látnak egy külső objektív képet a vagyonukról, stratégiai tanácsadás,
CTO támogatás, befektető cégek az általuk managel-t startup-ok pillanatnyi helyzetéről.

AI válaszol 
	↓
AI nem biztos felhívja a figyelmet a tanácsadásra
    ↓
Online tanácsadó (megkapja a kérdést és előre egyeztetett időpontban online válaszol)
    ↓
Speciális ügy
    ↓
Adótanácsadó / Ügyvéd / CFO (megkapják a kérdést és előre egyeztetett időpontban online válaszolnak)


## Árazás

három csomagot kínálnék (A tanácsadás előre tervezett időben):
- Starter: 149 000 Ft/hó havi 1 óra Online tanácsadó 
- Growth: 249 000 Ft/hó havi 1 óra CFO meeting 
- Executive: 499 000 Ft/hó havi 1 óra CFO, Jogász, Felsővezető


---

## 🔗 Wiki Linkek
- **Specifikáció**: [[vision-spec.md|Vision Spec]]
- **Fő adatforrás**: [[invoice-core-spec.md|Invoice-Core Spec]] → [[invoice-core-prompt.md|Invoice-Core Prompt]]
- **UI minta**: [[invoice-core-ui-spec.md|Invoice-Core UI Spec]] → [[invoice-core-ui-prompt.md|Invoice-Core UI Prompt]]
- **Külső adatforrás**: [SrcProfit](https://srcprofit2.graphtrek.co/) (IBKR befektetések, külső szolgáltatás)
- **Projekt Index**: [[INDEX.md|Tiro Index]]