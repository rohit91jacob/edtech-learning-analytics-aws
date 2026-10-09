# Data licences and attribution

The code in this repository is MIT-licensed (see [LICENSE](LICENSE)). The data it processes is not
the author's and keeps its own licence.

## Open University Learning Analytics Dataset (OULAD): used

| | |
|---|---|
| Owner | The Open University, Walton Hall, Milton Keynes, MK7 6AA, United Kingdom |
| Authors | Jakub Kuzilek, Martin Hlosta, Zdenek Zdrahal |
| Licence | [Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/) |
| Licence statements | Data descriptor abstract: "freely available ... under a CC-BY 4.0 license"; figshare record 5081998 licence field `CC BY 4.0`; UCI Machine Learning Repository page for dataset 349: CC BY 4.0 |
| Download used by the pipeline | figshare, <https://doi.org/10.6084/m9.figshare.5081998.v1> (file `anonymisedData.zip`, md5 `7412686fd77cf0e0ee1e8c3e9b354308`), fallback UCI mirror <https://archive.ics.uci.edu/dataset/349/open+university+learning+analytics+dataset> (DOI 10.24432/C5KK69) |
| Paper | Kuzilek, J., Hlosta, M. & Zdrahal, Z. Open University Learning Analytics dataset. *Sci. Data* 4, 170171 (2017). <https://doi.org/10.1038/sdata.2017.171> |

**Attribution for derived data and the results site:** "Contains data from the Open University
Learning Analytics Dataset (OULAD), © The Open University, licensed under CC BY 4.0
(https://doi.org/10.6084/m9.figshare.5081998.v1). Changes: sampled, aggregated and modelled."

### What is committed

The full archive (46.7 MB zipped, 464 MB unzipped) is downloaded at runtime and never committed.
CC BY 4.0 permits redistribution with attribution, so `tests/fixtures/oulad/` holds a small
**real** sample, rebuilt deterministically by `scripts/build_fixtures.py` (seed 20171128):

* four module presentations (AAA 2013J, AAA 2014J, CCC 2014B, CCC 2014J);
* a stratified sample of 288 students (up to 24 Pass, 8 Distinction, 16 Fail and 24 Withdrawn per
  presentation) and every row that belongs to them in each table;
* rows are unchanged; only the selection is ours. `studentVle` is split into four gzip parts.
  Every file is under 300 KB.

Nothing in this repository is simulated or synthetic, except values typed into a few unit tests to
exercise parsing edge cases (marked in the tests).

## ASSISTments: evaluated, not used

The ASSISTments datasets (WPI) were considered as a second, mastery-learning source. Their
[Terms of Use](https://sites.google.com/site/assistmentsdata/termsofuseforusingdata) require a
written agreement and state "I agree to not give this data to anyone else". That rules out
committing fixtures or republishing derived row-level data, and the download is not
credential-free, so the project does not use it.

## Khan Academy

Khan Academy's learner data is **not public**. The project's framing (mastery learning, the
engagement-to-mastery funnel) is inspired by that style of product, but every number here comes
from OULAD, a UK distance-learning university, not from Khan Academy.
