select
    account_id,
    cast(deployed_date as date) as deployed_date,
    model_name
from {{ source('telemetry', 'deployments') }}
