select
    opportunity_id,
    stage,
    cast(entered_date as date) as entered_date
from {{ source('crm', 'opportunity_history') }}
