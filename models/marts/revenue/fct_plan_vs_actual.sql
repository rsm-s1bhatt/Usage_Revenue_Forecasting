-- 2026 plan versus actual by region and month, with the variance split into the part from
-- customers who were already billing before 2026 and the part from 2026 new logos.
with actual as (
    select
        region,
        revenue_month,
        sum(revenue_usd)                                                        as actual_usd,
        sum(case when f.first_invoice_month <  date '2026-01-01' then revenue_usd else 0 end) as existing_base_usd,
        sum(case when f.first_invoice_month >= date '2026-01-01' then revenue_usd else 0 end) as new_logo_usd
    from {{ ref('fct_revenue_monthly') }} r
    join (select account_id, min(revenue_month) as first_invoice_month
          from {{ ref('fct_revenue_monthly') }} group by all) f using (account_id)
    group by all
)
select
    p.region,
    p.plan_month,
    p.plan_revenue_usd,
    a.actual_usd,
    a.actual_usd - p.plan_revenue_usd                    as variance_usd,
    (a.actual_usd - p.plan_revenue_usd) / p.plan_revenue_usd as variance_pct,
    a.existing_base_usd - p.plan_revenue_usd             as existing_base_variance_usd,
    a.new_logo_usd                                       as new_logo_variance_usd
from {{ ref('stg_plan__revenue_monthly') }} p
join actual a on a.region = p.region and a.revenue_month = p.plan_month
