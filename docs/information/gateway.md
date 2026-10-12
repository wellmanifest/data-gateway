---
{
  "schema": "wellmanifest.docs/document/v1",
  "id": "gateway",
  "kind": "information",
  "version": 1,
  "title": "Referencyjny gateway data-plane.line/v1",
  "status": "proposed",
  "owner": "wellmanifest/data-gateway",
  "created": "2026-10-12",
  "updated": "2026-10-12",
  "review_after": "2026-10-26",
  "source_revision": "bdf1a3bc46aa6ef2408249f4d5733760f864e7a7",
  "affected_repositories": [
    "wellmanifest/data-gateway"
  ],
  "evidence": [
    "https://github.com/wellmanifest/data-plane/blob/bdf1a3bc46aa6ef2408249f4d5733760f864e7a7/docs/information/line-format.md",
    "https://github.com/wellmanifest/data-plane/blob/bdf1a3bc46aa6ef2408249f4d5733760f864e7a7/contracts/operations.json",
    "https://github.com/wellmanifest/logs/blob/cd9d9558e09b9135ef92712096eb951fd524aa75/docs/ARCHITECTURE.md"
  ]
}
---

# Referencyjny gateway data-plane.line/v1

<!-- docs:section purpose -->
## Purpose

Wykonuje linie `typ: obiekt {zmienne}` standardu data-plane jednym kernelem dla
shell, REST, gRPC i MCP oraz zapisuje każde wykonanie jako zdarzenie audytu
`wellmanifest.logs/event/v1`. Repozytorium jest adopterem: standard i jego kod
pozostają w `wellmanifest/data-plane` i `wellmanifest/logs`.

<!-- docs:section scope -->
## Scope

Operacje `resource.publish` i `resource.read` z katalogu data-plane `/v2`; reszta
katalogu odpowiada `GW-UNSUPPORTED-001`. Jeden plik SQLite, jeden writer. Brak TLS,
zewnętrznego IdP, relay do PostgreSQL i GraphQL.

<!-- docs:section evidence -->
## Evidence

Piny w `upstream.lock.json` (commit i SHA-256 plików): data-plane `bdf1a3b`,
logs `cd9d955`, docs `ebe7501`. Testy `tests/test_gateway.py`: zachowanie kernela,
rollback efektów, koperta eventu domenowego, walidacja audytu pinowanym
`logs_check.validate_event`, adopcja katalogu `GW`, identyczne linie przez cztery
transporty, kodek `Line` zgodny z protoc, tokeny i bind tylko na loopback.

<!-- docs:section content -->
## Content

**Kernel.** `Kernel.execute(line, scopes)` przyjmuje wyłącznie linie żądań
(`classify == request`), mapuje je bezstratnie na wejście `/v2`, waliduje
`inputSchema`, sprawdza scopes operacji, wykonuje handler i waliduje
`outputSchema`. Wynik to `result:` albo zamknięte `error:` z kodem `DP-*` lub `GW-*`.
Linia bez poprawnej składni lub `requestId` to naruszenie kontraktu bez linii odpowiedzi.

**Zapis (ES).** `resource.publish` w jednej transakcji: event
`resource.published` w kopercie `data-plane.domain-event/v1` (hash data-plane),
blob adresowany SHA-256, projekcja `resources`, receipt idempotencji i event audytu.
Błąd domenowy cofa efekty handlera (savepoint), a audyt odrzucenia zostaje.
Ten sam klucz z tym samym wejściem zwraca `replayed: true`; z innym wejściem
`DP-CONCURRENCY-001`. URN zasobu to UUIDv5 tenanta i klucza, więc retry jest
deterministyczny. Eventy i audyt są niemodyfikowalne (triggery). SQLite według
profilu low-ram data-plane: WAL, `synchronous=FULL`, `foreign_keys=ON`.

**Audyt.** Każde wykonanie dopisuje `gateway.request_completed` do łańcucha
`data-gateway-audit`: `correlationId` = `requestId`, `subjectRef` = obiekt linii,
`inputHash` = SHA-256 kanonicznej linii, `outcome` SUCCEEDED/REJECTED/FAILED, kod
błędu. Bez zmiennych, treści i tokenów. `python -m data_gateway audit` zwraca
kanoniczny JSONL; ten sam event ma bezstratną projekcję liniową data-plane.

**Transporty.**

| Transport | Wejście | Wynik |
| --- | --- | --- |
| Shell | `exec LINE` lub linie stdin | stdout; kod 0 result, 1 error, 2 naruszenie |
| REST | `POST /v2/line`, `text/plain` | linia; status według kodu (403, 404, 409, 501…) |
| gRPC | `LineGateway.Execute`/`Stream` | `Line`; naruszenie to `INVALID_ARGUMENT` |
| MCP | narzędzie `line.execute` (stdio) | treść = linia, `isError` dla błędu |

**Uwierzytelnianie.** Plik `--tokens` mapuje SHA-256 tokenu na scopes; REST używa
`Authorization: Bearer`, gRPC metadanej `authorization`. Bez pliku serwer odmawia
nasłuchu poza loopback, a lokalny operator (shell, MCP stdio) ma pełny dostęp.

<!-- docs:section limitations -->
## Limitations

Implementacja referencyjna, nie wdrożenie produkcyjne: brak TLS, rotacji tokenów,
limitów współbieżności poza blokadą SQLite, pomiaru RAM i testów obciążeniowych.
Obsługiwane są dwie z jedenastu operacji. Audyt i eventy domenowe nie mają relay
ani eksportu poza lokalny plik. Testy sieciowe działają na loopback w procesie testu.

<!-- docs:section next_actions -->
## Next actions

Kolejne handlery operacji z katalogu, każdy z testem równoważności transportów.
TLS i zewnętrzny dostawca tożsamości przed wystawieniem poza loopback. Pomiar
RAM według MEM-042 data-plane przed deklaracją profilu low-ram.
