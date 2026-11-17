-- The unified customer model must hold every CRM account exactly once, no more and no fewer.
select
    (select count(*) from {{ ref('dim_customers') }})     as customer_rows,
    (select count(*) from {{ ref('stg_crm__accounts') }}) as crm_accounts
where (select count(*) from {{ ref('dim_customers') }})
   != (select count(*) from {{ ref('stg_crm__accounts') }})
