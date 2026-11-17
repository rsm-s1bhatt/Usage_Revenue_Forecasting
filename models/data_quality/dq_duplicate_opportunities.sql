-- Opportunities that repeat another opportunity's account, type, amount and close date.
select opportunity_id, account_id, opportunity_type, amount_usd, close_date
from {{ ref('stg_crm__opportunities') }}
where is_duplicate
