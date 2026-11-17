select
    account_id,
    account_name,
    segment,
    industry,
    region,
    owner_rep_id,
    try_cast(nullif(first_usage_date::varchar, '') as date) as first_usage_date
from {{ source('crm', 'accounts') }}
