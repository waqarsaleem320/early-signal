# Requirements Document

## Introduction

Plant Self-Check lets a processor enter the plant's own routine FSIS Salmonella sampling record for the last 52 weeks. The Decision_Engine rebuilds the plant's FSIS performance status from that record using the existing per-product standards, shows the observed percent positive and the distance to the neighboring category, and uses the rebuilt status for the expected positivity rate when no published FSIS category is entered. A published category always takes precedence. The feature is decision support only: it authorizes nothing, is not a regulatory determination, names no plant, and makes no outbreak or illness claims. The FSIS category definitions follow the Salmonella performance standards that FSIS verifies under 9 CFR 381 and the plant's HACCP plan under 9 CFR 417.

## Glossary

- **Decision_Engine**: The module `src/decision/actions.py`, which holds risk level and action logic.
- **Dashboard**: The Streamlit page `app/dashboard.py`. The Dashboard displays results and holds no analysis.
- **Sidebar**: The "Your lot" input area of the Dashboard.
- **Section_1**: The "1 · Recommendation" section of the Dashboard.
- **Sample_Count**: The user-entered number of routine FSIS samples taken at the plant in the last 52 weeks, a non-negative integer.
- **Positive_Count**: The user-entered number of Salmonella positives among the Sample_Count samples, a non-negative integer.
- **Product_Group**: The FSIS rate group for the selected product, the first element of the `PRODUCTS` entry in the Decision_Engine.
- **Standard**: The FSIS Salmonella performance standard percent for the Product_Group, read from `STANDARD_PCT` in `src/context.py`.
- **Minimum_Samples**: The value `MIN_PLANT_SAMPLES` in `src/context.py` (currently 10).
- **Observed_Percent**: 100 × Positive_Count ÷ Sample_Count.
- **Rebuilt_Status**: The FSIS category computed from the Observed_Percent: Category 1 when Observed_Percent ≤ Standard ÷ 2; Category 2 when Standard ÷ 2 < Observed_Percent ≤ Standard; Category 3 when Observed_Percent > Standard.
- **Published_Category**: The FSIS category (1, 2 or 3) selected by the user in the Sidebar, or "Not listed".
- **Positives_To_Next**: For Rebuilt_Status Category 1 or 2, the smallest number of additional positives, at the same Sample_Count, that moves the Rebuilt_Status to a higher category. For every product offered in the Sidebar this is the next category up. For the carcass standards (9.8% and 7.1%) at small Sample_Count, one positive can move a line from Category 1 straight to Category 3, so the category reached is reported with the count.
- **Positives_To_Drop**: For Rebuilt_Status Category 3, the smallest number of fewer positives, at the same Sample_Count, that brings Observed_Percent to or below Standard. For every product offered in the Sidebar this lands in Category 2. For the carcass standards at small Sample_Count it can land in Category 1, so the category reached is reported with the count.
- **Self_Check_Result**: The Decision_Engine output holding Observed_Percent, Rebuilt_Status, Positives_To_Next or Positives_To_Drop, and an explanatory message.
- **Expected_Rate**: The share of samples expected positive, returned by `expected_rate` in the Decision_Engine together with a basis string.

## Requirements

### Requirement 1: Sidebar Sampling Inputs

**User Story:** As a plant food safety manager, I want to enter my plant's routine FSIS sampling record in the sidebar, so that the tool can check my plant's status without needing a published category.

#### Acceptance Criteria

1. THE Sidebar SHALL provide an optional integer input for Sample_Count with a minimum of 0 and a default of 0.
2. THE Sidebar SHALL provide an optional integer input for Positive_Count with a minimum of 0 and a default of 0.
3. THE Sidebar SHALL label the Sample_Count input as routine FSIS samples in the plant's last 52 weeks.
4. THE Sidebar SHALL label the Positive_Count input as positives among those samples.
5. THE Dashboard SHALL pass Sample_Count and Positive_Count to the Decision_Engine without computing Observed_Percent, Rebuilt_Status, Positives_To_Next or Positives_To_Drop in the Dashboard.
6. THE Sidebar SHALL request only counts and SHALL omit any input for a plant name or establishment identifier.

