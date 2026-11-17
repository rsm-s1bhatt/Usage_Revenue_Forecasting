select
    invoice_id,
    account_id,
    cast(invoice_month as date)       as invoice_month,
    cast(commit_usd as double)        as commit_usd,
    cast(usage_net_usd as double)     as usage_net_usd,
    cast(billed_usd as double)        as billed_usd
from {{ source('billing', 'invoices') }}
