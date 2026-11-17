-- Revenue per account per complete calendar quarter, with the prior quarter alongside.
-- Accounts appear in every quarter from their first invoice on, with zero when they bill nothing.
with q as (
    select
        account_id,
        date_trunc('quarter', invoice_month)::date as quarter_start,
        sum(billed_usd) as revenue_usd
    from {{ ref('stg_billing__invoices') }}
    group by all
),
quarters as (
    select distinct quarter_start from q
    where quarter_start + interval 3 month <= cast('{{ var("actuals_end") }}' as date) + interval 1 day
),
first_q as (select account_id, min(quarter_start) as first_quarter from q group by all),
spine as (
    select f.account_id, qs.quarter_start, f.first_quarter
    from first_q f
    join quarters qs on qs.quarter_start >= f.first_quarter
)
select
    s.account_id,
    s.quarter_start,
    s.quarter_start = s.first_quarter                                   as is_first_quarter,
    coalesce(q.revenue_usd, 0)                                          as revenue_usd,
    coalesce(lag(coalesce(q.revenue_usd, 0)) over (
        partition by s.account_id order by s.quarter_start), 0)         as prior_quarter_revenue_usd
from spine s
left join q using (account_id, quarter_start)
