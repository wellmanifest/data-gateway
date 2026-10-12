# GW-UNSUPPORTED-001: Operation not handled by this gateway

## Error DSL

```log-error-dsl
{"category":"CONFIGURATION","causes":["The reference gateway implements only resource.publish and resource.read."],"code":"GW-UNSUPPORTED-001","doNot":["Do not return a synthetic success for an unhandled operation."],"meaning":"The operation exists in the catalog but this gateway has no handler for it.","owner":"service:data-gateway","relatedEventTypes":["error_raised"],"remediation":["Route the line to a gateway that implements the operation."],"schema":"wellmanifest.logs/error/v1","severity":"WARNING","title":"Operation not handled by this gateway","verification":["Check the handler list in the gateway documentation."],"version":1}
```

## Situation

The reference gateway implements only resource.publish and resource.read.

## Meaning

The operation exists in the catalog but this gateway has no handler for it.

## Safe resolution

Route the line to a gateway that implements the operation.

## Verification

Check the handler list in the gateway documentation.

## Do not

Do not return a synthetic success for an unhandled operation.

## Related events

error_raised
