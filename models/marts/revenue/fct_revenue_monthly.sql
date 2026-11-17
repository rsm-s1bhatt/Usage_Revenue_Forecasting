-- One row per account and month: what was billed, how much of it was committed versus
-- consumption above commit, unused commit, GPU hours, infrastructure cost and gross margin.
with usage as (
    select account_id, usage_month,
           sum(gpu_hours) as gpu_hours,
           sum(list_value_usd) as list_value_usd,
           sum(infra_cost_usd) as infra_cost_usd
    from {{ ref('int_usage_monthly') }}
    group by all
),
first_month as (
    select account_id, min(invoice_month) as first_invoice_month
    from {{ ref('stg_billing__invoices') }} group by all
)
select
    i.account_id,
    i.invoice_month                                                  as revenue_month,
    a.segment,
    a.region,
    a.owner_rep_id,
    i.billed_usd                                                     as revenue_usd,
    i.commit_usd,
    i.usage_net_usd,
    least(i.commit_usd, i.billed_usd)                                as committed_revenue_usd,
    i.billed_usd - least(i.commit_usd, i.billed_usd)                 as overage_revenue_usd,
    greatest(i.commit_usd - i.usage_net_usd, 0)                      as unused_commit_usd,
    coalesce(u.gpu_hours, 0)                                         as gpu_hours,
    coalesce(u.infra_cost_usd, 0)                                    as infra_cost_usd,
    i.billed_usd - coalesce(u.infra_cost_usd, 0)                     as gross_margin_usd,
    i.invoice_month = f.first_invoice_month                          as is_first_month
from {{ ref('stg_billing__invoices') }} i
join {{ ref('stg_crm__accounts') }} a using (account_id)
join first_month f using (account_id)
left join usage u on u.account_id = i.account_id and u.usage_month = i.invoice_month
