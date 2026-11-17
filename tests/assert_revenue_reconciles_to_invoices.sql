-- Revenue in the mart must equal billed revenue on invoices, to the cent.
select
    (select round(sum(revenue_usd), 2) from {{ ref('fct_revenue_monthly') }})  as mart_revenue,
    (select round(sum(billed_usd), 2)  from {{ ref('stg_billing__invoices') }}) as invoiced_revenue
where (select round(sum(revenue_usd), 2) from {{ ref('fct_revenue_monthly') }})
   != (select round(sum(billed_usd), 2)  from {{ ref('stg_billing__invoices') }})
