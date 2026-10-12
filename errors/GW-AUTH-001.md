# GW-AUTH-001: Missing operation scope

## Error DSL

```log-error-dsl
{"category":"AUTHORITY","causes":["Token scopes do not include the operation scope."],"code":"GW-AUTH-001","doNot":["Do not run the gateway without authentication on a non-loopback address to bypass scopes."],"meaning":"The caller is authenticated but lacks the scope the operation declares.","owner":"service:data-gateway","relatedEventTypes":["error_raised"],"remediation":["Grant the declared scope through the owning access process, then retry the same line."],"schema":"wellmanifest.logs/error/v1","severity":"WARNING","title":"Missing operation scope","verification":["Repeat the line with a token whose scopes include the operation scope."],"version":1}
```

## Situation

Token scopes do not include the operation scope.

## Meaning

The caller is authenticated but lacks the scope the operation declares.

## Safe resolution

Grant the declared scope through the owning access process, then retry the same line.

## Verification

Repeat the line with a token whose scopes include the operation scope.

## Do not

Do not run the gateway without authentication on a non-loopback address to bypass scopes.

## Related events

error_raised
