# Lead Capture — website "Free Audit" form → your own AWS

The cloudthrift.io form (`website/form.html`) submits leads to **your** AWS account only.
No third-party form processor ever sees prospect data.

```
form.html  ──POST JSON──►  API Gateway (HTTP API)  ──►  Lambda
                                                          ├─► S3   leads/dt=YYYY-MM-DD/<uuid>.json
                                                          └─► SNS ─► email notification to you
                                                                 S3 ──(Glue table)──► Athena
```

Template: `pillar-a/cloudformation/lead-capture.yaml`

## 1. Deploy the stack

```bash
aws cloudformation deploy \
  --template-file pillar-a/cloudformation/lead-capture.yaml \
  --stack-name cloudthrift-lead-capture \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
      NotifyEmail=hello@cloudthrift.io \
      AllowedOrigin='*' \
  --profile <your-aws-profile> --region <region>
```

- `NotifyEmail` — where new-lead pings go. **Check that inbox and click the SNS "Confirm subscription" link**, or emails won't arrive.
- `AllowedOrigin` — leave `'*'` while testing locally; **set it to `https://cloudthrift.io` once the site is hosted** (locks the API to your domain).

## 2. Wire the form to the API

Get the API URL:

```bash
aws cloudformation describe-stacks --stack-name cloudthrift-lead-capture \
  --query "Stacks[0].Outputs[?OutputKey=='ApiEndpoint'].OutputValue" --output text \
  --profile <your-aws-profile> --region <region>
```

Paste that value into `website/form.html` → replace `REPLACE-WITH-API-ENDPOINT` in the
`LEAD_API` constant. (Or send it to Claude and it'll wire + commit.)

## 3. Query leads in Athena

Athena console → **Workgroup** `cloudthrift-leads-wg` → Database `cloudthrift_leads_db`:

```sql
-- newest leads first
SELECT received_at, name, company, email, monthly_spend, cost_concern
FROM cloudthrift_leads_db.leads
ORDER BY received_at DESC;

-- leads from a single day (uses the dt partition — cheap scan)
SELECT * FROM cloudthrift_leads_db.leads WHERE dt = '2026-07-25';
```

Partition projection is on, so there's **no `MSCK REPAIR` / add-partition step** — new days are
queryable automatically.

## Cost & security notes
- At low volume this is effectively free (Lambda free tier, S3/SNS pennies, Athena billed per TB scanned — leads are tiny).
- S3 buckets are private + encrypted (SSE-S3) + versioned; public access fully blocked.
- Lambda can only `PutObject` under `leads/*` and publish to the one SNS topic (least privilege).
- Honeypot field (`botcheck`) drops bots; API Gateway throttled to 5 req/s (burst 10).
- No PII is ever placed in URLs; the browser sends JSON in the POST body.
