-- Start + new + expansion - contraction - churn must equal ending revenue in every quarter.
select *
from {{ ref('fct_revenue_bridge_quarterly') }}
where abs(starting_revenue_usd + new_revenue_usd + expansion_usd - contraction_usd - churn_usd
          - ending_revenue_usd) > 0.01
