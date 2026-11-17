-- Revenue allocated to GPU types must add back up to each account-month's billed revenue.
with g as (
    select account_id, revenue_month, sum(revenue_usd) as gpu_revenue
    from {{ ref('fct_gross_margin_by_gpu') }} group by all
)
select r.account_id, r.revenue_month, r.revenue_usd, g.gpu_revenue
from {{ ref('fct_revenue_monthly') }} r
join g using (account_id, revenue_month)
where abs(r.revenue_usd - g.gpu_revenue) > 0.01
