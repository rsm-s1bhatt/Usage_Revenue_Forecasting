-- Opportunities pointing at an account that does not exist in the CRM account table.
select opportunity_id, account_id, amount_usd
from {{ ref('stg_crm__opportunities') }}
where has_unknown_account
