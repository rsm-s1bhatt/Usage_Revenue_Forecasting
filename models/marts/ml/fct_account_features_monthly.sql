-- Point-in-time features for account scoring. One row per active account per snapshot date
-- (the first day of a month). Features use only data from before the snapshot; labels use the
-- 3 months starting at the snapshot and are filled only when those months are fully observed.
{% set end = "cast('" ~ var('actuals_end') ~ "' as date)" %}
with rev as (
    select account_id, revenue_month, revenue_usd, usage_net_usd, commit_usd
    from {{ ref('fct_revenue_monthly') }}
),
accts as (
    select account_id, segment, min(revenue_month) as first_month
    from {{ ref('fct_revenue_monthly') }} group by all
),
snapshots as (
    select unnest(generate_series(date '2024-04-01', date_trunc('month', {{ end }}) + interval 1 month, interval 1 month))::date as snapshot_date
),
spine as (
    -- accounts past their first 6 months (so onboarding ramps are not mistaken for expansion) that billed in the month before the snapshot
    select a.account_id, a.segment, a.first_month, s.snapshot_date
    from accts a
    join snapshots s on a.first_month <= s.snapshot_date - interval 6 month
    join rev r on r.account_id = a.account_id and r.revenue_month = s.snapshot_date - interval 1 month
),
rev_feats as (
    select
        sp.account_id, sp.snapshot_date,
        sum(case when r.revenue_month =  sp.snapshot_date - interval 1 month then r.revenue_usd end)  as rev_l1m,
        sum(case when r.revenue_month =  sp.snapshot_date - interval 2 month then r.revenue_usd end)  as rev_l2m,
        sum(case when r.revenue_month >= sp.snapshot_date - interval 3 month and r.revenue_month < sp.snapshot_date then r.revenue_usd end) as rev_l3m,
        sum(case when r.revenue_month >= sp.snapshot_date - interval 6 month and r.revenue_month < sp.snapshot_date - interval 3 month then r.revenue_usd end) as rev_p3m,
        sum(case when r.revenue_month >= sp.snapshot_date and r.revenue_month < sp.snapshot_date + interval 3 month then r.revenue_usd end) as rev_n3m,
        max(case when r.revenue_month =  sp.snapshot_date - interval 1 month then r.commit_usd end)    as commit_l1m,
        max(case when r.revenue_month =  sp.snapshot_date - interval 1 month then r.usage_net_usd end) as usage_net_l1m
    from spine sp
    left join rev r on r.account_id = sp.account_id
       and r.revenue_month >= sp.snapshot_date - interval 6 month
       and r.revenue_month <  sp.snapshot_date + interval 3 month
    group by all
),
activity as (
    select sp.account_id, sp.snapshot_date,
           count(distinct u.usage_date) filter (where u.usage_date >= sp.snapshot_date - interval 30 day) as active_days_l30d,
           count(distinct u.gpu_type)                                                                  as gpu_types_l3m,
           count(distinct u.gpu_type) filter (where u.usage_date >= sp.snapshot_date - interval 2 month)
             - count(distinct u.gpu_type) filter (where u.usage_date <  sp.snapshot_date - interval 2 month) as gpu_types_added_l2m
    from spine sp
    join {{ ref('stg_telemetry__usage_daily') }} u
      on u.account_id = sp.account_id and u.gpu_hours > 0
     and u.usage_date >= sp.snapshot_date - interval 3 month and u.usage_date < sp.snapshot_date
    group by all
),
deploys as (
    select sp.account_id, sp.snapshot_date,
           count(*) filter (where d.deployed_date >= sp.snapshot_date - interval 60 day)  as deployments_l60d,
           count(*) filter (where d.deployed_date <  sp.snapshot_date - interval 60 day
                              and d.deployed_date >= sp.snapshot_date - interval 120 day) as deployments_p60d,
           date_diff('day', max(d.deployed_date), sp.snapshot_date)                      as days_since_last_deployment
    from spine sp
    join {{ ref('stg_telemetry__deployments') }} d
      on d.account_id = sp.account_id and d.deployed_date < sp.snapshot_date
    group by sp.account_id, sp.snapshot_date
)
select
    sp.account_id,
    sp.snapshot_date,
    sp.segment,
    date_diff('month', sp.first_month, sp.snapshot_date)                   as tenure_months,
    f.rev_l1m,
    f.rev_l3m,
    f.rev_l3m / nullif(f.rev_p3m, 0)                                       as growth_l3m_vs_p3m,
    f.rev_l1m / nullif(f.rev_l2m, 0)                                       as growth_l1m_vs_l2m,
    f.commit_l1m > 0                                                       as has_commit,
    case when f.commit_l1m > 0 then f.usage_net_l1m / f.commit_l1m end     as commit_utilization_l1m,
    coalesce(a.active_days_l30d, 0)                                        as active_days_l30d,
    coalesce(a.gpu_types_l3m, 0)                                           as gpu_types_l3m,
    greatest(coalesce(a.gpu_types_added_l2m, 0), 0)                        as gpu_types_added_l2m,
    coalesce(d.deployments_l60d, 0)                                        as deployments_l60d,
    coalesce(d.deployments_p60d, 0)                                        as deployments_p60d,
    coalesce(d.days_since_last_deployment, 999)                            as days_since_last_deployment,
    -- labels: only where the next 3 months are fully inside actuals
    sp.snapshot_date + interval 3 month <= {{ end }} + interval 1 day      as label_observed,
    case when sp.snapshot_date + interval 3 month <= {{ end }} + interval 1 day
         then coalesce(f.rev_n3m, 0) end                                   as rev_n3m,
    case when sp.snapshot_date + interval 3 month <= {{ end }} + interval 1 day
         then coalesce(f.rev_n3m, 0) < 0.25 * f.rev_l3m end                as label_churn_or_major_contraction,
    case when sp.snapshot_date + interval 3 month <= {{ end }} + interval 1 day
         then coalesce(f.rev_n3m, 0) >= 1.4 * f.rev_l3m end                as label_expansion
from spine sp
join rev_feats f using (account_id, snapshot_date)
left join activity a using (account_id, snapshot_date)
left join deploys d using (account_id, snapshot_date)
