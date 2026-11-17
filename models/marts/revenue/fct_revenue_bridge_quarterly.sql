-- Quarter-over-quarter revenue bridge: starting revenue, plus new logos and expansion,
-- minus contraction and churn, equals ending revenue. Also net and gross revenue retention.
with classified as (
    select
        quarter_start,
        prior_quarter_revenue_usd as start_usd,
        revenue_usd               as end_usd,
        case when is_first_quarter then revenue_usd else 0 end                                         as new_usd,
        case when not is_first_quarter and prior_quarter_revenue_usd = 0 then revenue_usd else 0 end   as reactivated_usd,
        case when prior_quarter_revenue_usd > 0 and revenue_usd > prior_quarter_revenue_usd
             then revenue_usd - prior_quarter_revenue_usd else 0 end                                    as expansion_usd,
        case when prior_quarter_revenue_usd > 0 and revenue_usd > 0 and revenue_usd < prior_quarter_revenue_usd
             then prior_quarter_revenue_usd - revenue_usd else 0 end                                    as contraction_usd,
        case when prior_quarter_revenue_usd > 0 and revenue_usd = 0
             then prior_quarter_revenue_usd else 0 end                                                  as churn_usd
    from {{ ref('int_account_quarters') }}
)
select
    quarter_start,
    sum(start_usd)                       as starting_revenue_usd,
    sum(new_usd) + sum(reactivated_usd)  as new_revenue_usd,
    sum(expansion_usd)                   as expansion_usd,
    sum(contraction_usd)                 as contraction_usd,
    sum(churn_usd)                       as churn_usd,
    sum(end_usd)                         as ending_revenue_usd,
    (sum(start_usd) + sum(expansion_usd) - sum(contraction_usd) - sum(churn_usd))
        / nullif(sum(start_usd), 0)      as net_revenue_retention,
    (sum(start_usd) - sum(contraction_usd) - sum(churn_usd))
        / nullif(sum(start_usd), 0)      as gross_revenue_retention
from classified
group by all
order by quarter_start
