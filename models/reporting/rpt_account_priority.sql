-- The list a rep works from: every active account with its revenue, margin, 3-month forecast,
-- churn and expansion scores, the main reason behind each score, and one recommended action.
-- Built after scripts/score_accounts.py and scripts/forecast_revenue.py write to the ml schema.
with fc as (
    select account_id, sum(forecast_usd) as forecast_next_3m_usd
    from {{ source('ml', 'revenue_forecast') }}
    where component = 'existing'
    group by all
)
select
    c.account_id,
    c.account_name,
    c.segment,
    c.region,
    c.owner_rep_id,
    c.revenue_l3m_usd,
    fc.forecast_next_3m_usd,
    c.gross_margin_pct_l3m,
    c.current_monthly_commit_usd,
    c.overage_l3m_usd,
    c.contract_end_date,
    s.churn_score,
    s.churn_tier,
    s.churn_top_reason,
    s.expansion_score,
    s.expansion_tier,
    s.expansion_top_reason,
    case
        when s.churn_tier = 'Top 10%'                                   then 'Retention: owner check-in this week'
        when s.expansion_tier = 'Top 10%' and c.overage_l3m_usd > 0      then 'Expansion: propose a larger commit'
        when s.expansion_tier = 'Top 10%'                               then 'Expansion: confirm the new workload'
        when c.gross_margin_pct_l3m < 0.30                              then 'Margin review: discount and GPU mix'
        else 'Monitor'
    end                                                                 as recommended_action,
    s.churn_score * c.revenue_l3m_usd                                   as revenue_at_risk_usd
from {{ ref('dim_customers') }} c
join {{ source('ml', 'account_scores') }} s using (account_id)
left join fc using (account_id)
where c.customer_status = 'Active'
