# Venue: ISPASS 2027

The ISPASS 2027 call for papers is not published yet (2026-10-02:
`ispass.org/ispass2027/` returns 404). Until it is, the paper follows the
ISPASS 2026 submission rules (`ispass.org/ispass2026/submission.php`), and
everything here is re-checked against the 2027 call when it appears:

| rule (ISPASS 2026) | how this draft meets it |
| --- | --- |
| at most **9** pages, double-column, single-spaced; everything but references (figures, appendices) inside them | `make -C paper pdf`; the page count is checked after every edit |
| references unlimited; every author listed for works with fewer than 10 authors | `IEEEtran` style; no bibliography yet (P6.4) |
| IEEE conference style, 10-point, US letter | `\documentclass[conference,10pt]{IEEEtran}`; Times via TeX Gyre Termes under tectonic (XeTeX) |
| pages numbered | `\pagestyle{plain}` after `\maketitle` (IEEEtran's conference mode omits them) |
| double-blind: no names, self-citation in the third person, no identifying URLs | author block "Anonymous submission"; the existing planner is named in the third person; no repository URL in the PDF |

2026 dates for scale: abstract 2025-12-08, paper 2025-12-15, notification
2026-02-23. The 2027 dates are expected a year later and are not assumed here.
