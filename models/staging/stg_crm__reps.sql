select
    rep_id,
    region,
    cast(annual_quota_usd as double) as annual_quota_usd
from {{ source('crm', 'reps') }}
