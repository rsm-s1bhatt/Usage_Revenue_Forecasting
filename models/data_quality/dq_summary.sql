-- One row per data-quality check with the number of records it flagged.
select 'duplicate_opportunities' as check_name, count(*) as flagged_records from {{ ref('dq_duplicate_opportunities') }}
union all select 'opportunities_unknown_account', count(*) from {{ ref('dq_opportunities_unknown_account') }}
union all select 'invoice_mismatches', count(*) from {{ ref('dq_invoice_mismatches') }}
union all select 'negative_usage_rows', count(*) from {{ ref('dq_negative_usage') }}
