-- Open pipeline as of the end of actuals, weighted by historical stage win rates, with the
-- monthly revenue each deal would add once live.
select
    o.opportunity_id,
    o.account_id,
    a.segment,
    a.region,
    o.owner_rep_id,
    o.opportunity_type,
    o.stage,
    o.amount_usd,
    o.amount_usd / 12                                  as monthly_value_usd,
    o.close_date,
    w.historical_win_rate,
    o.amount_usd * w.historical_win_rate               as weighted_amount_usd
from {{ ref('stg_crm__opportunities') }} o
join {{ ref('stg_crm__accounts') }} a using (account_id)
join {{ ref('fct_stage_win_rates') }} w using (stage)
where o.is_valid and not o.is_closed
