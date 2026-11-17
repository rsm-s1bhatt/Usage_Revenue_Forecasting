-- Every month's revenue splits exactly into committed revenue and consumption above commit.
select account_id, revenue_month, revenue_usd, committed_revenue_usd, overage_revenue_usd
from {{ ref('fct_revenue_monthly') }}
where abs(committed_revenue_usd + overage_revenue_usd - revenue_usd) > 0.01
