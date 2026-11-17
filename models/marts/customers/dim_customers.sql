-- One trusted row per account, joining CRM, billing and telemetry: who the customer is,
-- whether they are live, what they pay, what it costs to serve them, and what is in pipeline.
{% set end = "cast('" ~ var('actuals_end') ~ "' as date)" %}
with rev as (
    select
        account_id,
        min(revenue_month)                                             as first_revenue_month,
        max(revenue_month)                                             as last_revenue_month,
        sum(revenue_usd)                                               as lifetime_revenue_usd,
        sum(case when revenue_month > {{ end }} - interval 3 month then revenue_usd end)      as revenue_l3m_usd,
        sum(case when revenue_month > {{ end }} - interval 3 month then gross_margin_usd end) as gross_margin_l3m_usd,
        sum(case when revenue_month > {{ end }} - interval 3 month then overage_revenue_usd end) as overage_l3m_usd,
        sum(case when revenue_month > {{ end }} - interval 3 month then unused_commit_usd end)  as unused_commit_l3m_usd
    from {{ ref('fct_revenue_monthly') }}
    group by all
),
contract as (
    select account_id, monthly_commit_usd, discount_pct, end_date as contract_end_date
    from {{ ref('stg_billing__contracts') }}
    where start_date <= {{ end }} and end_date >= {{ end }}
),
tele as (
    select account_id,
           count(distinct gpu_type) filter (where usage_month > {{ end }} - interval 3 month) as gpu_types_l3m
    from {{ ref('int_usage_monthly') }} group by all
),
deploy as (
    select account_id, count(*) filter (where deployed_date > {{ end }} - interval 90 day) as deployments_l90d
    from {{ ref('stg_telemetry__deployments') }} group by all
),
pipe as (
    select account_id, sum(amount_usd) as open_pipeline_usd, sum(weighted_amount_usd) as weighted_pipeline_usd
    from {{ ref('fct_pipeline_open') }} group by all
)
select
    a.account_id,
    a.account_name,
    a.segment,
    a.industry,
    a.region,
    a.owner_rep_id,
    case
        when r.account_id is null then 'Prospect'
        when r.last_revenue_month = date_trunc('month', {{ end }}) then 'Active'
        else 'Churned'
    end                                                               as customer_status,
    r.first_revenue_month,
    r.last_revenue_month,
    date_diff('month', r.first_revenue_month, date_trunc('month', {{ end }})) + 1 as tenure_months,
    coalesce(r.lifetime_revenue_usd, 0)                               as lifetime_revenue_usd,
    coalesce(r.revenue_l3m_usd, 0)                                    as revenue_l3m_usd,
    r.gross_margin_l3m_usd / nullif(r.revenue_l3m_usd, 0)             as gross_margin_pct_l3m,
    coalesce(r.overage_l3m_usd, 0)                                    as overage_l3m_usd,
    coalesce(r.unused_commit_l3m_usd, 0)                              as unused_commit_l3m_usd,
    c.monthly_commit_usd                                              as current_monthly_commit_usd,
    c.discount_pct                                                    as current_discount_pct,
    c.contract_end_date,
    coalesce(t.gpu_types_l3m, 0)                                      as gpu_types_l3m,
    coalesce(d.deployments_l90d, 0)                                   as deployments_l90d,
    coalesce(p.open_pipeline_usd, 0)                                  as open_pipeline_usd,
    coalesce(p.weighted_pipeline_usd, 0)                              as weighted_pipeline_usd
from {{ ref('stg_crm__accounts') }} a
left join rev r using (account_id)
left join contract c using (account_id)
left join tele t using (account_id)
left join deploy d using (account_id)
left join pipe p using (account_id)
