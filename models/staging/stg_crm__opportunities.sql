-- Every opportunity as recorded in the CRM, with flags for the two known data problems.
-- Downstream marts use only rows where is_valid is true.
with src as (
    select
        opportunity_id,
        account_id,
        owner_rep_id,
        opportunity_type,
        stage,
        cast(amount_usd as double) as amount_usd,
        cast(created_date as date) as created_date,
        cast(close_date as date)   as close_date
    from {{ source('crm', 'opportunities') }}
),

flagged as (
    select
        src.*,
        row_number() over (
            partition by account_id, opportunity_type, amount_usd, close_date
            order by opportunity_id
        ) > 1                                       as is_duplicate,
        a.account_id is null                        as has_unknown_account
    from src
    left join {{ source('crm', 'accounts') }} a using (account_id)
)

select
    *,
    stage in ('Closed Won', 'Closed Lost')          as is_closed,
    stage = 'Closed Won'                            as is_won,
    not is_duplicate and not has_unknown_account    as is_valid
from flagged
