-- Scoring features must come from before the snapshot: an account cannot have a snapshot
-- dated earlier than its first 6 months of billing, and labels are only filled once observed.
select f.account_id, f.snapshot_date
from {{ ref('fct_account_features_monthly') }} f
join (select account_id, min(revenue_month) as first_month
      from {{ ref('fct_revenue_monthly') }} group by all) m using (account_id)
where f.snapshot_date < m.first_month + interval 6 month
   or (not f.label_observed and f.label_expansion is not null)
