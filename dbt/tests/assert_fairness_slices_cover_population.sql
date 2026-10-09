-- Each slice dimension partitions the whole population: its slices add up to the overall count.
with totals as (
    select slice_dimension, sum(n_enrolments) as n
    from {{ ref('mart_outcome_fairness_slices') }}
    group by slice_dimension
)
select t.slice_dimension, t.n, o.n as overall_n
from totals as t
cross join (select n from totals where slice_dimension = 'overall') as o
where t.n <> o.n
