-- GPU hours, requests, list-price value and infrastructure cost per account, month and GPU type.
-- Rows with non-positive GPU hours are left out here and reported by dq_negative_usage.
select
    u.account_id,
    date_trunc('month', u.usage_date)::date        as usage_month,
    u.gpu_type,
    sum(u.gpu_hours)                                as gpu_hours,
    sum(u.requests)                                 as requests,
    sum(u.gpu_hours * r.list_price_per_gpu_hour)    as list_value_usd,
    sum(u.gpu_hours * r.infra_cost_per_gpu_hour)    as infra_cost_usd
from {{ ref('stg_telemetry__usage_daily') }} u
join {{ ref('stg_ref__gpu_rates') }} r using (gpu_type)
where u.gpu_hours > 0
group by all
