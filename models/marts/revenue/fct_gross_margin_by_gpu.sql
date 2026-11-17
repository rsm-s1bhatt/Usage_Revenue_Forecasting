-- Revenue, infrastructure cost and gross margin by account, month and GPU type.
-- Billed revenue is allocated to GPU types by each type's share of list-price usage value,
-- so unused commit (pure margin) is spread across the GPUs the account actually ran.
with u as (
    select *,
           list_value_usd / nullif(sum(list_value_usd) over (partition by account_id, usage_month), 0) as value_share
    from {{ ref('int_usage_monthly') }}
)
select
    u.account_id,
    u.usage_month                                   as revenue_month,
    u.gpu_type,
    r.segment,
    u.gpu_hours,
    r.revenue_usd * u.value_share                   as revenue_usd,
    u.infra_cost_usd,
    r.revenue_usd * u.value_share - u.infra_cost_usd as gross_margin_usd,
    (r.revenue_usd * u.value_share - u.infra_cost_usd)
        / nullif(r.revenue_usd * u.value_share, 0)  as gross_margin_pct
from u
join {{ ref('fct_revenue_monthly') }} r
  on r.account_id = u.account_id and r.revenue_month = u.usage_month
