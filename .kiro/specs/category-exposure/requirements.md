# Requirements: category-conditioned exposure

## Requirement 1
**User story:** As a plant food safety lead, I want risk based on my own FSIS category, so that the
recommendation reflects my line and not only a national product rate.

1. WHEN the user selects a product and category THEN the system SHALL show expected positivity next year.
2. WHEN the category is not listed THEN the system SHALL use the national product rate and say so.
3. WHEN expected positivity is above the FSIS standard THEN the system SHALL set the level to High.
4. WHEN it is above half the standard THEN the system SHALL set the level to at least Elevated.

## Requirement 2
**User story:** As a judge, I want the category link tested forward in time, so that I can trust it.

1. The system SHALL score each status on the following 52 weeks only.
2. The system SHALL compare category and product with product alone on a held-out year.
3. The system SHALL report intervals that resample plants.
