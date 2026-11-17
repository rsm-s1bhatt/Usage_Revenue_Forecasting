-- Historical win rate for opportunities that reached each stage, from closed opportunities only.
-- These calibrated rates replace the CRM's default stage probabilities in the weighted pipeline.
with reached as (
    select distinct h.opportunity_id, h.stage, o.is_won, o.opportunity_type
    from {{ ref('stg_crm__opportunity_history') }} h
    join {{ ref('stg_crm__opportunities') }} o using (opportunity_id)
    where o.is_valid and o.is_closed
      and h.stage not in ('Closed Won', 'Closed Lost')
)
select
    stage,
    count(*)                                   as closed_opportunities_reaching_stage,
    sum(is_won::int)                           as won,
    sum(is_won::int) * 1.0 / count(*)          as historical_win_rate,
    case stage when 'Discovery' then 0.10 when 'Evaluation' then 0.25
               when 'Technical Validation' then 0.50 when 'Negotiation' then 0.75 end as crm_default_probability
from reached
group by all