### Requirement 2: Observed Percent and Rebuilt Status

**User Story:** As a plant food safety manager, I want the observed percent positive and status computed by the FSIS rule, so that I can see where my plant stands against the standard.

#### Acceptance Criteria

1. WHEN Sample_Count is at least Minimum_Samples, THE Decision_Engine SHALL compute Observed_Percent as 100 × Positive_Count ÷ Sample_Count.
2. WHEN Sample_Count is at least Minimum_Samples and Observed_Percent is at or below Standard ÷ 2, THE Decision_Engine SHALL set Rebuilt_Status to Category 1.
3. WHEN Sample_Count is at least Minimum_Samples and Observed_Percent is above Standard ÷ 2 and at or below Standard, THE Decision_Engine SHALL set Rebuilt_Status to Category 2.
4. WHEN Sample_Count is at least Minimum_Samples and Observed_Percent is above Standard, THE Decision_Engine SHALL set Rebuilt_Status to Category 3.
5. THE Decision_Engine SHALL evaluate the Category boundaries exactly, so that an Observed_Percent equal to Standard ÷ 2 yields Category 1 and an Observed_Percent equal to Standard yields Category 2.
6. THE Decision_Engine SHALL read Standard from `STANDARD_PCT` and Minimum_Samples from `MIN_PLANT_SAMPLES` imported from `src/context.py`.
7. THE Decision_Engine SHALL look up Standard using the Product_Group of the selected product.
8. THE Decision_Engine SHALL expose the self-check logic as type-hinted functions listed in the module `__all__`.

### Requirement 3: Distance to Neighboring Category

**User Story:** As a plant food safety manager, I want to know how many positives separate my plant from the neighboring category, so that I can see how close I am to a change in status.

#### Acceptance Criteria

1. WHEN Rebuilt_Status is Category 1, THE Decision_Engine SHALL report Positives_To_Next as the smallest number of additional positives at the same Sample_Count that makes Observed_Percent exceed Standard ÷ 2.
2. WHEN Rebuilt_Status is Category 2, THE Decision_Engine SHALL report Positives_To_Next as the smallest number of additional positives at the same Sample_Count that makes Observed_Percent exceed Standard.
3. WHEN Rebuilt_Status is Category 3, THE Decision_Engine SHALL report Positives_To_Drop as the smallest number of fewer positives at the same Sample_Count that makes Observed_Percent at or below Standard.
4. THE Decision_Engine SHALL report Positives_To_Next and Positives_To_Drop as positive integers.

### Requirement 4: Small or Invalid Sample Counts

**User Story:** As a plant food safety manager, I want a small sample count flagged instead of used, so that I do not act on an unreliable status.

#### Acceptance Criteria

1. WHEN Sample_Count is above 0 and below Minimum_Samples and Positive_Count is at most Sample_Count, THE Decision_Engine SHALL return a Self_Check_Result with no Rebuilt_Status and a message stating that the sample count is too small to rebuild a category and, when Published_Category is "Not listed", that the national rate is used, or, when Published_Category is 1, 2 or 3, that the Published_Category drives Expected_Rate.
2. WHEN Sample_Count is above 0 and below Minimum_Samples and Published_Category is "Not listed", THE Decision_Engine SHALL return the national Product_Group rate as Expected_Rate.
3. WHEN Sample_Count is 0, THE Decision_Engine SHALL treat the self-check as not entered, regardless of Positive_Count, and return Expected_Rate as computed before this feature.
4. IF Sample_Count is above 0 and Positive_Count exceeds Sample_Count, THEN THE Decision_Engine SHALL return a Self_Check_Result with no Rebuilt_Status and a message stating that positives cannot exceed samples.
5. IF Sample_Count is above 0 and Positive_Count exceeds Sample_Count, THEN THE Decision_Engine SHALL return Expected_Rate as computed before this feature.

### Requirement 5: Expected Rate Precedence

