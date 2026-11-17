select
    gpu_type,
    cast(list_price_per_gpu_hour as double) as list_price_per_gpu_hour,
    cast(infra_cost_per_gpu_hour as double) as infra_cost_per_gpu_hour
from {{ source('ref', 'gpu_rates') }}
