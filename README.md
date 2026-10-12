# wellmanifest/data-gateway

Referencyjny gateway dla jednoliniowego formatu
[`data-plane.line/v1`](https://github.com/wellmanifest/data-plane/blob/bdf1a3bc46aa6ef2408249f4d5733760f864e7a7/docs/information/line-format.md):
jedna linia `typ: obiekt {zmienne}` wykonywana tym samym kernelem przez shell, REST,
gRPC i MCP, z audytem w `wellmanifest/logs`.

```bash
pip install -r requirements-dev.txt
make upstream            # przypięty data-plane, logs i docs do build/upstream
make test                # kernel, audyt, równoważność transportów
python -m data_gateway exec 'resource.read: urn:uuid:… {"requestId":"…"}'
python -m data_gateway rest --port 8080    # POST /v2/line (loopback bez tokenów)
python -m data_gateway grpc --port 50051   # LineGateway.Execute / Stream
python -m data_gateway mcp                 # narzędzie line.execute przez stdio
python -m data_gateway audit               # kanoniczny JSONL wellmanifest/logs
```

Obsługiwane operacje: `resource.publish` i `resource.read`. Pozostałe operacje katalogu
zwracają `error:` z kodem `GW-UNSUPPORTED-001`. Szczegóły, granice i dowody:
[dokumentacja](docs/README.md).

Status: implementacja referencyjna, nie produkcyjny gateway. Nie ma TLS ani
zewnętrznego dostawcy tożsamości; bez pliku tokenów serwery sieciowe nasłuchują tylko
na loopback.