**User Story:** As a plant food safety manager, I want the rebuilt status used for the expected rate when no published category exists, and the published category to win when one does, so that the estimate uses the best available status.

#### Acceptance Criteria

1. WHEN Published_Category is "Not listed" and a Rebuilt_Status exists, THE Decision_Engine SHALL compute Expected_Rate from the forward rate for the Product_Group and the Rebuilt_Status.
2. WHEN Published_Category is "Not listed" and a Rebuilt_Status exists, THE Decision_Engine SHALL return a basis string stating that the rate uses the status rebuilt from the plant's last 52 weeks of samples.
3. WHEN Published_Category is 1, 2 or 3, THE Decision_Engine SHALL compute Expected_Rate from the Published_Category regardless of Rebuilt_Status.
4. THE Decision_Engine SHALL apply the Expected_Rate chosen under this requirement in both `risk_level` and `compare_actions`.
5. WHILE Published_Category is "Not listed" and no Rebuilt_Status exists, THE Decision_Engine SHALL return the national Product_Group rate as Expected_Rate.

### Requirement 6: Section 1 Display

**User Story:** As a plant food safety manager, I want the self-check shown in the recommendation section, with any disagreement against the published category flagged, so that I can see both views at once.

#### Acceptance Criteria

1. WHEN a Rebuilt_Status exists, THE Section_1 SHALL display Observed_Percent, Sample_Count, Positive_Count, Rebuilt_Status and the Standard.
2. WHEN Rebuilt_Status is Category 1 or 2, THE Section_1 SHALL display Positives_To_Next with the statement that the count applies at the same Sample_Count.
3. WHEN Rebuilt_Status is Category 3, THE Section_1 SHALL display Positives_To_Drop with the statement that the count applies at the same Sample_Count.
4. WHEN Published_Category is 1, 2 or 3 and a Rebuilt_Status exists that differs from Published_Category, THE Section_1 SHALL display both categories and a note stating the Rebuilt_Status read from the last 52 weeks and that the Published_Category drives Expected_Rate.
5. WHEN Sample_Count is above 0 and below Minimum_Samples and Positive_Count is at most Sample_Count, THE Section_1 SHALL display the too-small message from Requirement 4.1.
6. IF Sample_Count is above 0 and Positive_Count exceeds Sample_Count, THEN THE Section_1 SHALL display the message that positives cannot exceed samples.
7. WHEN Sample_Count is 0, THE Section_1 SHALL display the recommendation without a self-check block.
8. THE Section_1 SHALL state that the Rebuilt_Status is a self-check for decision support and is not an FSIS determination.
9. THE Section_1 SHALL present the self-check without a plant name and without any outbreak or illness claim.
10. THE Section_1 SHALL describe the Expected_Rate source for an unlisted line as the national rate unless a Rebuilt_Status exists, in which case the rebuilt status is used.

### Requirement 7: Tests and Unchanged Results

**User Story:** As a maintainer, I want boundary tests and unchanged published results, so that the feature is verified and the analysis stays reproducible.

#### Acceptance Criteria

1. THE test module `tests/test_decision.py` SHALL include tests at Sample_Count equal to Minimum_Samples − 1 and equal to Minimum_Samples.
2. THE test module `tests/test_decision.py` SHALL include tests at Observed_Percent exactly equal to Standard ÷ 2 and exactly equal to Standard, and at one positive above each boundary.
3. THE test module `tests/test_decision.py` SHALL include tests of Positives_To_Next for Category 1 and Category 2 and of Positives_To_Drop for Category 3.
4. THE test module `tests/test_decision.py` SHALL include tests that a Published_Category takes precedence over a differing Rebuilt_Status for Expected_Rate.
5. THE test module `tests/test_decision.py` SHALL include a test that Positive_Count above Sample_Count yields no Rebuilt_Status.
6. WHEN the command `.\.venv\Scripts\python.exe -m pytest -q tests` runs, THE test suite SHALL pass.
7. THE feature SHALL leave `src/context.py` `_plant_status`, README numbers and files under `artifacts/` unchanged.
