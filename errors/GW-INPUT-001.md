# GW-INPUT-001: Input violates the operation contract

## Error DSL

```log-error-dsl
{"category":"CONTRACT","causes":["Missing or extra argument, wrong format or non-canonical base64."],"code":"GW-INPUT-001","doNot":["Do not relax the operation schema in the gateway."],"meaning":"The request line maps to an input that the operation schema or encoding rules reject.","owner":"service:data-gateway","relatedEventTypes":["error_raised"],"remediation":["Correct the variables to match the operation inputSchema and resend."],"schema":"wellmanifest.logs/error/v1","severity":"WARNING","title":"Input violates the operation contract","verification":["Validate the line with `dp_line.py to-request` and the operation schema."],"version":1}
```

## Situation

Missing or extra argument, wrong format or non-canonical base64.

## Meaning

The request line maps to an input that the operation schema or encoding rules reject.

## Safe resolution

Correct the variables to match the operation inputSchema and resend.

## Verification

Validate the line with `dp_line.py to-request` and the operation schema.

## Do not

Do not relax the operation schema in the gateway.

## Related events

error_raised
