# Verification against published figures

`edtech verify` recomputes figures that were published independently of this repository and
compares them with the pipeline's silver tables and marts. The run below is the full release
(figshare archive, md5 `7412686fd77cf0e0ee1e8c3e9b354308`, raw version
`version=1d0e901af651617c`), executed locally on 9 October 2026. The same table is regenerated on
every run into `ops/verification.json` and the results site.

Sources:

* **[P]** Kuzilek, J., Hlosta, M. & Zdrahal, Z. (2017). Open University Learning Analytics
  dataset. *Scientific Data* 4, 170171. <https://doi.org/10.1038/sdata.2017.171>. Row counts are
  in the "Data Records" section; the module summary is
  [Table 1](https://www.nature.com/articles/sdata2017171/tables/1).
* **[U]** `OULAD.names`, the description file in the UCI Machine Learning Repository archive
  (<https://archive.ics.uci.edu/dataset/349/open+university+learning+analytics+dataset>).

**Result: 17 match, 3 differ because the published sources contradict the data or each other
(explained below), 0 unexplained mismatches.**

| Check | Source | Published | Pipeline | Status |
|---|---|---|---|---|
| rows in courses | [P] | 22 | 22 | match |
| rows in assessments | [P] | 206 | 206 | match |
| rows in vle | [P] | 6,364 | 6,364 | match |
| rows in studentInfo | [P] | 32,593 | 32,593 | match |
| rows in studentRegistration | [P] | 32,593 | 32,593 | match |
| rows in studentAssessment | [P] | 173,912 | 173,912 | match |
| rows in studentVle | [P] | 10,655,280 | 10,655,280 | match |
| students in courses | [U] | 32,953 | 32,593 | documented mismatch (1) |
| Table 1: AAA, Social Sciences | [P] | 2 presentations, 748 students | 2, 748 | match |
| Table 1: BBB, Social Sciences | [P] | 4, 7,909 | 4, 7,909 | match |
| Table 1: CCC, STEM | [P] | 2, 4,434 | 2, 4,434 | match |
| Table 1: DDD, STEM | [P] | 4, 6,272 | 4, 6,272 | match |
| Table 1: EEE, STEM | [P] | 3, 2,934 | 3, 2,934 | match |
| Table 1: FFF, STEM | [P] | 4, 7,762 | 4, 7,762 | match |
| Table 1: GGG, Social Sciences | [P] | 3, 2,534 | 3, 2,534 | match |
| module presentations | [P] abstract | 22 | 22 | match |
| STEM / Social Sciences modules | [P] Data selection | 4 / 3 | 4 / 3 | match |
| assessment score range | [P] studentAssessment | 0 to 100 | 0 to 100 | match |
| unregistered students are Withdrawn | [P] studentRegistration | all | 9 unregistered are not Withdrawn; 93 Withdrawn have no unregistration day | documented mismatch (2) |
| non-exam weights sum to 100%, exams 100% | [P] assessments | "typically" | GGG 2013J, 2014B, 2014J sum to 0%; all 24 exams at 100% | documented mismatch (3) |

1. **32,953 vs 32,593.** `OULAD.names` swaps two digits. The paper, the figshare archive and the
   UCI archive all have 32,593 rows in `studentInfo.csv`.
2. **Withdrawals without dates, and dates without withdrawals.** The paper says students who
   unregistered have `final_result = 'Withdrawn'`. In the release 9 enrolments with an
   unregistration day are `Fail`, and 93 `Withdrawn` enrolments have no unregistration day. The
   pipeline treats `final_result` as the truth for labels and the unregistration day as optional
   (a silver warning check counts the 93 every run).
3. **Weights.** The paper says the non-exam weights "typically" add up to 100%. Module GGG's TMAs
   and CMAs are all weighted 0% in its three presentations (the exam carries the grade). Other
   presentations still reach 100% but contain 0%-weight items too: FFF has seven 0% CMAs in each
   presentation, and BBB 2014J's first TMA is 0%-weighted and scored almost only 1 or 100
   (1,022 and 717 of 1,776 results). In total 56 non-exam assessments carry 0% weight; the funnel
   marks them `is_formative` and the site leaves them out of the mastery rates.

## Reconciliations inside the pipeline

These run on every execution as data-quality gates and stop the pipeline when they fail:

* silver row count = raw row count for every table, with zero cast failures (`ops_load_audit`);
* weekly activity and weekly engagement clicks sum exactly to the clickstream (39,605,099 clicks
  in the full release), and every clickstream row lands in exactly one weekly bucket;
* `dim_module_presentation`, `fct_first_submission` and the overall fairness slice each cover
  exactly the 32,593 silver enrolments; the overall withdrawal rate equals the silver rate;
* every silver assessment result is counted once in the funnel (submitted + banked = 173,912);
* the risk table contains exactly the enrolments still registered on the cut-off day (27,553).

## What was not verifiable

* **The model.** The paper publishes no predictive benchmark, so the AUC on the site (0.669 on
  the held-out 2014J presentations) is compared with this repository's own clicks-only baseline
  (0.591), not with a published figure. Published OULAD models use different cut-offs, labels and
  splits, so their AUCs are not comparable and are not quoted.
* **Outcome distribution.** The paper does not publish the distribution of `final_result`; the
  site's 47.2% pass (incl. distinction) and 31.2% withdrawal are computed, not verified.
* **The OU's own download page.** The dataset URL in the paper
  (`analyse.kmi.open.ac.uk/open_dataset`) now redirects to a page whose zip link returns HTTP 404
  (checked 9 October 2026). The figshare record cited as the paper's data citation is used
  instead, with its md5 pinned, and the UCI copy as a fallback. The two archives differ only in
  how missing values are written (`""` vs `"?"`); silver normalises both.
