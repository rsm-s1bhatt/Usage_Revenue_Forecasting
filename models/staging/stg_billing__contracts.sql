select
    contract_id,
    account_id,
    cast(start_date as date)          as start_date,
    cast(end_date as date)            as end_date,
    cast(monthly_commit_usd as double) as monthly_commit_usd,
    cast(discount_pct as double)      as discount_pct
from {{ source('billing', 'contracts') }}
