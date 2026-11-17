-- Rep performance by calendar year: bookings from won new-business and expansion deals,
-- attainment against quota (2026 prorated to the end of actuals), win rate, sales cycle,
-- and open pipeline coverage of the quota still to close.
with years as (select unnest([2025, 2026]) as yr),
deals as (
    select o.*, year(o.close_date) as yr
    from {{ ref('stg_crm__opportunities') }} o
    where o.is_valid and o.is_closed and o.opportunity_type in ('New Business', 'Expansion')
),
by_rep as (
    select
        r.rep_id, r.region, y.yr, r.annual_quota_usd,
        sum(case when d.is_won then d.amount_usd else 0 end)                 as bookings_usd,
        count(d.opportunity_id)                                              as closed_deals,
        sum(d.is_won::int)                                                   as won_deals,
        avg(case when d.is_won then date_diff('day', d.created_date, d.close_date) end) as avg_sales_cycle_days
    from {{ ref('stg_crm__reps') }} r
    cross join years y
    left join deals d on d.owner_rep_id = r.rep_id and d.yr = y.yr
    group by all
),
pipe as (
    select owner_rep_id as rep_id, sum(amount_usd) as open_pipeline_usd, sum(weighted_amount_usd) as weighted_pipeline_usd
    from {{ ref('fct_pipeline_open') }} group by all
)
select
    b.*,
    case when b.yr = 2026
         then b.annual_quota_usd * month(cast('{{ var("actuals_end") }}' as date)) / 12
         else b.annual_quota_usd end                                          as quota_to_date_usd,
    b.bookings_usd / quota_to_date_usd                                        as attainment_pct,
    b.won_deals * 1.0 / nullif(b.closed_deals, 0)                             as win_rate,
    case when b.yr = 2026 then coalesce(p.open_pipeline_usd, 0) end           as open_pipeline_usd,
    case when b.yr = 2026 then coalesce(p.weighted_pipeline_usd, 0) end       as weighted_pipeline_usd,
    case when b.yr = 2026
         then coalesce(p.open_pipeline_usd, 0) / nullif(greatest(b.annual_quota_usd - b.bookings_usd, 0), 0)
    end                                                                       as pipeline_coverage
from by_rep b
left join pipe p using (rep_id)
