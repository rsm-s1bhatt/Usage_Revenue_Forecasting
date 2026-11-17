select
    region,
    cast(plan_month as date)          as plan_month,
    cast(plan_revenue_usd as double)  as plan_revenue_usd
from {{ source('plan', 'revenue_monthly') }}
