# GW-NOTFOUND-001: Resource not found

## Error DSL

```log-error-dsl
{"category":"STORAGE","causes":["Unknown URN, a publish that was never committed, or a different gateway database."],"code":"GW-NOTFOUND-001","doNot":["Do not create placeholder resources to satisfy a read."],"meaning":"No projected resource exists for the requested URN.","owner":"service:data-gateway","relatedEventTypes":["error_raised"],"remediation":["Confirm the URN from the publish result and the gateway instance."],"schema":"wellmanifest.logs/error/v1","severity":"WARNING","title":"Resource not found","verification":["Read the resource again after the publish result is received."],"version":1}
```

## Situation

Unknown URN, a publish that was never committed, or a different gateway database.

## Meaning

No projected resource exists for the requested URN.

## Safe resolution

Confirm the URN from the publish result and the gateway instance.

## Verification

Read the resource again after the publish result is received.

## Do not

Do not create placeholder resources to satisfy a read.

## Related events

error_raised
