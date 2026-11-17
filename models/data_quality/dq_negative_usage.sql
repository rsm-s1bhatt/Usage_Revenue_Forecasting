-- Telemetry rows with zero or negative GPU hours, which cannot happen on a real platform.
select usage_date, account_id, gpu_type, gpu_hours
from {{ ref('stg_telemetry__usage_daily') }}
where gpu_hours <= 0
