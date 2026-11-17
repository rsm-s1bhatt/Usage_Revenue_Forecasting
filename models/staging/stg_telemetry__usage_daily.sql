select
    cast(usage_date as date)          as usage_date,
    account_id,
    gpu_type,
    cast(gpu_hours as double)         as gpu_hours,
    cast(requests as bigint)          as requests
from {{ source('telemetry', 'usage_daily') }}
