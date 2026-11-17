-- Invoices where the billed amount is not the greater of commit and discounted usage.
select invoice_id, account_id, invoice_month, commit_usd, usage_net_usd, billed_usd,
       billed_usd - greatest(commit_usd, usage_net_usd) as difference_usd
from {{ ref('stg_billing__invoices') }}
where abs(billed_usd - greatest(commit_usd, usage_net_usd)) > 0.02
